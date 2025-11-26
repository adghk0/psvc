import sys
import asyncio
import logging
from psvc import Service, Commander, Releaser, Updater

async def ainput(prompt="", loop=None):
    loop = loop or asyncio.get_running_loop()
    print(prompt, end="", flush=True)
    msg = await loop.run_in_executor(None, sys.stdin.readline)
    return msg.strip()

class Server(Service):
    async def init(self):
        self.cmdr = Commander(self)
        Releaser(self, self.cmdr)
        await self.cmdr.bind('0.0.0.0', 50000)
    
    async def run(self):
        await asyncio.sleep(1)

class Client(Service):
    async def init(self):
        self.cmdr = Commander(self)
        await self.cmdr.connect('127.0.0.1', 50000)

    
    async def run(self):
        msg = await ainput('>')
        if msg == 'l':
            self.cmdr.send_command(Releaser.__send_versions__, {}, 1)
            print(self.cmdr.sock().recv_str(1))
        await asyncio.sleep(3)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        svc = Server('ReleaseServer', __file__, config_file='release.conf', level=logging.DEBUG)
    else:
        svc = Client('UpdateTester', __file__, config_file='updater.conf', level=logging.DEBUG)
    svc.on()