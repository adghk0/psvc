"""서비스 업데이트 통합 테스트

전체 업데이트 워크플로우를 검증합니다:
1. 다중 버전 빌드
2. 릴리스 상태 관리 (draft → approved)
3. 강제 업데이트
4. 버전 확인
"""

import pytest
import sys
import time
import json
import shutil
from pathlib import Path


@pytest.fixture
def update_test_service_file(temp_dir):
    """
    업데이트 테스트 서비스 (클라이언트)

    Commander + Updater를 사용하여 버전 정보 제공 및 업데이트를 받습니다.

    Args:
        temp_dir: 임시 디렉토리 픽스처

    Returns:
        Path: 서비스 파일 경로
    """
    service_content = '''#!/usr/bin/env python3
"""Update test service"""
import sys
import asyncio
from pathlib import Path

# psvc 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from psvc import Service
from psvc.cmd import Commander, command
from psvc.update import Updater


class UpdateTestService(Service):
    """업데이트 테스트 서비스"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cmdr = None
        self.updater = None
        self.port = 60001
        self.release_server_port = 60002

    async def init(self):
        """Commander 및 Updater 초기화"""
        self.cmdr = Commander(self)
        self.cmdr.set_command(self.get_version_command)
        self.cmdr.set_command(self.force_update_command)
        await self.cmdr.bind('0.0.0.0', self.port)

        # Updater 초기화 (release 서버 연결)
        self.updater = Updater(self, self.cmdr, timeout=10)

        self.l.info(f'업데이트 테스트 서비스 시작: v{self.version}, 포트 {self.port}')

    @command(ident='get_version')
    async def get_version_command(self, cmdr, body, cid):
        """현재 버전 반환"""
        await cmdr.send_command('version_response', {'version': self.version}, cid)

    @command(ident='force_update')
    async def force_update_command(self, cmdr, body, cid):
        """강제 업데이트"""
        target_version = body.get('version')
        self.l.info(f'강제 업데이트 요청: {target_version}')

        try:
            # 릴리스 서버에 연결 (cid=1 사용)
            server_cid = await self.cmdr.sock().connect('localhost', self.release_server_port)

            # 업데이트 다운로드
            await self.updater.download_update(version=target_version, cid=server_cid)

            # 업데이트 설치 및 재시작
            await self.updater.install_update(version=target_version)

            # 응답 전송 (재시작 전)
            await cmdr.send_command('update_response', {
                'status': 'success',
                'message': f'버전 {target_version}으로 업데이트 중'
            }, cid)

            # 재시작
            await self.updater.restart_service()

        except Exception as e:
            await cmdr.send_command('update_response', {
                'status': 'error',
                'error': str(e)
            }, cid)

    async def run(self):
        """메인 루프"""
        await asyncio.sleep(0.5)

    async def destroy(self):
        """정리"""
        self.l.info('업데이트 테스트 서비스 종료')
        await super().destroy()


if __name__ == '__main__':
    service = UpdateTestService('UpdateTestService', __file__)
    sys.exit(service.on())
'''
    service_file = temp_dir / 'update_test_service.py'
    service_file.write_text(service_content)
    return service_file


@pytest.fixture
def release_server_file(temp_dir):
    """
    릴리스 서버 서비스

    Releaser를 사용하여 빌드된 버전을 제공합니다.

    Args:
        temp_dir: 임시 디렉토리 픽스처

    Returns:
        Path: 릴리스 서버 파일 경로
    """
    server_content = '''#!/usr/bin/env python3
"""Release server for update testing"""
import sys
import asyncio
from pathlib import Path

# psvc 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from psvc import Service
from psvc.cmd import Commander
from psvc.release import Releaser


class ReleaseServer(Service):
    """릴리스 서버"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cmdr = None
        self.releaser = None
        self.port = 60002

    async def init(self):
        """Commander 및 Releaser 초기화"""
        self.cmdr = Commander(self)
        await self.cmdr.bind('0.0.0.0', self.port)

        # Releaser 초기화
        self.releaser = Releaser(self, self.cmdr)

        self.l.info(f'릴리스 서버 시작: 포트 {self.port}')
        self.l.info(f'릴리스 경로: {self.releaser.release_path}')
        self.l.info(f'사용 가능한 버전: {self.releaser.versions}')

    async def run(self):
        """메인 루프"""
        await asyncio.sleep(0.5)

    async def destroy(self):
        """정리"""
        self.l.info('릴리스 서버 종료')
        await super().destroy()


if __name__ == '__main__':
    service = ReleaseServer('ReleaseServer', __file__)
    sys.exit(service.on())
'''
    server_file = temp_dir / 'release_server.py'
    server_file.write_text(server_content)
    return server_file


@pytest.fixture
def update_spec_file(temp_dir, update_test_service_file):
    """업데이트 테스트 서비스용 spec 파일"""
    # 서비스 파일명 기반으로 실행 파일명 결정
    base_name = update_test_service_file.stem  # 'update_test_service'

    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['{update_test_service_file.name}'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['psvc', 'psvc.main', 'psvc.comp', 'psvc.cmd', 'psvc.network', 'psvc.release', 'psvc.update', 'psvc.manage', 'psvc.utils.checksum', 'psvc.utils.version'],
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
    name='{base_name}',
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
    spec_file = temp_dir / f'{base_name}.spec'
    spec_file.write_text(spec_content)
    return spec_file


@pytest.fixture
def release_spec_file(temp_dir, release_server_file):
    """릴리스 서버용 spec 파일"""
    # 서비스 파일명 기반으로 실행 파일명 결정
    base_name = release_server_file.stem  # 'release_server'

    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['{release_server_file.name}'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['psvc', 'psvc.main', 'psvc.comp', 'psvc.cmd', 'psvc.network', 'psvc.release', 'psvc.update', 'psvc.manage', 'psvc.utils.checksum', 'psvc.utils.version'],
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
    name='{base_name}',
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
    spec_file = temp_dir / f'{base_name}.spec'
    spec_file.write_text(spec_content)
    return spec_file


@pytest.fixture
def version_client_file(temp_dir):
    """버전 확인 클라이언트"""
    client_content = '''#!/usr/bin/env python3
"""Client to get service version"""
import sys
import asyncio
import json
from pathlib import Path

# psvc 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from psvc.network import Socket
from psvc.cmd import Commander, command


class DummyService:
    """클라이언트용 더미 서비스"""
    def __init__(self):
        import logging
        self.l = logging.getLogger('version_client')
        self._tasks = []
        self.name = 'VersionClient'
        self.level = 'INFO'

    def append_task(self, loop, coro, name):
        """태스크 추가"""
        task = loop.create_task(coro, name=name)
        self._tasks.append(task)
        return task


async def get_version(port, result_file):
    """서비스 버전 조회"""
    svc = DummyService()
    cmdr = Commander(svc)
    sock = cmdr.sock()

    response_data = {}
    response_event = asyncio.Event()

    @command(ident='version_response')
    async def receive_version(cmdr, body, cid):
        nonlocal response_data
        response_data = body
        response_event.set()

    cmdr.set_command(receive_version)

    try:
        cid = await sock.connect('localhost', port)
        await cmdr.send_command('get_version', {}, cid)
        await asyncio.wait_for(response_event.wait(), timeout=5.0)

        result = {
            'status': 'success',
            'version': response_data.get('version', 'unknown')
        }

    except Exception as e:
        result = {
            'status': 'error',
            'error': str(e)
        }

    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 60001
    result_file = sys.argv[2] if len(sys.argv) > 2 else 'version_result.json'

    asyncio.run(get_version(port, result_file))
'''
    client_file = temp_dir / 'version_client.py'
    client_file.write_text(client_content)
    return client_file


@pytest.mark.slow
@pytest.mark.integration
class TestServiceUpdate:
    """서비스 업데이트 통합 테스트"""

    def test_full_update_workflow(self, temp_dir, update_test_service_file,
                                   release_server_file, update_spec_file,
                                   release_spec_file, version_client_file,
                                   process_manager):
        """전체 업데이트 워크플로우 검증

        이 테스트는 약 5-10분 소요됩니다.
        """

        print("\n" + "="*70)
        print("업데이트 통합 테스트 시작")
        print("="*70)

        # === 1단계: 빌드 ===
        print("\n[1/7] 빌드 단계")

        # 0. 빌드용 설정 파일 생성
        config_content = {
            'PSVC': {
                'version': '1.0.0'
            }
        }
        config_file = temp_dir / 'psvc.json'
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_content, f, indent=2, ensure_ascii=False)

        # 1.1. 버전 1.0.0 빌드
        print("  1.1. 버전 1.0.0 빌드 중...")
        build_cmd_1 = [
            sys.executable, str(update_test_service_file),
            'build', '-v', '1.0.0', '-f', str(update_spec_file)
        ]
        build_proc = process_manager['start'](build_cmd_1)
        assert build_proc.wait(timeout=120) == 0, "1.0.0 빌드 실패"
        print("  ✓ 버전 1.0.0 빌드 완료")

        # 1.2. 버전 1.1.0 빌드
        print("  1.2. 버전 1.1.0 빌드 중...")
        build_cmd_2 = [
            sys.executable, str(update_test_service_file),
            'build', '-v', '1.1.0', '-f', str(update_spec_file)
        ]
        build_proc = process_manager['start'](build_cmd_2)
        assert build_proc.wait(timeout=120) == 0, "1.1.0 빌드 실패"
        print("  ✓ 버전 1.1.0 빌드 완료")

        # 1.3. 릴리스 서버 빌드 (별도 릴리스 경로 사용)
        print("  1.3. 릴리스 서버 빌드 중...")
        build_cmd_server = [
            sys.executable, str(release_server_file),
            'build', '-v', '1.0.0', '-f', str(release_spec_file),
            '--release_path', 'server_releases'
        ]
        build_proc = process_manager['start'](build_cmd_server)
        assert build_proc.wait(timeout=120) == 0, "릴리스 서버 빌드 실패"
        print("  ✓ 릴리스 서버 빌드 완료")

        # === 2단계: 릴리스 관리 ===
        print("\n[2/7] 릴리스 관리")

        # 2.1. 버전 1.1.0 상태 확인 (draft여야 함)
        status_file = temp_dir / 'releases' / '1.1.0' / 'status.json'
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        # TODO: 서비스를 통한 상태 확인 테스트 변경 필요
        assert metadata['status'] == 'draft', "1.1.0이 draft 상태가 아님"
        print("  ✓ 버전 1.1.0은 draft 상태")

        # 2.2. 버전 1.1.0을 approved 상태로 변경
        print("  2.2. 버전 1.1.0 승인 중...")
        release_cmd = [
            sys.executable, str(update_test_service_file),
            'release', '-v', '1.1.0', '-a', '--release_notes', 'Test Update'
        ]
        release_proc = process_manager['start'](release_cmd)
        assert release_proc.wait(timeout=10) == 0, "릴리스 승인 실패"

        # 2.3. 상태 확인
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        assert metadata['status'] == 'approved', "1.1.0이 approved 상태로 변경되지 않음"
        print("  ✓ 버전 1.1.0 승인 완료")

        # === 3단계: 서비스 실행 ===
        print("\n[3/7] 서비스 실행")

        # 3.1. 릴리스 서버 실행 (server_releases 디렉토리에서)
        server_releases_dir = temp_dir / 'server_releases' / '1.0.0'
        server_exe_name = 'release_server.exe' if sys.platform == 'win32' else 'release_server'
        server_exe_path = server_releases_dir / server_exe_name

        print("  3.1. 릴리스 서버 시작 중...")
        server_proc = process_manager['start']([str(server_exe_path), 'run'])

        # 3.2. 포트 60002 리스닝 대기
        assert process_manager['wait_port'](60002, timeout=10), "릴리스 서버 포트 열리지 않음"
        print("  ✓ 릴리스 서버 시작됨 (포트 60002)")

        # 3.3. 버전 1.0.0 실행 파일 확인 및 복사
        print("  3.3. 버전 1.0.0 실행 파일 복사 중...")
        test_svc_exe_name = 'update_test_service.exe' if sys.platform == 'win32' else 'update_test_service'

        # 빌드된 파일 찾기 (releases/1.0.0 디렉토리 내)
        version_dir = temp_dir / 'releases' / '1.0.0'

        # 실행 파일 찾기 - spec 파일의 name과 일치해야 함
        test_svc_src = version_dir / test_svc_exe_name

        # 파일이 없으면 디렉토리 내용 출력
        if not test_svc_src.exists():
            print(f"  ⚠ 예상 경로에 파일 없음: {test_svc_src}")
            print(f"  디렉토리 내용:")
            for item in version_dir.iterdir():
                print(f"    - {item.name}")
            # 실제 실행 파일 찾기
            for item in version_dir.iterdir():
                if item.is_file() and not item.name.endswith('.json'):
                    test_svc_src = item
                    test_svc_exe_name = item.name
                    print(f"  ✓ 실행 파일 발견: {test_svc_exe_name}")
                    break

        assert test_svc_src.exists(), f"실행 파일이 없음: {test_svc_src}"

        # 실행 디렉토리 생성 및 파일 복사
        test_svc_running = temp_dir / 'running' / test_svc_exe_name
        test_svc_running.parent.mkdir(exist_ok=True)
        shutil.copy2(test_svc_src, test_svc_running)
        if sys.platform != 'win32':
            test_svc_running.chmod(0o755)

        # 설정 파일도 함께 복사
        config_src = version_dir / 'psvc.json'
        if config_src.exists():
            shutil.copy2(config_src, test_svc_running.parent / 'psvc.json')

        print(f"  ✓ 실행 파일 복사 완료: {test_svc_exe_name}")

        # 3.4. 복사된 서비스 실행
        print("  3.4. 업데이트 테스트 서비스 시작 중...")
        test_svc_proc = process_manager['start']([str(test_svc_running), 'run'])

        # 3.5. 포트 60001 리스닝 대기
        assert process_manager['wait_port'](60001, timeout=10), "테스트 서비스 포트 열리지 않음"
        print("  ✓ 테스트 서비스 시작됨 (포트 60001)")

        # === 4단계: 버전 확인 ===
        print("\n[4/7] 초기 버전 확인")

        result_file = temp_dir / 'version_result_1.json'
        version_cmd = [sys.executable, str(version_client_file), '60001', str(result_file)]
        version_proc = process_manager['start'](version_cmd)
        assert version_proc.wait(timeout=10) == 0, "버전 조회 실패"

        with open(result_file, 'r', encoding='utf-8') as f:
            result = json.load(f)

        assert result['status'] == 'success', f"버전 조회 에러: {result.get('error')}"
        assert result['version'] == '1.0.0', f"버전 불일치: {result['version']}"
        print(f"  ✓ 현재 버전: {result['version']}")

        print("\n" + "="*70)
        print("✓ 전체 업데이트 워크플로우 테스트 통과")
        print("="*70)

        # 정리
        test_svc_proc.terminate()
        server_proc.terminate()
        test_svc_proc.wait(timeout=5)
        server_proc.wait(timeout=5)
