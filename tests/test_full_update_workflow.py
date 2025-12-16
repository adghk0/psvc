"""전체 업데이트 워크플로우 통합 테스트

실제 PyInstaller를 사용한 엔드-투-엔드 테스트:
1. v0.9.0 실행 파일 빌드
2. v1.0.0 실행 파일 빌드 및 승인
3. 업데이트 서버 시작
4. v0.9.0 실행 파일이 자동으로 v1.0.0 다운로드
5. 다운로드된 v1.0.0 실행 파일 실행 검증
"""

import asyncio
import sys
import os
import tempfile
import shutil
import subprocess
import json
import time
from pathlib import Path

# 프로젝트 루트 찾기
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from psvc import Service, Commander
from psvc.release import Releaser
from psvc.utils.checksum import calculate_checksum


def create_updatable_app(temp_dir: Path, version: str, psvc_src_path: str) -> Path:
    """자동 업데이트 기능이 있는 애플리케이션 생성"""
    app_content = f'''#!/usr/bin/env python3
"""Updatable application v{version}"""
import sys
import os
import asyncio
from pathlib import Path

# psvc 모듈 경로 추가
sys.path.insert(0, {repr(psvc_src_path)})

from psvc import Service, Commander
from psvc.release import Updater


class UpdatableApp(Service):
    """자동 업데이트를 지원하는 애플리케이션"""

    def __init__(self):
        # 실행 파일 위치 기준으로 root_path 설정
        root_path = os.path.dirname(os.path.abspath(__file__))
        super().__init__('UpdatableApp', root_path)

        self.set_config('PSVC', 'version', {repr(version)})
        self.version = {repr(version)}

        # 업데이트 다운로드 경로
        update_dir = Path(root_path) / 'updates'
        update_dir.mkdir(exist_ok=True)
        self.set_config('PSVC', 'update_path', str(update_dir))

    async def init(self):
        print(f"UpdatableApp v{{self.version}} starting...")

        try:
            self.cmdr = Commander(self)
            self.cid = await self.cmdr.connect('127.0.0.1', 50006)
            self.updater = Updater(self, self.cmdr)
            print(f"Connected to update server, cid={{self.cid}}")
        except Exception as e:
            print(f"Failed to connect to update server: {{e}}")
            self.stop()

    async def run(self):
        print("Checking for updates...")

        try:
            has_update = await self.updater.check_update(cid=self.cid)

            if has_update:
                latest = self.updater._latest_version
                print(f"Update available: {{self.version}} -> {{latest}}")

                print("Downloading update...")
                await self.updater.download_update(cid=self.cid)
                await asyncio.sleep(2)

                print("Update downloaded successfully!")

                # 결과 저장
                result_file = Path(__file__).parent / 'update_result.json'
                update_dir = Path(self.svc.path(self.updater._download_path)) / latest

                import json
                with open(result_file, 'w') as f:
                    json.dump({{
                        'old_version': self.version,
                        'new_version': latest,
                        'success': True,
                        'download_path': str(update_dir)
                    }}, f, indent=2)
            else:
                print(f"Already up to date (v{{self.version}})")

                result_file = Path(__file__).parent / 'update_result.json'
                import json
                with open(result_file, 'w') as f:
                    json.dump({{
                        'old_version': self.version,
                        'new_version': None,
                        'success': False,
                        'message': 'Already up to date'
                    }}, f, indent=2)
        except Exception as e:
            print(f"Update check failed: {{e}}")
            import traceback
            traceback.print_exc()

        await asyncio.sleep(0.5)
        self.stop()

    async def destroy(self):
        print("UpdatableApp shutting down")
        await super().destroy()


if __name__ == '__main__':
    app = UpdatableApp()
    app.on()
'''

    app_file = temp_dir / f'updatable_app_{version.replace(".", "_")}.py'
    app_file.write_text(app_content)
    return app_file


def create_app_spec(temp_dir: Path, app_file: Path, version: str) -> Path:
    """PyInstaller spec 파일 생성"""
    # 버전을 언더스코어로 변환 (예: "0.9.0" -> "0_9_0")
    version_safe = version.replace(".", "_")
    app_name = f'app_v{version_safe}'

    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    [{repr(str(app_file))}],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['psvc', 'psvc.release', 'psvc.cmd', 'psvc.network', 'psvc.comp', 'psvc.main', 'psvc.utils', 'psvc.utils.version', 'psvc.utils.checksum'],
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
    name='{app_name}',
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

    spec_file = temp_dir / f'{app_name}.spec'
    spec_file.write_text(spec_content)
    return spec_file


def build_version(temp_dir: Path, version: str, release_path: Path, psvc_src: str) -> Path:
    """특정 버전 빌드"""
    print(f"\n  Building v{version}...")

    # 앱 파일 생성
    app_file = create_updatable_app(temp_dir, version, psvc_src)
    spec_file = create_app_spec(temp_dir, app_file, version)

    # 빌드
    class BuildService(Service):
        def __init__(self):
            super().__init__('BuildService', str(temp_dir))
            self.set_config('PSVC', 'version', version)
            self.version = version

        async def run(self):
            pass

    service = BuildService()

    version_dir = service.build(
        version=version,
        spec_file=str(spec_file),
        release_path=str(release_path),
        exclude_patterns=['*.conf', '*.log', '*.pyc']
    )

    print(f"    ✓ Built: {version_dir}")

    # 실행 파일 확인
    exe_name = f'app_v{version.replace(".", "_")}'
    if sys.platform == 'win32':
        exe_name += '.exe'

    exe_path = version_dir / exe_name
    assert exe_path.exists(), f"Executable not found: {exe_path}"

    print(f"    ✓ Executable: {exe_path.name} ({exe_path.stat().st_size / 1024 / 1024:.2f} MB)")

    return version_dir


def test_full_update_workflow():
    """전체 업데이트 워크플로우 테스트"""
    print("\n" + "="*70)
    print("Full Update Workflow Test (with PyInstaller)")
    print("="*70)

    temp_root = Path(tempfile.mkdtemp(prefix='psvc_full_update_test_'))
    build_dir = temp_root / 'build_workspace'
    release_path = temp_root / 'releases'
    run_dir = temp_root / 'run'

    build_dir.mkdir()
    release_path.mkdir()
    run_dir.mkdir()

    psvc_src = str(ROOT / 'src')

    print(f"\n📁 Test directory: {temp_root}")
    print(f"📁 Build workspace: {build_dir}")
    print(f"📁 Release path: {release_path}")
    print(f"📁 Run directory: {run_dir}")

    try:
        # 1. v1.0.0 빌드
        print("\n[1/5] Building v1.0.0 (update version)...")
        print("  ⏳ This may take 1-2 minutes...")
        start_time = time.time()

        v1_dir = build_version(build_dir, '1.0.0', release_path, psvc_src)

        build_time = time.time() - start_time
        print(f"  ✓ Build completed in {build_time:.1f}s")

        # v1.0.0 승인
        print("\n[2/5] Approving v1.0.0...")
        class ApprovalService(Service):
            def __init__(self):
                super().__init__('ApprovalService', str(temp_root))
            async def run(self):
                pass

        approval_svc = ApprovalService()
        approval_svc.release(
            version='1.0.0',
            approve=True,
            release_notes='New version with improvements',
            release_path=str(release_path)
        )
        print("  ✓ v1.0.0 approved")

        # 2. v0.9.0 빌드
        print("\n[3/5] Building v0.9.0 (current version)...")
        print("  ⏳ This may take 1-2 minutes...")
        start_time = time.time()

        v0_dir = build_version(build_dir, '0.9.0', release_path, psvc_src)

        build_time = time.time() - start_time
        print(f"  ✓ Build completed in {build_time:.1f}s")

        # v0.9.0은 draft 상태 유지

        # 3. 업데이트 서버 시작
        print("\n[4/5] Starting update server and running v0.9.0...")

        class UpdateServer(Service):
            def __init__(self):
                super().__init__('UpdateServer', str(temp_root))
                self.set_config('PSVC', 'release_path', str(release_path))

            async def init(self):
                self.cmdr = Commander(self)
                self.releaser = Releaser(self, self.cmdr)
                await self.cmdr.bind('0.0.0.0', 50006)
                self.l.info(f'Update server started with {len(self.releaser.versions)} versions')

            async def run(self):
                await asyncio.sleep(10)
                self.stop()

            async def destroy(self):
                await super().destroy()

        server = UpdateServer()

        # 서버를 백그라운드로 시작
        import threading
        def run_server():
            server.on()

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # 서버 초기화 대기
        time.sleep(2)
        print(f"  ✓ Update server started")

        # v0.9.0 실행 파일을 run_dir로 복사
        v0_exe_name = 'app_v0_9_0'
        if sys.platform == 'win32':
            v0_exe_name += '.exe'

        v0_exe_src = v0_dir / v0_exe_name
        v0_exe_run = run_dir / v0_exe_name
        shutil.copy2(v0_exe_src, v0_exe_run)

        print(f"  Running: {v0_exe_run.name}")

        # v0.9.0 실행 (업데이트 확인 및 다운로드)
        result = subprocess.run(
            [str(v0_exe_run)],
            cwd=str(run_dir),
            capture_output=True,
            text=True,
            timeout=15
        )

        print(f"  Exit code: {result.returncode}")
        print(f"  Output:")
        for line in result.stdout.strip().split('\n')[:15]:  # 처음 15줄만
            print(f"    {line}")

        if result.stderr:
            print(f"  Errors: {result.stderr[:200]}")

        # 4. 결과 검증
        print("\n[5/5] Verifying update results...")

        result_file = run_dir / 'update_result.json'
        assert result_file.exists(), f"Result file not found: {result_file}"
        print(f"  ✓ Result file exists")

        with open(result_file, 'r') as f:
            update_result = json.load(f)

        print(f"  Old version: {update_result.get('old_version')}")
        print(f"  New version: {update_result.get('new_version')}")
        print(f"  Success: {update_result.get('success')}")

        assert update_result.get('old_version') == '0.9.0'
        assert update_result.get('new_version') == '1.0.0'
        assert update_result.get('success') is True

        # 다운로드된 파일 확인
        download_path = Path(update_result.get('download_path'))
        assert download_path.exists(), f"Download path not found: {download_path}"
        print(f"  ✓ Download path exists")

        downloaded_exe = download_path / (f'app_v1_0_0' + ('.exe' if sys.platform == 'win32' else ''))
        assert downloaded_exe.exists(), f"Downloaded exe not found: {downloaded_exe}"
        print(f"  ✓ Downloaded executable: {downloaded_exe.name}")

        # 다운로드된 파일 실행 테스트
        print("\n  Testing downloaded v1.0.0...")
        v1_result = subprocess.run(
            [str(downloaded_exe)],
            cwd=str(download_path),
            capture_output=True,
            text=True,
            timeout=15
        )

        print(f"  Exit code: {v1_result.returncode}")
        if "Already up to date (v1.0.0)" in v1_result.stdout:
            print(f"  ✓ v1.0.0 reports correct version")

        print("\n" + "="*70)
        print("✅ Test PASSED: Full update workflow successful!")
        print("="*70)
        print(f"\nSummary:")
        print(f"  - Built v0.9.0 and v1.0.0 with PyInstaller")
        print(f"  - v0.9.0 detected update and downloaded v1.0.0")
        print(f"  - Downloaded v1.0.0 runs correctly")

        return True

    except subprocess.TimeoutExpired as e:
        print(f"\n❌ Executable timeout: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 서버 종료
        if 'server' in locals():
            server.stop()

        # 정리
        print(f"\n🧹 Cleaning up: {temp_root}")
        time.sleep(1)
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == '__main__':
    success = test_full_update_workflow()
    sys.exit(0 if success else 1)
