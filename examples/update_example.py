"""
업데이트 시스템 사용 예시

실행 방법:
1. 릴리스 디렉토리 구조 생성:
   python3 examples/update_example.py setup

2. 서버 실행:
   python3 examples/update_example.py server

3. 클라이언트 실행:
   python3 examples/update_example.py client
"""

import sys
import asyncio
from psvc import Service, Commander, Releaser, Updater


class UpdateServer(Service):
    """업데이트 서버 - Releaser를 붙이면 자동으로 업데이트 서버 기능 활성화"""

    async def init(self):
        # Commander 생성
        self.cmdr = Commander(self)
        await self.cmdr.bind('0.0.0.0', 50001)

        # Releaser를 붙이면 자동으로 업데이트 명령어들이 등록됨
        # 설정 파일에 PSVC\release_path가 있어야 함
        try:
            self.releaser = Releaser(self, self.cmdr)
            self.l.info('Update server is ready with %d versions', len(self.releaser.versions))
        except Exception as e:
            self.l.error('Failed to initialize Releaser: %s', e)
            self.l.info('Make sure to configure PSVC\\release_path in psvc.conf')
            self.stop()

    async def run(self):
        await asyncio.sleep(1)

    async def destroy(self):
        self.l.info('Update server shutting down')
        await super().destroy()


class UpdateClient(Service):
    """업데이트 클라이언트 - Updater를 붙이면 자동으로 업데이트 확인/다운로드 기능 활성화"""

    async def init(self):
        # Commander 생성
        self.cmdr = Commander(self)
        await self.cmdr.connect('127.0.0.1', 50001)

        # Updater를 붙이면 자동으로 업데이트 명령어들이 등록됨
        self.updater = Updater(self, self.cmdr)
        self.l.info('Update client initialized, current version: %s', self.version)

    async def run(self):
        # 업데이트 확인 예시
        self.l.info('Checking for updates...')
        has_update = await self.updater.check_update(cid=1)

        if has_update:
            self.l.info('Update available! Latest: %s', self.updater._latest_version)

            # 사용자에게 물어보기 (실제로는 UI 구현 필요)
            # 여기서는 자동으로 업데이트
            self.l.info('Downloading update...')
            await self.updater.download_update(cid=1)

            # 다운로드 완료 대기
            await asyncio.sleep(3)

            self.l.info('Update download completed!')
            # restart=False로 설정하면 재시작하지 않음
            # 실제로는 사용자가 원할 때 restart_service() 호출
        else:
            self.l.info('Already up to date')

        # 종료
        await asyncio.sleep(1)
        self.stop()

    async def destroy(self):
        self.l.info('Update client shutting down')
        await super().destroy()


def create_example_releases():
    """예시 릴리스 파일 생성"""
    import os

    base_dir = 'releases'
    versions = ['0.1', '0.2', '1.0']

    for version in versions:
        version_dir = os.path.join(base_dir, version)
        os.makedirs(version_dir, exist_ok=True)

        # 더미 프로그램 파일 생성
        program_file = os.path.join(version_dir, 'program.py')
        with open(program_file, 'w') as f:
            f.write(f'# Program version {version}\n')
            f.write('print("Hello from version %s")' % version)

        print(f'Created: {program_file}')

    print('\nExample releases created in "releases/" directory')
    print('Add this to psvc.conf:')
    print('[PSVC]')
    print('release_path = releases')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        if sys.argv[1] == 'server':
            svc = UpdateServer('UpdateServer', __file__)
            svc.on()
        elif sys.argv[1] == 'client':
            svc = UpdateClient('UpdateClient', __file__)
            svc.on()
        elif sys.argv[1] == 'setup':
            create_example_releases()
        else:
            print('Usage: python3 examples/update_example.py [server|client|setup]')
    else:
        print('Usage: python3 examples/update_example.py [server|client|setup]')
        print('')
        print('Commands:')
        print('  setup  - Create example release files')
        print('  server - Start update server')
        print('  client - Start update client')
