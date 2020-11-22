import socket
import logging
import time

import PySimpleGUIQt as sg

def main():
    logging.basicConfig(level=logging.INFO)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    #udp_ip = socket.gethostname()
    udp_ip = 'localhost' 
    udp_port = 49100

    logging.info(f'Binding to UDP socket {udp_ip}:{udp_port}.')
    sock.bind(('localhost', udp_port))

    sg.theme('DarkAmber')   # Add a touch of color
    # All the stuff inside your window.
    layout = [  [sg.Text('Some text on Row 1')],
                [sg.Text('Enter something on Row 2'), sg.InputText()],
                [sg.Button('Ok'), sg.Button('Cancel')] ]
    
    # Create the Window
    window = sg.Window('Window Title', layout)
    # Event Loop to process "events" and get the "values" of the inputs
    while True:
        event, values = window.read()
        if event == sg.WIN_CLOSED or event == 'Cancel': # if user closes window or clicks cancel
            break
        print('You entered ', values[0])
    
    while True:
        data, addr = sock.recvfrom(2048)
        logging.info(f"Received message: {data}")

        # See marvelmind.com/pics/dashboard_udp_protocol.pdf
        # This is the protocol for packets with mm resolution coordinates
        # (dashboard V4.92+, modem/beacon V5.35)
        addr = data[0] 
        packet_type = data[1] 
        data_size = data[4]
        data_code = int.from_bytes(data[2:4], byteorder='little', signed=False)
        timestamp = int.from_bytes(data[5:9], byteorder='little', signed=False)
        x_mm = int.from_bytes(data[9:13], byteorder='little', signed=True)
        y_mm = int.from_bytes(data[13:17], byteorder='little', signed=True)
        z_mm = int.from_bytes(data[17:21], byteorder='little', signed=True)

        logging.info(f"Data for address: {addr}")
        logging.info(f"Packet type: {packet_type}")
        logging.info(f"data_code: {data_code}")
        logging.info(f"data_size: {data_size}")
        logging.info(f"timestamp: {timestamp}")
        logging.info(f"X={x_mm}, Y={y_mm}, Z={z_mm}")

        time.sleep(2.)

    window.close()


if __name__ == '__main__':
    main()