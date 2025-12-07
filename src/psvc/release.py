import asyncio
import os

from .comp import Component
from .main import Service
from .cmd import Commander, command


def _version(s):
    return tuple(map(int, s.split('.')))


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
    
    def get_version_list(self):
        versions = sorted(os.listdir(self.release_path), key=_version)
        return versions

class Updater(Component):
    def __init__(self, svc: Service, commander: Commander, name='Updater'):
        super().__init__(svc, name)
        self._cmdr = commander

