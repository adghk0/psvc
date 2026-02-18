"""
EchoServer - 메시지 에코 및 업데이트 서버

클라이언트로부터 메시지를 받아 그대로 돌려주는 에코 서버입니다.
동시에 UpdateServer 역할을 수행하여 클라이언트 업데이트를 제공합니다.

실행 방법:
    python server.py

명령어:
    /version        - 서버 버전 확인
    /clients        - 연결된 클라이언트 목록
    /shutdown       - 서버 종료
"""

import sys
import asyncio
from pathlib import Path

# psvc 모듈 임포트
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from psvc import Service, Commander
from psvc.release import Releaser


class EchoServer(Service):
    """에코 서버 (UpdateServer 겸용)"""
    async def init(self):
        """초기화"""
        self.port = int(self.get_config('Server', 'port', '50010'))
        self.release_path = self.get_config('PSVC', 'release_path', 'releases')
        self.cmdr = Commander(self)
        self.releaser = Releaser(self, self.cmdr)

        # 서버 바인딩
        await self.cmdr.bind('0.0.0.0', self.port)
        self.l.info('EchoServer v%s listening on port %d', self.version, self.port)
        self.l.info('Release path: %s', self.path(self.release_path))
        self.l.info('Available versions: %s', self.releaser.get_version_list())

    async def run(self):
        """메인 루프"""
        await asyncio.sleep(1)

    async def destroy(self):
        """종료 처리"""
        self.l.info('EchoServer shutting down')
        await super().destroy()


if __name__ == '__main__':
    server = EchoServer('EchoServer', __file__, config_file='server.json')
    server.on()
