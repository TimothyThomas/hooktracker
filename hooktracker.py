import json
import cmath
import math
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
                    'coord_sys': 'cartesian',
                    'units': 'feet.inches',
                    'log_dir': str(Path('C:\Marvelmind\dashboard\logs')),
                    'hedge_addrs': '36,38',
                    'allowed_system_vs_log_time_delta': 1000,
                    'color_theme': 'DarkBlue13', 
                    }
SETTINGS_KEYS_TO_ELEMENT_KEYS = {
                    'precision': '-PREC-',
                    'update_freq': '-FREQ-', 
                    'coord_sys': '-COORD_SYS-',
                    'units': '-UNITS-',
                    'log_dir': '-LOGDIR-',
                    'hedge_addrs': '-ADDR-',
                    'allowed_system_vs_log_time_delta': '-ALLOW_DELTA_T-',
                    'color_theme': '-THEME-',
                    }

UNITS_CHOICES = ['m', 'mm', 'inches', 'feet.inches']
COORD_SYS_CHOICES = ['cartesian', 'cylindrical']
PREC_CHOICES = [0,1,2]
DEGREE_SIGN = u'\N{DEGREE SIGN}'


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
                [TextLabel('Coordinate System'), sg.Combo(COORD_SYS_CHOICES, key='-COORD_SYS-')],
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


def get_hedge_logfile(dir):
    """Find the log file by selecting the file with the most recent modification time in the logfile directory.
    If no file found, return None."""
    logfiles = Path(dir).glob('*')
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
        logging.warning(f"No hedge log found. Ensure hedge logfile is being written and correct address is entered in settings.")
    return current_log


def get_last_logfile_line(logfile, addr):
    """Return most recent complete line written to CSV log file for hedge addr.""" 
    addr_found = False
    last_line = None 
    fields = []
    MAX_TRIES = 20 
    tries = 0
    while not addr_found:
        if tries >= MAX_TRIES:
            return None
        with open(logfile, 'r') as f:
            # grab last 10 lines from file
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
        if not addr_found:
            tries += 1
            time.sleep(0.1)
    return fields 


def parse_log_file_fields(fields):
    unix_time = int(fields[0])
    addr = int(fields[3])
    x_m, y_m, z_m = float(fields[4]), float(fields[5]), float(fields[6])
    in_exclusion_zone = True if int(fields[-4]) else False
    return x_m, y_m, z_m, unix_time, in_exclusion_zone
    

def get_hedge_position_from_log(logfile, addrs, units='feet.inches', coord_sys='cartesian', precision=0):
    positions = {}
    in_exclusion_zone = False
    for addr in addrs:
        log_data = get_last_logfile_line(logfile, addr)
        if not log_data:
            logging.error(f'Unable to find log data for address {addr}.')
            return None
        else:
            logging.info(f'Logfile data: {log_data}')
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
    
    if coord_sys == 'cylindrical': 
        x, y = cmath.polar(complex(x,y))

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

    if coord_sys == 'cylindrical':
        # y coordinate becomes angle if coordinate system is cylindrincal.
        # x,z already handled
        y_str = f'{math.degrees(y):{fmt}}{DEGREE_SIGN}'
    
    return x_str, y_str, z_str, unix_time, in_exclusion_zone


def create_main_window(settings):
    sg.theme(settings['color_theme'])
    layout = [
                [sg.Image('assets/RVB_FRAMATOME_HD_15pct.png')],
                [sg.Text('Crane Hook Tracker', justification='center', font=('Work Sans', 14))],
                [sg.Text(' '*30)],
                [sg.Text(' '*30)],
                [sg.Text(size=(17,1)), sg.Text(justification='left', font=('Work Sans', 20), key='-XPOS-')],
                [sg.Text(size=(17,1)), sg.Text(justification='left', font=('Work Sans', 20), key='-YPOS-')],
                [sg.Text(size=(17,1)), sg.Text(justification='left', font=('Work Sans', 20), key='-ZPOS-')],
                [sg.Text('_'*64)],
                [sg.Text(' '*40)],
                [sg.Text('  Status:  ', size=(11,1), font=('Work Sans', 20)), 
                 sg.Text('Acquiring Location', size=(34,2), font=('Work Sans', 20), justification='left', text_color='yellow', key='-MSG-')],
                [sg.Text(' '*40)],
                [sg.Text(' '*40)],
                [sg.Button('Exit', font=('Work Sans', 12)), sg.Button('Settings', font=('Work Sans', 12))],
             ]
    return sg.Window('Hook Tracker', layout=layout, keep_on_top=True, resizable=False, icon='assets/favicon.ico')


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
        if not hedge_log:
            logging.error('No log file found. Check log directory in settings.')
            window['-MSG-'].update('No log file found. Check\nlog directory in settings.')
            window['-MSG-'].update(text_color='yellow')
            window['-XPOS-'].update(f'X: ?')
            window['-YPOS-'].update(f'Y: ?')
            window['-ZPOS-'].update(f'Z: ?')
            continue
        else:
            hedge_addrs = [int(x) for x in settings['hedge_addrs'].strip().split(',') if x]
            if not hedge_addrs:
                logging.error(f'No addresses to track.')
                window['-MSG-'].update(f'No addresses entered\nin settings.')
                window['-MSG-'].update(text_color='yellow')
                window['-XPOS-'].update(f'X: ?')
                window['-YPOS-'].update(f'Y: ?')
                window['-ZPOS-'].update(f'Z: ?')
                continue

            logging.info(f"Tracking hedge addresses: {hedge_addrs}")
            log_data = get_hedge_position_from_log(hedge_log, 
                                                        hedge_addrs, 
                                                        units=settings['units'],
                                                        coord_sys=settings['coord_sys'],
                                                        precision=int(settings['precision']),
                                                        )
            if not log_data:
                logging.error(f'Unable to get logfile data for addresses {hedge_addrs}.')
                window['-MSG-'].update(f'No data for addresses:\n{hedge_addrs}.')
                window['-MSG-'].update(text_color='yellow')
                window['-XPOS-'].update(f'X: ?')
                window['-YPOS-'].update(f'Y: ?')
                window['-ZPOS-'].update(f'Z: ?')
                continue
            else:
                x,y,z,t,in_ez = log_data

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
        if settings['coord_sys'] == 'cartesian':
            window['-XPOS-'].update(f'X: {x}')
            window['-YPOS-'].update(f'Y: {y}')
            window['-ZPOS-'].update(f'Z: {z}')
        elif settings['coord_sys'] == 'cylindrical':
            window['-XPOS-'].update(f'R: {x}')
            window['-YPOS-'].update(f'P: {y}')
            window['-ZPOS-'].update(f'Z: {z}')

    window.close()

if __name__ == '__main__':
    main()