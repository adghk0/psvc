from abc import ABCMeta, abstractmethod

import os
import time, traceback
import re

from configparser import ConfigParser

from .file import ps_path, copy
from .sockets import PsSocket
from .log import Level

_rollback_ignore = [
    re.compile(r'(^|[/\\])\.[^/\\]+'),  # .으로 시작하는 파일/폴더
    re.compile(r'(^|[/\\])log$'),       # log로 끝나는 파일/폴더
    re.compile(r'\.conf$'),             # .conf로 끝나는 파일
]

# Work
# 서비스 명령어
class Work (metaclass=ABCMeta):
    def __init__(self, service, key):
        self.key = key
        self.service = service

    @abstractmethod
    def exec(self, commander, param):
        pass


# === Default ===

class WorkNop (Work):
    def exec(self, commander, param):
        pass


class WorkStart (Work):
    def exec(self, commander, param):
        self.service._start()
        commander.print('Service Started')


class WorkStop (Work):
    def exec(self, commander, param):
        commander.print('Service Stopping...')
        self.service._stop()


class WorkRestart (Work):
    def exec(self, commander, param):
        commander.print('Service Restarting...')
        self.service._restart()


class WorkUnknown (Work):
    def exec(self, commander, param):
        commander.print('unknown command - ' + param)


class WorkStatus (Work):
    def exec(self, commander, param):
        commander.print('status!!!')
        for name, tr in self.service.threads.items():
            commander.print(name + ' - ' + str(tr.is_alive()))

class WorkVersion (Work):
    def exec(self, commander, param):
        commander.print(self.service.version)


class WorkExit (Work):
    def exec(self, commander, param):
        commander.exit()


# === Version ===

class WorkCheckUpdate (Work):
    def exec(self, commander, param):
        service = commander.control.service
        result = (None, '')
        try:
            sock = PsSocket(service, name='UpdateSocket')
            sock.connect(service.update_server, service.update_port)
            sock.send_str('latest %s\n' % (param[0],) )
            latest = sock.recv_str()[0].strip()
            commander.print(latest + '\r\n')
            if latest.split('.') > service.ps_version.split('.'):
                result = (True, latest)
            else:
                result = (False, '')
        except Exception as e:
            service.log_warn('Cannot connect to update server (%s)' % (param[0],))
            service.log(Level.DEBUG, traceback.format_exc())
        finally:
            if sock:
                sock.close()
        return result
        

class WorkUpdate (Work):
    def exec(self, commander, param):
        service = commander.control.service
        sock = None
        try:
            copy(service.root_path, os.path.join(service.root_path, '.rollback', service.name), _rollback_ignore)
            sock = PsSocket(service, name='UpdateSocket')
            sock.connect(service.update_server, service.update_port)
            sock.send_str('req %s %s\n' % (param[0], param[1]))
            sock.recv_files(service.root_path)
            service.set_config(param[0], 'version', param[1])
        except Exception as e:
            service.log_warn('Cannot update from update server (%s)' % (param[0],))
            service.log(Level.DEBUG, traceback.format_exc())
        finally:
            if sock:
                sock.close()

# === File ===

class WorkFileList (Work):
    def exec(self, commander, param):
        if len(param) > 0:
            path = ps_path(commander.control.service, param[0])
        else:
            path = commander.control.service.root_path
        if os.path.exists(path) and os.path.isdir(path):
            commander.print('=== File List at %s ===' % (path,))
            for l in os.listdir(path):
                commander.print(l)
            commander.print('=== End of List ===')
        else:
            commander.print('%s is not Exist' % (path, ))
