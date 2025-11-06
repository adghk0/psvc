import logging
from abc import ABC, abstractmethod
import traceback
import datetime

import os
import sys
import asyncio, aiofiles
import signal
import traceback
import contextlib
import itertools
import struct
import json
import subprocess
from typing import Tuple


class Component:
    def __init__(self, svc, name):
        if svc == None:
            self.svc = None
            self.name = name
        else:
            self.svc = svc
            self.name = svc.name+'-'+name
            self.l = logging.getLogger(name=self.name)
            self.svc.append_component(self)
        self._component_index = itertools.count(1)
        self._components = {}

    def append_component(self, component):
        index = next(self._component_index)
        self._components[index] = component

    def delete_component(self, index):
        del(self._components[index])

    def __repr__(self):
        return '<%s>' % (self.name,)


class Service(Component, ABC):
    _fmt = '%(asctime)s : %(name)s [%(levelname)s] %(message)s - %(lineno)s'

    def __init__(self, name='Service', root_file=None):
        Component.__init__(self, svc=None, name=name)
        self._sigterm = asyncio.Event()
        self._loop = None
        self._tasks = []
        self._subsvcs = {}
        self.status = None

        if not os.path.basename(sys.executable).startswith('python'):
            self._root_path = os.path.abspath(os.path.dirname(sys.executable))
        elif root_file:
            self._root_path = os.path.abspath(os.path.dirname(root_file))
        else:
            self._root_path = None

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

    def append_svc(self, executable, name, args):
        self.l.debug(sys.path)
        subsvc = subprocess.Popen(executable=executable, args=[executable, *args],
                                  stdout=None, stderr=None)
        self._subsvcs[name] = subsvc
        self.l.debug(args)
    
    async def delete_svc(self, name):
        self._subsvcs[name].terminate()
        self._subsvcs[name].wait()
        del(self._subsvcs[name])

    def set_status(self, status):
        self.l.info('Status=%s', status)
        self.status = status

    def stop(self):
        self._sigterm.set()

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
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self.append_task(self._loop, self._service(), 'ServiceWork')

        try:
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))
        except KeyboardInterrupt as i:
            self.l.info('Stopping by KeyBoardInterrupt')
        finally:
            for t in self._tasks:
                t.cancel()
            for svc in self._subsvcs:
                self.delete_svc(svc)
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))

        self._loop.close()

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
        pass

    @abstractmethod
    async def run(self):
        pass

    async def destroy(self):
        pass

    def __repr__(self):
        return '<%s> - %s' % (self.name, self.status)


class Socket(Component):
    _max_size = 64 * 1024
    
    def __init__(self, svc: Service, name='Socket', callback=None, callback_end=None):
        super().__init__(svc, name)
        self._gen = itertools.count(1)
        self._conns = {}
        self._recvs = {}
        self._handle_task = None
        self.callback = callback
        self.callback_end = callback_end
               
    async def bind(self, addr:str, port:int):
        self.server = await asyncio.start_server(self._handler, host=addr, port=port)
        addrs = ", ".join(str(sock.getsockname()) for sock in self.server.sockets)
        self.l.debug('Serving on %s', addrs)
        self._handle_task = self.svc.append_task(asyncio.get_running_loop(), self._serv(), self.name)

    async def server_join(self):
        await self.server.wait_closed()

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
        self._handle_task = self.svc.append_task(asyncio.get_running_loop(), self._handler(r, w), self.name)

    async def _add_connection(self, cid, reader, writer):
        peer = writer.get_extra_info("peername")
        self.l.debug('new connection %s', peer)
        self._conns[cid] = (peer, reader, writer)
        self._recvs[cid] = asyncio.Queue()
        if self.callback:
            await self.callback(cid)

    async def _del_connection(self, cid):
        del(self._conns[cid])
        del(self._recvs[cid])
        if self.callback_end:
            await self.callback_end(cid)

    async def _handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        cid = next(self._gen)
        await self._add_connection(cid, reader, writer)
        try:
            while True:
                raw = await reader.readexactly(4)
                (size, ) = struct.unpack('!I', raw)
                if size <= 0 or size > Socket._max_size:
                    raise ValueError('invalid header length')
                buf = await reader.readexactly(size)
                self.l.debug('Receive %s from %d' % (buf, cid))
                await self._recvs[cid].put(buf)
        except asyncio.CancelledError:
            pass
        except asyncio.IncompleteReadError:
            self.l.info('Connection Ended (%d)' % (cid))
        finally:
            writer.close()
            await self._del_connection(cid)
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _send(self, msg: bytes, cid: int) -> None:
        _, _, writer = self._conns[cid]
        writer: asyncio.StreamWriter
        mv = memoryview(msg)
        i, n = 0, len(mv)
        self.l.debug('Send %s to %d' % (msg, cid))
        while i < n:
            size = min(Socket._max_size, n-i)
            buf = mv[i:i+size]
            writer.write(struct.pack('!I', size))
            writer.write(buf)
            await writer.drain()
            i += size

    async def recv(self, cid=None) -> Tuple[int, bytes]:
        if cid == None:
            while True:
                try:
                    for cid, buf in self._recvs.items():
                        try:
                            data = buf.get_nowait()
                            return cid, data
                        except asyncio.QueueEmpty:
                            continue
                        except Exception as e:
                            self.l.exception(e)
                    await asyncio.sleep(0.1)  
                except asyncio.CancelledError:
                    break
        else:
            data = await self._recvs[cid].get()
            return cid, data

    async def send(self, msg: bytes, cid: int) -> None:
        if len(msg) <= 0:
            raise ValueError('Cannot send Null message')
        await self._send(msg, cid)

    async def recv_str(self, cid: int) -> str:
        _, msg = await self.recv(cid)
        return msg.decode()

    async def send_str(self, string: str, cid: int) -> None:
        await self.send(string.encode(), cid)

    async def recv_file(self, path: os.PathLike, cid: int) -> None:
        try:
            fsize = int(await self.recv_str(cid))
            rsize = 0
            async with aiofiles.open(path, 'wb') as af:
                while rsize < fsize:
                    _, chunk = await self.recv(cid)
                    rsize += len(chunk)
                    await af.write(chunk)
                    if rsize > fsize:
                        raise Exception('Unmatched file data')
        except ValueError as ve:
            self.l.error('Value Error')

    async def send_file(self, path: os.PathLike, cid: int) -> None:
        fsize = os.path.getsize(path)
        await self.send_str(str(fsize), cid)
        async with aiofiles.open(path, 'rb') as af:
            while True:
                chunk = await af.read(self._max_size)
                if chunk:
                    await self.send(chunk, cid)
                else:
                    break
    
    async def recv_file_piece(self, path: os.PathLike, cid: int) -> None:
        try:
            f_size = int(await self.recv_str(cid))
            pos = int(await self.recv_str(cid))
            f_size -= pos
            cur_size = 0
            if f_size > 0:
                async with aiofiles.open(path, 'ab') as af:
                    af.seek(pos, 0)
                    while cur_size < f_size:
                        _, chunk = await self.recv(cid)
                        cur_size += len(chunk)
                        await af.write(chunk)
                        if cur_size > f_size:
                            raise Exception('Unmatched file data')
        except ValueError as ve:
            self.l.error('Value Error')

    async def send_file_piece(self, path: os.PathLike, pos: int, send_size: int, cid: int) -> int:
        rem_size = os.path.getsize(path) - pos
        send_size = min(rem_size, send_size) if send_size > 0 else rem_size
        cur_size = 0
        await self.send_str(str(send_size), cid)
        await self.send_str(str(pos), cid)
        if send_size > 0:
            async with aiofiles.open(path, 'rb') as af:
                af.seek(pos, 0)
                while cur_size < send_size:
                    chunk = await af.read(min(self._max_size, rem_size - cur_size))
                    if chunk:
                        cur_size += len(chunk)
                        await self.send(chunk, cid)
                    else:
                        break
        return send_size

    async def close(self):
        if self._handle_task:
            await self.svc.delete_task(self._handle_task)
        self._handle_task = None


class Command:
    def __init__(self, commander, ident):
        self._cmdr = commander
        self._ident = ident
    
    async def handle(self, body, cid):
        await asyncio.sleep(0.1)
    
class Print(Command):
    async def handle(self, body, cid):
        self._cmdr.l.debug('print: %s at %d', body, cid)

class Echo(Command):
    async def handle(self, body, cid):
        await self._cmdr.send_command('_print', body, cid)

class Commander(Component):
    def __init__(self, svc: Service, name='Commander'):
        super().__init__(svc, name)
        self._sock = Socket(self.svc, name+'-Sock')
        self._en = json.JSONEncoder()
        self._de = json.JSONDecoder()
        self._cmds = {}
        self._task = self.svc.append_task(asyncio.get_running_loop(), self._receive(), name+'-Res')
        self._handle_lock = asyncio.Lock()

    def sock(self):
        return self._sock

    async def bind(self, addr: str, port: int):
        await self._sock.bind(addr, port)
    
    async def connect(self, addr: str, port: int):
        await self._sock.connect(addr, port)
    
    def set_default_command(self):
        self.set_command(Print, '_print')
        self.set_command(Echo, '_echo')

    def set_command(self, cmd, ident):
        self._cmds[ident] = cmd(self, ident)

    async def send_command(self, cmd_ident, body, cid):
        cmd_header = {
            'ident': cmd_ident,
            'body': body,
        }
        await self._sock.send_str(self._en.encode(cmd_header), cid)
        
    async def handle(self, cmd_ident, body, cid):
        cmd_header = {
            'ident': cmd_ident,
            'body': body,
        }
        return await self._handle(cmd_header, cid)

    async def _handle(self, cmd_header, cid):
        result = None
        try:
            ident = cmd_header['ident']
            body = cmd_header['body']
            async with self._handle_lock:
                result = await self._cmds[ident].handle(body, cid)
        except Exception as e:
            self.l.exception(e)
        return result
    
    async def _receive(self):
        try:
            while True:
                cid, msg = await self._sock.recv()
                msg = msg.decode()
                cmd_header = self._de.decode(msg)
                await self._handle(cmd_header, cid)
        except asyncio.CancelledError:
            self.l.exception('Commander Error')
        finally:
            await self._sock.close()


async def ainput(prompt="", loop=None):
    loop = loop or asyncio.get_running_loop()
    print(prompt, end="", flush=True)
    msg = await loop.run_in_executor(None, sys.stdin.readline)
    return msg.strip()

'''
svc = MyService()
svc.on()
'''