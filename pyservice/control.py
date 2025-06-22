from abc import ABCMeta, abstractmethod

import signal
from threading import Lock
import time

from .threads import PsThread
from .sockets import PsSocket

from .works import *

# Commander
# 서비스 명령기
class Commander (metaclass=ABCMeta):
    def __init__(self, id, control):
        self.id = id
        self.control = control

    def _show_ready(self):
        self.print('\n[ %s ] $> ' % (self.control.service.name(),), end='')

    @abstractmethod
    def handle(self, cmd_str):
        pass

    @abstractmethod
    def print(self, str, end='\n'):
        pass


class CommanderConsole (Commander):
    def __init__(self, id, control):
        super().__init__(id, control)
        self.console_worker = PsThread(self.control.service, id, target=self._console)
        self.console_worker.start()
        self.cmd_str = None
    
    def _console(self):
        while self.control.service.is_alive:
            cmd_str = input()
            self.control._commanding(self.id, cmd_str)
    
    def handle(self, cmd_str):
        self.control.command(self, cmd_str)

    def print(self, str, end='\n'):
        print(str, end=end)


class CommanderSocket (Commander):
    def __init__(self, id, control, socket: PsSocket):
        super().__init__(id, control)
        self.socket = socket
        self.recv_worker = PsThread(self.control.service, self.id, target=self._receive)
        self.recv_worker.start()

    def _receive(self):
        while self.control.service.is_alive:
            msg, sock_id = self.socket.recv_str()
            if sock_id != None and msg != None:
                self.control._commanding(self.id, msg, sock_id)
            time.sleep(0.1)

    def _new_connection(self, id):
        self.control._commanding(self.id, 'NOP', id)
            
    def handle(self, cmd_str):
        self.control.command(self, cmd_str)

    def print(self, str, end='\r\n'):
        self.socket.send_str(str + end, self.control.commander_sep)


class CommanderService (Commander):
    def handle(self, cmd_str):
        self.control.command(self, cmd_str)

    def print(self, str, end='\n'):
        print(str, end=end)

# Controller
# 서비스 명령 처리기
class Controller:
    def __init__(self, service):
        self.service = service
        
        self.works = {
            'NOP': WorkNop,
            'start': WorkStart,
            'stop': WorkStop,
            'restart': WorkRestart, 
            'status': WorkStatus,
            'version': WorkVersion,
            'ps': {
                'services': WorkServices,
                'versions': WorkShowVersions,
                'latest': WorkCheckLatest,
                'update': WorkUpdate, 
            },
            'file': {
                'list': WorkFileList,
            },
            'unknown': WorkUnknown,
        }
        self.works = self._set_command([], self.works)
        self.commader_sig = signal.signal(signal.SIGINT, self._handle)
        self.commanders = {}
        self.commander_cmd = ''
        self.commander_id = ''
        self.commander_sep = 0
        self.commander_lock = Lock()
        self.commanders['Ps'] = CommanderService('Ps', self)

        conf = self.service.config['PyService']
        if int(conf['use_console']) == 1:
            self.commanders['Commander-Console'] = CommanderConsole('Commander-Console', self)
        if int(conf['use_socket']) == 1:
            self.socket = PsSocket(self.service, 'Commander-Socket')
            self.commanders['Commander-Socket'] = CommanderSocket('Commander-Socket', self, self.socket)
            self.socket.set_connect_callback(self.commanders['Commander-Socket']._new_connection)
            self.socket.bind(conf['cmd_address'], conf['cmd_port'])

    def _cmd_prework(cmd):
        new_cmd = []
        for c in cmd:
            if c == '\b' and new_cmd:
                new_cmd.pop()
            else:
                new_cmd.append(c)
        new_cmd = ''.join(new_cmd)
        return new_cmd.strip()

    def _commanding(self, commander_id, commander_cmd, sep=0):
        self.commander_lock.acquire()
        self.commander_id = commander_id
        self.commander_cmd = Controller._cmd_prework(commander_cmd)
        self.commander_sep = sep
        signal.raise_signal(signal.SIGINT)

    def _handle(self, signum, frame):
        commander = self.commanders[self.commander_id]
        commander.handle(self.commander_cmd)
        self.commander_lock.release()
        commander._show_ready()

    def _set_command(self, up_key: list, works: dict|Work):
        for key, work in works.items():
            if type(work) == dict:
                works[key] = self._set_command([*up_key, key], work)
            elif issubclass(work, Work):
                works[key] = works[key](self.service, up_key.append(key))
        return works

    def _command(self, commander, cmds, works):
        if isinstance(works, Work):
            works.exec(commander, cmds)
        else:
            cmd = cmds.pop(0)
            if cmd in works:
                self._command(commander, cmds, works[cmd])
            else:
                self.works['unknown'].exec(commander, cmd)

    def set_work(self, key: list, work: Work):
        current_key = key.pop(0)
        works = self.works
        result = True
        while current_key in works:
            if type(current_key) == dict:
                works = works[current_key]
            else:
                result = False
                break
        if result:
            works[current_key] = work
        return result
    
    def command(self, commander, cmd_str: str): 
        print(cmd_str)
        cmds = [c.strip() for c in cmd_str.split(' ')]
        self._command(commander, cmds, self.works)

        
