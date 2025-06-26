import sys, os
import time
import re

from .main import Service
from .control import CommanderSocket, Controller
from .sockets import PsSocket
from .works import *
from .file import copy


class ServerService (Service):
    def init(self):
        self.server_conf = self.config['PsServer']
        self.server_address = self.server_conf['address']
        self.server_port = int(self.server_conf['port'])
        self.server_service = self.server_conf['service_name']
        self.server_dir = os.path.join(self.server_conf['server_dir'], self.server_service)
        self._release_ignore = [
            re.compile(r'(^|[/\\])\.[^/\\]+'),  # .으로 시작하는 파일/폴더
            re.compile(r'(^|[/\\])log$'),       # log로 끝나는 파일/폴더
            re.compile(r'\.conf$'),    # .conf로 끝나는 파일
        ]

        self.server_sock = PsSocket(self, 'PsServer-Socket')
        self.server_sock.bind(self.server_address, self.server_port)
        self.server_ctrl = Controller(self, least=True)
        self.server_ctrl.commanders['PsServer-Socket'] = CommanderSocket('PsServer-Socket', self.server_ctrl, self.server_sock)
        self.server_versions = os.listdir(self.server_dir)
        self.server_versions.sort()
        
        self.server_ctrl.set_work(['list'], WorkVersionList)
        self.server_ctrl.set_work(['latest'], WorkLatest)
        self.server_ctrl.set_work(['ls'], WorkFileList)
        self.server_ctrl.set_work(['release'], WorkRelease)
        self.server_ctrl.set_work(['req'], WorkRequest)

    def name(self):
        return 'PyService Server'

    def run(self):
        time.sleep(5)

    def append_ignore(self, rec: re.Pattern):
        self._release_ignore.append(rec)
    
# Server 
class WorkVersionList (Work):
    def exec(self, commander, param):
        id = commander.control.commander_sep
        service = commander.control.service
        sock = service.server_sock
        sock: PsSocket
        sock.send_str('|'.join(service.server_versions) + '\r\n', id)

class WorkLatest (Work):
    def exec(self, commander, param):
        id = commander.control.commander_sep
        service = commander.control.service
        sock = service.server_sock
        sock: PsSocket
        sock.send_str(service.server_versions[-1] + '\r\n', id)

class WorkRelease (Work):
    def exec(self, commander, param):
        id = commander.control.commander_sep
        service = commander.control.service
        sock = service.server_sock
            
        if len(param) == 0:
            if len(service.server_versions) > 0:
                vers = service.server_versions[-1].split('.')
                vers[-1] = str(int(vers[-1])+1)
            else:
                vers = ['0']*3
            param.append('.'.join(vers))
        
        if len(param) == 1:
            param.append(service.server_conf['source_dir'])

        result = copy(param[1], os.path.join(service.server_dir, param[0]), service._release_ignore)
        if result == 1:
            sock.send_str('Fail\r\n', id)
        else:
            sock.send_str('OK\r\n', id)
            commander.control.service.command('restart')

class WorkRequest (Work):
    def exec(self, commander, param):
        id = commander.control.commander_sep
        service = commander.control.service
        sock = service.server_sock
        if len(param) == 0:
            param.append(service.server_versions[-1])
        
        sock.send_files(os.path.join(service.server_dir, param[0]), id)
