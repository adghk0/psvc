"""pytest 설정 및 공통 픽스처"""

import pytest
import tempfile
import shutil
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

# 프로젝트 루트를 path에 추가
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(autouse=True)
def mock_argv():
    """
    Service 클래스가 sys.argv를 파싱하지 않도록 모킹

    pytest 실행 시 sys.argv에 테스트 관련 인자가 포함되어
    Service 클래스의 argparse와 충돌하는 것을 방지합니다.
    """
    with patch.object(sys, 'argv', ['test_program']):
        yield


@pytest.fixture
def temp_dir():
    """
    임시 디렉토리 생성 및 테스트 후 자동 정리

    Yields:
        Path: 임시 디렉토리 경로
    """
    temp_path = Path(tempfile.mkdtemp(prefix='psvc_test_'))
    yield temp_path
    # 테스트 후 정리
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def release_dir(temp_dir):
    """
    릴리스 디렉토리 생성

    Args:
        temp_dir: 임시 디렉토리 픽스처

    Returns:
        Path: 릴리스 디렉토리 경로
    """
    release_path = temp_dir / 'releases'
    release_path.mkdir(parents=True, exist_ok=True)
    return release_path


@pytest.fixture
def update_dir(temp_dir):
    """
    업데이트 디렉토리 생성

    Args:
        temp_dir: 임시 디렉토리 픽스처

    Returns:
        Path: 업데이트 디렉토리 경로
    """
    update_path = temp_dir / 'updates'
    update_path.mkdir(parents=True, exist_ok=True)
    return update_path


@pytest.fixture
def event_loop():
    """
    비동기 테스트를 위한 이벤트 루프

    Yields:
        asyncio.AbstractEventLoop: 이벤트 루프
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture
def dummy_app_file(temp_dir):
    """
    테스트용 더미 애플리케이션 파일 생성

    Args:
        temp_dir: 임시 디렉토리 픽스처

    Returns:
        Path: 더미 앱 파일 경로
    """
    app_content = '''#!/usr/bin/env python3
"""Dummy application for testing"""
import sys

def main():
    print("Dummy App v1.0.0")
    return 0

if __name__ == '__main__':
    sys.exit(main())
'''
    app_file = temp_dir / 'dummy_app.py'
    app_file.write_text(app_content)
    return app_file


@pytest.fixture
def spec_file(temp_dir):
    """
    PyInstaller spec 파일 생성

    Args:
        temp_dir: 임시 디렉토리 픽스처

    Returns:
        Path: spec 파일 경로
    """
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['dummy_app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
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
    name='dummy_app',
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
    spec_path = temp_dir / 'dummy_app.spec'
    spec_path.write_text(spec_content)
    return spec_path


def create_dummy_build(release_path: Path, version: str, status: str = 'draft'):
    """
    더미 빌드 파일 및 메타데이터 생성

    Args:
        release_path: 릴리스 디렉토리 경로
        version: 버전 문자열
        status: 릴리스 상태 (draft, approved, deprecated)

    Returns:
        Path: 생성된 버전 디렉토리 경로
    """
    import json
    from datetime import datetime
    from psvc.utils.checksum import calculate_checksum

    # 버전 디렉토리 생성
    version_dir = release_path / version
    version_dir.mkdir(parents=True, exist_ok=True)

    # 더미 실행 파일 생성
    exe_name = 'dummy_app.exe' if sys.platform == 'win32' else 'dummy_app'
    exe_path = version_dir / exe_name
    exe_path.write_text(f'#!/usr/bin/env python3\nprint("Dummy App v{version}")\n')
    exe_path.chmod(0o755)

    # 체크섬 계산
    checksum = calculate_checksum(str(exe_path))
    file_size = exe_path.stat().st_size

    # 메타데이터 생성
    metadata = {
        'version': version,
        'status': status,
        'build_time': datetime.utcnow().isoformat() + 'Z',
        'platform': sys.platform,
        'files': [{
            'path': exe_name,
            'size': file_size,
            'checksum': checksum
        }],
        'exclude_patterns': ['*.conf', '*.log'],
        'rollback_target': None,
        'release_notes': ''
    }

    # status.json 저장
    status_file = version_dir / 'status.json'
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return version_dir


@pytest.fixture
def create_build():
    """
    더미 빌드 생성 함수를 반환하는 픽스처

    Returns:
        callable: create_dummy_build 함수
    """
    return create_dummy_build


@pytest.fixture
def process_manager(temp_dir):
    """
    프로세스 생명주기 관리 헬퍼

    통합 테스트에서 서비스 프로세스를 시작하고 정리하는 기능 제공.
    테스트 종료 시 모든 프로세스를 자동으로 강제 종료합니다.

    Yields:
        dict: 프로세스 관리 함수 딕셔너리
            - 'start': 프로세스 시작 함수
            - 'wait_port': 포트 리스닝 대기 함수
            - 'processes': 실행 중인 프로세스 리스트
    """
    import subprocess
    import socket
    import time

    processes = []

    def start_process(cmd, log_file=None, **kwargs):
        """
        프로세스 시작

        Args:
            cmd: 실행할 명령 (리스트)
            log_file: 로그 파일 경로 (optional)
            **kwargs: subprocess.Popen에 전달할 추가 인자

        Returns:
            subprocess.Popen: 시작된 프로세스 객체
        """
        default_kwargs = {
            'stdout': subprocess.PIPE,
            'stderr': subprocess.PIPE,
            'cwd': str(temp_dir)
        }
        default_kwargs.update(kwargs)

        proc = subprocess.Popen(cmd, **default_kwargs)
        processes.append(proc)
        return proc

    def wait_for_port(port, timeout=10):
        """
        포트가 리스닝 상태가 될 때까지 대기

        Args:
            port: 대기할 포트 번호
            timeout: 타임아웃 (초)

        Returns:
            bool: 포트가 열렸으면 True, 타임아웃 시 False
        """
        start = time.time()
        while time.time() - start < timeout:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.1)
                result = sock.connect_ex(('localhost', port))
                sock.close()
                if result == 0:
                    return True
            except Exception:
                pass
            time.sleep(0.1)
        return False

    yield {
        'start': start_process,
        'wait_port': wait_for_port,
        'processes': processes
    }

    # 정리: 모든 프로세스 강제 종료
    for proc in processes:
        if proc.poll() is None:  # 아직 실행 중이면
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()  # terminate 실패 시 강제 종료
                except Exception:
                    pass
