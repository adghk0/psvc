# server.py
# 파일 에이전트에 주기적으로 접속하여 대상 파일 다운로드

from psvc import Service, Commander, command

agent_list = [
    ('127.0.0.1', 50620),
]
configs = {
    ('\\wsl.localhost\\Ubuntu\\home\\manager\\test_dir', '*.txt')
}

class FileServer(Service):
    @command(ident='__send_config__')
    async def _cmd_send_config(self, cmdr, body, serial):
        pass

    @command(ident='__recv_file__')
    async def _cmd_recv_file(self, cmdr, body, serial):
        pass

    async def init(self):
        pass

    async def run(self):
        pass


if __name__ == '__main__':
    fs = FileServer(name='FileServer', root_file=__file__)
    fs.on()
