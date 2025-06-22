from abc import ABCMeta, abstractmethod

import os

from .file import ps_path

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


# === Version ===

class WorkServices (Work):
    def exec(self, commander, param):
        pass


class WorkShowVersions(Work):
    def exec(self, commander, param):
        pass


class WorkCheckLatest (Work):
    def exec(self, commander, param):
        pass


class WorkUpdate (Work):
    def exec(self, commander, param):
        pass


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
