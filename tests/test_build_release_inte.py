"""빌드 및 릴리스 통합 테스트

이 테스트는 다음 시나리오를 검증합니다:
1. 개발 서비스가 빌드를 수행하여 새 버전 생성 (draft 상태)
2. 릴리스 서버 시작
3. 개발 서비스가 릴리스 서버에 접속
4. 릴리스 명령 전달하여 버전 승인 (approved 상태)
5. 릴리스 서버가 승인된 버전만 제공하는지 확인
"""

import asyncio
import sys
import os
import tempfile
import shutil
from pathlib import Path

# 프로젝트 루트 찾기
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from psvc import Service, Commander
from psvc.release import Releaser
from psvc.cmd import command


class ReleaseServer(Service):
    """릴리스 서버 (Releaser 포함)"""

    def __init__(self, name, root_path, release_path):
        super().__init__(name, root_path, version='1.0.0')
        self.release_path = release_path
        self.set_config('PSVC', 'release_path', release_path)

    async def init(self):
        self.cmdr = Commander(self)
        self.releaser = Releaser(self, self.cmdr)

        # 개발 서비스로부터 release 명령을 받을 핸들러 등록
        self.cmdr.set_command(self._cmd_release_approve, self._cmd_exit)

        await self.cmdr.bind('0.0.0.0', 50003)
        self.l.info('Release server started')

    @command(ident='release_approve')
    async def _cmd_release_approve(self, cmdr: Commander, body, cid):
        """개발 서비스로부터 릴리스 승인 요청"""
        version = body.get('version')
        release_notes = body.get('release_notes', '')

        self.l.info('Release approval requested: version=%s', version)

        try:
            # Service.release() 메서드 호출
            self.release(version=version, approve=True, release_notes=release_notes)

            # 버전 목록 갱신
            self.releaser.versions = self.releaser.get_version_list()

            await cmdr.send_command('release_result', {
                'success': True,
                'version': version,
                'approved_versions': self.releaser.versions
            }, cid)

        except Exception as e:
            self.l.exception('Release approval failed')
            await cmdr.send_command('release_result', {
                'success': False,
                'error': str(e)
            }, cid)

    @command(ident='exit')
    async def _cmd_exit(self, cmdr: Commander, body, cid):
        """종료 명령"""
        self.l.info('Exit command received')
        self.stop()

    async def run(self):
        await asyncio.sleep(0.5)

    async def destroy(self):
        self.l.info('Release server shutting down')
        await super().destroy()


class DeveloperService(Service):
    """개발 서비스 (빌드 및 릴리스 요청)"""

    def __init__(self, name, root_path, release_path, spec_file):
        super().__init__(name, root_path, version='0.9.0')
        self.release_path = release_path
        self.spec_file = spec_file
        self.result = None

    async def init(self):
        self.cmdr = Commander(self)
        self.cmdr.set_command(self._cmd_release_result)
        self.cid = await self.cmdr.connect('127.0.0.1', 50003)
        self.l.info('Developer service connected, cid=%d', self.cid)

    @command(ident='release_result')
    async def _cmd_release_result(self, cmdr: Commander, body, cid):
        """릴리스 결과 수신"""
        self.result = body
        self.l.info('Release result received: %s', body)

    async def run(self):
        # 1. 빌드 수행
        self.l.info('Starting build process...')
        new_version = '1.0.0'

        try:
            version_dir = self.build(
                version=new_version,
                spec_file=self.spec_file,
                release_path=self.release_path
            )
            self.l.info('Build completed: %s', version_dir)

        except Exception as e:
            self.l.exception('Build failed')
            self.stop()
            return

        await asyncio.sleep(0.5)

        # 2. 릴리스 서버에 승인 요청
        self.l.info('Requesting release approval for version %s', new_version)
        await self.cmdr.send_command('release_approve', {
            'version': new_version,
            'release_notes': 'Initial release with core features'
        }, self.cid)

        # 3. 응답 대기
        await asyncio.sleep(1)

        # 4. 결과 확인
        if self.result and self.result.get('success'):
            self.l.info('✓ Release approved successfully!')
            self.l.info('  Approved versions: %s', self.result.get('approved_versions'))
        else:
            self.l.error('✗ Release approval failed: %s',
                        self.result.get('error') if self.result else 'No response')

        # 5. 서버 종료 요청
        await self.cmdr.send_command('exit', {}, self.cid)
        await asyncio.sleep(0.5)

        self.stop()

    async def destroy(self):
        self.l.info('Developer service shutting down')
        await super().destroy()


def create_test_spec_file(temp_dir: Path) -> Path:
    """테스트용 간단한 spec 파일 생성"""
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
    spec_file = temp_dir / 'dummy_app.spec'
    spec_file.write_text(spec_content)
    return spec_file


def create_dummy_app(temp_dir: Path) -> Path:
    """테스트용 더미 애플리케이션"""
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


def test_build_and_release():
    """빌드 및 릴리스 통합 테스트"""
    print("\n" + "="*70)
    print("Build and Release Integration Test")
    print("="*70)

    # 임시 디렉토리 생성
    temp_root = Path(tempfile.mkdtemp(prefix='psvc_build_test_'))
    release_path = temp_root / 'releases'
    release_path.mkdir()

    print(f"\n📁 Test directory: {temp_root}")
    print(f"📁 Release path: {release_path}")

    try:
        # 더미 앱 및 spec 파일 생성
        print("\n[1/4] Creating dummy application and spec file...")
        app_file = create_dummy_app(temp_root)
        spec_file = create_test_spec_file(temp_root)
        print(f"  ✓ Created: {app_file.name}")
        print(f"  ✓ Created: {spec_file.name}")

        # 릴리스 서버 시작
        print("\n[2/4] Starting release server...")
        server = ReleaseServer('ReleaseServer', str(temp_root), str(release_path))
        server_task = asyncio.create_task(server.on_async())

        # 서버 초기화 대기
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(1))
        print("  ✓ Release server started")

        # 개발 서비스 시작 (빌드 및 릴리스 요청)
        print("\n[3/4] Starting developer service (build + release)...")
        dev_service = DeveloperService(
            'DeveloperService',
            str(temp_root),
            str(release_path),
            str(spec_file)
        )

        # 개발 서비스 실행
        asyncio.get_event_loop().run_until_complete(dev_service.on_async())

        # 서버 종료 대기
        try:
            asyncio.get_event_loop().run_until_complete(
                asyncio.wait_for(server_task, timeout=5)
            )
        except asyncio.TimeoutError:
            print("  ⚠ Server timeout, forcing shutdown...")
            server.stop()

        print("\n[4/4] Verifying results...")

        # 결과 검증
        version_dir = release_path / '1.0.0'
        status_file = version_dir / 'status.json'

        assert version_dir.exists(), f"Version directory not found: {version_dir}"
        print(f"  ✓ Version directory exists: {version_dir}")

        assert status_file.exists(), f"Status file not found: {status_file}"
        print(f"  ✓ Status file exists: {status_file}")

        # status.json 내용 확인
        import json
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        assert metadata['version'] == '1.0.0', "Version mismatch"
        print(f"  ✓ Version: {metadata['version']}")

        assert metadata['status'] == 'approved', f"Status should be 'approved', got '{metadata['status']}'"
        print(f"  ✓ Status: {metadata['status']}")

        assert len(metadata['files']) > 0, "No files in metadata"
        print(f"  ✓ Files: {len(metadata['files'])} file(s)")

        assert metadata['release_notes'] == 'Initial release with core features'
        print(f"  ✓ Release notes: {metadata['release_notes'][:50]}...")

        # 개발 서비스 결과 확인
        assert dev_service.result is not None, "No result received from server"
        assert dev_service.result.get('success'), "Release approval failed"
        assert '1.0.0' in dev_service.result.get('approved_versions', [])
        print(f"  ✓ Developer service received approval confirmation")

        print("\n" + "="*70)
        print("✅ Test PASSED: Build and release workflow successful!")
        print("="*70)

    finally:
        # 임시 디렉토리 정리
        print(f"\n🧹 Cleaning up: {temp_root}")
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == '__main__':
    try:
        test_build_and_release()
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
