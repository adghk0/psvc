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
        self.print('\n[ %s ] $> ' % (self.control.service.name, ), end='')

    @abstractmethod
    def handle(self, cmd_str):
        pass

    @abstractmethod
    def print(self, str, end='\n'):
        pass

    @abstractmethod
    def exit(self):
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

    def exit(self):
        self.print('Console commander can not exit')


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

    def exit(self):
        id = self.control.commander_sep
        self.socket.close_connection(id)


class CommanderService (Commander):
    def handle(self, cmd_str):
        self.control.command(self, cmd_str)

    def print(self, str, end='\n'):
        print(str, end=end)

    def exit(self):
        pass

# Controller
# 서비스 명령 처리기
class Controller:
    def __init__(self, service, least=False):
        self.service = service
        self.least = least

        if not least:
            self.works = {
                'NOP': WorkNop,
                'start': WorkStart,
                'stop': WorkStop,
                'restart': WorkRestart, 
                'status': WorkStatus,
                'version': WorkVersion,
                'exit': WorkExit,
                'ps': {
                    'check_update': WorkCheckUpdate,
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
            self._command_result = None
            self.command_wait = False
            self.commander_lock = Lock()
            self.commanders['Ps'] = CommanderService('Ps', self)

            conf = self.service.config[self.service.name]

            # Console
            if 'use_console' in conf and int(conf['use_console']) == 1:
                n = '%s-Commander-Socket' % (self.service.name,)
                self.commanders[n] = CommanderConsole(n, self)

            # Socket
            self.socket = PsSocket(self.service, 'Commander-Socket')
            n = '%s-Commander-Socket' % (self.service.name,)
            self.commanders[n] = CommanderSocket(n, self, self.socket)
            self.socket.set_connect_callback(self.commanders[n]._new_connection)
            if 'cmd_bind' not in conf:
                bind_addr = '127.0.0.1'
            else:
                bind_addr = conf['cmd_bind']
            self.service.log(Level.SYSTEM, '(%s) Command Port = %s' % (self.service.name, conf['cmd_port']))
            self.socket.bind(bind_addr, conf['cmd_port'])

        else:
            self.works = {}
            self.commader_sig = signal.signal(signal.SIGTERM, self._handle)
            self.commanders = {}
            self.commander_cmd = ''
            self.commander_id = ''
            self.commander_sep = 0
            self._command_result = None
            self.command_wait = False
            self.commander_lock = Lock()
            self.commanders['Ps'] = CommanderService('Ps', self)

    def _cmd_prework(cmd):
        new_cmd = []
        for c in cmd:
            if c == '\b' and new_cmd:
                new_cmd.pop()
            else:
                new_cmd.append(c)
        new_cmd = ''.join(new_cmd)
        return new_cmd.strip()

    def _commanding(self, commander_id, commander_cmd, sep=0, wait=False):
        self.commander_lock.acquire()
        self._command_result = None
        self.command_wait = wait
        self.commander_id = commander_id
        self.commander_cmd = Controller._cmd_prework(commander_cmd)
        self.commander_sep = sep
        if self.least:
            signal.raise_signal(signal.SIGTERM)
        else:
            signal.raise_signal(signal.SIGINT)

    def _handle(self, signum, frame):
        commander = self.commanders[self.commander_id]
        commander.handle(self.commander_cmd)
        if not self.command_wait:
            self.commander_lock.release()
        if not self.least:
            commander._show_ready()

    def _set_command(self, up_key: list, works: dict|Work):
        for key, work in works.items():
            if type(work) == dict:
                works[key] = self._set_command([*up_key, key], work)
            elif issubclass(work, Work):
                works[key] = works[key](self.service, up_key.append(key))
        return works

    def _command(self, commander, cmds, works):
        result = None
        if isinstance(works, Work):
            result = works.exec(commander, cmds)
        else:
            cmd = cmds.pop(0)
            if cmd in works:
                result = self._command(commander, cmds, works[cmd])
            else:
                if not self.least:
                    self.works['unknown'].exec(commander, cmd)
        return result

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
            works[current_key] = work(self.service, key)
        return result
    
    def command(self, commander, cmd_str: str): 
        cmds = [c.strip() for c in cmd_str.split(' ')]
        try:
            self._command_result = self._command(commander, cmds, self.works)
        except:
            self.service.log_err('Controller Execute Error')
        if self._command_result == None:
            self._command_result = 1
    
    @property
    def command_finished(self):
        return self._command_result != None

    def command_result(self):
        result = self._command_result
        self.commander_lock.release()
        return result

        
