import sys
import asyncio
from psvc import Service, Commander, Command

class Print(Command):
    async def handle(self, body, cid):
        self._cmdr.l.debug('print: %s at %d', body, cid)

class Echo(Command):
    async def handle(self, body, cid):
        await self._cmdr.send_command('_print', body, cid)

class Server(Service):
    async def init(self):
        self.cmdr = Commander(self)
        self.cmdr.set_command(Echo, 'echo')
        await self.cmdr.bind('0.0.0.0', 50000)
    
    async def run(self):
        await asyncio.sleep(1)

class Client(Service):
    async def init(self):
        self.cmdr = Commander(self)
        self.cmdr.set_command(Print, '_print')
        self.lastpos = 0
        await self.cmdr.connect('127.0.0.1', 50000)
    
    async def run(self):
        msg = ainput('>')
        self.lastpos += await self.cmdr.handle('echo', msg, 1)
        await asyncio.sleep(3)

async def ainput(prompt="", loop=None):
    loop = loop or asyncio.get_running_loop()
    print(prompt, end="", flush=True)
    msg = await loop.run_in_executor(None, sys.stdin.readline)
    return msg.strip()

if __name__ == '__main__':
    if len(sys.argv) > 1:
        svc = Server('Server')
    else:
        svc = Client('Service')
    svc.on()