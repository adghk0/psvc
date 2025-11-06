import asyncio
import sys, os

from psvc import Service, Commander, Command, Socket

class CmdSendLog(Command):
    async def handle(self, body, cid):
        sock = self._cmdr.sock()
        sock: Socket
        pos = body['pos']
        self._cmdr.l.info('Send file start at %d', pos)
        await sock.send_file_piece('Service.log', pos, 0, cid)

class CmdRecvLog(Command):
    async def handle(self, body, cid):
        sock = self._cmdr.sock()
        sock: Socket
        self._cmdr.l.info('Recv file piece')
        await sock.recv_file_piece('copy.log', cid)


class Server(Service):
    async def init(self):
        self.cmdr = Commander(self)
        await self.cmdr.bind('0.0.0.0', 50000)
    
    async def run(self):
        await asyncio.sleep(1)

class Client(Service):
    async def init(self):
        self.cmdr = Commander(self)
        self.cmdr.set_command(CmdSendLog, 'send')
        self.lastpos = 0
        await self.cmdr.connect('127.0.0.1', 50000)
    
    async def run(self):
        self.lastpos += self.cmdr.handle('send', {'pos': self.lastpos})
        await asyncio.sleep(3)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        svc = Server('Server')
    else:
        svc = Client('Service')
    svc.on()