"""
업데이트 시스템 통합 테스트

테스트 시나리오:
1. 릴리스 서버 시작 (버전 0.1, 0.2, 1.0 제공)
2. 클라이언트 시작 (현재 버전 0.0)
3. 클라이언트가 최신 버전 확인
4. 클라이언트가 업데이트 다운로드
5. 다운로드된 파일 검증
6. 정상 종료
"""

import sys
import time
import subprocess
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def setup_test_environment():
    """테스트 환경 설정"""
    # 릴리스 디렉토리 생성
    release_dir = ROOT / "test_releases"
    if release_dir.exists():
        shutil.rmtree(release_dir)

    versions = ['0.1', '0.2', '1.0']
    for version in versions:
        version_dir = release_dir / version
        version_dir.mkdir(parents=True, exist_ok=True)

        # 더미 프로그램 파일 생성
        program_file = version_dir / 'test_program.py'
        program_file.write_text(
            f'# Test Program version {version}\n'
            f'print("Version {version}")\n'
        )

    # 설정 파일 생성
    config_file = release_dir / 'psvc.conf'
    config_file.write_text(
        '[PSVC]\n'
        f'release_path = {release_dir}\n'
        'version = 0.0\n'
    )

    # 다운로드 디렉토리 생성
    download_dir = ROOT / "test_downloads"
    if download_dir.exists():
        shutil.rmtree(download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)

    return release_dir, download_dir


def cleanup_test_environment(release_dir, download_dir):
    """테스트 환경 정리"""
    if release_dir.exists():
        shutil.rmtree(release_dir)
    if download_dir.exists():
        shutil.rmtree(download_dir)


def create_update_server_script(release_dir):
    """업데이트 서버 스크립트 생성"""
    script = ROOT / "test_update_server.py"
    script.write_text(f'''
import sys
import asyncio
sys.path.insert(0, str({repr(str(ROOT / "src"))}))

from psvc import Service, Commander, Releaser

class UpdateServer(Service):
    async def init(self):
        self.cmdr = Commander(self)
        await self.cmdr.bind('0.0.0.0', 50002)
        self.releaser = Releaser(self, self.cmdr)
        self.l.info('Update server ready with versions: %s', self.releaser.versions)

    async def run(self):
        await asyncio.sleep(1)

    async def destroy(self):
        await super().destroy()

if __name__ == '__main__':
    svc = UpdateServer('UpdateServer', __file__, config_file={repr(str(release_dir / "psvc.conf"))})
    svc.on()
''')
    return script


def create_update_client_script(release_dir, download_dir):
    """업데이트 클라이언트 스크립트 생성"""
    script = ROOT / "test_update_client.py"
    script.write_text(f'''
import sys
import asyncio
sys.path.insert(0, str({repr(str(ROOT / "src"))}))

from psvc import Service, Commander, Updater

class UpdateClient(Service):
    async def init(self):
        self.cmdr = Commander(self)
        self.cid = await self.cmdr.connect('127.0.0.1', 50002)
        # 다운로드 경로를 download_dir로 설정
        self.set_config('PSVC', 'update_path', {repr(str(download_dir))})
        self.updater = Updater(self, self.cmdr)
        self.l.info('Client initialized, version: %s, cid: %d', self.version, self.cid)

    async def run(self):
        # 버전 목록 가져오기
        versions = await self.updater.fetch_versions(cid=self.cid)
        self.l.info('Available versions: %s', versions)

        # 최신 버전 확인
        latest = await self.updater.fetch_latest_version(cid=self.cid)
        self.l.info('Latest version: %s', latest)

        # 업데이트 확인
        has_update = await self.updater.check_update(cid=self.cid)
        self.l.info('Has update: %s', has_update)

        if has_update:
            # 업데이트 다운로드 (재시작 안함)
            await self.updater.download_update(cid=self.cid)
            await asyncio.sleep(3)  # 다운로드 완료 대기
            self.l.info('Download completed!')

        await asyncio.sleep(1)
        self.stop()

    async def destroy(self):
        await super().destroy()

if __name__ == '__main__':
    svc = UpdateClient('UpdateClient', __file__, config_file={repr(str(release_dir / "psvc.conf"))})
    svc.on()
''')
    return script


def test_update_system():
    """업데이트 시스템 통합 테스트"""
    print("=== Setting up test environment ===")
    release_dir, download_dir = setup_test_environment()

    try:
        print(f"Release directory: {release_dir}")
        print(f"Download directory: {download_dir}")

        # 서버/클라이언트 스크립트 생성
        server_script = create_update_server_script(release_dir)
        client_script = create_update_client_script(release_dir, download_dir)

        print("\n=== Starting update server ===")
        server = subprocess.Popen(
            [sys.executable, str(server_script)],
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            # 서버 시작 대기
            time.sleep(2)

            print("\n=== Starting update client ===")
            client = subprocess.run(
                [sys.executable, str(client_script)],
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )

            print("\n=== Client output ===")
            print(client.stdout)
            if client.stderr:
                print("\n=== Client errors ===")
                print(client.stderr)

            # 서버 종료
            print("\n=== Stopping server ===")
            server.terminate()
            server_out, server_err = server.communicate(timeout=5)

            print("\n=== Server output ===")
            print(server_out)
            if server_err:
                print("\n=== Server errors ===")
                print(server_err)

            # 검증
            print("\n=== Verification ===")

            # 1. 클라이언트가 정상 종료되었는지
            assert client.returncode == 0, f"Client failed with code {client.returncode}"
            print("✓ Client exited successfully")

            # 2. 서버가 정상 종료되었는지
            assert server.returncode in [0, -15], f"Server failed with code {server.returncode}"
            print("✓ Server exited successfully")

            # 3. 클라이언트 로그에 필요한 정보가 있는지
            combined_output = client.stdout + client.stderr
            assert "Available versions" in combined_output, "No version list in output"
            print("✓ Version list received")

            assert "Latest version: 1.0" in combined_output, "Latest version not 1.0"
            print("✓ Latest version is 1.0")

            assert "Has update: True" in combined_output, "Update check failed"
            print("✓ Update check passed")

            assert "Download completed" in combined_output, "Download not completed"
            print("✓ Download completed")

            # 4. 다운로드된 파일 확인
            downloaded_files = list(download_dir.glob("*.py"))
            assert len(downloaded_files) > 0, "No files downloaded"
            print(f"✓ Downloaded file: {downloaded_files[0].name}")

            # 5. 다운로드된 파일 내용 확인
            downloaded_content = downloaded_files[0].read_text()
            assert "1.0" in downloaded_content, "Downloaded file doesn't contain version 1.0"
            print("✓ Downloaded file contains correct version")

            print("\n=== All tests passed! ===")
            return True

        finally:
            # 서버가 아직 실행 중이면 강제 종료
            if server.poll() is None:
                server.kill()
                server.wait()

            # 테스트 스크립트 삭제
            if server_script.exists():
                server_script.unlink()
            if client_script.exists():
                client_script.unlink()

    finally:
        # 환경 정리
        print("\n=== Cleaning up test environment ===")
        cleanup_test_environment(release_dir, download_dir)


if __name__ == '__main__':
    try:
        test_update_system()
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
