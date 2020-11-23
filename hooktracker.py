import socket
import logging
import time
import sys

import PySimpleGUIQt as sg

DASHBOARD_UDP_PORT = 49100
COORDINATE_PRECISION = 0    # number of digits after decimal
UPDATE_FREQUENCY = 1000      # time in milliseconds
COORDINATE_UNITS = 'feet.inches'  #  feet.inches, inches, mm

def connect_to_udp_stream():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    #udp_ip = socket.gethostname()
    udp_ip = 'localhost' 
    logging.info(f'Binding to UDP socket {udp_ip}:{DASHBOARD_UDP_PORT}.')
    sock.bind(('localhost', DASHBOARD_UDP_PORT))
    return sock


def get_hedge_coords():
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


def main():
    logging.basicConfig(level=logging.INFO)

    x,y,z = get_hedge_coords()

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
        if event in (sg.WIN_CLOSED,  'Exit'):
            break

        x,y,z = get_hedge_coords()
        window['-XPOS-'].update(f'X: {x}')
        window['-YPOS-'].update(f'Y: {y}')
        window['-ZPOS-'].update(f'Z: {z}')

    window.close()


if __name__ == '__main__':
    main()