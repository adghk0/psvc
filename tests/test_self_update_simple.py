"""간단한 자가 업데이트 통합 테스트

PyInstaller 빌드 없이 더미 파일로 자가 업데이트 시나리오 검증:
1. v0.9.0과 v1.0.0 릴리스 준비 (v1.0.0만 approved)
2. 업데이트 서버 시작
3. v0.9.0 클라이언트 실행
4. 자동으로 업데이트 확인 및 다운로드
5. 다운로드된 파일 검증 (체크섬, 크기, 디렉토리 구조)
"""

import asyncio
import sys
import os
import tempfile
import shutil
import json
from pathlib import Path

# 프로젝트 루트 찾기
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from psvc import Service, Commander
from psvc.release import Releaser, Updater
from psvc.utils.checksum import calculate_checksum
from datetime import datetime


class UpdateServer(Service):
    """업데이트 서버 (Releaser 포함)"""

    def __init__(self, name, root_path, release_path):
        super().__init__(name, root_path)
        self.set_config('PSVC', 'version', '1.0.0')
        self.version = '1.0.0'
        self.set_config('PSVC', 'release_path', release_path)

    async def init(self):
        self.cmdr = Commander(self)
        self.releaser = Releaser(self, self.cmdr)
        await self.cmdr.bind('0.0.0.0', 50005)
        self.l.info('Update server started with %d versions', len(self.releaser.versions))

    async def run(self):
        # 서버는 클라이언트가 완료할 때까지 대기
        await asyncio.sleep(5)
        self.stop()

    async def destroy(self):
        self.l.info('Update server shutting down')
        await super().destroy()


class UpdateClient(Service):
    """업데이트 클라이언트 (v0.9.0)"""

    def __init__(self, name, root_path, download_path):
        super().__init__(name, root_path)
        self.set_config('PSVC', 'version', '0.9.0')
        self.version = '0.9.0'
        self.set_config('PSVC', 'update_path', download_path)
        self.download_path = download_path

    async def init(self):
        self.cmdr = Commander(self)
        self.cid = await self.cmdr.connect('127.0.0.1', 50005)
        self.updater = Updater(self, self.cmdr)
        self.l.info('Client initialized, version=%s, cid=%d', self.version, self.cid)

    async def run(self):
        self.l.info('Checking for updates...')

        # 업데이트 확인
        has_update = await self.updater.check_update(cid=self.cid)
        self.l.info('Has update: %s', has_update)

        if has_update:
            latest = self.updater._latest_version
            self.l.info('Update available: %s -> %s', self.version, latest)

            # 업데이트 다운로드
            self.l.info('Downloading update...')
            await self.updater.download_update(cid=self.cid)

            # 다운로드 완료 대기
            await asyncio.sleep(2)

            self.l.info('✓ Update downloaded successfully!')
        else:
            self.l.info('Already up to date')

        await asyncio.sleep(0.5)
        self.stop()

    async def destroy(self):
        self.l.info('Client shutting down')
        await super().destroy()


def create_dummy_release(release_path: Path, version: str, status: str = 'approved', num_files: int = 3):
    """더미 릴리스 생성"""
    version_dir = release_path / version
    version_dir.mkdir(parents=True, exist_ok=True)

    files = []

    # 여러 파일 생성
    for i in range(num_files):
        if i == 0:
            # 실행 파일
            file_name = 'app.exe' if sys.platform == 'win32' else 'app'
            content = f'#!/usr/bin/env python3\n# Version {version}\nprint("App v{version}")\n'
        else:
            # 추가 파일 (라이브러리, 리소스 등)
            file_name = f'lib/module_{i}.py'
            content = f'# Module {i} for version {version}\n'

        file_path = version_dir / file_name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)

        if i == 0:
            file_path.chmod(0o755)

        # 메타데이터 생성
        checksum = calculate_checksum(str(file_path))
        file_size = file_path.stat().st_size

        files.append({
            'path': file_name,
            'size': file_size,
            'checksum': checksum
        })

    # status.json 생성
    metadata = {
        'version': version,
        'status': status,
        'build_time': datetime.now().isoformat(),
        'platform': sys.platform,
        'files': files,
        'exclude_patterns': ['*.conf', '*.log'],
        'rollback_target': None,
        'release_notes': f'Release {version}'
    }

    status_file = version_dir / 'status.json'
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    return version_dir


def test_self_update():
    """자가 업데이트 테스트"""
    print("\n" + "="*70)
    print("Self-Update Integration Test (Simplified)")
    print("="*70)

    # 임시 디렉토리 생성
    temp_root = Path(tempfile.mkdtemp(prefix='psvc_selfupdate_test_'))
    release_path = temp_root / 'releases'
    release_path.mkdir()
    download_path = temp_root / 'downloads'
    download_path.mkdir()

    print(f"\n📁 Test directory: {temp_root}")
    print(f"📁 Release path: {release_path}")
    print(f"📁 Download path: {download_path}")

    try:
        # 1. v1.0.0 릴리스 생성 (approved)
        print("\n[1/4] Creating v1.0.0 release (approved)...")
        create_dummy_release(release_path, '1.0.0', status='approved', num_files=3)
        print("  ✓ v1.0.0 created with 3 files")

        # 2. v0.9.0 릴리스 생성 (draft - 서버에서 제공 안함)
        print("\n[2/4] Creating v0.9.0 release (draft)...")
        create_dummy_release(release_path, '0.9.0', status='draft', num_files=2)
        print("  ✓ v0.9.0 created with 2 files")

        # 3. 업데이트 서버 및 클라이언트 시작
        print("\n[3/4] Starting update server and client...")

        server = UpdateServer('UpdateServer', str(temp_root), str(release_path))
        client = UpdateClient('UpdateClient', str(temp_root), str(download_path))

        # 이벤트 루프 생성
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        server_task = loop.create_task(server._service())

        # 서버 초기화 대기
        loop.run_until_complete(asyncio.sleep(0.5))
        print(f"  ✓ Server started with versions: {server.releaser.versions}")

        client_task = loop.create_task(client._service())

        # 두 서비스 완료 대기
        loop.run_until_complete(asyncio.gather(server_task, client_task, return_exceptions=True))
        loop.close()

        print("  ✓ Update process completed")

        # 4. 결과 검증
        print("\n[4/4] Verifying download results...")

        # 다운로드 디렉토리 확인
        downloaded_version_dir = download_path / '1.0.0'
        assert downloaded_version_dir.exists(), f"Download directory not found: {downloaded_version_dir}"
        print(f"  ✓ Download directory exists: {downloaded_version_dir}")

        # 다운로드된 파일 확인
        downloaded_files = list(downloaded_version_dir.rglob('*'))
        file_count = len([f for f in downloaded_files if f.is_file()])
        assert file_count == 3, f"Expected 3 files, got {file_count}"
        print(f"  ✓ Downloaded {file_count} files")

        # 각 파일 체크섬 검증
        original_status = release_path / '1.0.0' / 'status.json'
        with open(original_status, 'r') as f:
            original_metadata = json.load(f)

        for file_info in original_metadata['files']:
            file_path = file_info['path']
            expected_checksum = file_info['checksum']
            expected_size = file_info['size']

            # 다운로드된 파일 확인
            downloaded_file = downloaded_version_dir / file_path
            assert downloaded_file.exists(), f"File not found: {downloaded_file}"

            # 체크섬 검증
            actual_checksum = calculate_checksum(str(downloaded_file))
            assert actual_checksum == expected_checksum, \
                f"Checksum mismatch for {file_path}"

            # 크기 검증
            actual_size = downloaded_file.stat().st_size
            assert actual_size == expected_size, \
                f"Size mismatch for {file_path}: expected {expected_size}, got {actual_size}"

            print(f"  ✓ Verified: {file_path} ({actual_size} bytes)")

        # 디렉토리 구조 확인
        lib_dir = downloaded_version_dir / 'lib'
        assert lib_dir.exists(), "lib directory not found"
        assert lib_dir.is_dir(), "lib is not a directory"
        print(f"  ✓ Directory structure preserved: lib/")

        print("\n" + "="*70)
        print("✅ Test PASSED: Self-update workflow successful!")
        print("="*70)

    finally:
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
