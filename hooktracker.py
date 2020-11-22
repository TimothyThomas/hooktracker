import socket
import logging
import time

def main():
    logging.basicConfig(level=logging.INFO)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    #udp_ip = socket.gethostname()
    udp_ip = 'localhost' 
    udp_port = 49100

    logging.info(f'Binding to UDP socket {udp_ip}:{udp_port}.')
    sock.bind(('localhost', udp_port))

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
        logging.info(f"X={xpos}, Y={ypos}, Z={zpos}")

        time.sleep(2.)



if __name__ == '__main__':
    main()