import sys
from abc import ABCMeta, abstractmethod
from functools import wraps
from threading import Thread, Lock
from configparser import ConfigParser

from .control import Controller

'''
----- status -----
Init
Ready
Running
Stopping - StopReady
Dead
'''

class Service (metaclass=ABCMeta):
    def __init__(self, config_file='./config.conf'):
        self.status = 'Init'
        self.worker = None
        self.commands = []
        self.config = ConfigParser()
        self.config.read(config_file)
        self.control = Controller(self)
        self.init()
        self.status = 'Ready'
    
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
            self.worker = Thread(target=self._run)
            self.worker.start()

    def _stop(self):
        self.status = 'Stopping'
        result = self.destory()
        if result == None:
            self.status = 'StopReady'

    ####

    def command(self, cmd_str):
        self.control.command(cmd_str)

    def join(self):
        self.control.join()
    
    @property
    def is_ready(self):
        return self.status in ['Ready']
    
    @property
    def is_run(self):
        return self.status in ['Running', 'Stopping', 'StopReady']

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
