import json
import cmath
import math
import socket
import logging
import time
import sys
import os
import subprocess
import winsound
from datetime import datetime
from pathlib import Path

import PySimpleGUIQt as sg
import tailer

LOG_LEVEL = logging.INFO
SETTINGS_FILE = Path(Path(__file__).parent, 'settings.cfg')
DEFAULT_SETTINGS = {'precision': 0,
                    'update_freq': 1000, 
                    'coord_sys': 'cartesian',
                    'units': 'feet.inches',
                    'log_dir': str(Path('C:\Marvelmind\dashboard\logs')),
                    'num_log_lines': 10,
                    'hedge_addrs': '36,38',
                    'allowed_system_vs_log_time_delta': 2000,
                    'color_theme': 'DarkBlue13', 
                    }
SETTINGS_KEYS_TO_ELEMENT_KEYS = {
                    'precision': '-PREC-',
                    'update_freq': '-FREQ-', 
                    'coord_sys': '-COORD_SYS-',
                    'units': '-UNITS-',
                    'log_dir': '-LOGDIR-',
                    'num_log_lines': '-NUMLINES-',
                    'hedge_addrs': '-ADDR-',
                    'allowed_system_vs_log_time_delta': '-ALLOW_DELTA_T-',
                    'color_theme': '-THEME-',
                    }

UNITS_CHOICES = ['m', 'mm', 'inches', 'feet.inches']
COORD_SYS_CHOICES = ['cartesian', 'cylindrical']
PREC_CHOICES = [0,1,2,3]
DEGREE_SIGN = u'\N{DEGREE SIGN}'
NEWLINE_INDENT = '\n  '


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
                [TextLabel('Number of position values to average'),sg.Input(key='-NUMLINES-')],
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
        logging.debug(f"Reading hedge logfile {current_log}.")
    else:
        logging.warning(f"No hedge log found. Ensure hedge logfile is being written and correct address is entered in settings.")
    return current_log


def get_last_logfile_lines(logfile, addrs, n=10):
    """Return last n complete lines (as lists of fields) written to the CSV log file 
    for each hedge addr.""" 

    # Try to grab more than we need n*3 since the number of lines we need is actually
    # n times the number of beacon addresses.
    # tailer.tail() will grab all lines if the requested number is less than the total.
    enough_lines = False
    d = {addr: [] for addr in addrs}
    max_tries = 10
    num_tries = 0
    while not enough_lines:
        num_tries += 1
        with open(logfile, 'r') as f:
            lastlines = tailer.tail(f, n*5)
            lastlines = lastlines[1:-1]  # exclude first/last line since they might only be partially written.
        # need at least 1 line for each address
        # Note that we may not get the requested number of lines.
        # No big deal since we will just return what we have and the next tick will attempt again.

        for line in lastlines:
            fields = [x for x in line.strip().split(',') if x]
            try:
                addr = int(fields[3])
            except ValueError:
                continue
            if addr in addrs and (len(d[addr]) < n):
                d[addr].append(fields)
        
        # make sure we have at least one data point (i.e. row/line) for each address
        # Otherwise, we just loop again. 
        # This check needed because occasionally, the logfile has data for stationary beacons.
        if all([d[addr] for addr in addrs]):
            enough_lines = True
        
        if num_tries >= max_tries:
            return None
        
    logging.debug(f"Parsing these lines from logfile:\n  {NEWLINE_INDENT.join(lastlines)}")
    return d 


def parse_log_file_fields(fields):
    unix_time = int(fields[0])
    addr = int(fields[3])
    x_m, y_m, z_m = float(fields[4]), float(fields[5]), float(fields[6])
    in_exclusion_zone = True if int(fields[-4]) else False
    return x_m, y_m, z_m, unix_time, in_exclusion_zone
    

def calc_hedge_position(log_data, units='feet.inches', coord_sys='cartesian', precision=0):
    positions = {}
    in_exclusion_zone = False

    # Calculate average position of each hedge individually.
    while log_data:
        addr, fields_list = log_data.popitem()
        logging.debug(f"Calculating avg pos for addr {addr} from fields:\n  {NEWLINE_INDENT.join([','.join(f) for f in fields_list])}")
        xa, ya, za, ta, eza = [], [], [], [], []
        for fields in fields_list:
            x, y, z, t, ez = parse_log_file_fields(fields)
            xa.append(x)
            ya.append(y)
            za.append(z)
            ta.append(t)
            eza.append(ez)

        xavg = sum(xa) / len(xa) 
        yavg = sum(ya) / len(ya) 
        zavg = sum(za) / len(za) 
        tavg = sum(ta) / len(ta) 
        ez = len([v for v in eza if ez])
        # If about half of the ez values are True for any hedge, we return True
        if ez > len(eza) // 2:
            in_exclusion_zone = True  # if any hedge is in an exclusion zone, we return True 
        positions[addr] = (xavg,yavg,zavg,tavg)

        logging.debug(f"{addr=} {xavg=}, {yavg=}, {zavg=}, {tavg=}") 

    # Get average of all hedges positions and time stamps.
    x = sum([positions[k][0] for k in positions]) / len(positions)
    y = sum([positions[k][1] for k in positions]) / len(positions)
    z = sum([positions[k][2] for k in positions]) / len(positions)
    t = sum([positions[k][3] for k in positions]) / len(positions)

    logging.info(f"Final average: {x=:.3f}, {y=:.3f}, {z=:.3f}, {t=}") 
    
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
        angle = math.degrees(y)
        if angle < 0.0:
            angle += 360.0  # it's desired to have angle range be 0,360 instead of -180,180
        y_str = f'{angle:{fmt}}{DEGREE_SIGN}'
    
    return x_str, y_str, z_str, t, in_exclusion_zone


def create_main_window(settings, status, loc=(None,None)):
    sg.theme(settings['color_theme'])
    layout = [
                [sg.Image('assets/RVB_FRAMATOME_HD_15pct.png')],
                [sg.Text('REPS Tracking System', justification='center', font=('Work Sans', 14))],
                [sg.Text(' '*30)],
                [sg.Text(' '*30)],
                [sg.Text(size=(16,1)), sg.Text(justification='left', font=('Work Sans', 20), key='-XPOS-')],
                [sg.Text(size=(16,1)), sg.Text(justification='left', font=('Work Sans', 20), key='-YPOS-')],
                [sg.Text(size=(16,1)), sg.Text(justification='left', font=('Work Sans', 20), key='-ZPOS-')],
                [sg.Text(' '*40)],
                [sg.Button('Save Current Position', font=('Work Sans', 12))],
                [sg.Text('_'*64)],
                [sg.Text(' '*40)],
                [sg.Text('  Status:  ', size=(11,1), font=('Work Sans', 20)), 
                 #sg.Text('Acquiring Location', size=(34,2), font=('Work Sans', 20), justification='left', text_color='yellow', key='-MSG-')],
                 sg.Text(status, size=(34,2), font=('Work Sans', 20), justification='left', text_color='yellow', key='-MSG-')],
                [sg.Text(' '*40)],
                [sg.Text(' '*40)],
                [sg.Button('Exit', font=('Work Sans', 12)), sg.Button('Settings', font=('Work Sans', 12))],
             ]
    return sg.Window('REPS', layout=layout, keep_on_top=True, location=loc, resizable=False, icon='assets/favicon.ico')


def main():
    logging.basicConfig(level=LOG_LEVEL)
    window, settings = None, load_settings(SETTINGS_FILE, DEFAULT_SETTINGS) 
    orig_color_theme = settings['color_theme']
    position_logfile = Path(f'position_log_{datetime.now().strftime("%Y_%m_%d-%I_%M_%S_%p")}.txt') 
    loc_idx = 1
    notepad_proc = None
    status = 'Acquiring Location'
    prev_status = status
    cur_loc = (None,None)
    EZ_THEME = 'HotDogStand'
    
    in_ez = False
    x_str, y_str, z_str = 'X: ?', 'Y: ?', 'Z: ?'

    while True:
        if prev_status != status: 
            if in_ez:
                settings['color_theme'] = EZ_THEME 
                cur_loc = window.current_location()
                window.close()
                window = None
            else:
                settings['color_theme'] = orig_color_theme 
                cur_loc = window.current_location()
                window.close()
                window = None
        prev_status = status
        
        if window is None:
            window = create_main_window(settings, status, loc=cur_loc)

        event, values = window.read(timeout=int(settings['update_freq']))
        window['-XPOS-'].update(x_str)
        window['-YPOS-'].update(y_str)
        window['-ZPOS-'].update(z_str)

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

            hedge_addrs_str = ', '.join([str(a) for a in hedge_addrs])
            logging.info(f"Tracking hedge address(es): {hedge_addrs_str}")
            log_lines = get_last_logfile_lines(hedge_log, hedge_addrs, n=int(settings['num_log_lines']))
            if not log_lines:
                logging.error(f'Unable to get logfile data for all addresses {hedge_addrs_str}.')
                window['-MSG-'].update(f'No data for\naddress(es): {hedge_addrs_str}')
                window['-MSG-'].update(text_color='yellow')
                window['-XPOS-'].update(f'X: ?')
                window['-YPOS-'].update(f'Y: ?')
                window['-ZPOS-'].update(f'Z: ?')
                continue

            x,y,z,t,in_ez = calc_hedge_position(log_lines, 
                                                units=settings['units'],
                                                coord_sys=settings['coord_sys'],
                                                precision=int(settings['precision']),
                                               )

        # Time in log file appears to depend on locality, not UTC.  time.time() returns unix time in UTC
        # so we have to subtract the offset (time.timezone).
        sys_log_time_delta = time.time() - time.timezone - t/1000.
        logging.debug(f'Time delta:  {sys_log_time_delta:.3f} sec.')
        if sys_log_time_delta > float(settings['allowed_system_vs_log_time_delta'])/1000.:
            logging.warning(f'Time difference ({sys_log_time_delta}) between logfile and system time exceeds threshold.')
            status = "Log data stale.\nPosition may be inaccurate."
            status_text_color = 'yellow'
        elif in_ez:
            logging.warning("Hedge in an exclusion zone!!")
            status = '   !!  EXCLUSION ZONE  !!'
            status_text_color = 'yellow'
            winsound.PlaySound("assets/alarm2.wav", winsound.SND_ASYNC | winsound.SND_LOOP)
        else:
            status = 'OK'
            status_text_color = 'green'
            winsound.PlaySound(None, winsound.SND_ASYNC)

        window['-MSG-'].update(status)
        window['-MSG-'].update(text_color=status_text_color)
        if settings['coord_sys'] == 'cartesian':
            x_str = f'X: {x}'
            y_str = f'Y: {y}'
            z_str = f'Z: {z}'
        elif settings['coord_sys'] == 'cylindrical':
            x_str = f'R: {x}'
            y_str = f'P: {y}'
            z_str = f'Z: {z}'

        if event == 'Save Current Position':
            loc_label = sg.popup_get_text('Provide a name for current position: ',
                                keep_on_top=True,
                                size=(40,1),
                                title='Save Current Position',
                                default_text=f'Location {loc_idx}')
            if loc_label:
                loc_idx += 1
                logging.info(f"Location '{loc_label}' saved to {position_logfile.absolute()}.")
                with position_logfile.open('a') as f:
                    f.write(f'{loc_label}\n{x_str}\n{y_str}\n{z_str}\n\n')
                if notepad_proc:
                    notepad_proc.terminate()
                notepad_proc = subprocess.Popen(["notepad", position_logfile.absolute()])

    window.close()

if __name__ == '__main__':
    main()