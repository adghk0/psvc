import socket
from threading import Thread
import time

sock = None

def recv():
    while True:
        msg = sock.recv(1024).decode()
        if msg != '':
            print(msg)
        time.sleep(1)
        
addr = '127.0.0.1'
port = 50000

if __name__ == '__main__':
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((addr, port))
    sock_tr = Thread(target=recv)
    sock_tr.start()
    while True:
        sock.send((input()+'\n').encode())
