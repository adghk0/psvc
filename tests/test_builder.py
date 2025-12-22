"""Builder 클래스 실제 빌드 테스트 (PyInstaller 사용)"""

import pytest
import sys
import json
from pathlib import Path
from psvc.builder import Builder, BuildError


@pytest.fixture
def test_app_file(temp_dir):
    """
    실제 빌드 가능한 테스트 애플리케이션 생성

    Returns:
        Path: 테스트 앱 파일 경로
    """
    app_content = '''#!/usr/bin/env python3
"""PyService 테스트 애플리케이션"""
import sys
from psvc import Service


class TestApp(Service):
    """간단한 테스트 애플리케이션"""

    async def run(self):
        """메인 실행 로직"""
        print(f"TestApp v{self.version} 실행 중")
        self.stop()


if __name__ == '__main__':
    app = TestApp('TestApp', __file__)
    sys.exit(app.on())
'''
    app_file = temp_dir / 'test_app.py'
    app_file.write_text(app_content)
    return app_file


@pytest.fixture
def test_spec_file(temp_dir, test_app_file):
    """
    실제 빌드용 PyInstaller spec 파일 생성

    Args:
        temp_dir: 임시 디렉토리
        test_app_file: 테스트 앱 파일

    Returns:
        Path: spec 파일 경로
    """
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['{test_app_file.name}'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['psvc', 'psvc.main', 'psvc.comp', 'psvc.builder'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='test_app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
'''
    spec_file = temp_dir / 'test_app.spec'
    spec_file.write_text(spec_content)
    return spec_file


class TestBuilder:
    """Builder 클래스 단위 테스트"""

    def test_builder_initialization(self, temp_dir):
        """Builder 초기화 테스트"""
        builder = Builder(
            service_name='TestService',
            root_path=str(temp_dir),
            release_path=str(temp_dir / 'releases')
        )

        assert builder.service_name == 'TestService'
        assert builder.root_path == Path(temp_dir)
        assert builder.release_path == Path(temp_dir / 'releases')

    def test_builder_default_release_path(self, temp_dir):
        """기본 릴리스 경로 테스트"""
        builder = Builder(
            service_name='TestService',
            root_path=str(temp_dir)
        )

        expected_path = Path(temp_dir) / 'releases'
        assert builder.release_path == expected_path

    def test_build_metadata_structure(self, temp_dir, release_dir, create_build):
        """빌드 메타데이터 구조 검증"""
        # 더미 빌드 생성
        version_dir = create_build(release_dir, '1.0.0', 'draft')

        # 메타데이터 검증
        status_file = version_dir / 'status.json'
        assert status_file.exists()

        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        # 필수 필드 확인
        assert 'version' in metadata
        assert 'status' in metadata
        assert 'build_time' in metadata
        assert 'platform' in metadata
        assert 'files' in metadata
        assert 'exclude_patterns' in metadata

        # 파일 정보 구조 확인
        assert len(metadata['files']) > 0
        file_info = metadata['files'][0]
        assert 'path' in file_info
        assert 'size' in file_info
        assert 'checksum' in file_info

    def test_build_exclude_patterns(self, temp_dir):
        """제외 패턴 테스트"""
        builder = Builder(
            service_name='TestService',
            root_path=str(temp_dir)
        )

        # 기본 제외 패턴
        default_patterns = ['*.conf', '*.log', '*.pyc', '__pycache__']

        # 커스텀 제외 패턴과 병합 확인
        custom_patterns = ['*.txt', '*.md']
        all_patterns = default_patterns + custom_patterns

        assert len(all_patterns) == 6

    def test_version_directory_creation(self, temp_dir, release_dir, create_build):
        """버전 디렉토리 생성 확인"""
        version = '2.5.10'
        version_dir = create_build(release_dir, version, 'draft')

        assert version_dir.exists()
        assert version_dir.is_dir()
        assert version_dir.name == version


@pytest.mark.slow
class TestRealBuild:
    """실제 PyInstaller 빌드 테스트 (느림)"""

    @pytest.mark.skipif(
        not Path('.venv/bin/pyinstaller').exists() and
        not Path('.venv/Scripts/pyinstaller.exe').exists(),
        reason="PyInstaller가 설치되지 않음"
    )
    def test_real_pyinstaller_build(self, temp_dir, test_app_file, test_spec_file):
        """
        실제 PyInstaller 빌드 테스트

        이 테스트는 PyInstaller가 설치되어 있어야 하며,
        실행 시간이 약 30초~1분 소요됩니다.
        """
        # Builder 생성
        builder = Builder(
            service_name='TestApp',
            root_path=str(temp_dir),
            release_path=str(temp_dir / 'releases')
        )

        # 빌드 실행
        version = '1.0.0'
        try:
            version_dir = builder.build(
                version=version,
                spec_file=str(test_spec_file),
                exclude_patterns=['*.pyc', '__pycache__', '*.log']
            )

            # 빌드 결과 확인
            assert version_dir.exists()
            assert version_dir.is_dir()

            # 메타데이터 확인
            status_file = version_dir / 'status.json'
            assert status_file.exists()

            with open(status_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            assert metadata['version'] == version
            assert metadata['status'] == 'draft'
            assert len(metadata['files']) > 0

            # 실행 파일 확인
            exe_name = 'test_app.exe' if sys.platform == 'win32' else 'test_app'
            exe_path = version_dir / exe_name
            assert exe_path.exists()

            # 체크섬 확인
            for file_info in metadata['files']:
                if file_info['path'] == exe_name:
                    assert 'sha256:' in file_info['checksum']
                    assert file_info['size'] > 0
                    break

            print(f"\n✓ 빌드 성공: {version_dir}")
            print(f"  실행 파일: {exe_path}")
            print(f"  파일 크기: {exe_path.stat().st_size / 1024 / 1024:.2f} MB")

        except BuildError as e:
            pytest.fail(f"빌드 실패: {e}")

    @pytest.mark.skipif(
        not Path('.venv/bin/pyinstaller').exists() and
        not Path('.venv/Scripts/pyinstaller.exe').exists(),
        reason="PyInstaller가 설치되지 않음"
    )
    def test_build_without_spec_file(self, temp_dir, test_app_file):
        """
        spec 파일 없이 빌드 시도 (실패 예상)
        """
        builder = Builder(
            service_name='TestApp',
            root_path=str(temp_dir)
        )

        # spec 파일 없이 빌드 시도
        with pytest.raises(BuildError, match="spec 파일이 필요합니다"):
            builder.build(
                version='1.0.0',
                spec_file=None
            )

    @pytest.mark.skipif(
        not Path('.venv/bin/pyinstaller').exists() and
        not Path('.venv/Scripts/pyinstaller.exe').exists(),
        reason="PyInstaller가 설치되지 않음"
    )
    def test_build_with_invalid_spec(self, temp_dir):
        """
        존재하지 않는 spec 파일로 빌드 시도
        """
        builder = Builder(
            service_name='TestApp',
            root_path=str(temp_dir)
        )

        with pytest.raises(BuildError):
            builder.build(
                version='1.0.0',
                spec_file='/nonexistent/file.spec'
            )

    def test_build_metadata_checksum(self, temp_dir, release_dir, create_build):
        """체크섬 무결성 검증"""
        from psvc.utils.checksum import verify_checksum

        # 더미 빌드 생성
        version_dir = create_build(release_dir, '1.0.0', 'draft')

        # 메타데이터 로드
        status_file = version_dir / 'status.json'
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        # 각 파일의 체크섬 검증
        for file_info in metadata['files']:
            file_path = version_dir / file_info['path']
            assert file_path.exists()

            # 체크섬 검증
            is_valid = verify_checksum(str(file_path), file_info['checksum'])
            assert is_valid, f"체크섬 불일치: {file_info['path']}"


class TestBuildVersioning:
    """빌드 버전 관리 테스트"""

    def test_multiple_versions(self, temp_dir, release_dir, create_build):
        """여러 버전 동시 관리"""
        versions = ['0.9.0', '1.0.0', '1.1.0', '2.0.0']

        for version in versions:
            version_dir = create_build(release_dir, version, 'draft')
            assert version_dir.exists()

        # 모든 버전 디렉토리 확인
        created_versions = [d.name for d in release_dir.iterdir() if d.is_dir()]
        for version in versions:
            assert version in created_versions

    def test_version_status_progression(self, temp_dir, release_dir, create_build):
        """버전 상태 진행 (draft -> approved -> deprecated)"""
        from psvc import Service

        # 테스트 서비스
        class TestService(Service):
            async def run(self):
                pass

        # 버전 생성 (draft)
        version_dir = create_build(release_dir, '1.0.0', 'draft')
        status_file = version_dir / 'status.json'

        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        assert metadata['status'] == 'draft'

        # approved로 변경
        metadata['status'] = 'approved'
        metadata['release_notes'] = 'Production ready'

        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # 상태 확인
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        assert metadata['status'] == 'approved'
        assert metadata['release_notes'] == 'Production ready'

        # deprecated로 변경
        metadata['status'] = 'deprecated'
        metadata['rollback_target'] = '0.9.0'

        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # 최종 상태 확인
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        assert metadata['status'] == 'deprecated'
        assert metadata['rollback_target'] == '0.9.0'
