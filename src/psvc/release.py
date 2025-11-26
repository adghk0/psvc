import asyncio
import os

from .comp import Component
from .main import Service
from .cmd import Commander, Command


def _version(s):
    return tuple(s.split('.'))


class CmdSendVersions(Command):
    async def handle(self, body, cid):
        pass

class CmdSendLatestVersion(Command):
    async def handle(self, body, cid):
        pass

class CmdSendProgram(Command):
    async def handle(self, body, cid):
        pass

class CmdRecvProgram(Command):
    async def handle(self, body, cid):
        pass

class CmdRollback(Command):
    async def handle(self, body, cid):
        pass


class Releaser(Component):
    _release_path_conf = 'PSVC\\release_path'
    __send_versions__ = '__send_versions__'
    __send_latest_version__ = '__send_latest_version__'
    __send_program__ = '__send_program__'

    def __init__(self, svc: Service, commnader: Commander, name='Releaser'):
        super().__init__(svc, name)
        self._cmdr = commnader
        try:
            self.release_path = self.svc.get_config(Releaser._release_path_conf, None)
        except KeyError:
            raise KeyError('the release path is not setted (%s)' % (Releaser._release_path_conf,))
        self.versions = self.get_version_list()
        self.l.debug('new Releaser attached')

    def set_releaser_command(self):
        self._cmdr.set_command(CmdSendVersions, '__send_versions__')
        self._cmdr.set_command(CmdSendLatestVersion, '__send_latest_version__')
        self._cmdr.set_command(CmdSendProgram, '__send_program__')
    
    def get_version_list(self):
        versions = os.listdir(self.release_path)
        return versions.sort(key=lambda v: _version(v))
    

class Updater(Component):
    def __init__(self, svc: Service, commander: Commander, name='Updater'):
        super().__init__(svc, name)
        self._cmdr = commander


