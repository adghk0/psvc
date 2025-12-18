"""실행 파일 자가 업데이트 통합 테스트

이 테스트는 다음 시나리오를 검증합니다:
1. PyInstaller로 v0.9.0 실행 파일 빌드
2. 릴리스 서버에 v1.0.0 업데이트 준비
3. v0.9.0 실행 파일 실행
4. 자동으로 업데이트 확인 및 다운로드
5. 다운로드된 파일 검증 (체크섬, 크기)
6. 업데이트 완료 확인
"""

import asyncio
import sys
import os
import tempfile
import shutil
import subprocess
import json
from pathlib import Path

# 프로젝트 루트 찾기
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from psvc import Service, Commander
from psvc.release import Releaser, Updater


class UpdateServer(Service):
    """업데이트 서버 (Releaser 포함)"""

    def __init__(self, name, root_path, release_path):
        super().__init__(name, root_path, version='1.0.0')
        self.set_config('PSVC', 'release_path', release_path)

    async def init(self):
        self.cmdr = Commander(self)
        self.releaser = Releaser(self, self.cmdr)
        await self.cmdr.bind('0.0.0.0', 50004)
        self.l.info('Update server started with %d versions', len(self.releaser.versions))

    async def run(self):
        # 서버는 계속 실행
        await asyncio.sleep(10)

    async def destroy(self):
        self.l.info('Update server shutting down')
        await super().destroy()


def create_updatable_app_spec(temp_dir: Path, version: str) -> Path:
    """업데이트 가능한 앱의 spec 파일 생성"""
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['updatable_app.py'],
    pathex=[{repr(str(temp_dir))}],
    binaries=[],
    datas=[],
    hiddenimports=['psvc', 'psvc.release', 'psvc.cmd', 'psvc.network', 'psvc.comp', 'psvc.main'],
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
    name='updatable_app',
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
    spec_file = temp_dir / f'updatable_app_{version}.spec'
    spec_file.write_text(spec_content)
    return spec_file


def create_updatable_app(temp_dir: Path, version: str, psvc_path: str) -> Path:
    """업데이트 가능한 애플리케이션 생성"""
    app_content = f'''#!/usr/bin/env python3
"""Updatable application for testing"""
import asyncio
import sys
import os
from pathlib import Path

# psvc 모듈 경로 추가
sys.path.insert(0, {repr(psvc_path)})

from psvc import Service, Commander
from psvc.release import Updater


class UpdatableApp(Service):
    """자동 업데이트를 지원하는 애플리케이션"""

    def __init__(self):
        super().__init__('UpdatableApp', __file__, version={repr(version)})
        # 업데이트 다운로드 경로 설정
        update_path = Path(__file__).parent / 'updates'
        update_path.mkdir(exist_ok=True)
        self.set_config('PSVC', 'update_path', str(update_path))

    async def init(self):
        self.l.info('UpdatableApp v%s starting...', self.version)
        self.cmdr = Commander(self)
        self.cid = await self.cmdr.connect('127.0.0.1', 50004)
        self.updater = Updater(self, self.cmdr)
        self.l.info('Connected to update server, cid=%d', self.cid)

    async def run(self):
        self.l.info('Checking for updates...')

        # 업데이트 확인
        has_update = await self.updater.check_update(cid=self.cid)

        if has_update:
            latest = self.updater._latest_version
            self.l.info('Update available: %s -> %s', self.version, latest)

            # 업데이트 다운로드
            self.l.info('Downloading update...')
            await self.updater.download_update(cid=self.cid)

            # 다운로드 완료 대기
            await asyncio.sleep(2)

            self.l.info('✓ Update downloaded successfully!')

            # 다운로드 경로 확인
            update_dir = Path(self.svc.path(self.updater._download_path)) / latest
            if update_dir.exists():
                files = list(update_dir.rglob('*'))
                self.l.info('Downloaded files: %d', len([f for f in files if f.is_file()]))

                # 결과 파일 작성 (테스트 검증용)
                result_file = Path(__file__).parent / 'update_result.json'
                import json
                with open(result_file, 'w') as f:
                    json.dump({{
                        'old_version': self.version,
                        'new_version': latest,
                        'success': True,
                        'download_path': str(update_dir),
                        'file_count': len([f for f in files if f.is_file()])
                    }}, f, indent=2)
        else:
            self.l.info('Already up to date (v%s)', self.version)

            # 결과 파일 작성
            result_file = Path(__file__).parent / 'update_result.json'
            import json
            with open(result_file, 'w') as f:
                json.dump({{
                    'old_version': self.version,
                    'new_version': None,
                    'success': False,
                    'message': 'Already up to date'
                }}, f, indent=2)

        await asyncio.sleep(0.5)
        self.stop()

    async def destroy(self):
        self.l.info('UpdatableApp shutting down')
        await super().destroy()


if __name__ == '__main__':
    app = UpdatableApp()
    app.on()
'''
    app_file = temp_dir / 'updatable_app.py'
    app_file.write_text(app_content)
    return app_file


def build_app_version(temp_dir: Path, version: str, release_path: Path, psvc_path: str):
    """특정 버전의 앱 빌드"""
    print(f"\n  Building version {version}...")

    # 앱 파일 및 spec 파일 생성
    app_file = create_updatable_app(temp_dir, version, psvc_path)
    spec_file = create_updatable_app_spec(temp_dir, version)

    # PyInstaller 실행
    print(f"    Running PyInstaller...")
    build_dir = temp_dir / 'build'
    dist_dir = temp_dir / 'dist'

    cmd = [
        sys.executable, '-m', 'PyInstaller',
        str(spec_file),
        '--distpath', str(dist_dir),
        '--workpath', str(build_dir / 'work'),
        '--specpath', str(build_dir),
        '--clean',
    ]

    result = subprocess.run(cmd, cwd=str(temp_dir), capture_output=True)

    if result.returncode != 0:
        print(f"    ✗ PyInstaller failed:")
        print(result.stderr.decode())
        raise RuntimeError(f"PyInstaller failed for version {version}")

    # 빌드 결과 확인
    exe_name = 'updatable_app.exe' if sys.platform == 'win32' else 'updatable_app'
    exe_path = dist_dir / exe_name

    if not exe_path.exists():
        raise FileNotFoundError(f"Executable not found: {exe_path}")

    print(f"    ✓ Built: {exe_path.name} ({exe_path.stat().st_size / 1024:.1f} KB)")

    # 릴리스 디렉토리로 복사
    version_dir = release_path / version
    version_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(exe_path, version_dir / exe_name)

    # 메타데이터 생성
    from psvc.utils.checksum import calculate_checksum
    from datetime import datetime

    checksum = calculate_checksum(str(version_dir / exe_name))
    file_size = (version_dir / exe_name).stat().st_size

    metadata = {
        'version': version,
        'status': 'approved',  # 테스트용으로 바로 승인
        'build_time': datetime.utcnow().isoformat() + 'Z',
        'platform': sys.platform,
        'files': [{
            'path': exe_name,
            'size': file_size,
            'checksum': checksum
        }],
        'exclude_patterns': ['*.conf', '*.log'],
        'rollback_target': None,
        'release_notes': f'Test version {version}'
    }

    status_file = version_dir / 'status.json'
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"    ✓ Release prepared: {version_dir}")

    return exe_path


def test_self_update():
    """실행 파일 자가 업데이트 테스트"""
    print("\n" + "="*70)
    print("Self-Update Executable Integration Test")
    print("="*70)

    # 임시 디렉토리 생성
    temp_root = Path(tempfile.mkdtemp(prefix='psvc_selfupdate_test_'))
    release_path = temp_root / 'releases'
    release_path.mkdir()
    run_dir = temp_root / 'run'
    run_dir.mkdir()

    print(f"\n📁 Test directory: {temp_root}")
    print(f"📁 Release path: {release_path}")
    print(f"📁 Run directory: {run_dir}")

    psvc_path = str(ROOT / 'src')

    try:
        # 1. v1.0.0 빌드 (업데이트 버전)
        print("\n[1/5] Building update version (v1.0.0)...")
        build_app_version(temp_root, '1.0.0', release_path, psvc_path)

        # 2. v0.9.0 빌드 (현재 버전)
        print("\n[2/5] Building current version (v0.9.0)...")
        exe_path = build_app_version(temp_root, '0.9.0', release_path, psvc_path)

        # v0.9.0은 status를 draft로 변경 (릴리스 서버에서 제공하지 않음)
        status_file = release_path / '0.9.0' / 'status.json'
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        metadata['status'] = 'draft'
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        # 3. 업데이트 서버 시작
        print("\n[3/5] Starting update server...")
        server = UpdateServer('UpdateServer', str(temp_root), str(release_path))
        server_task = asyncio.create_task(server.on_async())

        # 서버 초기화 대기
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(1))
        print(f"  ✓ Update server started")
        print(f"  Available versions: {server.releaser.versions}")

        # 4. v0.9.0 실행 파일 실행
        print("\n[4/5] Running v0.9.0 executable...")

        # 실행 디렉토리로 복사
        exe_name = exe_path.name
        run_exe = run_dir / exe_name
        shutil.copy2(exe_path, run_exe)

        print(f"  Running: {run_exe}")
        result = subprocess.run([str(run_exe)], cwd=str(run_dir), capture_output=True, text=True)

        print(f"  Exit code: {result.returncode}")
        if result.stdout:
            print(f"  Output preview: {result.stdout[:200]}...")

        # 5. 결과 검증
        print("\n[5/5] Verifying update results...")

        result_file = run_dir / 'update_result.json'
        assert result_file.exists(), f"Result file not found: {result_file}"
        print(f"  ✓ Result file exists")

        with open(result_file, 'r') as f:
            update_result = json.load(f)

        print(f"  Old version: {update_result.get('old_version')}")
        print(f"  New version: {update_result.get('new_version')}")
        print(f"  Success: {update_result.get('success')}")

        assert update_result.get('old_version') == '0.9.0', "Old version mismatch"
        assert update_result.get('new_version') == '1.0.0', "New version mismatch"
        assert update_result.get('success') is True, "Update failed"

        # 다운로드된 파일 확인
        download_path = Path(update_result.get('download_path'))
        assert download_path.exists(), f"Download path not found: {download_path}"
        print(f"  ✓ Download path exists: {download_path}")

        downloaded_files = list(download_path.rglob('*'))
        file_count = len([f for f in downloaded_files if f.is_file()])
        assert file_count > 0, "No files downloaded"
        print(f"  ✓ Downloaded files: {file_count}")

        # 체크섬 검증
        downloaded_exe = download_path / exe_name
        assert downloaded_exe.exists(), f"Downloaded executable not found: {downloaded_exe}"
        print(f"  ✓ Downloaded executable: {downloaded_exe.name}")

        from psvc.utils.checksum import calculate_checksum
        downloaded_checksum = calculate_checksum(str(downloaded_exe))

        # 원본과 비교
        original_exe = release_path / '1.0.0' / exe_name
        original_checksum = calculate_checksum(str(original_exe))

        assert downloaded_checksum == original_checksum, "Checksum mismatch!"
        print(f"  ✓ Checksum verified: {downloaded_checksum[:20]}...")

        print("\n" + "="*70)
        print("✅ Test PASSED: Self-update workflow successful!")
        print("="*70)

    finally:
        # 서버 종료
        if 'server' in locals():
            server.stop()
            try:
                asyncio.get_event_loop().run_until_complete(
                    asyncio.wait_for(server_task, timeout=2)
                )
            except:
                pass

        # 임시 디렉토리 정리
        print(f"\n🧹 Cleaning up: {temp_root}")
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == '__main__':
    try:
        test_self_update()
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
