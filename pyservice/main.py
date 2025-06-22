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
        self.status = 'Init'
        self.worker = None
        self.threads = {}
        self.sockets = {}
        self.commands = []
        self.executable = sys.executable
        self.services = {
            # 'PyService': ('0.0', 'server', 0)
        }

        # Initing        
        self.root_path = os.path.abspath(os.path.dirname(pgm_file))
        self.config_path = ps_path(self, config_file)
        self.pgm_path = os.path.abspath(pgm_file)
        self.config = ConfigParser()
        self.config.read(self.config_path)
        
        self.add_service('PyService')
        self.add_service(self.name())
        
        self.log_path = self.config['PyService']['log_path']
        self.logger = Logger(self, self.log_path, int(self.config['PyService']['log_level']))
        self.log(Level.SYSTEM, 'PyService Initting - (%s)' % (self.name(), ))

        self.version = self.config['PyService']['version']
        self.ps_version = self.config['PyService']['version']
        self.control = Controller(self)
        self.init()
        
        # Version Managing
        try:
            for name in self.services.keys():
                result, version = self.command('ps update ' + name)
                if result[0] == None:
                    self.log(Level.SYSTEM, '[%s] is a latest version (%s)' % (self.ps_version, ))
                elif result[0] == True:
                    self.log(Level.SYSTEM, '[%s] is updated (%s)' % (version, ))
                    self.set_config(name, 'version', version)
                    self._restart()
                else:
                    self.log(Level.SYSTEM, '[%s] was not updated (%s)' % (self.ps_version, ))
        except:
            pass

        self.status = 'Ready'
        self.log(Level.SYSTEM, 'PyService Init Complete - (%s)' % (self.name(), ))
    
    def _stop_ready(self):
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
            for socket_name, socket in self.sockets.items():
                socket.close()
            self.status = 'StopReady'
            self.log(Level.SYSTEM, 'PyService is Stopped - (%s)' % (self.name(), ))

    def _restart(self):
        self.log(Level.SYSTEM, 'Service Restarting...')
        os.execv(self.executable, [self.executable, self.pgm_path])
        os._exit(0)

    # === Status methods ===

    def command(self, cmd_str):
        result = self.control._commanding('Ps', cmd_str)
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

    def add_service(self, name):
        if name != None and name in self.config.sections():
            version = self.config[name]['version']
            update_address = self.config[name]['update_address']
            update_port = int(self.config[name]['update_port'])
            self.services[name] = (version, update_address, update_port)

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


    # === User Overrides methods ===
     
    def name(self):
        return None

    @abstractmethod
    def run(self):
        pass

    def init(self):
        pass

    def destory(self):
        pass

