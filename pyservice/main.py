import os, sys
import subprocess
from functools import wraps
from configparser import ConfigParser

import time
import traceback

from .log import Level, Logger
from .file import ps_path, copy
from .control import Controller
from .threads import PsThread
from .sockets import PsSocket

# PyService Version 0.0.1

'''
----- status -----
Init
Ready
Running
Stopping - StopReady
Dead
'''

class Service:
    def __init__(self, pgm_file, config_file='./config.conf', name='PyService'):
        self.status = 'Init'
        self.root_path = os.path.abspath(os.path.dirname(pgm_file))
        self.name = name
        self.worker = None
        self.threads = {}
        self.sockets = {}
        self.commands = []
        self.executable = sys.executable
        self.pgm_file = pgm_file
        self.services = {
            # 'PyService': <PsSocket>
        }

        # Initing        
        self.config_path = ps_path(self, config_file)
        self.pgm_path = os.path.abspath(pgm_file)
        self.config = ConfigParser()
        self.config.read(self.config_path)
        self.update_server = self.config['PyService']['update_address']
        self.update_port = self.config['PyService']['update_port']
        
        self.log_path = self.config['PyService']['log_path']
        self.logger = Logger(self, self.log_path, int(self.config['PyService']['log_level']))
        self.log(Level.SYSTEM, 'PyService Initting - (%s)' % (self.name, ))

        self.ps_version = self.config[self.name]['version']
        self.control = Controller(self)
        self.init()

        # Version Managing
        if self.config['PyService']['start_update'] == '1' and self.config[self.name]['update_failed'] == '0':

            result, version = self.command('ps check_update %s' % (self.name, ), True)
            if result == None:
                self.log(Level.SYSTEM, '[%s] is a latest version (%s)' % (self.name, self.ps_version, ))

            elif result == True:
                self.set_config(self.name, 'update_failed', 1)
                self.log(Level.SYSTEM, '[%s] is updating (%s)' % (self.name, self.ps_version))
                result = self.command('ps update %s %s' % (self.name, version), True)
                
                self.log(Level.SYSTEM, '[%s] is updated (%s)' % (self.name, version))
                self._restart()

            else:
                self.log(Level.SYSTEM, '[%s] was not updated (%s)' % (self.name, self.ps_version, ))

        self._init_services()

        self.status = 'Ready'
        self.log(Level.SYSTEM, 'PyService Init Complete - (%s)' % (self.name, ))


    def _init_services(self):
        if 'services' in self.config[self.name]:
            for s in self.config[self.name]['services'].split(','):
                sub_service = s.strip()
                self.log(Level.SYSTEM, 'Sub Services - %s initting' % (sub_service, ))

                subprocess.Popen(' '.join([self.executable, self.pgm_file, sub_service]))
                ctrl_sock = PsSocket(self, '%s_Control' % (sub_service, ))
                ctrl_sock.connect('127.0.0.1', self.config[sub_service]['cmd_port'])
                self.services[sub_service] = ctrl_sock
                
                self.log(Level.SYSTEM, 'Sub Services - %s initted' % (sub_service, ))

    def _stop_ready(self):
        self.status = 'StopReady'

    def _run(self):
        while self.status in ['Running', 'Stopping']:
            try:
                self.run()
                self.set_config(self.name, 'update_failed', 0)
            except:
                if self.config[self.name]['update_failed'] == '1':
                    copy(os.path.join(self.pgm_path, '.rollback', self.name), self.pgm_path)
                    self.set_config(self.name, 'update_failed', 1)
                self.log_err('Error in Service Running')
            if self.status == 'Stopping':
                self._stop()
        self.status = 'Dead'

    def _start(self):
        if self.status == 'Ready':
            self.status = 'Running'
            self.worker = PsThread(self, 'Worker', target=self._run)
            self.worker.start()
            for sub_sock in self.services:
                self.services[sub_sock].send_str('start\r\n')
            self.log(Level.SYSTEM, 'PyService Started - (%s)' % (self.name, ))

    def _stop(self):
        for sub_sock in self.services:
            self.services[sub_sock].send_str('stop\r\n')
            time.sleep(1)
        
        self.status = 'Stopping'
        self.log(Level.SYSTEM, 'PyService is Stopping - (%s)' % (self.name, ))
        
        result = self.destory()
        
        if result == None:
            for socket_name, socket in self.sockets.items():
                socket.close()
            self.status = 'StopReady'
            self.log(Level.SYSTEM, 'PyService is Stopped - (%s)' % (self.name, ))

    def _restart(self):
        self.log(Level.SYSTEM, 'Service Restarting...')
        self._stop()
        os.execv(self.executable, [self.executable, self.pgm_file, self.name])

    # === Status methods ===
 
    def command(self, cmd_str, wait=False):
        self.control._commanding('Ps', cmd_str, wait=wait)
        result = None
        if wait:
            while self.control.command_finished:
                time.sleep(0.1)
            result = self.control.command_result()
        self.log(Level.DEBUG, '(%s) executed a command - "%s"' % (self.name(), cmd_str))
        return result

    def join(self):
        self.worker.join()
    
    def set_config(self, section, key, value):
        self.config.set(section, key, value)
        with open(self.config_path, 'w') as f:
            self.config.write(f)

    @property
    def is_ready(self):
        return self.status in ['Ready']
    
    @property
    def is_run(self):
        return self.status in ['Running', 'Stopping', 'StopReady']
    
    @property
    def is_alive(self):
        return self.status not in ['Dead']
    
    
    # === User uses methods ===
    def set_work(self, key, work):
        self.control._set_command(key, work)

    def log(self, level: int, msg: str, file=None):
        self.logger.log(level, msg, file)
    
    def log_err(self, msg: str, file=None):
        self.logger.log(Level.ERROR, msg, file)
        self.logger.log(Level.ERROR, traceback.format_exc(), file)

    def log_warn(self, msg: str, file=None):
        self.logger.log(Level.WARN, msg, file)
    
    def log_info(self, msg: str, file=None):
        self.logger.log(Level.INFO, msg, file)

    def log_debug(self, msg: str, file=None):
        self.logger.log(Level.DEBUG, msg, file)


    # === User Overrides methods ===
    def run(self):
        time.sleep(1)

    def init(self):
        pass

    def destory(self):
        pass


