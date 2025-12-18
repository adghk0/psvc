import sys
import asyncio
from psvc import Service, Commander, command

async def ainput(prompt="", loop=None):
    loop = loop or asyncio.get_running_loop()
    print(prompt, end="", flush=True)
    msg = await loop.run_in_executor(None, sys.stdin.readline)
    return msg.strip()

@command
async def print_cmd(cmdr: Commander, body, cid):
    # 서버에서 되돌려 준 문자열 출력
    cmdr.l.info('print: %s at %d', body, cid)

@command(ident='echo')
async def echo_cmd(cmdr: Commander, body, cid):
    # 클라이언트에서 보낸 문자열을 뒤집어서 다시 보냄
    await cmdr.send_command('print_cmd', body, cid)

@command(ident='exit')
async def exit_cmd(cmdr: Commander, body, cid):
    cmdr.l.info('exit: %s at %d', body, cid)
    cmdr.svc.stop()

class Server(Service):
    async def init(self):
        self.cmdr = Commander(self)
        self.cmdr.set_command(echo_cmd, exit_cmd)
        await self.cmdr.bind('0.0.0.0', 50000)
    
    async def run(self):
        await asyncio.sleep(1)

    async def destroy(self):
        self.l.info('Server destroy() called')
        await super().destroy()

class Client(Service):
    async def init(self):
        self.cmdr = Commander(self)
        self.cmdr.set_command(print_cmd)
        self.cid = await self.cmdr.connect('127.0.0.1', 50000)
        self.l.debug('Connected with cid=%d', self.cid)

    async def run(self):
        msg = await ainput('>')
        if not msg:
            return

        if msg.lower() in ('exit', 'quit', 'q'):
            # 서버에 종료 요청
            await self.cmdr.send_command('exit', msg, self.cid)
            # 클라이언트 서비스도 정상 종료
            self.l.info('Client terminate by command: %s', msg)
            self.stop()
            await asyncio.sleep(0.1)
            return

        await self.cmdr.send_command('echo', msg, self.cid)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        svc = Server('EchoServer', __file__)
    else:
        svc = Client('EchoTester', __file__)
    svc.on()