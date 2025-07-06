import socket
import os 

from .threads import PsThread
from .log import Level
from .file import mkdir

from threading import Lock
import time
import re

class PsSocket:
    _chunk = 16384
    _file_re = re.compile(r'^\|(.+)\|$')
    
    def __init__(self, service, name='Socket', dead_status=['Dead'], log=True):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.service = service
        self.name = name
        self.service.sockets[self.name] = self
        self.socket_worker = None
        self.clients = {}
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
        
    def reconnect(self):
        self.__init__(self.service, self.name, self.dead_status, self.log)
        self.connect(self.addr, self.port)

    def connect(self, addr, port):
        id = 0
        self.close()
        self.addr = addr
        self.port = port
        self.socket.connect((addr, int(port)))
        client_name = self.name + '-Client-' + str(id)
        client_worker = PsThread(self.service, client_name, target=self._recv_work, args=(id,))
        self.clients[id] = [self.socket, b'', Lock()]
        self.role = 'Client'
        client_worker.start()
        if self.log:
            self.service.log(Level.DEBUG, '(%s) New Socket connecting to - (%s : %s)' % (self.name, addr, str(port)), file=self.name)

    def _min_index(self):
        result = None
        cnt = 0
        while result == None:
            cnt += 1
            if cnt not in self.clients:
                result = cnt
                break
        return result

    # 쓰레드 동작
    def _server_work(self):
        while self.service.status not in self.dead_status and self.run_listen:
            try:
                conn, addr = self.socket.accept()
                client_id = self._min_index()
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
                        self.service.log(Level.DEBUG, '(%s) Receive a message - "%s" (%d) from %d' % (self.name, msg, len(msg), client_id), file=self.name)
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
            del(self.clients[id])
            conn.close()
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
        self.role = None
        self.clients = {}
        self.client_cnt = 0

    def send_bytes(self, msg:bytes, target:None|int=None):
        if target == None and self.role == 'Client':
            target = 0
        self.clients[target][0].send(msg)
        if self.log:
            self.service.log(Level.DEBUG, '(%s) Send a message - "%s" (%d) to %d' % (self.name, msg, len(msg), target), file=self.name)
    
    # 송수신 메소드
    def send_str(self, msg: str, target:None|int|list=None):
        if target == None and self.role == 'Client':
            self.socket.send(msg.encode())
            if self.log:
                if len(msg) > 10:
                    show_msg = msg[:10]
                else:
                    show_msg = msg
                self.service.log(Level.DEBUG, '(%s) Send a message - "%s" (%d) to %d' % (self.name, show_msg, len(msg), 0), file=self.name)
        else:
            try:
                if type(target) == int and target in self.clients:
                    self.clients[target][0].send(msg.encode())
                    if self.log:
                        if len(msg) > 10:
                            show_msg = msg[:10]
                        else:
                            show_msg = msg
                        self.service.log(Level.DEBUG, '(%s) Send a message - "%s" (%d) to %d' % (self.name, show_msg, len(msg), target), file=self.name)
                elif type(target) == list:
                    for id in target:
                        self.send_str(msg, id)
                else:
                    print('send socket unknown')
            except socket.error as e:
                self.close_connection(target)
    
    def send_file(self, file: str, target:int, show_dir=''):
        self.send_str('|file,%s|\n' % (os.path.join(show_dir, os.path.basename(file))), target)

        with open(file, 'rb') as f:
            self.send_str(str(os.path.getsize(file)) + '\n', target)
            while True:
                msg = f.read(PsSocket._chunk)
                if not msg:
                    break
                self.send_bytes(msg, target)

    def send_files(self, file_dir: str, target:int, dir='', show_dir=''):
        file_dir = os.path.join(dir, file_dir)
        if show_dir == '':
            self.send_str('|files_start|\n',target)

        if os.path.isdir(file_dir):
            for f in os.listdir(file_dir):
                if os.path.isdir(os.path.join(file_dir, f)):
                    _show_dir = os.path.join(show_dir, f)
                    self.send_str('|dir,%s|\n'% (_show_dir, ), target)
                    self.send_files(f, target, file_dir, _show_dir)
                else:
                    self.send_file(os.path.join(file_dir, f), target, show_dir)        
        else:
            self.send_file(file_dir, target, show_dir)

        if show_dir == '':
            self.send_str('|files_end|\n', target)

    def recv_bytes(self, max_length, target: int = 0):
        data = b''
        while len(data) < max_length:
            with self.clients[target][2]:  # Lock
                buf = self.clients[target][1]
                if len(buf) == 0:
                    pass  # 아무것도 수신되지 않았음
                else:
                    to_take = min(max_length - len(data), len(buf))
                    data += buf[:to_take]
                    self.clients[target][1] = buf[to_take:]  # 남은 건 다시 저장
            if len(data) < max_length:
                time.sleep(0.01)  # 잠깐 기다리기
        return data
        
    def recv_str(self, max_length=0, until='\n', target=None, wait=True):
        result = (None, target)
        recv_end = False

        if target == None:
            while wait and not recv_end:
                for id, (conn, buf, buf_lock) in self.clients.items():
                    result = self.recv_str(max_length, until, target=id, wait=False)
                    if result[0] != None:
                        recv_end = True
                time.sleep(0.1)
        
        else:
            while not recv_end:
                if self.recv_available(target, until)[0] > 0:
                    conn, buf, buf_lock = self.clients[target]
                    with buf_lock:
                        if until == None:
                            msg = buf.decode()
                            self.clients[target][1] = b''
                            result = (msg, target)
                            recv_end = True
                        else:
                            buf: bytes
                            cnt = buf.find(until.encode())
                            if cnt >= 0:
                                msg = buf[:cnt].decode()
                                self.clients[target][1] = buf[cnt+1:]
                                result = (msg, target)
                                recv_end = True
                            else:
                                time.sleep(0.1)
                else:
                    if not wait:
                        recv_end = True
                        result = (None, target)

        return result

    def recv_file(self, file_path, target:int=0):
        size = int(self.recv_str(target=target)[0].strip())
        c_size = 0
        with open(file_path, 'wb') as f:
            while c_size < size:
                msg = self.recv_bytes(min(PsSocket._chunk, size - c_size), target)
                c_size += len(msg)
                self.service.log(0, '%d, %d, %d' % (size, len(msg), c_size), 'Debug' )
                self.service.log(0, '%s' % msg, 'Debug' )
                f.write(msg)
        
    def recv_files(self, file_dir, target:int=0):
        while True:
            rec = self.recv_str(target=target)[0].strip()
            rec_find = self._file_re.findall(rec)
            if rec_find:
                msg = rec_find[0]
                if msg == 'files_start':
                    pass
                elif msg.startswith('dir,'):
                    t_path = os.path.join(file_dir, msg.split(',')[1])
                    if not os.path.isdir(t_path):
                        mkdir(t_path)
                elif msg.startswith('file,'):
                    t_path = os.path.join(file_dir, msg.split(',')[1])
                    self.recv_file(t_path, target)
                else:
                    break
            else:
                print(rec)
