import socket
import logging
import time
import sys
import os
from pathlib import Path

import PySimpleGUIQt as sg
from file_read_backwards import FileReadBackwards

DASHBOARD_UDP_PORT = 49100
COORDINATE_PRECISION = 0    # number of digits after decimal
UPDATE_FREQUENCY = 1000      # time in milliseconds
COORDINATE_UNITS = 'feet.inches'  #  feet.inches, inches, mm
LOG_FILE_DIRECTORY = Path('C:\Marvelmind\dashboard\logs')
LOGFILE_LINE_INDEX_FROM_END = 2   # Recommended value is 2.  e.g., if =2, read second line counting from end of logfile
                                  # We don't want to read the last line of the logfile because it is often not completely
                                  # written at the time it is read.
HEDGE_ADDR = 36


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
    return current_log


def get_last_logfile_line(logfile, addr):
    """Return most recent complete line written to CSV log file for hedge addr.""" 
    #  Use this method so we don't have to read the entire file:
    #  stackoverflow.com/a/54278929
    with open(logfile, 'rb') as f:
        f.seek(-2, os.SEEK_END)
        end_lines = 0
        line_found = False
        while not line_found:
            while end_lines < LOGFILE_LINE_INDEX_FROM_END:
                next_char = f.read(1)
                if next_char == b'\n' :
                    end_lines += 1
                if end_lines < LOGFILE_LINE_INDEX_FROM_END:
                    f.seek(-2, os.SEEK_CUR)
            last_line = f.readline().decode()
            last_line_fields = [x for x in last_line.strip().split(',') if x]  # we want to ignore the final empty field since most lines end with ','
            if int(last_line_fields[3]) == addr:
                line_found = True
            else:
                end_lines = 1
        logging.info(f'Logfile data: {last_line}')
    return last_line_fields

def parse_log_file_fields(fields):
    unix_time = int(fields[0])
    addr = int(fields[3])
    x_m, y_m, z_m = float(fields[4]), float(fields[5]), float(fields[6])
    logging.info(f'exclusion zone field: {fields[-6:]}')
    in_exclusion_zone = True if int(fields[-4]) else False
    
    fmt = f'.{COORDINATE_PRECISION}f'
    if COORDINATE_UNITS == 'feet.inches':
        x = f"""{x_m / 0.0254 // 12}\' {x_m / 0.0254 % 12:{fmt}}\""""
        y = f"""{y_m / 0.0254 // 12}\' {y_m / 0.0254 % 12:{fmt}}\""""
        z = f"""{z_m / 0.0254 // 12}\' {z_m / 0.0254 % 12:{fmt}}\""""
    
    elif COORDINATE_UNITS == 'inches':
        x = f'{x_m / 0.0254:{fmt}}'
        y = f'{y_m / 0.0254:{fmt}}'
        z = f'{z_m / 0.0254:{fmt}}'
    
    elif COORDINATE_UNITS == 'mm':
        x = f'{x_m/1000.:{fmt}}'
        y = f'{y_m/1000.:{fmt}}'
        z = f'{z_m/1000.:{fmt}}'

    else:
        logging.error('invalid COORDINATE_UNITS input. Exiting.')
        sys.exit(1)

    logging.info(f"Data for address: {addr}")
    logging.info(f"timestamp: {unix_time}")
    logging.info(f"X={x}, Y={y}, Z={z}")

    return x, y, z, addr, unix_time, in_exclusion_zone


def main():
    logging.basicConfig(level=logging.INFO)

    hedge_log = get_hedge_logfile()
    if hedge_log:
        logging.info(f"Reading hedge logfile {hedge_log}.")
    else:
        logging.info(f"No hedge log found. Ensure hedge logfile is being written and restart program.")
        sys.exit(1)
    
    #x,y,z = get_hedge_pos_udp()

    log_data = get_last_logfile_line(hedge_log, HEDGE_ADDR)
    x, y, z, addr, unix_time, in_exclusion_zone = parse_log_file_fields(log_data)

    sg.theme('DarkBlue13')   # Add a touch of color
    # All the stuff inside your window.
    layout = [
                [sg.Image('logo/RVB_FRAMATOME_HD_10pct.png')],
                [sg.Text('Crane Hook Tracker', size=(30,2), font=('Work Sans', 14), justification='center')],
                [sg.Text(f'X: {x}', size=(30,1), font=('Work Sans', 20), justification='center', key='-XPOS-')],
                [sg.Text(f'Y: {y}', size=(30,1), font=('Work Sans', 20), justification='center', key='-YPOS-')],
                [sg.Text(f'Z: {z}', size=(30,1), font=('Work Sans', 20), justification='center', key='-ZPOS-')],
                [sg.Text(f'', size=(30,1))],
                [sg.Button('Exit', font=('Work Sans', 12), size=(30,2))],
             ]
    
    # Create the Window
    window = sg.Window('Hook Tracker', layout)
    # Event Loop to process "events" and get the "values" of the inputs
    while True:
        event, values = window.read(timeout=UPDATE_FREQUENCY)
        logging.info((event, values))
        log_data = get_last_logfile_line(hedge_log, HEDGE_ADDR)
        if event in (sg.WIN_CLOSED,  'Exit'):
            break

        #x,y,z = get_hedge_pos()
        x, y, z, addr, unix_time, in_exclusion_zone = parse_log_file_fields(log_data)
        window['-XPOS-'].update(f'X: {x}')
        window['-YPOS-'].update(f'Y: {y}')
        window['-ZPOS-'].update(f'Z: {z}')

        if in_exclusion_zone:
            logging.warn("WARNING: you have entered an exclusion zone!!")

    window.close()


if __name__ == '__main__':
    main()