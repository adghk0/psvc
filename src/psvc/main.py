import logging
from abc import ABC, abstractmethod
import traceback
import datetime

import asyncio
import signal
import traceback
import contextlib
import itertools
import struct
import sys

'''
class Commander(metaclass=ABCMeta):
    def __init__(self):
        pass

    async def ready(self): # -> bool
        pass

    async def request(self): # -> (str, str)
        pass

    async def print(self): # -> None
        pass


class CommanderSocket(Commander):
    def __init__(self):
        pass

    '''


class Service(ABC):
    _fmt = '%(asctime)s : %(name)s [%(levelname)s] %(message)s - %(lineno)s'

    def __init__(self, name='Service'):
        self.name = name
        self.status = None
        self.tasks = []
        self.sigterm = asyncio.Event()
        self.loop = None

    def append_task(self, loop:asyncio.AbstractEventLoop, coro, name):
        task = loop.create_task(coro, name=name)
        self.tasks.append(task)
    
    async def delete_task(self, task: asyncio.Task):
        if task in self.tasks and not task.done():
            if task is asyncio.current_task():
                raise RuntimeError('Cannot delete the current running task')
            
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self.tasks.remove(task)

    def set_status(self, status):
        self.l.info('Status=%s', status)
        self.status = status

    def stop(self):
        self.sigterm.set()

    def on(self, level=logging.DEBUG):
        fh = logging.FileHandler(self.name+'.log')
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter(Service._fmt))
        logging.basicConfig(level=level, force=True,
                            format=Service._fmt)
        self.l = logging.getLogger(name='PyService')
        self.l.addHandler(fh)
        signal.signal(signal.SIGTERM, self.stop)

        self.l.info('PyService Start %s', self)
        self.loop = asyncio.get_event_loop()
        asyncio.set_event_loop(self.loop)

        self.append_task(self.loop, self._commanding(), 'CommandWork')
        self.append_task(self.loop, self._service(), 'ServiceWork')

        try:
            self.loop.run_until_complete(asyncio.gather(*self.tasks, return_exceptions=True))
        except KeyboardInterrupt as i:
            self.l.info('Stopping by KeyBoardInterrupt')
        finally:
            for t in self.tasks:
                t.cancel()
            self.loop.run_until_complete(asyncio.gather(*self.tasks, return_exceptions=True))

        self.loop.close()
    
    async def _commanding(self):
        pass

    async def _service(self):
        self.set_status('Initting')
        await self.init()
        
        self.set_status('Running')
        try:
            while not self.sigterm.is_set():
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
        pass

    @abstractmethod
    async def run(self):
        pass

    async def destroy(self):
        pass

    def __repr__(self):
        return '<%s> - %s' % (self.name, self.status)
    
class Socket:
    _max_size = 64 * 1024
    
    def __init__(self, svc: Service, name=''):
        self.svc = svc
        self.name = svc.name+'-'+name
        self.l = logging.getLogger(name=self.name)
        self._gen = itertools.count(1)
        self._conns = {}
        self._recvs = asyncio.Queue()
               
    async def bind(self, addr:str, port:int):
        self.server = await asyncio.start_server(self._handler, host=addr, port=port)
        addrs = ", ".join(str(sock.getsockname()) for sock in self.server.sockets)
        self.l.debug('Serving on %s', addrs)
        self.svc.append_task(asyncio.get_running_loop(), self._serv(), self.name)
    
    async def server_join(self):
        await self.server.serve_forever()

    async def _serv(self):
        try:
            self.server: asyncio.Server
            await self.server.serve_forever()
        except asyncio.CancelledError:
            self.l.error('socket cancelled')
        finally:
            self.server.close()
            await self.server.wait_closed()

    async def connect(self, addr, port):
        r, w = await asyncio.open_connection(addr, port)
        self.svc.append_task(asyncio.get_running_loop(), self._handler(r, w), self.name)

    def _add_connection(self, cid, reader, writer):
        peer = writer.get_extra_info("peername")
        self.l.debug('new connection %s', peer)
        self._conns[cid] = (peer, reader, writer)

    async def _handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        cid = next(self._gen)
        
        self._add_connection(cid, reader, writer)
        try:
            while True:
                raw = await reader.readexactly(4)
                (size, ) = struct.unpack('!I', raw)
                if size <= 0 or size > Socket._max_size:
                    raise ValueError('invalid header length')
                buf = await reader.readexactly(size)
                await self._recvs.put((cid, buf))
        except asyncio.CancelledError:
            pass
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def recv(self):
        return await self._recvs.get()

    async def _send(self, msg, cid):
        _, _, writer = self._conns[cid]
        writer: asyncio.StreamWriter
        mv = memoryview(msg)
        i, n = 0, len(mv)
        while i < n:
            size = min(Socket._max_size, n-i)
            buf = mv[i:i+size]
            writer.write(struct.pack('!I', size))
            writer.write(buf)
            await writer.drain()
            i += size

    async def send(self, msg, cid=None):
        if len(msg) <= 0:
            raise ValueError('Cannot send Null message')
        if cid == None:
            cid = next(iter(self._conns))
        await self._send(msg, cid)


class EchoService(Service):
    async def run(self):
        sock = Socket(self, 'Echo')
        await sock.bind('0.0.0.0', 60620)
        while True:
            cid, msg = await sock.recv()
            await sock.send(msg, cid)

async def ainput(prompt="", loop=None):
    loop = loop or asyncio.get_running_loop()
    print(prompt, end="", flush=True)
    msg = await loop.run_in_executor(None, sys.stdin.readline)
    return msg.strip()

class SendService(Service):
    async def run(self):
        sock = Socket(self, 'Send')
        await sock.connect('127.0.0.1', 60620)
        while True:
            msg = await ainput()
            await sock.send(msg.encode())
            cid, rcv = await sock.recv()
            self.l.info('Recv %d %s', cid, rcv)
            
if __name__ == '__main__':
    if input() == 's':
        svc = EchoService()
        svc.on()
    else:
        svc = SendService()
        svc.on()