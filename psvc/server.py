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
        self.server_address = self.server_conf['server_address']
        self.server_port = int(self.server_conf['server_port'])
        self.server_dir = self.server_conf['server_dir']
        self._release_ignore = [
            re.compile(r'(^|[/\\])\.[^/\\]+'),  # .으로 시작하는 파일/폴더
            re.compile(r'(^|[/\\])log$'),       # log로 끝나는 파일/폴더
            re.compile(r'\.conf$'),    # .conf로 끝나는 파일
        ]

        self.server_sock = PsSocket(self, 'PsServer-Socket')
        self.server_sock.bind(self.server_address, self.server_port)
        self.server_ctrl = Controller(self, least=True)
        self.server_ctrl.commanders['PsServer-Socket'] = CommanderSocket('PsServer-Socket', self.server_ctrl, self.server_sock)
        self.server_services = os.listdir(self.server_dir)
        self.server_versions = {}
        for service in self.server_services:
            service_dir = os.path.join(self.server_dir, service)
            versions = sorted(os.listdir(service_dir), key=lambda v: [int(x) for x in v.split('.')])
            self.server_versions[service] = versions
        
        self.server_ctrl.set_work(['services'], WorkServiceList)
        self.server_ctrl.set_work(['list'], WorkVersionList)
        self.server_ctrl.set_work(['latest'], WorkLatest)
        self.server_ctrl.set_work(['ls'], WorkFileList)
        self.server_ctrl.set_work(['release'], WorkRelease)
        self.server_ctrl.set_work(['req'], WorkRequest)

    def run(self):
        time.sleep(1)

    def append_ignore(self, rec: re.Pattern):
        self._release_ignore.append(rec)
    
# Server 
class WorkServiceList (Work):
    def exec(self, commander, param):
        id = commander.control.commander_sep
        service = commander.control.service
        sock = service.server_sock
        sock: PsSocket
        sock.send_str('|'.join(['%d %s' % (i, s) for i, s in enumerate(service.server_services)]) + '\r\n', id)

class WorkVersionList (WorkServiceList):
    def exec(self, commander, param):
        if len(param) > 0:
            id = commander.control.commander_sep
            service = commander.control.service
            sock = service.server_sock
            sock: PsSocket
            if param[0].isdecimal():
                param[0] = service.server_services[int(param[0])]
            sock.send_str('|'.join(service.server_versions[param[0]]) + '\r\n', id)
        else:
            super().exec(commander, param)

class WorkLatest (Work):
    def exec(self, commander, param):
        id = commander.control.commander_sep
        service = commander.control.service
        sock = service.server_sock
        sock: PsSocket
        sock.send_str(service.server_versions[param[0]][-1] + '\r\n', id)

class WorkRelease (Work):
    def exec(self, commander, param):
        id = commander.control.commander_sep
        service = commander.control.service
        sock = service.server_sock
            
        if param[0].isdecimal():
            param[0] = service.server_services[int(param[0])]

        if len(param) == 1:
            param.append(os.path.join(service.server_conf['source_dir']))

        if len(param) == 2:
            if param[0] in service.server_versions and len(service.server_versions[param[0]]) > 0:
                vers = service.server_versions[param[0]][0-1].split('.')
                vers[-1] = str(int(vers[-1])+1)
            else:
                vers = ['0']*3
            param.append('.'.join(vers))
        

        result = copy(param[1], os.path.join(service.server_dir, param[0], param[2]), service._release_ignore)
        if result == 1:
            sock.send_str('Fail' + str(param) + '\r\n', id)
        else:
            sock.send_str('OK\r\n', id)
            commander.control.service.command('restart')

class WorkRequest (Work):
    def exec(self, commander, param):
        id = commander.control.commander_sep
        service = commander.control.service
        sock = service.server_sock

        if param[0].isdecimal():
            param[0] = service.server_services[int(param[0])]

        if len(param) == 1:
            param.append(service.server_versions[param[0]][-1])
        
        sock.send_files(os.path.join(service.server_dir, param[0], param[1]), id)
