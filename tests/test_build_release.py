"""릴리스 승인 및 롤백 테스트"""

import pytest
import json
from pathlib import Path
from psvc import Service


class ReleaseTestService(Service):
    """릴리스 테스트용 서비스"""

    async def run(self):
        """더미 실행"""
        pass


class TestRelease:
    """릴리스 승인 및 관리 테스트"""

    def test_release_metadata_creation(self, temp_dir, release_dir, create_build):
        """빌드 메타데이터 생성 테스트"""
        # 더미 빌드 생성
        version_dir = create_build(release_dir, '1.0.0', 'draft')

        # 디렉토리 및 파일 존재 확인
        assert version_dir.exists()
        status_file = version_dir / 'status.json'
        assert status_file.exists()

        # 메타데이터 검증
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        assert metadata['version'] == '1.0.0'
        assert metadata['status'] == 'draft'
        assert len(metadata['files']) > 0
        assert 'checksum' in metadata['files'][0]

    def test_release_approval(self, temp_dir, release_dir, create_build):
        """릴리스 승인 테스트"""
        # 더미 빌드 생성
        version_dir = create_build(release_dir, '1.0.0', 'draft')

        # 서비스 생성 및 승인
        service = ReleaseTestService('ReleaseService', str(temp_dir))
        service.release(
            version='1.0.0',
            approve=True,
            release_notes='Test release',
            release_path=str(release_dir)
        )

        # 상태 확인
        status_file = version_dir / 'status.json'
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        assert metadata['status'] == 'approved'
        assert metadata['release_notes'] == 'Test release'

    def test_release_info_display(self, temp_dir, release_dir, create_build):
        """릴리스 정보 조회 테스트 (승인 없이)"""
        # 더미 빌드 생성
        version_dir = create_build(release_dir, '1.0.0', 'draft')

        # 서비스 생성
        service = ReleaseTestService('ReleaseService', str(temp_dir))

        # 정보만 조회 (approve=False)
        metadata = service.release(
            version='1.0.0',
            approve=False,
            release_path=str(release_dir)
        )

        # 메타데이터 확인
        assert metadata['version'] == '1.0.0'
        assert metadata['status'] == 'draft'  # 아직 승인되지 않음
        assert len(metadata['files']) > 0

    def test_rollback_workflow(self, temp_dir, release_dir, create_build):
        """롤백 워크플로우 테스트"""
        # 두 버전 생성
        create_build(release_dir, '0.9.0', 'approved')
        create_build(release_dir, '1.0.0', 'approved')

        # 서비스 생성
        service = ReleaseTestService('ReleaseService', str(temp_dir))

        # 롤백 수행
        result = service.rollback(
            from_version='1.0.0',
            to_version='0.9.0',
            release_path=str(release_dir)
        )

        # 롤백 결과 확인
        assert result['from_version'] == '1.0.0'
        assert result['to_version'] == '0.9.0'

        # 1.0.0이 deprecated로 변경되었는지 확인
        status_file = release_dir / '1.0.0' / 'status.json'
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        assert metadata['status'] == 'deprecated'
        assert metadata['rollback_target'] == '0.9.0'

        # 0.9.0은 여전히 approved인지 확인
        status_file = release_dir / '0.9.0' / 'status.json'
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        assert metadata['status'] == 'approved'

    def test_multiple_approvals(self, temp_dir, release_dir, create_build):
        """여러 버전 순차 승인 테스트"""
        versions = ['0.9.0', '1.0.0', '1.1.0']

        # 서비스 생성
        service = ReleaseTestService('ReleaseService', str(temp_dir))

        # 각 버전 빌드 및 승인
        for version in versions:
            create_build(release_dir, version, 'draft')

            service.release(
                version=version,
                approve=True,
                release_notes=f'Release {version}',
                release_path=str(release_dir)
            )

        # 모든 버전이 approved 상태인지 확인
        for version in versions:
            status_file = release_dir / version / 'status.json'
            with open(status_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            assert metadata['status'] == 'approved'
            assert metadata['release_notes'] == f'Release {version}'
