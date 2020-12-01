import json
import socket
import logging
import time
import sys
import os
import winsound
from pathlib import Path

import PySimpleGUIQt as sg
import tailer

SETTINGS_FILE = Path(Path(__file__).parent, 'settings.cfg')
DEFAULT_SETTINGS = {'precision': 1,
                    'update_freq': 500, 
                    'units': 'feet.inches',
                    'log_dir': str(Path('C:\Marvelmind\dashboard\logs')),
                    'hedge_addrs': '36,38',
                    'allowed_system_vs_log_time_delta': 1000,
                    'color_theme': 'DarkBlue13', 
                    }
SETTINGS_KEYS_TO_ELEMENT_KEYS = {
                    'precision': '-PREC-',
                    'update_freq': '-FREQ-', 
                    'units': '-UNITS-',
                    'log_dir': '-LOGDIR-',
                    'hedge_addrs': '-ADDR-',
                    'allowed_system_vs_log_time_delta': '-ALLOW_DELTA_T-',
                    'color_theme': '-THEME-',
                    }

UNITS_CHOICES = ['m', 'mm', 'inches', 'feet.inches']
PREC_CHOICES = [0,1,2]


def load_settings(settings_file, default_settings):
    try:
        with open(settings_file, 'r') as f:
            settings = json.load(f)
    except Exception as e:
        settings = default_settings
        save_settings(settings_file, settings, None)
    return settings


def save_settings(settings_file, settings, values):
    if values:
        for key in SETTINGS_KEYS_TO_ELEMENT_KEYS:  # update window with the values read from settings file
            try:
                settings[key] = values[SETTINGS_KEYS_TO_ELEMENT_KEYS[key]]
            except Exception as e:
                print(f'Problem updating settings from window values. Key = {key}')

    with open(settings_file, 'w') as f:
        json.dump(settings, f)


def create_settings_window(settings):
    sg.theme(settings['color_theme'])

    def TextLabel(text): return sg.Text(text+':', justification='r', size=(25,1))

    layout = [  [sg.Text('Settings', font=('Work Sans', 12))],
                [TextLabel('Track Hedge Address(es)'),sg.Input(key='-ADDR-')],
                [TextLabel('Units'), sg.Combo(UNITS_CHOICES, key='-UNITS-')],
                [TextLabel('Precision'), sg.Combo(PREC_CHOICES, key='-PREC-')],
                [TextLabel('Refresh Rate (ms)'), sg.Input(key='-FREQ-')],
                [TextLabel('Logfile Folder'),sg.Input(key='-LOGDIR-'), sg.FolderBrowse(target='-LOGDIR-')],
                [TextLabel('Time until log considered stale (ms)'), sg.Input(key='-ALLOW_DELTA_T-')],
                [TextLabel('Color Theme'),sg.Combo(sg.theme_list(), key='-THEME-')],
                [sg.Button('Save'), sg.Button('Restore Defaults'), sg.Button('Exit')]  ]

    window = sg.Window('Settings', layout, keep_on_top=True, finalize=True)

    for key in SETTINGS_KEYS_TO_ELEMENT_KEYS:   # update window with the values read from settings file
        try:
            window[SETTINGS_KEYS_TO_ELEMENT_KEYS[key]].update(value=settings[key])
        except Exception as e:
            print(f'Problem updating PySimpleGUI window from settings. Key = {key}')

    return window


def connect_to_udp_stream():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    #udp_ip = socket.gethostname()
    udp_ip = 'localhost' 
    logging.info(f'Binding to UDP socket {udp_ip}:{DASHBOARD_UDP_PORT}.')
    sock.bind(('localhost', DASHBOARD_UDP_PORT))
    return sock


def get_hedge_pos_udp():
    # TODO: add a timeout
    sock = connect_to_udp_stream()
    data, addr = sock.recvfrom(1024)
    sock.close()
    logging.info(f"Received message: {data}")
    logging.info(f"Message length: {len(data)}")

    # See marvelmind.com/pics/dashboard_udp_protocol.pdf
    # This is the protocol for packets with mm resolution coordinates
    # (dashboard V4.92+, modem/beacon V5.35)
    addr = data[0] 
    packet_type = data[1] 
    data_size = data[4]
    data_code = int.from_bytes(data[2:4], byteorder='little', signed=False)
    timestamp = int.from_bytes(data[5:9], byteorder='little', signed=False) / 64
    x_mm = int.from_bytes(data[9:13], byteorder='little', signed=True)
    y_mm = int.from_bytes(data[13:17], byteorder='little', signed=True)
    z_mm = int.from_bytes(data[17:21], byteorder='little', signed=True)

    return x, y, z, timestamp


def get_hedge_logfile(dir):
    """Find the log file by selecting the file with the most recent modification time in the logfile directory.
    If no file found, return None."""
    logfiles = Path(dir).glob('*csv')
    max_m_time = -1
    current_log = None
    for lf in logfiles:
        mtime = lf.stat().st_mtime
        if mtime > max_m_time:
            max_m_time = mtime
            current_log = lf
    if current_log:
        logging.info(f"Reading hedge logfile {current_log}.")
    else:
        logging.info(f"No hedge log found. Ensure hedge logfile is being written and restart program.")
        sys.exit(1)
    return current_log


def get_last_logfile_line(logfile, addr):
    """Return most recent complete line written to CSV log file for hedge addr.""" 
    addr_found = False
    last_line = None 
    fields = []
    while not addr_found:
        with open(logfile, 'r') as f:
            lastlines = tailer.tail(f, 10)[:-2]  # exclude final line since it may only be partially written
        for line in lastlines[::-1]:  # iterate in reverse order to process latest data first
            fields = [x for x in line.strip().split(',') if x]  # we want to ignore the final empty field since most lines end with ','
            try:
                if int(fields[3]) == addr:
                    addr_found = True
                    last_line = line
                    break
            except IndexError:
                continue
        logging.info(f'Logfile data: {last_line}')
    return fields 


def parse_log_file_fields(fields):
    unix_time = int(fields[0])
    addr = int(fields[3])
    x_m, y_m, z_m = float(fields[4]), float(fields[5]), float(fields[6])
    in_exclusion_zone = True if int(fields[-4]) else False
    return x_m, y_m, z_m, unix_time, in_exclusion_zone
    

def get_hedge_position_from_log(logfile, addrs, units='feet.inches', precision=0):
    positions = {}
    in_exclusion_zone = False
    for addr in addrs:
        log_data = get_last_logfile_line(logfile, addr)
        x, y, z, unix_time, in_ez = parse_log_file_fields(log_data)
        positions[addr] = (x,y,z)
        if in_ez:
            in_exclusion_zone = True  # if any hedge is in an exclusion zone, we return True 

    if len(addrs) == 1:
        x,y,z = positions[addrs[0]]
    else:
        # Get average of all hedges
        x = sum([positions[addr][0] for addr in addrs]) / len(addrs)
        y = sum([positions[addr][1] for addr in addrs]) / len(addrs)
        z = sum([positions[addr][2] for addr in addrs]) / len(addrs)

    # X,Y,Z coordinates from logfile are in meters
    fmt = f' .{precision}f'
    if units == 'feet.inches':
        x_str = f"""{int(x / 0.0254 / 12): d}\'{abs(x) / 0.0254 % 12:{fmt}}\""""
        y_str = f"""{int(y / 0.0254 / 12): d}\'{abs(y) / 0.0254 % 12:{fmt}}\""""
        z_str = f"""{int(z / 0.0254 / 12): d}\'{abs(z) / 0.0254 % 12:{fmt}}\""""
    
    elif units == 'inches':
        x_str = f'{x / 0.0254:{fmt}} inches'
        y_str = f'{y / 0.0254:{fmt}} inches'
        z_str = f'{z / 0.0254:{fmt}} inches'
    
    elif units == 'mm':
        x_str = f'{x*1000.:{fmt}} mm'
        y_str = f'{y*1000.:{fmt}} mm'
        z_str = f'{z*1000.:{fmt}} mm'

    elif units == 'm':
        x_str = f'{x:{fmt}} m'
        y_str = f'{y:{fmt}} m'
        z_str = f'{z:{fmt}} m'

    else:
        logging.error('invalid units input. Exiting.')
        sys.exit(1)
    
    return x_str, y_str, z_str, unix_time, in_exclusion_zone

def create_main_window(settings):
    sg.theme(settings['color_theme'])
    layout = [
                [sg.Image('assets/RVB_FRAMATOME_HD_15pct.png')],
                [sg.Text('Crane Hook Tracker', justification='center', font=('Work Sans', 14))],
                [sg.Text(' '*30)],
                [sg.Text(' '*30)],
                [sg.Text(justification='center', font=('Work Sans', 20), key='-XPOS-')],
                [sg.Text(justification='center', font=('Work Sans', 20), key='-YPOS-')],
                [sg.Text(justification='center', font=('Work Sans', 20), key='-ZPOS-')],
                [sg.Text('_'*64)],
                [sg.Text(' '*40)],
                [sg.Text('  Status:  ', size=(11,1), font=('Work Sans', 20)), 
                 sg.Text('Acquiring Location', size=(34,2), font=('Work Sans', 20), justification='left', text_color='yellow', key='-MSG-')],
                [sg.Text(' '*40)],
                [sg.Text(' '*40)],
                [sg.Button('Exit', font=('Work Sans', 12)), sg.Button('Settings', font=('Work Sans', 12))],
             ]
    return sg.Window('Hook Tracker', layout=layout, resizable=False, icon='assets/favicon.ico')


def main():
    logging.basicConfig(level=logging.INFO)
    window, settings = None, load_settings(SETTINGS_FILE, DEFAULT_SETTINGS) 
    
    in_exclusion_zone = False
    msg_on = True  # funky way to make EXCL. ZONE message flash 

    while True:
        if window is None:
            window = create_main_window(settings)

        event, values = window.read(timeout=int(settings['update_freq']))
        if event in (sg.WIN_CLOSED,  'Exit'):
            break
        if event == 'Settings':
            event, values = create_settings_window(settings).read(close=True)
            if event == 'Save':
                window.close()
                window = None
                save_settings(SETTINGS_FILE, settings, values)
            elif event == 'Restore Defaults':
                SETTINGS_FILE.unlink(missing_ok=True)
                window.close()
                window = None
                settings = load_settings(SETTINGS_FILE, DEFAULT_SETTINGS) 
            continue

        hedge_log = get_hedge_logfile(settings['log_dir'])
        hedge_addrs = [int(x) for x in settings['hedge_addrs'].strip().split(',') if x]
        logging.info(f"Tracking hedge addresses: {hedge_addrs}")
        x,y,z,t,in_ez = get_hedge_position_from_log(hedge_log, 
                                                    hedge_addrs, 
                                                    units=settings['units'],
                                                    precision=int(settings['precision']),
                                                    )

        # Time in log file appears to depend on locality, not UTC.  time.time() returns unix time in UTC
        # so we have to subtract the offset (time.timezone).
        sys_log_time_delta = time.time() - time.timezone - t/1000.
        logging.debug(f'Time delta:  {sys_log_time_delta} sec.')
        if sys_log_time_delta > float(settings['allowed_system_vs_log_time_delta'])/1000.:
            logging.warning(f'Time difference ({sys_log_time_delta}) between logfile and system time exceeds threshold.')
            status_text = "Log data stale.\nPosition may be inaccurate."
            status_text_color = 'yellow'
        elif in_ez:
            logging.warning("Hedge in an exclusion zone!!")
            status_text = 'EXCLUSION ZONE' if msg_on else '' 
            msg_on = False if msg_on else True
            status_text_color = 'red'
            winsound.PlaySound("assets/alarm2.wav", winsound.SND_ASYNC | winsound.SND_LOOP)
        else:
            status_text = 'OK'
            status_text_color = 'green'
            winsound.PlaySound(None, winsound.SND_ASYNC)

        window['-MSG-'].update(status_text)
        window['-MSG-'].update(text_color=status_text_color)
        window['-XPOS-'].update(f'X: {x}')
        window['-YPOS-'].update(f'Y: {y}')
        window['-ZPOS-'].update(f'Z: {z}')

    window.close()

if __name__ == '__main__':
    main()