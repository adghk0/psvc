import asyncio
import os
import sys
import subprocess

from .comp import Component
from .main import Service
from .cmd import Commander, command


def _version(s):
    return tuple(map(int, s.split('.')))


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
        """릴리스 디렉토리에서 버전 목록 가져오기"""
        try:
            versions = [d for d in os.listdir(self.release_path)
                       if os.path.isdir(os.path.join(self.release_path, d))]
            return sorted(versions, key=_version)
        except Exception as e:
            self.l.error('Failed to get version list: %s', e)
            return []

    def get_latest_version(self):
        """최신 버전 반환"""
        if not self.versions:
            return None
        return self.versions[-1]

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
        """클라이언트가 특정 버전 다운로드 요청"""
        version = body.get('version')
        self.l.info('Update download requested from cid=%d: version=%s', cid, version)

        if version not in self.versions:
            await cmdr.send_command('__download_failed__',
                                   {'error': 'Version not found: %s' % version}, cid)
            return

        try:
            program_path = self.get_program_path(version)
            self.l.info('Sending program file: %s', program_path)

            # 파일 전송 시작 알림
            await cmdr.send_command('__download_start__',
                                   {'version': version, 'filename': os.path.basename(program_path)},
                                   cid)

            # 파일 전송
            await cmdr.sock().send_file(program_path, cid)

            # 전송 완료 알림
            await cmdr.send_command('__download_complete__',
                                   {'version': version}, cid)
            self.l.info('Update download completed for cid=%d', cid)

        except Exception as e:
            self.l.exception('Failed to send update file')
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

    def __init__(self, svc: Service, commander: Commander, name='Updater', parent=None):
        super().__init__(svc, name, parent)
        self._cmdr = commander
        self._available_versions = []
        self._latest_version = None
        self._download_path = self.svc.get_config(Updater._update_path_conf, None, 'updates')

        # 다운로드 디렉토리 생성
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
        """서버로부터 사용 가능한 버전 목록 가져오기"""
        self.l.info('Fetching available versions from server')
        await self._cmdr.send_command('__request_versions__', {}, cid)
        await asyncio.sleep(0.5)  # 응답 대기
        return self._available_versions

    async def fetch_latest_version(self, cid=1):
        """서버로부터 최신 버전 정보 가져오기"""
        self.l.info('Fetching latest version from server')
        await self._cmdr.send_command('__request_latest_version__', {}, cid)
        await asyncio.sleep(0.5)  # 응답 대기
        return self._latest_version

    async def check_update(self, cid=1):
        """업데이트 확인"""
        latest = await self.fetch_latest_version(cid)
        if latest is None:
            self.l.warning('No version information available from server')
            return False

        current = self.svc.version
        self.l.info('Version check: current=%s, latest=%s', current, latest)

        return _version(latest) > _version(current)

    async def download_update(self, version=None, cid=1):
        """업데이트 다운로드"""
        if version is None:
            version = self._latest_version

        if version is None:
            raise ValueError('No version specified and no latest version available')

        self.l.info('Requesting download for version %s', version)
        await self._cmdr.send_command('__download_update__', {'version': version}, cid)

    async def download_and_install(self, cid=1, restart=True):
        """업데이트 다운로드 및 설치 (재시작)"""
        if not await self.check_update(cid):
            self.l.info('Already up to date')
            return False

        await self.download_update(cid=cid)

        # 다운로드 완료 대기 (실제로는 이벤트 기반으로 처리해야 함)
        await asyncio.sleep(2)

        if restart:
            self.restart_service()

        return True

    def restart_service(self):
        """서비스 재시작"""
        self.l.info('Restarting service for update...')

        # 현재 실행 파일 경로
        executable = sys.executable

        # 새 프로세스로 재시작
        if sys.platform == 'win32':
            subprocess.Popen([executable] + sys.argv)
        else:
            subprocess.Popen([executable] + sys.argv,
                           start_new_session=True)

        # 현재 서비스 종료
        self.svc.stop()

    @command(ident='__receive_versions__')
    async def _cmd_receive_versions(self, cmdr: Commander, body, cid):
        """서버로부터 버전 목록 수신"""
        self._available_versions = body
        self.l.info('Received %d versions: %s', len(body), body)

    @command(ident='__receive_latest_version__')
    async def _cmd_receive_latest_version(self, cmdr: Commander, body, cid):
        """서버로부터 최신 버전 정보 수신"""
        self._latest_version = body
        self.l.info('Received latest version: %s', body)

    @command(ident='__download_start__')
    async def _cmd_download_start(self, cmdr: Commander, body, cid):
        """다운로드 시작 알림"""
        version = body.get('version')
        filename = body.get('filename')
        self.l.info('Download starting: version=%s, file=%s', version, filename)

        # 파일 수신
        download_file = os.path.join(self.svc.path(self._download_path), filename)
        self.l.info('Saving to: %s', download_file)
        await cmdr.sock().recv_file(download_file, cid)

    @command(ident='__download_complete__')
    async def _cmd_download_complete(self, cmdr: Commander, body, cid):
        """다운로드 완료 알림"""
        version = body.get('version')
        self.l.info('Download completed: version=%s', version)
        # 여기서 설치 로직 추가 가능

    @command(ident='__download_failed__')
    async def _cmd_download_failed(self, cmdr: Commander, body, cid):
        """다운로드 실패 알림"""
        error = body.get('error')
        self.l.error('Download failed: %s', error)

