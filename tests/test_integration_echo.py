"""에코 서비스 및 Commander 통합 테스트

Commander를 통한 명령어 처리 및 네트워크 통신을 검증합니다.
"""

import pytest
import sys
import time
import json
from pathlib import Path


@pytest.fixture
def echo_service_file(temp_dir):
    """
    에코 명령을 가진 테스트 서비스

    Args:
        temp_dir: 임시 디렉토리 픽스처

    Returns:
        Path: 에코 서비스 파일 경로
    """
    service_content = '''#!/usr/bin/env python3
"""Echo service for testing Commander"""
import sys
import asyncio
from pathlib import Path

# psvc 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from psvc import Service
from psvc.cmd import Commander, command


class EchoService(Service):
    """에코 서비스 - Commander를 통한 메시지 에코"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cmdr = None
        self.port = 50005

    async def init(self):
        """Commander 초기화 및 포트 바인딩"""
        self.cmdr = Commander(self)
        self.cmdr.set_command(self.echo_command)
        await self.cmdr.bind('0.0.0.0', self.port)
        self.l.info(f'에코 서비스 시작: 포트 {self.port}')

    @command(ident='echo')
    async def echo_command(self, cmdr, body, serial):
        """
        에코 명령 처리기

        Args:
            cmdr: Commander 인스턴스
            body: 명령 본문 {'message': str}
            serial: 소켓 serial 번호

        Returns:
            str: 에코된 메시지
        """
        message = body.get('message', '')
        self.l.info(f'에코 요청 수신: {message}')

        # 응답 전송
        await cmdr.send_command('echo_response', {'message': message}, serial)

    async def run(self):
        """메인 루프"""
        await asyncio.sleep(0.5)

    async def destroy(self):
        """정리"""
        self.l.info('에코 서비스 종료 중')
        await super().destroy()


if __name__ == '__main__':
    service = EchoService('EchoService', __file__)
    sys.exit(service.on())
'''
    service_file = temp_dir / 'echo_service.py'
    service_file.write_text(service_content)
    return service_file


@pytest.fixture
def echo_spec_file(temp_dir, echo_service_file):
    """
    에코 서비스용 PyInstaller spec 파일

    Args:
        temp_dir: 임시 디렉토리 픽스처
        echo_service_file: 에코 서비스 파일 픽스처

    Returns:
        Path: spec 파일 경로
    """
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['{echo_service_file.name}'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['psvc', 'psvc.main', 'psvc.comp', 'psvc.cmd', 'psvc.network', 'psvc.manage'],
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
    name='echo_service',
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
    spec_file = temp_dir / 'echo_service.spec'
    spec_file.write_text(spec_content)
    return spec_file


@pytest.fixture
def echo_client_file(temp_dir):
    """
    에코 클라이언트 스크립트

    Args:
        temp_dir: 임시 디렉토리 픽스처

    Returns:
        Path: 클라이언트 파일 경로
    """
    client_content = '''#!/usr/bin/env python3
"""Echo client for testing"""
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
        import itertools
        self.l = logging.getLogger('echo_client')
        self._tasks = []
        self.name = 'EchoClient'
        self.level = 'INFO'
        self._socket_serial = itertools.count(1)

    def append_task(self, loop, coro, name):
        """태스크 추가"""
        task = loop.create_task(coro, name=name)
        self._tasks.append(task)
        return task

    def next_socket_serial(self):
        """Generate next unique socket serial number"""
        return next(self._socket_serial)


async def send_echo(message, result_file):
    """
    에코 명령 전송 및 응답 수신

    Args:
        message: 전송할 메시지
        result_file: 결과 저장 파일 경로
    """
    svc = DummyService()
    cmdr = Commander(svc)
    sock = cmdr.sock()

    # 응답 수신용
    response_data = {}
    response_event = asyncio.Event()

    @command(ident='echo_response')
    async def receive_response(cmdr, body, serial):
        nonlocal response_data
        response_data = body
        response_event.set()

    cmdr.set_command(receive_response)

    try:
        # 서버 연결
        serial = await sock.connect('localhost', 50005)

        # 에코 명령 전송
        await cmdr.send_command('echo', {'message': message}, serial)

        # 응답 대기
        await asyncio.wait_for(response_event.wait(), timeout=5.0)

        # 결과 저장
        result = {
            'status': 'success',
            'response': response_data.get('message', '')
        }

    except Exception as e:
        import traceback
        result = {
            'status': 'error',
            'error': str(e) if str(e) else repr(e),
            'traceback': traceback.format_exc()
        }

    # 결과 파일에 저장
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == '__main__':
    message = sys.argv[1] if len(sys.argv) > 1 else 'Hello World'
    result_file = sys.argv[2] if len(sys.argv) > 2 else 'echo_result.json'

    asyncio.run(send_echo(message, result_file))
'''
    client_file = temp_dir / 'echo_client.py'
    client_file.write_text(client_content)
    return client_file


@pytest.mark.slow
@pytest.mark.integration
class TestEchoService:
    """에코 서비스 통합 테스트"""

    def test_echo_command_execution(self, temp_dir, echo_service_file,
                                    echo_spec_file, echo_client_file,
                                    process_manager):
        """에코 명령 실행 및 응답 검증"""

        # 1. 에코 서비스 빌드
        build_cmd = [
            sys.executable, str(echo_service_file),
            'build', '-v', '1.0.0', '-f', str(echo_spec_file)
        ]
        build_proc = process_manager['start'](build_cmd)
        returncode = build_proc.wait(timeout=60)

        assert returncode == 0, f"빌드 실패: {build_proc.stderr.read().decode()}"

        # 2. 빌드된 실행 파일 찾기
        releases_dir = temp_dir / 'releases' / '1.0.0'
        exe_name = 'echo_service.exe' if sys.platform == 'win32' else 'echo_service'
        exe_path = releases_dir / exe_name

        assert exe_path.exists(), f"실행 파일이 없음: {exe_path}"

        # 3. 에코 서비스 실행 (백그라운드)
        run_cmd = [str(exe_path), 'run']
        run_proc = process_manager['start'](run_cmd)

        # 4. 포트 리스닝 대기
        port_ready = process_manager['wait_port'](50005, timeout=10)
        assert port_ready, "포트 50005가 10초 내에 열리지 않음"

        print("\n✓ 에코 서비스 시작됨, 포트 50005 리스닝 중")

        # 5. 에코 클라이언트 실행
        result_file = temp_dir / 'echo_result.json'
        client_cmd = [
            sys.executable, str(echo_client_file),
            'Hello World', str(result_file)
        ]
        client_proc = process_manager['start'](client_cmd)
        client_returncode = client_proc.wait(timeout=10)

        assert client_returncode == 0, f"클라이언트 실행 실패: {client_proc.stderr.read().decode()}"

        # 6. 결과 파일 확인
        assert result_file.exists(), "결과 파일이 생성되지 않음"

        with open(result_file, 'r', encoding='utf-8') as f:
            result = json.load(f)

        assert result['status'] == 'success', f"클라이언트 실행 실패: {result.get('error', 'Unknown')}"
        assert result['response'] == 'Hello World', f"에코 응답 불일치: {result['response']}"

        print(f"✓ 에코 명령 테스트 통과: '{result['response']}'")

        # 7. 에코 서비스 종료
        run_proc.terminate()
        run_proc.wait(timeout=5)

        print("✓ 에코 서비스 정상 종료")

    def test_multiple_commands(self, temp_dir, echo_service_file,
                               echo_spec_file, echo_client_file,
                               process_manager):
        """여러 명령 순차 실행"""

        # 빌드 (이미 빌드되어 있으면 재사용)
        releases_dir = temp_dir / 'releases' / '1.0.0'
        exe_name = 'echo_service.exe' if sys.platform == 'win32' else 'echo_service'
        exe_path = releases_dir / exe_name

        if not exe_path.exists():
            build_cmd = [
                sys.executable, str(echo_service_file),
                'build', '-v', '1.0.0', '-f', str(echo_spec_file)
            ]
            build_proc = process_manager['start'](build_cmd)
            build_proc.wait(timeout=60)

        # 에코 서비스 실행
        run_cmd = [str(exe_path), 'run']
        run_proc = process_manager['start'](run_cmd)

        # 포트 대기
        port_ready = process_manager['wait_port'](50005, timeout=10)
        assert port_ready, "포트가 열리지 않음"

        # 여러 메시지 전송
        messages = ['First Message', 'Second Message', 'Third Message']

        for i, message in enumerate(messages):
            result_file = temp_dir / f'echo_result_{i}.json'

            client_cmd = [
                sys.executable, str(echo_client_file),
                message, str(result_file)
            ]
            client_proc = process_manager['start'](client_cmd)
            client_proc.wait(timeout=10)

            # 결과 검증
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)

            assert result['status'] == 'success', f"메시지 {i+1} 실패"
            assert result['response'] == message, f"응답 불일치: {result['response']}"

            print(f"✓ 메시지 {i+1} 성공: '{message}'")

        # 서비스 종료
        run_proc.terminate()
        run_proc.wait(timeout=5)

        print(f"\n✓ 다중 명령 테스트 통과 ({len(messages)}개 메시지)")
