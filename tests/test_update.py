"""업데이트 기능 테스트"""

import pytest
import asyncio
import json
from pathlib import Path
from psvc import Service, Commander
from psvc.release import Releaser, Updater
from psvc.cmd import command


class UpdateServer(Service):
    """업데이트 서버"""

    def __init__(self, name, root_path, release_path, port=50004):
        super().__init__(name, root_path)
        self.set_config('PSVC', 'version', '1.0.0')
        self.set_config('PSVC', 'release_path', release_path)
        self.port = port

    async def init(self):
        """서버 초기화"""
        self.cmdr = Commander(self)
        self.releaser = Releaser(self, self.cmdr)
        await self.cmdr.bind('0.0.0.0', self.port)
        self.l.info('업데이트 서버 시작됨: 포트 %d', self.port)

    async def run(self):
        """서버 실행 루프"""
        await asyncio.sleep(0.5)

    async def destroy(self):
        """서버 종료"""
        self.l.info('업데이트 서버 종료 중')
        await super().destroy()


class TestUpdate:
    """업데이트 기능 테스트"""

    def test_version_list(self, temp_dir, release_dir, create_build):
        """버전 목록 가져오기"""
        # 여러 버전 생성
        create_build(release_dir, '0.9.0', 'draft')
        create_build(release_dir, '1.0.0', 'approved')
        create_build(release_dir, '1.1.0', 'approved')

        # Releaser 생성 (Commander 모킹)
        from unittest.mock import MagicMock
        server = UpdateServer('UpdateServer', str(temp_dir), str(release_dir))
        server.set_config('Releaser', 'release_path', str(release_dir))
        cmdr_mock = MagicMock()
        releaser = Releaser(server, cmdr_mock)

        # 버전 목록 확인 (approved만 반환되어야 함)
        versions = releaser.get_version_list()

        assert '1.0.0' in versions
        assert '1.1.0' in versions
        assert '0.9.0' not in versions  # draft는 제외

    def test_updater_version_comparison(self, temp_dir):
        """버전 비교 로직 테스트"""
        from psvc.utils.version import compare_versions

        # 업데이트 가능
        assert compare_versions('1.1.0', '0.9.0') > 0

        # 최신 버전
        assert compare_versions('1.0.0', '1.1.0') < 0

        # 동일 버전
        assert compare_versions('1.0.0', '1.0.0') == 0

    def test_build_metadata(self, release_dir, create_build):
        """빌드 메타데이터 검증"""
        import json

        # 버전 생성
        version_dir = create_build(release_dir, '1.0.0', 'approved')

        # 메타데이터 확인
        status_file = version_dir / 'status.json'
        assert status_file.exists()

        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        assert metadata['version'] == '1.0.0'
        assert metadata['status'] == 'approved'
        assert len(metadata['files']) > 0

