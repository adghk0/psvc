from abc import ABCMeta, abstractmethod

import os
import time, traceback

from .file import ps_path, copy
from .sockets import PsSocket
from .log import Level

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
        info = service.services[param[0]]
        result = (None, '')
        try:
            sock = PsSocket(service, name='UpdateSocket')
            sock.connect(info[1], info[2])
            sock.send_str('latest')
            latest = sock.recv_str()[0].strip()
            if latest > info[0]:
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
        info = service.services[param[0]]
        try:
            copy(service.pgm_path, os.path.join(service.pgm_path, '.rollback'))
            sock = PsSocket(service, name='UpdateSocket')
            sock.connect(info[1], info[2])
            sock.send_str('req %s' % param[1])
            sock.recv_files(service.pgm_path)
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
