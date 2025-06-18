from abc import ABCMeta, abstractmethod
from threading import Thread
import socket
import signal
from threading import Thread, Lock

# Work
# 서비스 명령어
class Work (metaclass=ABCMeta):
    def __init__(self, service, key):
        self.key = key
        self.service = service

    @abstractmethod
    def exec(self, commander, param):
        pass


class WorkStart (Work):
    def exec(self, commander, param):
        self.service._start()


class WorkStop (Work):
    def exec(self, commander, param):
        self.service._stop()


class WorkUnknown (Work):
    def exec(self, commander, param):
        commander.print('unknown command - ' + param)


class WorkStatus (Work):
    def exec(self, commander, param):
        commander.print('status!!!')


# Commander
# 서비스 명령기
class Commander (metaclass=ABCMeta):
    def __init__(self, id, control):
        self.id = id
        self.control = control

    @abstractmethod
    def handle(self, cmd_str):
        pass

    @abstractmethod
    def print(self, str):
        pass


class CommanderConsole (Commander):
    def __init__(self, id, control):
        super().__init__(id, control)
        self.console_worker = Thread(target=self._console, name='CMD-'+id)
        self.console_worker.start()
        self.cmd_str = None
    
    def _console(self):
        while self.control.service.status not in ['Dead']:
            cmd_str = input('>')
            self.control._commanding(self.id, cmd_str)
            signal.raise_signal(signal.SIGINT)
    
    def handle(self, cmd_str):
        self.control.command(self, cmd_str)

    def print(self, str):
        print(str)


class CommanderSocket (Commander):
    def __init__(self, id, control, socket: socket.socket):
        super().__init__(id, control)
        self.socket = socket
        self.recv_worker = Thread(target=self._receive, name='CMD-'+id)
        self.recv_worker.start()

    def _receive(self):
        while self.control.service.status not in ['Dead']:
            self.socket.send('>'.encode())
            cmd_ended = False
            msg = ''
            while not cmd_ended:
                msg += self.socket.recv(1024).decode()
                if msg.endswith('\n'):
                    cmd_ended = True
            self.control._commanding(self.id, msg.replace('\n', ''))
            signal.raise_signal(signal.SIGINT)
            
    def handle(self, cmd_str):
        self.print('executting...')
        self.control.command(self, cmd_str)

    def print(self, str):
        self.socket.send((str + '\n').encode())


# Controller
# 서비스 명령 처리기
class Controller:
    def __init__(self, service):
        self.service = service
        
        self.works = {
            'start': WorkStart,
            'stop': WorkStop,
            'unknown': WorkUnknown, 
            'status': WorkStatus,
        }
        self.works = self._set_command([], self.works)
        self.commader_sig = signal.signal(signal.SIGINT, self._handle)
        self.commanders = {}
        self.commander_cmd = ''
        self.commander_id = ''
        self.commander_lock = Lock()

        conf = self.service.config['PyService']
        if conf['use_console']:
            self.commanders['Console'] = CommanderConsole('Console', self)
        if conf['use_socket']:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.bind((conf['address'], int(conf['port'])))
            print('waiting for the socket connection in', conf['address'], conf['port'])
            self.socket.listen()
            self.socket_worker = Thread(target=self._socket_work, name='Controller-SocketWorker')
            self.socket_cnt = 0
            self.socket_worker.start()
    
    def _commanding(self, commander_id, commander_cmd):
        with self.commander_lock:
            self.commander_id = commander_id
            self.commander_cmd = commander_cmd

    def _handle(self, signum, frame):
        commander = self.commanders[self.commander_id]
        commander.handle(self.commander_cmd)

    def _set_command(self, up_key: list, works: dict):
        for key, work in works.items():
            if issubclass(work, Work):
                works[key] = works[key](self.service, up_key.append(key))
            else:
                works[key] = self._set_command(up_key.append(key), work)
        return works
    
    def _socket_work(self):
        while self.service != 'Dead':
            conn, addr = self.socket.accept()
            socket_id = 'Socket' + str(self.socket_cnt)
            self.commanders[socket_id] = CommanderSocket(socket_id, self, conn)
            self.socket_cnt += 1
            print('new socket connection in', addr, socket_id)

    def _command(self, commander, cmds, works):
        if isinstance(works, Work):
            works.exec(commander, cmds)
        else:
            cmd = cmds.pop(0)
            if cmd in works:
                self._command(commander, cmds, works[cmd])
            else:
                self.works['unknown'].exec(commander, cmd)

    def command(self, commander, cmd_str: str):
        cmds = cmd_str.split(' ')
        self._command(commander, cmds, self.works)
        

