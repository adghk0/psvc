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
        self.log_debug(self.cnt, 'Count')
        self.cnt += 1
        time.sleep(1)

if __name__ == '__main__':
    ts = TestService(__file__, './service_test.conf')
    ts.command('start')

    while ts.is_alive:
        time.sleep(1)