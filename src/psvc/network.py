import os
import asyncio
import aiofiles
import itertools
import contextlib
import struct
from typing import Tuple

from .comp import Component
from .main import Service


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
        self.l.debug('new Socket attached')
               
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
                await self._recvs[cid].put(buf)

                buf_debug = buf[0:min(len(buf), 20)]
                self.l.debug('Receive %s (%d) from %d' % (buf_debug, len(buf), cid))
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

        while i < n:
            size = min(Socket._max_size, n-i)
            buf = mv[i:i+size]
            writer.write(struct.pack('!I', size))
            writer.write(buf)
            await writer.drain()
            i += size
        
        msg_debug = msg[0:min(len(msg), 20)]
        self.l.debug('Send %s (%d) to %d' % (msg_debug, len(msg), cid))

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
                    await af.seek(pos, 0)
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
                await af.seek(pos, 0)
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
