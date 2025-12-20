import asyncio
import os
import sys
import subprocess
import json

from .comp import Component
from .main import Service
from .cmd import Commander, command
from .utils.version import compare_versions
from .utils.checksum import verify_checksum


class Releaser(Component):
    """
    릴리스 서버 컴포넌트
    Commander에 붙이면 자동으로 업데이트 서버 기능 활성화

    설정 필요:
    - PSVC\\release_path: 릴리스 파일들이 저장된 디렉토리 경로

    디렉토리 구조 예시:
    release_path/
        0.1/
            program.exe
        0.2/
            program.exe
        1.0/
            program.exe
    """
    _release_path_conf = 'PSVC\\release_path'

    def __init__(self, svc: Service, commander: Commander, name='Releaser', parent=None):
        super().__init__(svc, name, parent)
        self._cmdr = commander
        try:
            self.release_path = self.svc.get_config(Releaser._release_path_conf, None)
        except KeyError:
            raise KeyError('Release path is not configured (%s)' % (Releaser._release_path_conf,))

        if not os.path.isdir(self.release_path):
            raise ValueError('Release path does not exist: %s' % self.release_path)

        self.versions = self.get_version_list()
        self.l.info('Releaser initialized with %d versions: %s', len(self.versions), self.versions)

        # 명령어 자동 등록
        self._register_commands()

    def _register_commands(self):
        """Releaser 명령어들을 Commander에 자동 등록"""
        self._cmdr.set_command(
            self._cmd_request_versions,
            self._cmd_request_latest_version,
            self._cmd_download_update
        )
        self.l.debug('Releaser commands registered')

    def get_version_list(self):
        """
        status='approved'인 버전 목록만 반환 (Semantic versioning 정렬)
        """
        approved_versions = []

        try:
            for version_dir in os.listdir(self.release_path):
                dir_path = os.path.join(self.release_path, version_dir)

                if not os.path.isdir(dir_path):
                    continue

                # status.json 확인
                status_file = os.path.join(dir_path, 'status.json')
                if not os.path.exists(status_file):
                    self.l.warning('No status.json in %s, skipping', version_dir)
                    continue

                with open(status_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # approved 상태만 포함
                if metadata.get('status') == 'approved':
                    approved_versions.append(version_dir)
                else:
                    self.l.debug('Version %s status=%s, skipping',
                                version_dir, metadata.get('status'))

        except Exception as e:
            self.l.error('Failed to get version list: %s', e)

        # Semantic versioning으로 정렬 (Major.Minor.Patch 또는 Major.Minor 지원)
        try:
            from .utils.version import parse_version
            approved_versions.sort(key=lambda v: parse_version(v))
        except ValueError as e:
            self.l.warning('Some versions have invalid format: %s', e)

        return approved_versions

    def get_latest_version(self):
        """최신 버전 반환 (approved 버전 중)"""
        if not self.versions:
            return None
        return self.versions[-1]

    def get_metadata(self, version: str) -> dict:
        """특정 버전의 메타데이터 읽기"""
        status_file = os.path.join(self.release_path, version, 'status.json')

        if not os.path.exists(status_file):
            raise FileNotFoundError(f'Metadata not found for version {version}')

        with open(status_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_program_path(self, version):
        """특정 버전의 프로그램 파일 경로 반환"""
        version_dir = os.path.join(self.release_path, version)

        # 실행 파일 찾기 (Windows: .exe, Linux/Mac: 실행 권한 있는 파일)
        if sys.platform == 'win32':
            for f in os.listdir(version_dir):
                if f.endswith('.exe'):
                    return os.path.join(version_dir, f)
        else:
            for f in os.listdir(version_dir):
                fpath = os.path.join(version_dir, f)
                if os.path.isfile(fpath) and os.access(fpath, os.X_OK):
                    return fpath

        # 실행 파일이 없으면 첫 번째 파일 반환
        files = [f for f in os.listdir(version_dir)
                if os.path.isfile(os.path.join(version_dir, f))]
        if files:
            return os.path.join(version_dir, files[0])

        raise FileNotFoundError('No program file found in version %s' % version)

    @command(ident='__request_versions__')
    async def _cmd_request_versions(self, cmdr: Commander, body, cid):
        """클라이언트가 사용 가능한 버전 목록 요청"""
        self.l.info('Version list requested from cid=%d', cid)
        self.versions = self.get_version_list()  # 최신 목록으로 갱신
        await cmdr.send_command('__receive_versions__', self.versions, cid)

    @command(ident='__request_latest_version__')
    async def _cmd_request_latest_version(self, cmdr: Commander, body, cid):
        """클라이언트가 최신 버전 정보 요청"""
        latest = self.get_latest_version()
        self.l.info('Latest version requested from cid=%d: %s', cid, latest)
        await cmdr.send_command('__receive_latest_version__', latest, cid)

    @command(ident='__download_update__')
    async def _cmd_download_update(self, cmdr: Commander, body, cid):
        """클라이언트가 특정 버전 다운로드 요청 (다중 파일 지원)"""
        version = body.get('version')
        self.l.info('Update download requested from cid=%d: version=%s', cid, version)

        if version not in self.versions:
            await cmdr.send_command('__download_failed__',
                                   {'error': 'Version not found: %s' % version}, cid)
            return

        try:
            # 메타데이터 읽기
            metadata = self.get_metadata(version)
            files = metadata.get('files', [])

            if not files:
                raise ValueError(f'No files found in version {version}')

            # 총 크기 계산
            total_size = sum(f['size'] for f in files)

            self.l.info('Sending %d files (total: %.2f MB) for version %s',
                       len(files), total_size / 1024 / 1024, version)

            # 파일 전송 시작 알림
            await cmdr.send_command('__download_start__', {
                'version': version,
                'files': files,
                'total_size': total_size,
                'file_count': len(files)
            }, cid)

            # 각 파일 순차 전송
            for file_info in files:
                file_path = os.path.join(self.release_path, version, file_info['path'])

                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"File not found: {file_info['path']}")

                self.l.debug('Sending file: %s (%d bytes)',
                            file_info['path'], file_info['size'])

                # 파일 전송
                await cmdr.sock().send_file(file_path, cid)

            # 전송 완료 알림
            await cmdr.send_command('__download_complete__',
                                   {'version': version, 'file_count': len(files)}, cid)

            self.l.info('Update download completed for cid=%d: %d files sent', cid, len(files))

        except Exception as e:
            self.l.exception('Failed to send update files')
            await cmdr.send_command('__download_failed__',
                                   {'error': str(e)}, cid)


class Updater(Component):
    """
    업데이트 클라이언트 컴포넌트
    Commander에 붙이면 자동으로 업데이트 확인 및 다운로드 기능 활성화

    사용 예시:
        updater = Updater(service, commander)

        # 업데이트 확인
        has_update = await updater.check_update()
        if has_update:
            await updater.download_and_install()
    """
    _update_path_conf = 'PSVC\\update_path'

    def __init__(
        self,
        svc: Service,
        commander: Commander,
        name='Updater',
        parent=None,
        timeout: float = 30.0
    ):
        super().__init__(svc, name, parent)
        self._cmdr = commander
        self._timeout = timeout

        # 응답 데이터
        self._available_versions = []
        self._latest_version = None
        self._download_status = None
        self._download_error = None

        # 🔒 동기화 이벤트 (blocking 제어용)
        self._versions_received = asyncio.Event()
        self._latest_received = asyncio.Event()
        self._download_completed = asyncio.Event()

        # 다운로드 경로
        self._download_path = self.svc.get_config(Updater._update_path_conf, None, 'updates')
        full_download_path = self.svc.path(self._download_path)
        os.makedirs(full_download_path, exist_ok=True)

        self.l.info('Updater initialized, download path: %s', full_download_path)

        # 명령어 자동 등록
        self._register_commands()

    def _register_commands(self):
        """Updater가 받을 명령어들을 Commander에 자동 등록"""
        self._cmdr.set_command(
            self._cmd_receive_versions,
            self._cmd_receive_latest_version,
            self._cmd_download_start,
            self._cmd_download_complete,
            self._cmd_download_failed
        )
        self.l.debug('Updater commands registered')

    async def fetch_versions(self, cid=1):
        """
        🔒 서버로부터 사용 가능한 버전 목록 가져오기 (Blocking)

        타임아웃 내에 응답을 기다립니다.
        """
        self.l.info('Fetching available versions from server')

        # 이벤트 초기화
        self._versions_received.clear()
        self._available_versions = []

        # 요청 전송
        await self._cmdr.send_command('__request_versions__', {}, cid)

        # 🔒 응답 대기 (blocking)
        try:
            await asyncio.wait_for(
                self._versions_received.wait(),
                timeout=self._timeout
            )
            return self._available_versions
        except asyncio.TimeoutError:
            self.l.error('Timeout waiting for version list (%.1fs)', self._timeout)
            raise TimeoutError(f'No response from server within {self._timeout}s')

    async def fetch_latest_version(self, cid=1):
        """
        🔒 서버로부터 최신 버전 정보 가져오기 (Blocking)

        타임아웃 내에 응답을 기다립니다.
        """
        self.l.info('Fetching latest version from server')

        # 이벤트 초기화
        self._latest_received.clear()
        self._latest_version = None

        # 요청 전송
        await self._cmdr.send_command('__request_latest_version__', {}, cid)

        # 🔒 응답 대기 (blocking)
        try:
            await asyncio.wait_for(
                self._latest_received.wait(),
                timeout=self._timeout
            )
            return self._latest_version
        except asyncio.TimeoutError:
            self.l.error('Timeout waiting for latest version (%.1fs)', self._timeout)
            raise TimeoutError(f'No response from server within {self._timeout}s')

    async def check_update(self, cid=1):
        """
        업데이트 확인

        Returns:
            bool: 업데이트 가능 여부
        """
        latest = await self.fetch_latest_version(cid)
        if latest is None:
            self.l.warning('No version information available from server')
            return False

        current = self.svc.version
        self.l.info('Version check: current=%s, latest=%s', current, latest)

        return compare_versions(latest, current) > 0

    async def download_update(self, version=None, cid=1):
        """
        🔒 업데이트 다운로드 (Blocking)

        다운로드 완료까지 대기합니다.

        Args:
            version: 다운로드할 버전 (None이면 최신 버전)
            cid: 연결 ID

        Raises:
            ValueError: 버전 정보 없음
            TimeoutError: 다운로드 타임아웃
            RuntimeError: 다운로드 실패
        """
        if version is None:
            version = self._latest_version

        if version is None:
            raise ValueError('No version specified and no latest version available')

        self.l.info('Requesting download for version %s', version)

        # 이벤트 및 상태 초기화
        self._download_completed.clear()
        self._download_status = None
        self._download_error = None

        # 다운로드 요청
        await self._cmdr.send_command('__download_update__', {'version': version}, cid)

        # 🔒 다운로드 완료 대기 (blocking)
        try:
            await asyncio.wait_for(
                self._download_completed.wait(),
                timeout=self._timeout * 3  # 다운로드는 더 긴 타임아웃
            )

            # 에러 체크
            if self._download_error:
                raise RuntimeError(f'Download failed: {self._download_error}')

            self.l.info('✓ Download completed: %s', self._download_status)
            return self._download_status

        except asyncio.TimeoutError:
            self.l.error('Timeout waiting for download (%.1fs)', self._timeout * 3)
            raise TimeoutError(f'Download not completed within {self._timeout * 3}s')

    def _get_install_paths(self):
        """
        설치 경로 확인

        Returns:
            tuple: (실행 디렉토리, 실행 파일명)
        """
        # 서비스의 root_path가 설정되어 있으면 사용
        if self.svc._root_path:
            exe_dir = self.svc._root_path
            # PyInstaller 환경인지 확인
            if getattr(sys, 'frozen', False):
                exe_name = os.path.basename(sys.executable)
            else:
                exe_name = os.path.basename(sys.argv[0])
        # PyInstaller 환경 확인
        elif getattr(sys, 'frozen', False):
            # PyInstaller로 패키징된 실행 파일
            exe_path = sys.executable
            exe_dir = os.path.dirname(exe_path)
            exe_name = os.path.basename(exe_path)
        else:
            # 개발 환경 (Python 스크립트)
            exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            exe_name = os.path.basename(sys.argv[0])

        return exe_dir, exe_name

    def _create_backup(self):
        """
        현재 버전 백업

        Returns:
            str: 백업 디렉토리 경로
        """
        import shutil
        from datetime import datetime

        exe_dir, exe_name = self._get_install_paths()
        exe_path = os.path.join(exe_dir, exe_name)

        if not os.path.exists(exe_path):
            self.l.warning('Current executable not found: %s', exe_path)
            return None

        # 백업 디렉토리 생성 (타임스탬프)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_dir = os.path.join(exe_dir, f'backup_{timestamp}')
        os.makedirs(backup_dir, exist_ok=True)

        # 현재 버전의 모든 파일 백업
        for item in os.listdir(exe_dir):
            item_path = os.path.join(exe_dir, item)
            if os.path.isfile(item_path) and not item.startswith('backup_'):
                backup_path = os.path.join(backup_dir, item)
                shutil.copy2(item_path, backup_path)
                self.l.debug('Backed up: %s', item)

        self.l.info('Backup created: %s', backup_dir)
        return backup_dir

    def _deploy_files(self, version):
        """
        다운로드된 파일을 설치 디렉토리로 배포

        Args:
            version: 배포할 버전

        Windows: .new 확장자로 저장 (재시작 시 교체)
        Linux: 직접 덮어쓰기
        """
        import shutil

        # 다운로드 경로
        download_dir = os.path.join(self.svc.path(self._download_path), version)
        if not os.path.exists(download_dir):
            raise FileNotFoundError(f'Downloaded version not found: {download_dir}')

        # 설치 경로
        exe_dir, _ = self._get_install_paths()
        self.l.info('Deploying from %s to %s', download_dir, exe_dir)

        # 다운로드된 모든 파일 배포
        deployed_count = 0
        for root, dirs, files in os.walk(download_dir):
            for file_name in files:
                src_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(src_path, download_dir)

                if sys.platform == 'win32':
                    # Windows: .new 확장자로 저장
                    dest_path = os.path.join(exe_dir, rel_path + '.new')
                else:
                    # Linux: 직접 덮어쓰기
                    dest_path = os.path.join(exe_dir, rel_path)

                # 디렉토리 생성
                dest_dir = os.path.dirname(dest_path)
                if dest_dir:  # dest_dir가 빈 문자열이 아닐 때만
                    os.makedirs(dest_dir, exist_ok=True)

                # 파일 복사
                self.l.info('Copying: %s -> %s', src_path, dest_path)
                shutil.copy2(src_path, dest_path)

                # 실행 권한 유지 (Linux)
                if sys.platform != 'win32':
                    src_stat = os.stat(src_path)
                    os.chmod(dest_path, src_stat.st_mode)

                deployed_count += 1

        self.l.info('Deployed %d file(s) for version %s', deployed_count, version)

    def _update_version_config(self, new_version):
        """
        Config 파일의 버전 정보 업데이트

        Args:
            new_version: 새 버전
        """
        self.svc.set_config('PSVC', 'version', new_version)
        self.svc.version = new_version
        self.l.info('Version updated in config: %s', new_version)

    async def install_update(self, version=None):
        """
        다운로드된 업데이트 설치

        Args:
            version: 설치할 버전 (None이면 다운로드된 최신 버전)

        Raises:
            FileNotFoundError: 다운로드된 버전 없음
            RuntimeError: 설치 실패
        """
        if version is None:
            version = self._download_status or self._latest_version

        if version is None:
            raise ValueError('No version to install')

        self.l.info('Installing update: %s', version)

        # 백업 생성
        backup_dir = self._create_backup()

        try:
            # 파일 배포
            self._deploy_files(version)

            # Config 버전 업데이트
            self._update_version_config(version)

            self.l.info('Installation completed: %s', version)

        except Exception as e:
            self.l.error('Installation failed: %s', e)
            # 롤백 (필요시)
            if backup_dir and os.path.exists(backup_dir):
                self.l.warning('Rollback not implemented, backup saved at: %s', backup_dir)
            raise RuntimeError(f'Installation failed: {e}') from e

    async def download_and_install(self, cid=1, restart=True):
        """
        업데이트 다운로드 및 설치 (재시작)

        Returns:
            bool: 업데이트 수행 여부
        """
        if not await self.check_update(cid):
            self.l.info('Already up to date')
            return False

        # 다운로드
        await self.download_update(cid=cid)

        # 설치
        await self.install_update()

        # 재시작
        if restart:
            await self.restart_service()

        return True

    async def restart_service(self):
        """서비스 재시작 (안전한 종료 후 새 프로세스 시작)"""
        self.l.info('Preparing to restart for update...')

        # 1. 새 프로세스 시작 함수 정의
        def start_new_process(executable, args):
            """종료 후 새 프로세스 시작"""
            if sys.platform == 'win32':
                subprocess.Popen([executable] + args)
            else:
                subprocess.Popen([executable] + args, start_new_session=True)

        # 2. closer로 등록 (on() 종료 시 실행됨)
        executable = sys.executable
        args = sys.argv
        self.svc.append_closer(start_new_process, [executable, args])
        self.l.info('New process scheduled to start after shutdown')

        # 3. 서비스 중지 (destroy()는 _service의 finally 블록에서 자동 호출됨)
        self.l.info('Stopping current service')
        self.svc.stop()

    @command(ident='__receive_versions__')
    async def _cmd_receive_versions(self, cmdr: Commander, body, cid):
        """서버로부터 버전 목록 수신"""
        self._available_versions = body
        self.l.info('Received %d versions: %s', len(body), body)
        # 🔓 이벤트 설정 (blocking 해제)
        self._versions_received.set()

    @command(ident='__receive_latest_version__')
    async def _cmd_receive_latest_version(self, cmdr: Commander, body, cid):
        """서버로부터 최신 버전 정보 수신"""
        self._latest_version = body
        self.l.info('Received latest version: %s', body)
        # 🔓 이벤트 설정 (blocking 해제)
        self._latest_received.set()

    @command(ident='__download_start__')
    async def _cmd_download_start(self, cmdr: Commander, body, cid):
        """다운로드 시작 알림 (다중 파일 지원)"""
        version = body.get('version')
        files = body.get('files', [])
        total_size = body.get('total_size', 0)
        file_count = body.get('file_count', 0)

        self.l.info('Download starting: version=%s, %d files (%.2f MB)',
                   version, file_count, total_size / 1024 / 1024)

        # 버전 디렉토리 생성
        version_dir = os.path.join(self.svc.path(self._download_path), version)
        os.makedirs(version_dir, exist_ok=True)

        # 각 파일 순차 수신
        for file_info in files:
            file_path = file_info['path']
            expected_checksum = file_info['checksum']
            expected_size = file_info['size']

            # 전체 경로 생성
            full_path = os.path.join(version_dir, file_path)

            # 하위 디렉토리 생성
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            self.l.debug('Receiving file: %s (%d bytes)', file_path, expected_size)

            try:
                # 파일 수신
                await cmdr.sock().recv_file(full_path, cid)

                # 체크섬 검증
                if not verify_checksum(full_path, expected_checksum):
                    raise ValueError(f'Checksum verification failed for {file_path}')

                # 파일 크기 검증
                actual_size = os.path.getsize(full_path)
                if actual_size != expected_size:
                    raise ValueError(
                        f'File size mismatch for {file_path}: '
                        f'expected {expected_size}, got {actual_size}'
                    )

                self.l.debug('File verified: %s', file_path)

            except Exception as e:
                self.l.error('Failed to receive file %s: %s', file_path, e)
                # 부분 다운로드 실패 시 정리
                if os.path.exists(full_path):
                    os.remove(full_path)
                raise

        self.l.info('All files received and verified for version %s', version)

    @command(ident='__download_complete__')
    async def _cmd_download_complete(self, cmdr: Commander, body, cid):
        """다운로드 완료 알림"""
        version = body.get('version')
        self.l.info('Download completed: version=%s', version)

        # 상태 저장
        self._download_status = version
        self._download_error = None

        # 🔓 이벤트 설정 (blocking 해제)
        self._download_completed.set()

    @command(ident='__download_failed__')
    async def _cmd_download_failed(self, cmdr: Commander, body, cid):
        """다운로드 실패 알림"""
        error = body.get('error')
        self.l.error('Download failed: %s', error)

        # 에러 저장
        self._download_status = None
        self._download_error = error

        # 🔓 이벤트 설정 (blocking 해제)
        self._download_completed.set()

