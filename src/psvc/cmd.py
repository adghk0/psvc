import asyncio
import json

from .comp import Component
from .main import Service
from .network import Socket


class Command:
    def __init__(self, commander, ident):
        self._cmdr = commander
        self._ident = ident
    
    async def handle(self, body, cid):
        await asyncio.sleep(0.1)


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

    def set_command(self, cmd, ident):
        if ident in self._cmds:
            raise ValueError('Ident is collided. (%s)' % (ident, ))
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
