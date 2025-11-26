import logging
from abc import ABC, abstractmethod
import traceback
import os
import sys
import asyncio, aiofiles
import signal
import configparser

from .comp import Component

_version_conf = 'PSVC\\version'

class Config(Component):
    def __init__(self, svc, config_file, name='Config'):
        super().__init__(svc, name)
        self._config = configparser.ConfigParser()
        self._config_file = self.svc.psvc_path(config_file)
        if self._config_file:    
            self._config.read(self._config_file)

    def set_config(self, section: str, key: str, value):
        if section not in self._config:
            self._config.add_section(section)
        self._config.set(section, key, value)
        if self._config_file:
            with open(self._config_file, 'w') as af:
                self._config.write(af)

    def get_config(self, section: str, key: str, default=None):
        if key is None:
            section, key = section.split('\\', 2)
        try:
            return self._config[section][key]
        except KeyError as e:
            if default is None:
                raise ValueError('Config is not exist %s\\%s' % (section, key))
            else:
                self.set_config(section, key, default)
                return default
        except Exception as e:
            raise e

class Service(Component, ABC):
    _fmt = '%(asctime)s : %(name)s [%(levelname)s] %(message)s - %(lineno)s'

    def __init__(self, name='Service', root_file=None, config_file=None, level=logging.INFO):
        Component.__init__(self, None, name)
        self._sigterm = asyncio.Event()
        self._loop = None
        self._tasks = []
        self._closers = []
        self._fh = None
        self.status = None
        self.level = level

        if not os.path.basename(sys.executable).startswith('python'):
            self._root_path = os.path.abspath(os.path.dirname(sys.executable))
        elif root_file:
            self._root_path = os.path.abspath(os.path.dirname(root_file))
        else:
            self._root_path = None
        
        self.set_logger(self.level)
        self._config_file = config_file
        self._config = Config(self, self._config_file)
        self.version = self.get_config(_version_conf, None, '0.0')
        
    def set_config(self, section: str, key: str, value):
        self._config.set_config(section, key, value)

    def get_config(self, section: str, key: str, default=None):
        self._config.get_config(section, key, default)

    def psvc_path(self, path):
        if os.path.isabs(path):
            return path
        else:
            return os.path.join(self._root_path, path)
        
    def append_task(self, loop:asyncio.AbstractEventLoop, coro, name):
        self.l.debug('Append Task - %s', name)
        task = loop.create_task(coro, name=name)
        self._tasks.append(task)
        return task
    
    async def delete_task(self, task: asyncio.Task):
        self.l.debug('Delete Task - %s', task.get_name())
        if task in self._tasks and not task.done():
            if task is asyncio.current_task():
                raise RuntimeError('Cannot delete the current running task')
            
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._tasks.remove(task)

    def append_closer(self, closer, args: list):
        self._closers.append((closer, args))

    def set_status(self, status: str):
        self.l.info('Status=%s', status)
        self.status = status

    def stop(self):
        self._sigterm.set()

    def set_logger(self, level):
        self._fh = logging.FileHandler(self.psvc_path(self.name+'.log'))
        self._fh.setLevel(level)
        self._fh.setFormatter(logging.Formatter(Service._fmt))
        logging.basicConfig(level=level, force=True,
                            format=Service._fmt)
        self.l = logging.getLogger(name='PyService')
        self.l.addHandler(self._fh)

    def on(self):
        signal.signal(signal.SIGTERM, self.stop)
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self.l.info('PyService Start %s', self)
        self.append_task(self._loop, self._service(), 'ServiceWork')
        try:
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))
        except KeyboardInterrupt as i:
            self.l.info('Stopping by KeyBoardInterrupt')
        finally:
            for t in self._tasks:
                t.cancel()
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))
        self._loop.close()

        for closer, args in self._closers:
            closer(*args)

    async def _service(self):
        self.set_status('Initting')
        await self.init()
        
        self.set_status('Running')
        try:
            while not self._sigterm.is_set():
                await self.run()
        except asyncio.CancelledError as c:
            self.l.error('Service Cancelled')
        except Exception as e:
            self.l.error(traceback.format_exc())
        finally:
            self.set_status('Stopping')
            await self.destroy()
            self.set_status('Stopped')

    async def init(self):
        await asyncio.sleep(0.1)

    @abstractmethod
    async def run(self):
        pass

    async def destroy(self):
        await asyncio.sleep(0.1)

    def __repr__(self):
        return '<%s> - %s' % (self.name, self.status)
