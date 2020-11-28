import socket
import logging
import time
import sys
import os
import winsound
from pathlib import Path

import PySimpleGUIQt as sg
import tailer

DASHBOARD_UDP_PORT = 49100
COORDINATE_PRECISION = 1    # number of digits after decimal
UPDATE_FREQUENCY = 500      # time in milliseconds
COORDINATE_UNITS = 'm'  #  feet.inches, inches, mm, m
LOG_FILE_DIRECTORY = Path('C:\Marvelmind\dashboard\logs')
HEDGE_ADDRS = [36, 38]  # list of addresses to be tracked. 


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

    fmt = f'.{COORDINATE_PRECISION}f'
    if COORDINATE_UNITS == 'feet.inches':
        x = f"""{x_mm / 25.4 // 12}\' {x_mm / 25.4 % 12:{fmt}}\""""
        y = f"""{y_mm / 25.4 // 12}\' {y_mm / 25.4 % 12:{fmt}}\""""
        z = f"""{z_mm / 25.4 // 12}\' {z_mm / 25.4 % 12:{fmt}}\""""
    
    elif COORDINATE_UNITS == 'inches':
        x = f'{x_mm / 25.4:{fmt}}'
        y = f'{y_mm / 25.4:{fmt}}'
        z = f'{z_mm / 25.4:{fmt}}'
    
    elif COORDINATE_UNITS == 'mm':
        x = f'{x_mm:{fmt}}'
        y = f'{y_mm:{fmt}}'
        z = f'{z_mm:{fmt}}'

    else:
        logging.error('invalid COORDINATE_UNITS input. Exiting.')
        sys.exit(1)


    logging.info(f"Data for address: {addr}")
    logging.info(f"Packet type: {packet_type}")
    logging.info(f"data_code: {data_code}")
    logging.info(f"data_size: {data_size}")
    logging.info(f"timestamp: {timestamp}")
    logging.info(f"X={x}, Y={y}, Z={z}")

    return x, y, z


def get_hedge_logfile():
    """Find the log file by selecting the file with the most recent modification time in the logfile directory.
    If no file found, return None."""
    logfiles = Path(LOG_FILE_DIRECTORY).glob('*csv')
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
    logging.info(f"Data for address: {addr}")
    logging.info(f"timestamp: {unix_time}")
    logging.info(f"X={x_m}, Y={y_m}, Z={z_m}")
    return x_m, y_m, z_m, unix_time, in_exclusion_zone
    

def get_hedge_position_from_log(logfile):
    # dictionary of hedge addr and x,y,z (as tuple) position
    positions = {}
    in_exclusion_zone = False
    for addr in HEDGE_ADDRS:
        log_data = get_last_logfile_line(logfile, addr)
        x, y, z, unix_time, in_ez = parse_log_file_fields(log_data)
        positions[addr] = (x,y,z)
        if in_ez:
            in_exclusion_zone = True  # if any hedge is in an exclusion zone, we return True 

    if len(HEDGE_ADDRS) == 1:
        x,y,z = positions[HEDGE_ADDRS[0]]
    else:
        # Get average of all hedges
        x = sum([positions[addr][0] for addr in HEDGE_ADDRS]) / len(HEDGE_ADDRS)
        y = sum([positions[addr][1] for addr in HEDGE_ADDRS]) / len(HEDGE_ADDRS)
        z = sum([positions[addr][2] for addr in HEDGE_ADDRS]) / len(HEDGE_ADDRS)

    # X,Y,Z coordinates from logfile are in meters
    fmt = f' .{COORDINATE_PRECISION}f'
    if COORDINATE_UNITS == 'feet.inches':
        x_str = f"""{x / 0.0254 // 12}\' {x / 0.0254 % 12:{fmt}}\""""
        y_str = f"""{y / 0.0254 // 12}\' {y / 0.0254 % 12:{fmt}}\""""
        z_str = f"""{z / 0.0254 // 12}\' {z / 0.0254 % 12:{fmt}}\""""
    
    elif COORDINATE_UNITS == 'inches':
        x_str = f'{x / 0.0254:{fmt}} inches'
        y_str = f'{y / 0.0254:{fmt}} inches'
        z_str = f'{z / 0.0254:{fmt}} inches'
    
    elif COORDINATE_UNITS == 'mm':
        x_str = f'{x/1000.:{fmt}} mm'
        y_str = f'{y/1000.:{fmt}} mm'
        z_str = f'{z/1000.:{fmt}} mm'

    elif COORDINATE_UNITS == 'm':
        x_str = f'{x:{fmt}} m'
        y_str = f'{y:{fmt}} m'
        z_str = f'{z:{fmt}} m'

    else:
        logging.error('invalid COORDINATE_UNITS input. Exiting.')
        sys.exit(1)
    
    return x_str, y_str, z_str, in_exclusion_zone


def main():
    logging.basicConfig(level=logging.INFO)
    sg.theme('DarkBlue13')
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
                [sg.Text('   Status: ', size=(11,1), font=('Work Sans', 20)), 
                 sg.Text('Acquiring Location', size=(30,1), font=('Work Sans', 20), justification='left', text_color='yellow', key='-MSG-')],
                [sg.Text(' '*40)],
                [sg.Text(' '*40)],
                [sg.Button('Exit', font=('Work Sans', 12)), sg.Button('Settings', font=('Work Sans', 12))],
             ]
    
    window = sg.Window('Hook Tracker', 
                        layout=layout, 
                        resizable=False,
                        icon='assets/favicon.ico'
                       )
    in_exclusion_zone = False
    msg_on = True  # funky way to make message flash 
    while True:
        event, values = window.read(timeout=UPDATE_FREQUENCY)
        logging.debug((event, values))

        if event in (sg.WIN_CLOSED,  'Exit'):
            break

        hedge_log = get_hedge_logfile()
        x,y,z,in_ez = get_hedge_position_from_log(hedge_log)

        if in_ez:
            logging.warning("Hedge in an exclusion zone!!")
            status_text = 'EXCLUSION ZONE' if msg_on else '' 
            msg_on = False if msg_on else True
            status_text_color = 'red'
            winsound.PlaySound("assets/alarm2.wav", winsound.SND_ASYNC | winsound.SND_LOOP)
            window['-MSG-'].update('INSIDE EXCLUSION ZONE')
            window['-MSG-'].update(text_color='red')
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