import socket
from threading import Thread
import time
import sys, os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pyservice import Service
from pyservice.sockets import PsSocket
from pyservice.threads import PsThread

class TestService (Service):
    def init(self):
        self.cnt = 0
        self.descnt = 0
    
    def name(self):
        return 'TestService'
        
    def run(self):
        print(self.cnt)
        self.cnt += 1
        time.sleep(1)
        

addr = '127.0.0.1'
port = 40000

def _read(sock):
    while True:
        if sock.recv_available()[0] > 0:
            print(sock.recv_str(until = None))
        else:
            time.sleep(0.1)

if __name__ == '__main__':

    role = input()
    ts = TestService(__file__, './sock_test.conf')
    sock = PsSocket(ts)

    if role == 's':
        addr = '0.0.0.0'
        sock.bind(addr, port)
        
        while ts.is_alive:
            (msg, target) = sock.recv_str(until = None)
            if msg != None:
                ids = sock.client_ids()
                print('Message From (%d) - %s' % (target, msg))
                sock.send_str('Message From (%d) - %s\n' % (target, msg), ids)
            else:
                time.sleep(0.1)

    else:
        port = input()
        sock.connect(addr, port.strip())
        tr = PsThread(ts, 'Reader', target=_read, args=(sock, ))
        tr.start()
        while True:
            msg = input()
            sock.send_str(msg + '\n')
