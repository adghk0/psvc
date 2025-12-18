"""설치 로직 테스트

Config 버전 업데이트 및 파일 배포 검증
"""

import asyncio
import sys
import os
import tempfile
import shutil
import json
import logging
from pathlib import Path

# 프로젝트 루트 찾기
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from psvc import Service, Commander
from psvc.release import Releaser, Updater
from psvc.utils.checksum import calculate_checksum
from datetime import datetime


def create_dummy_release(release_path: Path, version: str, status: str = 'approved'):
    """더미 릴리스 생성"""
    version_dir = release_path / version
    version_dir.mkdir(parents=True, exist_ok=True)

    # 실행 파일 생성
    exe_name = 'test_app.exe' if sys.platform == 'win32' else 'test_app'
    exe_path = version_dir / exe_name
    exe_path.write_text(f'#!/usr/bin/env python3\n# Version {version}\nprint("v{version}")\n')
    exe_path.chmod(0o755)

    # 추가 파일
    lib_file = version_dir / 'lib' / 'module.py'
    lib_file.parent.mkdir(parents=True, exist_ok=True)
    lib_file.write_text(f'# Module for version {version}\n')

    # 메타데이터
    files = []
    for file_path in [exe_path, lib_file]:
        checksum = calculate_checksum(str(file_path))
        rel_path = file_path.relative_to(version_dir)
        files.append({
            'path': str(rel_path).replace('\\', '/'),
            'size': file_path.stat().st_size,
            'checksum': checksum
        })

    metadata = {
        'version': version,
        'status': status,
        'build_time': datetime.now().isoformat(),
        'platform': sys.platform,
        'files': files,
        'exclude_patterns': ['*.conf', '*.log'],
        'rollback_target': None,
        'release_notes': f'Test version {version}'
    }

    status_file = version_dir / 'status.json'
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return version_dir


def test_install_logic():
    """설치 로직 테스트"""
    print("\n" + "="*70)
    print("Installation Logic Test")
    print("="*70)

    temp_root = Path(tempfile.mkdtemp(prefix='psvc_install_test_'))
    release_path = temp_root / 'releases'
    download_path = temp_root / 'downloads'
    install_dir = temp_root / 'install'

    release_path.mkdir()
    download_path.mkdir()
    install_dir.mkdir()

    print(f"\nTest directory: {temp_root}")
    print(f"Download path: {download_path}")
    print(f"Install dir: {install_dir}")

    try:
        # 1. v1.0.0 릴리스 생성 (approved)
        print("\n[1/5] Creating v1.0.0 release...")
        create_dummy_release(release_path, '1.0.0', status='approved')
        print("  Created v1.0.0")

        # 2. 업데이트 서버 및 클라이언트 설정
        print("\n[2/5] Setting up update server and client...")

        class UpdateServer(Service):
            def __init__(self):
                super().__init__('UpdateServer', str(temp_root))
                self.set_config('PSVC', 'release_path', str(release_path))

            async def init(self):
                self.cmdr = Commander(self)
                self.releaser = Releaser(self, self.cmdr)
                await self.cmdr.bind('0.0.0.0', 50007)

            async def run(self):
                await asyncio.sleep(5)
                self.stop()

            async def destroy(self):
                await super().destroy()

        class UpdateClient(Service):
            def __init__(self):
                # Pass a dummy file path inside install_dir so set_root_path extracts the directory correctly
                dummy_file = install_dir / '__dummy__.py'
                super().__init__('UpdateClient', str(dummy_file), level=logging.DEBUG)
                self.set_config('PSVC', 'version', '0.9.0')
                self.version = '0.9.0'
                self.set_config('PSVC', 'update_path', str(download_path))

            async def init(self):
                self.cmdr = Commander(self)
                self.cid = await self.cmdr.connect('127.0.0.1', 50007)
                self.updater = Updater(self, self.cmdr)

            async def run(self):
                print("\n[3/5] Checking for updates...")
                # 업데이트 확인
                has_update = await self.updater.check_update(cid=self.cid)
                if not has_update:
                    print("  No updates available")
                    return

                print(f"  Update available: {self.version} -> {self.updater._latest_version}")

                print("\n[4/5] Downloading update...")
                # 다운로드
                await self.updater.download_update(cid=self.cid)
                print("  Download completed")

                print("\n[5/5] Installing update...")
                # 설치
                await self.updater.install_update()
                print("  Installation completed")

                await asyncio.sleep(0.5)

            async def destroy(self):
                await super().destroy()

        # 서버와 클라이언트를 asyncio로 함께 실행
        import time

        async def run_both():
            # 서버 초기화
            server = UpdateServer()
            await server.init()

            # 초기화 대기
            await asyncio.sleep(0.5)

            # 클라이언트 초기화 및 실행
            client = UpdateClient()
            await client.init()
            await client.run()

            # 종료
            await client.destroy()
            await server.destroy()

            return client

        # 실행
        client = asyncio.run(run_both())

        # 6. 검증
        print("\n[6/6] Verifying installation...")

        # Config 버전 확인
        config_version = client.version
        assert config_version == '1.0.0', f"Version not updated: {config_version}"
        print(f"  Config version: {config_version}")

        # 다운로드 디렉토리 내용 출력
        download_ver_dir = download_path / '1.0.0'
        print(f"\n  Download directory ({download_ver_dir}):")
        for item in download_ver_dir.rglob('*'):
            if item.is_file():
                print(f"    {item.relative_to(download_ver_dir)}")

        # 설치 디렉토리 내용 출력
        print(f"\n  Install directory ({install_dir}):")
        for item in install_dir.rglob('*'):
            if item.is_file():
                print(f"    {item.relative_to(install_dir)}")

        # 설치된 파일 확인
        if sys.platform == 'win32':
            # Windows: .new 파일로 저장됨
            installed_exe = install_dir / 'test_app.exe.new'
            installed_lib = install_dir / 'lib' / 'module.py.new'
        else:
            # Linux: 직접 덮어쓰기
            installed_exe = install_dir / 'test_app'
            installed_lib = install_dir / 'lib' / 'module.py'

        assert installed_exe.exists(), f"Executable not installed: {installed_exe}"
        assert installed_lib.exists(), f"Library not installed: {installed_lib}"
        print(f"  Installed exe: {installed_exe.name}")
        print(f"  Installed lib: {installed_lib}")

        # 백업 확인
        backup_dirs = [d for d in install_dir.iterdir() if d.name.startswith('backup_')]
        print(f"  Backup created: {len(backup_dirs)} backup(s)")

        print("\n" + "="*70)
        print("Test PASSED: Installation logic successful!")
        print("="*70)

        if sys.platform == 'win32':
            print("\nNote: Windows uses .new files, actual swap happens on restart")

    except AssertionError as e:
        print(f"\nTest failed: {e}")
        return False
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 정리
        print(f"\nCleaning up: {temp_root}")
        shutil.rmtree(temp_root, ignore_errors=True)

    return True


if __name__ == '__main__':
    success = test_install_logic()
    sys.exit(0 if success else 1)
