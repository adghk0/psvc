"""서비스 실행 및 종료 통합 테스트

이 테스트는 실제 PyInstaller로 빌드된 실행 파일을 사용하여
서비스의 전체 생명주기(init → run → destroy)를 검증합니다.
"""

import pytest
import sys
import time
from pathlib import Path


@pytest.fixture
def simple_service_file(temp_dir):
    """
    단순 테스트 서비스 파일 생성

    3초 후 자동 종료되며, 생명주기 각 단계를 로그 파일에 기록합니다.

    Args:
        temp_dir: 임시 디렉토리 픽스처

    Returns:
        Path: 서비스 파일 경로
    """
    service_content = '''#!/usr/bin/env python3
"""Simple test service for lifecycle testing"""
import sys
import asyncio
import time
from pathlib import Path

# psvc 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from psvc import Service


class SimpleTestService(Service):
    """단순 테스트 서비스 - 3초 후 자동 종료"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_time = None
        # frozen 상태에서는 실행 파일의 부모 디렉토리(_root_path)에 로그 작성
        # 개발 모드에서는 스크립트 파일의 부모 디렉토리에 로그 작성
        if getattr(sys, 'frozen', False):
            self.log_file = Path(self._root_path) / 'service_lifecycle.log'
        else:
            self.log_file = Path(__file__).parent / 'service_lifecycle.log'

    def write_log(self, message):
        """로그 파일에 메시지 기록"""
        with open(self.log_file, 'a', encoding='utf-8') as f:
            timestamp = time.time()
            f.write(f"[{timestamp:.3f}] {message}\\n")

    async def init(self):
        """초기화 단계"""
        self.write_log("초기화 시작")
        self.start_time = time.time()
        self.l.info("서비스 초기화 완료")
        self.write_log("초기화 완료")

    async def run(self):
        """실행 단계"""
        if not hasattr(self, '_run_logged'):
            self.write_log("실행 시작")
            self._run_logged = True

        # 3초 후 자동 종료
        elapsed = time.time() - self.start_time
        if elapsed >= 3.0:
            self.l.info("3초 경과, 서비스 종료")
            self.write_log("자동 종료 시작")
            self.stop()
        else:
            await asyncio.sleep(0.5)

    async def destroy(self):
        """종료 단계"""
        self.write_log("종료 시작")
        self.l.info("서비스 정리 중")
        await asyncio.sleep(0.1)
        self.write_log("종료 완료")


if __name__ == '__main__':
    service = SimpleTestService('SimpleTestService', __file__)
    sys.exit(service.on())
'''
    service_file = temp_dir / 'simple_service.py'
    service_file.write_text(service_content)
    return service_file


@pytest.fixture
def simple_spec_file(temp_dir, simple_service_file):
    """
    단순 서비스용 PyInstaller spec 파일

    Args:
        temp_dir: 임시 디렉토리 픽스처
        simple_service_file: 서비스 파일 픽스처

    Returns:
        Path: spec 파일 경로
    """
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['{simple_service_file.name}'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['psvc', 'psvc.main', 'psvc.comp', 'psvc.manage'],
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
    name='simple_service',
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
    spec_file = temp_dir / 'simple_service.spec'
    spec_file.write_text(spec_content)
    return spec_file


@pytest.mark.slow
@pytest.mark.integration
class TestServiceLifecycle:
    """서비스 생명주기 통합 테스트"""

    def test_service_build_and_run(self, temp_dir, simple_service_file,
                                   simple_spec_file, process_manager):
        """서비스 빌드 후 실행 및 정상 종료 검증"""

        # 1. 서비스 빌드
        build_cmd = [
            sys.executable, str(simple_service_file),
            'build', '-v', '1.0.0', '-f', str(simple_spec_file)
        ]
        build_proc = process_manager['start'](build_cmd)
        returncode = build_proc.wait(timeout=60)

        assert returncode == 0, f"빌드 실패: {build_proc.stderr.read().decode()}"

        # 2. 빌드된 실행 파일 찾기
        releases_dir = temp_dir / 'releases' / '1.0.0'
        exe_name = 'simple_service.exe' if sys.platform == 'win32' else 'simple_service'
        exe_path = releases_dir / exe_name

        assert exe_path.exists(), f"실행 파일이 없음: {exe_path}"

        # 3. run 모드로 실행
        run_cmd = [str(exe_path), 'run']
        run_proc = process_manager['start'](run_cmd)

        # 4. 프로세스가 자동 종료될 때까지 대기 (최대 10초)
        try:
            returncode = run_proc.wait(timeout=10)
        except Exception as e:
            run_proc.terminate()
            raise AssertionError(f"서비스가 10초 내에 종료되지 않음: {e}")

        # 5. 로그 파일 검증 (frozen 모드에서는 실행 파일 디렉토리에 생성됨)
        log_file = releases_dir / 'service_lifecycle.log'
        assert log_file.exists(), f"로그 파일이 생성되지 않음: {log_file}"

        log_content = log_file.read_text(encoding='utf-8')

        # 생명주기 각 단계 확인
        assert "초기화 시작" in log_content, "초기화 시작 로그 없음"
        assert "초기화 완료" in log_content, "초기화 완료 로그 없음"
        assert "실행 시작" in log_content, "실행 시작 로그 없음"
        assert "자동 종료 시작" in log_content, "자동 종료 로그 없음"
        assert "종료 시작" in log_content, "종료 시작 로그 없음"
        assert "종료 완료" in log_content, "종료 완료 로그 없음"

        # 6. 종료 코드 확인
        assert returncode == 0, f"비정상 종료 코드: {returncode}"

        print(f"\n✓ 서비스 생명주기 테스트 통과")
        print(f"  빌드 경로: {exe_path}")
        print(f"  로그 파일: {log_file}")

    def test_service_sigterm_handling(self, temp_dir, simple_service_file,
                                     simple_spec_file, process_manager):
        """SIGTERM 시그널 처리 검증"""

        # 빌드 (이미 빌드되어 있으면 재사용)
        releases_dir = temp_dir / 'releases' / '1.0.0'
        exe_name = 'simple_service.exe' if sys.platform == 'win32' else 'simple_service'
        exe_path = releases_dir / exe_name

        if not exe_path.exists():
            build_cmd = [
                sys.executable, str(simple_service_file),
                'build', '-v', '1.0.0', '-f', str(simple_spec_file)
            ]
            build_proc = process_manager['start'](build_cmd)
            build_proc.wait(timeout=60)

        # 로그 파일 초기화 (frozen 모드에서는 실행 파일 디렉토리에 생성됨)
        log_file = releases_dir / 'service_lifecycle.log'
        if log_file.exists():
            log_file.unlink()

        # 실행
        run_cmd = [str(exe_path), 'run']
        run_proc = process_manager['start'](run_cmd)

        # 1초 대기 (서비스 초기화 완료)
        time.sleep(1.0)

        # SIGTERM 전송
        run_proc.terminate()

        # 정상 종료 대기
        try:
            returncode = run_proc.wait(timeout=5)
        except Exception:
            run_proc.kill()  # 강제 종료
            raise AssertionError("SIGTERM 후 5초 내에 종료되지 않음")

        # 로그 파일에서 destroy() 호출 확인
        if log_file.exists():
            log_content = log_file.read_text(encoding='utf-8')
            assert "종료 시작" in log_content, "destroy() 호출되지 않음"
            assert "종료 완료" in log_content, "destroy() 완료되지 않음"

        print(f"\n✓ SIGTERM 처리 테스트 통과")
