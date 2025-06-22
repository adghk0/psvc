import socket

from .main import Service
from .control import Work
from .threads import PsThread

class ServerService (Service):
    def init(self):
        self.service_conf = self.config['PyService']
        self.server_conf = self.config['PsServer']
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind((self.server_conf['address'], int(self.server_conf['port'])))
        self.socket_worker = PsThread(self, 'Server-Socket', target=self._socket_work)

    def _socket_work(self):
        while self.is_alive:
            conn, addr = self.socket.listen()


    def name(self):
        pass

    def run(self):
        pass

# Server 
class WorkRelease (Work):
    def exec(self, commander, param):
        pass
