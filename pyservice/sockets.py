import socket
import os 

from .threads import PsThread
from .log import Level

from threading import Lock
import time

class PsSocket:
    _chunk = 16384
    
    def __init__(self, service, name='Socket', dead_status=['Dead'], log=True):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.service = service
        self.name = name
        self.service.sockets[self.name] = self
        self.socket_worker = None
        self.clients = {}
        self.client_cnt = 0
        self.role = None

        # Server
        self._connect_callback = None
        # self.max_client = 0 # 최대 연결 (미구현)

        # Status
        self.run_listen = False
        self.dead_status = dead_status

        self.log = log
        if self.log:
            self.service.log(Level.DEBUG, '(%s) New Socket was created' % (self.name, ), file=self.name)

    # 연결 메소드
    def bind(self, addr, port):
        id = 0
        self.close()
        self.socket.bind((addr, int(port)))
        self.socket.listen()
        self.run_listen = True
        self.socket_worker = PsThread(self.service, self.name+'-Server-'+str(id), target=self._server_work)
        self.socket_worker.start()
        self.role = 'Server'
        if self.log:
            self.service.log(Level.DEBUG, '(%s) New Socket listen at - (%s : %s)' % (self.name, addr, str(port)), file=self.name)
        
    def connect(self, addr, port):
        id = 0
        self.close()
        self.socket.connect((addr, int(port)))
        client_name = self.name + '-Client-' + str(id)
        client_worker = PsThread(self.service, client_name, target=self._recv_work, args=(id,))
        self.clients[id] = [self.socket, b'', Lock()]
        self.role = 'Client'
        client_worker.start()
        if self.log:
            self.service.log(Level.DEBUG, '(%s) New Socket connecting to - (%s : %s)' % (self.name, addr, str(port)), file=self.name)

    # 쓰레드 동작
    def _server_work(self):
        while self.service.status not in self.dead_status and self.run_listen:
            try:
                conn, addr = self.socket.accept()
                self.client_cnt += 1
                client_id = self.client_cnt
                client_name = self.name + '-Client-' + str(client_id)
                client_worker = PsThread(self.service, client_name, target=self._recv_work, args=(client_id,))
                self.clients[client_id] = [conn, b'', Lock()]
                client_worker.start()
                if self._connect_callback != None:
                    self._connect_callback(client_id)

                if self.log:
                    self.service.log(Level.DEBUG, '(%s) Accpet a connection from - (%s)' % (self.name, addr), file=self.name)
            except socket.error as e:
                self.service.log(Level.WARN, '(%s) socket listening closed' % (self.name,), file=self.name)
                break
    
    def set_connect_callback(self, func):
        self._connect_callback = func

    def _recv_work(self, client_id):
        while self.service.status not in self.dead_status:
            try:
                msg = self.clients[client_id][0].recv(1024)
                if msg == b'':
                    raise socket.error
                with self.clients[client_id][2]:
                    self.clients[client_id][1] = self.clients[client_id][1] + msg
                    if self.log:
                        self.service.log(Level.DEBUG, '(%s) Receive a message - "%s" from %d' % (self.name, msg, client_id), file=self.name)
                        self.service.log(Level.DEBUG, '(%s) %d - Message Buffer : %s' % (self.name, client_id, self.clients[client_id][1].decode()), file=self.name)
            except socket.error as e:
                self.close_connection(client_id)
                break

    # 상태
    def recv_available(self, id=0, until=None):
        conn, buf, buf_lock = self.clients[id]
        result = (0, 0)
        with buf_lock:
            if until == None:
                result = (len(buf), id)
            else:
                loc = buf.find(until.encode())
                if loc != -1:
                    result = (loc, id)
                else:
                    result = (0, id)
        return result

    def client_ids(self):
        return list(self.clients.keys())

    def close_connection(self, id):
        if id in self.clients:
            conn = self.clients[id][0]
            conn.close()
            del(self.clients[id])
            if self.log:
                self.service.log(Level.DEBUG, '(%s) close a connection from %d' % (self.name, id), file=self.name)

    def close(self):
        if len(self.client_ids()) > 0:
            if self.log:
                self.service.log(Level.DEBUG, '(%s) close socket connection' % (self.name, ), file=self.name)
        if self.role == 'Server':
            for id in self.client_ids():
                self.close_connection(id)
            self.socket.close()
        else:
            self.close_connection(0)
        self.clients = {}
        self.client_cnt = 0

    def send_bytes(self, msg:bytes, target=None|int):
        if target == None and self.role == 'Client':
            target = 0
        self.clients[target][0].send(msg)
        self.service.log(Level.DEBUG, '(%s) Send a message - "%s" to %d' % (self.name, msg, target), file=self.name)
    
    # 송수신 메소드
    def send_str(self, msg: str, target=None|int|list):
        if target == None and self.role == 'Client':
            self.socket.send(msg.encode())
            self.service.log(Level.DEBUG, '(%s) Send a message - "%s" to %d' % (self.name, msg, 0), file=self.name)
        else:
            try:
                if type(target) == int and target in self.clients:
                    self.clients[target][0].send(msg.encode())
                    if self.log:
                        self.service.log(Level.DEBUG, '(%s) Send a message - "%s" to %d' % (self.name, msg, target), file=self.name)
                elif type(target) == list:
                    for id in target:
                        self.send_str(msg, id)
                else:
                    print('send socket unknown')
            except socket.error as e:
                self.close_connection(target)
    
    def recv_str(self, max_length=0, until='\n', target=None):
        result = (None, target)
        if target == None:
            for id, (conn, buf, buf_lock) in self.clients.items():
                if self.recv_available(id, until)[0] >= 0:
                    result = self.recv_str(max_length, until, target=id)
        else:
            if self.recv_available(target, until)[0] >= 0:
                conn, buf, buf_lock = self.clients[target]
                with buf_lock:
                    if until == None:
                        msg = buf.decode()
                        self.clients[target][1] = b''
                        result = (msg, target)
                    else:
                        buf: bytes
                        cnt = buf.find(until.encode())
                        if cnt >= 0:
                            msg = buf[:cnt].decode()
                            self.clients[target][1] = buf[cnt+1:]
                            result = (msg, target)
                        else:
                            result = (None, target)
            else:
                result = (None, target)
        return result
    
    def send_file(self, file: str, target:int, dir='', show_dir=''):
        self.send_str('|file|%s|' % (os.path.join(show_dir, os.path.basename(file)), ), target)
        with open(os.path.join(dir, file), 'rb') as f:
            self.send_str(str(os.path.getsize(file)) + '|')
            while True:
                msg = f.read(PsSocket._chunk)
                if not msg:
                    break
                self.send_bytes(msg, target)

    def send_files(self, file_dir: str, target:int, dir='', show_dir=''):
        file_dir = os.path.join(dir, file_dir)
        if os.path.isdir(file_dir):
            _dir = file_dir
            _show_dir = os.path.join(show_dir, os.path.basename(file_dir))
            self.send_str('|dir|%s|' % (_show_dir, ), target)

            for f in os.listdir(file_dir):
                self.send_files(f, target, _dir, _show_dir)
        else:
            self.send_file(os.path.join(dir, file_dir), target, dir, show_dir)
