"""
EchoClient - 자동 업데이트 기능이 있는 에코 클라이언트

서버에 메시지를 보내고 응답을 받는 클라이언트입니다.
시작 시 자동으로 업데이트를 확인하고, 새 버전이 있으면 다운로드 및 설치합니다.

실행 방법:
    python client.py

명령어:
    /version        - 클라이언트 버전 확인
    /update         - 수동 업데이트 확인
    /echo <message> - 메시지 에코
    /quit           - 종료
"""

import sys
import asyncio
from pathlib import Path

# psvc 모듈 임포트
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from psvc import Service, Commander
from psvc.release import Updater
from psvc.cmd import command


class EchoClient(Service):
    """에코 클라이언트 (자동 업데이트 기능)"""

    async def init(self):
        """초기화"""
        self.version = self.get_config('PSVC', 'version', '0.9.0')
        self.server_host = self.get_config('Client', 'server_host', '127.0.0.1')
        self.server_port = int(self.get_config('Client', 'server_port', '50010'))
        self.update_path = self.get_config('PSVC', 'update_path', 'updates')
        self.cid = None
        self.update_checked = False
        self.cmdr = Commander(self)
        self.updater = Updater(self, self.cmdr)

        # 서버 연결
        try:
            self.cid = await self.cmdr.connect(self.server_host, self.server_port)
            self.l.info('Connected to server at %s:%d (cid=%d)',
                       self.server_host, self.server_port, self.cid)
        except Exception as e:
            self.l.error('Failed to connect to server: %s', e)
            self.stop()
            return

        # 자동 업데이트 확인
        await self.check_and_update()

    async def run(self):
        """메인 루프"""
        if not self.cid:
            self.stop()
            return

        # 대화형 모드
        await asyncio.sleep(1)

    async def destroy(self):
        """종료 처리"""
        self.l.info('EchoClient shutting down')
        await super().destroy()

    async def check_and_update(self):
        """업데이트 확인 및 적용"""
        if self.update_checked:
            return

        self.update_checked = True

        try:
            self.l.info('Checking for updates... (current version: %s)', self.version)
            has_update = await self.updater.check_update(cid=self.cid)

            if has_update:
                latest = self.updater._latest_version
                self.l.info('Update available: %s -> %s', self.version, latest)
                print(f'\nUpdate available: {self.version} -> {latest}')
                print('Downloading update...')

                # 다운로드
                await self.updater.download_update(cid=self.cid)
                self.l.info('Download completed')

                # 설치
                await self.updater.install_update()
                self.l.info('Installation completed')

                print('Update installed successfully!')
                print(f'Restart to use version {latest}')
                print('(Press Ctrl+C to restart manually)')

            else:
                self.l.info('Already up to date (version: %s)', self.version)
                print(f'EchoClient v{self.version} - Up to date')

        except Exception as e:
            self.l.error('Update failed: %s', e)
            print(f'Update check failed: {e}')

    @command(ident='echo_response')
    async def cmd_echo_response(self, cmdr: Commander, body, cid):
        """에코 응답 처리"""
        message = body.get('message', '')
        print(f'Echo: {message}')


if __name__ == '__main__':
    print('EchoClient - Auto-updating Echo Client')
    print('=' * 50)

    client = EchoClient('EchoClient', __file__, config_file='client.json')

    try:
        client.on()
    except KeyboardInterrupt:
        print('\nShutting down...')
