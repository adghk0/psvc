import os, sys
from abc import ABCMeta, abstractmethod
from functools import wraps
from configparser import ConfigParser

from .log import Level, Logger
from .file import ps_path
from .control import Controller
from .threads import PsThread

'''
----- status -----
Init
Ready
Running
Stopping - StopReady
Dead
'''

class Service (metaclass=ABCMeta):
    def __init__(self, pgm_file, config_file='./config.conf'):
        self.root_path = os.path.abspath(os.path.dirname(pgm_file))
        self.status = 'Init'
        self.worker = None
        self.threads = {}
        self.commands = []
        
        self.config = ConfigParser()
        self.config.read(ps_path(self, config_file))
        self.ps_name = self.config['PyService']['name']
        self.log_path = self.config['PyService']['log_path']
        self.logger = Logger(self, self.log_path)
        self.log(Level.SYSTEM, 'PyService Initting - (%s)' % (self.name(), ))

        self.version = self.config['PyService']['version']
        self.control = Controller(self)
        self.init()

        self.status = 'Ready'
        self.log(Level.SYSTEM, 'PyService Init Complete - (%s)' % (self.name(), ))
    
    def stop_ready(self):
        self.status = 'StopReady'

    def _run(self):
        while self.status in ['Running', 'Stopping']:
            self.run()
            if self.status == 'Stopping':
                self._stop()
        self.status = 'Dead'

    def _start(self):
        if self.status == 'Ready':
            self.status = 'Running'
            self.worker = PsThread(self, 'Worker', target=self._run)
            self.worker.start()
            self.log(Level.SYSTEM, 'PyService Started - (%s)' % (self.name(), ))

    def _stop(self):
        self.status = 'Stopping'
        self.log(Level.SYSTEM, 'PyService is Stopping - (%s)' % (self.name(), ))
        result = self.destory()
        if result == None:
            self.status = 'StopReady'
            self.log(Level.SYSTEM, 'PyService is Stopped - (%s)' % (self.name(), ))

    ####
    def command(self, cmd_str):
        self.control.command(cmd_str)
        self.log(Level.DEBUG, '(%s) executed a command - "%s"' % (self.name(), cmd_str))

    def join(self):
        self.control.join()
    
    @property
    def is_ready(self):
        return self.status in ['Ready']
    
    @property
    def is_run(self):
        return self.status in ['Running', 'Stopping', 'StopReady']
    
    @property
    def is_alive(self):
        return self.status not in ['Dead']
    
    def set_work(self, key, work):
        self.control._set_command(key, work)

    def log(self, level: int, msg: str, file=None):
        self.logger.log(level, msg, file)
    
    def log_err(self, msg: str, file=None):
        self.logger.log(Level.ERROR, msg, file)

    def log_warn(self, msg: str, file=None):
        self.logger.log(Level.WARN, msg, file)
    
    def log_info(self, msg: str, file=None):
        self.logger.log(Level.INFO, msg, file)

    def log_debug(self, msg: str, file=None):
        self.logger.log(Level.DEBUG, msg, file)
    #### 
    
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def run(self):
        pass

    def init(self):
        pass

    def destory(self):
        pass
