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
    _release_path_conf = 'Releaser\\release_path'

    def __init__(self, svc: Service, commander: Commander, name='Releaser', parent=None):
        """
        Releaser 초기화

        Args:
            svc: 서비스 인스턴스
            commander: Commander 인스턴스 (명령어 등록용)
            name: 컴포넌트 이름
            parent: 부모 컴포넌트

        Raises:
            KeyError: release_path 설정이 없을 때
            ValueError: release_path가 존재하지 않는 디렉토리일 때
        """
        super().__init__(svc, name, parent)
        self._cmdr = commander
        try:
            self.release_path = self.svc.get_config(Releaser._release_path_conf, None)
        except KeyError:
            raise KeyError('릴리스 경로가 설정되지 않음 (%s)' % (Releaser._release_path_conf,))

        if not os.path.isdir(self.release_path):
            raise ValueError('릴리스 경로가 존재하지 않음: %s' % self.release_path)

        self.versions = self.get_version_list()
        self.l.info('Releaser 초기화됨 (%d개 버전): %s', len(self.versions), self.versions)

        # 명령어 자동 등록
        self._register_commands()

    def _register_commands(self):
        """Releaser 명령어들을 Commander에 자동 등록"""
        self._cmdr.set_command(
            self._cmd_request_versions,
            self._cmd_request_latest_version,
            self._cmd_download_update,
            self._cmd_force_update
        )
        self.l.debug('Releaser 명령어 등록됨')

    def get_version_list(self):
        """
        status='approved'인 버전 목록만 반환 (Semantic versioning 정렬)

        Returns:
            list: approved 상태의 버전 목록 (정렬됨)
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
                    self.l.warning('%s에 status.json 없음, 건너뜀', version_dir)
                    continue

                with open(status_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)

                # approved 상태만 포함
                if metadata.get('status') == 'approved':
                    approved_versions.append(version_dir)
                else:
                    self.l.debug('버전 %s 상태=%s, 건너뜀',
                                version_dir, metadata.get('status'))

        except Exception as e:
            self.l.error('버전 목록 가져오기 실패: %s', e)

        # Semantic versioning으로 정렬 (Major.Minor.Patch 또는 Major.Minor 지원)
        try:
            from .utils.version import parse_version
            approved_versions.sort(key=lambda v: parse_version(v))
        except ValueError as e:
            self.l.warning('일부 버전의 형식이 잘못됨: %s', e)

        return approved_versions

    def get_latest_version(self):
        """
        최신 버전 반환 (approved 버전 중)

        Returns:
            str: 최신 버전 문자열, 없으면 None
        """
        if not self.versions:
            return None
        return self.versions[-1]

    def get_metadata(self, version: str) -> dict:
        """
        특정 버전의 메타데이터 읽기

        Args:
            version: 버전 문자열

        Returns:
            dict: status.json의 메타데이터

        Raises:
            FileNotFoundError: status.json이 없을 때
        """
        status_file = os.path.join(self.release_path, version, 'status.json')

        if not os.path.exists(status_file):
            raise FileNotFoundError(f'버전 {version}의 메타데이터를 찾을 수 없음')

        with open(status_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_program_path(self, version):
        """
        특정 버전의 프로그램 파일 경로 반환

        Args:
            version: 버전 문자열

        Returns:
            str: 프로그램 실행 파일 경로

        Raises:
            FileNotFoundError: 프로그램 파일을 찾을 수 없을 때
        """
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

        raise FileNotFoundError('버전 %s에서 프로그램 파일을 찾을 수 없음' % version)

    @command(ident='__request_versions__')
    async def _cmd_request_versions(self, cmdr: Commander, body, cid):
        """
        클라이언트가 사용 가능한 버전 목록 요청

        Args:
            cmdr: Commander 인스턴스
            body: 요청 본문 (미사용)
            cid: 클라이언트 연결 ID
        """
        self.l.info('cid=%d로부터 버전 목록 요청됨', cid)
        self.versions = self.get_version_list()  # 최신 목록으로 갱신
        await cmdr.send_command('__receive_versions__', self.versions, cid)

    @command(ident='__request_latest_version__')
    async def _cmd_request_latest_version(self, cmdr: Commander, body, cid):
        """
        클라이언트가 최신 버전 정보 요청

        Args:
            cmdr: Commander 인스턴스
            body: 요청 본문 (미사용)
            cid: 클라이언트 연결 ID
        """
        latest = self.get_latest_version()
        self.l.info('cid=%d로부터 최신 버전 요청됨: %s', cid, latest)
        await cmdr.send_command('__receive_latest_version__', latest, cid)

    @command(ident='__download_update__')
    async def _cmd_download_update(self, cmdr: Commander, body, cid):
        """
        클라이언트가 특정 버전 다운로드 요청 (다중 파일 지원)

        Args:
            cmdr: Commander 인스턴스
            body: 요청 본문 (version 포함)
            cid: 클라이언트 연결 ID
        """
        version = body.get('version')
        self.l.info('cid=%d로부터 업데이트 다운로드 요청됨: version=%s', cid, version)

        if version not in self.versions:
            await cmdr.send_command('__download_failed__',
                                   {'error': '버전을 찾을 수 없음: %s' % version}, cid)
            return

        try:
            # 메타데이터 읽기
            metadata = self.get_metadata(version)
            files = metadata.get('files', [])

            if not files:
                raise ValueError(f'버전 {version}에 파일이 없음')

            # 총 크기 계산
            total_size = sum(f['size'] for f in files)

            self.l.info('버전 %s에 대해 %d개 파일 전송 중 (총 %.2f MB)',
                       version, len(files), total_size / 1024 / 1024)

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
                    raise FileNotFoundError(f"파일을 찾을 수 없음: {file_info['path']}")

                self.l.debug('파일 전송 중: %s (%d bytes)',
                            file_info['path'], file_info['size'])

                # 파일 전송
                await cmdr.sock().send_file(file_path, cid)

            # 전송 완료 알림
            await cmdr.send_command('__download_complete__',
                                   {'version': version, 'file_count': len(files)}, cid)

            self.l.info('cid=%d에 대한 업데이트 다운로드 완료: %d개 파일 전송됨', cid, len(files))

        except Exception as e:
            self.l.exception('업데이트 파일 전송 실패')
            await cmdr.send_command('__download_failed__',
                                   {'error': str(e)}, cid)

    @command(ident='__force_update__')
    async def _cmd_force_update(self, cmdr: Commander, body, cid):
        """
        원격에서 특정 버전으로 강제 업데이트 명령

        서버가 클라이언트에게 특정 버전으로 업데이트하도록 강제합니다.
        클라이언트는 이 명령을 받으면 자동으로 다운로드 및 재시작을 수행합니다.

        Args:
            cmdr: Commander 인스턴스
            body: 요청 본문
                {
                    'version': str,  # 강제 배포할 버전 (필수)
                    'restart': bool  # 즉시 재시작 여부 (기본: True)
                }
            cid: 클라이언트 연결 ID

        Raises:
            ValueError: 버전이 존재하지 않을 때
        """
        version = body.get('version')
        restart = body.get('restart', True)

        self.l.info('cid=%d에 강제 업데이트 명령 전송: version=%s, restart=%s',
                   cid, version, restart)

        # 버전 검증
        if version not in self.versions:
            error_msg = f'버전 {version}이(가) approved 목록에 없음 (사용 가능: {self.versions})'
            self.l.error(error_msg)
            await cmdr.send_command('__update_failed__',
                                   {'error': error_msg}, cid)
            return

        # 클라이언트에게 업데이트 명령 전송
        try:
            await cmdr.send_command('__apply_update__', {
                'version': version,
                'restart': restart
            }, cid)

            self.l.info('cid=%d에 강제 업데이트 명령 전송 완료', cid)

        except Exception as e:
            self.l.exception('강제 업데이트 명령 전송 실패')
            await cmdr.send_command('__update_failed__',
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
        """
        Updater 초기화

        Args:
            svc: 서비스 인스턴스
            commander: Commander 인스턴스
            name: 컴포넌트 이름
            parent: 부모 컴포넌트
            timeout: 서버 응답 대기 타임아웃 (초)
        """
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

        self.l.info('Updater 초기화됨, 다운로드 경로: %s', full_download_path)

        # 명령어 자동 등록
        self._register_commands()

    def _register_commands(self):
        """Updater가 받을 명령어들을 Commander에 자동 등록"""
        self._cmdr.set_command(
            self._cmd_receive_versions,
            self._cmd_receive_latest_version,
            self._cmd_download_start,
            self._cmd_download_complete,
            self._cmd_download_failed,
            self._cmd_apply_update
        )
        self.l.debug('Updater 명령어 등록됨')

    async def fetch_versions(self, cid=1):
        """
        서버로부터 사용 가능한 버전 목록 가져오기 (Blocking)

        타임아웃 내에 응답을 기다립니다.

        Args:
            cid: 연결 ID

        Returns:
            list: 사용 가능한 버전 목록

        Raises:
            TimeoutError: 타임아웃 내에 응답 없음
        """
        self.l.info('서버로부터 사용 가능한 버전 목록 가져오는 중')

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
            self.l.error('버전 목록 대기 타임아웃 (%.1f초)', self._timeout)
            raise TimeoutError(f'{self._timeout}초 내에 서버 응답 없음')

    async def fetch_latest_version(self, cid=1):
        """
        서버로부터 최신 버전 정보 가져오기 (Blocking)

        타임아웃 내에 응답을 기다립니다.

        Args:
            cid: 연결 ID

        Returns:
            str: 최신 버전, 없으면 None

        Raises:
            TimeoutError: 타임아웃 내에 응답 없음
        """
        self.l.info('서버로부터 최신 버전 정보 가져오는 중')

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
            self.l.error('최신 버전 대기 타임아웃 (%.1f초)', self._timeout)
            raise TimeoutError(f'{self._timeout}초 내에 서버 응답 없음')

    async def check_update(self, cid=1):
        """
        업데이트 확인

        Args:
            cid: 연결 ID

        Returns:
            bool: 업데이트 가능 여부
        """
        latest = await self.fetch_latest_version(cid)
        if latest is None:
            self.l.warning('서버로부터 버전 정보를 사용할 수 없음')
            return False

        current = self.svc.version
        self.l.info('버전 확인: current=%s, latest=%s', current, latest)

        return compare_versions(latest, current) > 0

    async def download_update(self, version=None, cid=1):
        """
        업데이트 다운로드 (Blocking)

        다운로드 완료까지 대기합니다.

        Args:
            version: 다운로드할 버전 (None이면 최신 버전)
            cid: 연결 ID

        Returns:
            str: 다운로드된 버전

        Raises:
            ValueError: 버전 정보 없음
            TimeoutError: 다운로드 타임아웃
            RuntimeError: 다운로드 실패
        """
        if version is None:
            version = self._latest_version

        if version is None:
            raise ValueError('버전이 지정되지 않았고 최신 버전 정보도 없음')

        self.l.info('버전 %s 다운로드 요청 중', version)

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
                raise RuntimeError(f'다운로드 실패: {self._download_error}')

            self.l.info('다운로드 완료: %s', self._download_status)
            return self._download_status

        except asyncio.TimeoutError:
            self.l.error('다운로드 대기 타임아웃 (%.1f초)', self._timeout * 3)
            raise TimeoutError(f'{self._timeout * 3}초 내에 다운로드 완료되지 않음')

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
            str: 백업 디렉토리 경로, 실행 파일이 없으면 None
        """
        import shutil
        from datetime import datetime

        exe_dir, exe_name = self._get_install_paths()
        exe_path = os.path.join(exe_dir, exe_name)

        if not os.path.exists(exe_path):
            self.l.warning('현재 실행 파일을 찾을 수 없음: %s', exe_path)
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
                self.l.debug('백업됨: %s', item)

        self.l.info('백업 생성됨: %s', backup_dir)
        return backup_dir

    def _deploy_files(self, version):
        """
        다운로드된 파일을 설치 디렉토리로 배포

        Args:
            version: 배포할 버전

        Raises:
            FileNotFoundError: 다운로드된 버전이 없을 때

        Note:
            Windows: .new 확장자로 저장 (재시작 시 교체)
            Linux: 직접 덮어쓰기
        """
        import shutil

        # 다운로드 경로
        download_dir = os.path.join(self.svc.path(self._download_path), version)
        if not os.path.exists(download_dir):
            raise FileNotFoundError(f'다운로드된 버전을 찾을 수 없음: {download_dir}')

        # 설치 경로
        exe_dir, _ = self._get_install_paths()
        self.l.info('%s에서 %s로 배포 중', download_dir, exe_dir)

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
                self.l.info('복사 중: %s -> %s', src_path, dest_path)
                shutil.copy2(src_path, dest_path)

                # 실행 권한 유지 (Linux)
                if sys.platform != 'win32':
                    src_stat = os.stat(src_path)
                    os.chmod(dest_path, src_stat.st_mode)

                deployed_count += 1

        self.l.info('버전 %s에 대해 %d개 파일 배포됨', version, deployed_count)

    def _update_version_config(self, new_version):
        """
        Config 파일의 버전 정보 업데이트

        Args:
            new_version: 새 버전
        """
        self.svc.set_config('PSVC', 'version', new_version)
        self.svc.version = new_version
        self.l.info('Config에서 버전 업데이트됨: %s', new_version)

    async def install_update(self, version=None):
        """
        다운로드된 업데이트 설치

        Args:
            version: 설치할 버전 (None이면 다운로드된 최신 버전)

        Raises:
            ValueError: 설치할 버전 정보 없음
            RuntimeError: 설치 실패
        """
        if version is None:
            version = self._download_status or self._latest_version

        if version is None:
            raise ValueError('설치할 버전이 없음')

        self.l.info('업데이트 설치 중: %s', version)

        # 백업 생성
        backup_dir = self._create_backup()

        try:
            # 파일 배포
            self._deploy_files(version)

            # Config 버전 업데이트
            self._update_version_config(version)

            self.l.info('설치 완료: %s', version)

        except Exception as e:
            self.l.error('설치 실패: %s', e)
            # 롤백 (필요시)
            if backup_dir and os.path.exists(backup_dir):
                self.l.warning('롤백이 구현되지 않음, 백업 저장 위치: %s', backup_dir)
            raise RuntimeError(f'설치 실패: {e}') from e

    async def download_and_install(self, cid=1, restart=True):
        """
        업데이트 다운로드 및 설치 (재시작)

        Args:
            cid: 연결 ID
            restart: 설치 후 재시작 여부

        Returns:
            bool: 업데이트 수행 여부
        """
        if not await self.check_update(cid):
            self.l.info('이미 최신 버전')
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
        """서비스 재시작 (안전한 종료 후 apply 모드로 새 프로세스 시작)"""
        self.l.info('업데이트를 위한 재시작 준비 중...')

        # 1. apply 모드로 새 프로세스 시작 함수 정의
        def start_apply_mode(executable):
            """종료 후 apply 모드로 새 프로세스 시작"""
            # apply 모드로 실행 (saved_args.json이 자동으로 로드됨)
            apply_args = [executable, 'apply']

            self.l.info('apply 모드로 재시작: %s', apply_args)

            if sys.platform == 'win32':
                subprocess.Popen(apply_args)
            else:
                subprocess.Popen(apply_args, start_new_session=True)

        # 2. closer로 등록 (on() 종료 시 실행됨)
        executable = sys.executable
        self.svc.append_closer(start_apply_mode, [executable])
        self.l.info('종료 후 apply 모드로 재시작 예약됨')

        # 3. 서비스 중지 (destroy()는 _service의 finally 블록에서 자동 호출됨)
        self.l.info('현재 서비스 중지 중')
        self.svc.stop()

    @command(ident='__receive_versions__')
    async def _cmd_receive_versions(self, cmdr: Commander, body, cid):
        """
        서버로부터 버전 목록 수신

        Args:
            cmdr: Commander 인스턴스 (미사용)
            body: 버전 목록
            cid: 클라이언트 연결 ID (미사용)
        """
        self._available_versions = body
        self.l.info('%d개 버전 수신됨: %s', len(body), body)
        # 🔓 이벤트 설정 (blocking 해제)
        self._versions_received.set()

    @command(ident='__receive_latest_version__')
    async def _cmd_receive_latest_version(self, cmdr: Commander, body, cid):
        """
        서버로부터 최신 버전 정보 수신

        Args:
            cmdr: Commander 인스턴스 (미사용)
            body: 최신 버전
            cid: 클라이언트 연결 ID (미사용)
        """
        self._latest_version = body
        self.l.info('최신 버전 수신됨: %s', body)
        # 🔓 이벤트 설정 (blocking 해제)
        self._latest_received.set()

    @command(ident='__download_start__')
    async def _cmd_download_start(self, cmdr: Commander, body, cid):
        """
        다운로드 시작 알림 (다중 파일 지원)

        Args:
            cmdr: Commander 인스턴스
            body: 다운로드 정보 (version, files, total_size, file_count)
            cid: 클라이언트 연결 ID
        """
        version = body.get('version')
        files = body.get('files', [])
        total_size = body.get('total_size', 0)
        file_count = body.get('file_count', 0)

        self.l.info('다운로드 시작: version=%s, %d개 파일 (%.2f MB)',
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

            self.l.debug('파일 수신 중: %s (%d bytes)', file_path, expected_size)

            try:
                # 파일 수신
                await cmdr.sock().recv_file(full_path, cid)

                # 체크섬 검증
                if not verify_checksum(full_path, expected_checksum):
                    raise ValueError(f'{file_path}의 체크섬 검증 실패')

                # 파일 크기 검증
                actual_size = os.path.getsize(full_path)
                if actual_size != expected_size:
                    raise ValueError(
                        f'{file_path}의 파일 크기 불일치: '
                        f'예상 {expected_size}, 실제 {actual_size}'
                    )

                self.l.debug('파일 검증됨: %s', file_path)

            except Exception as e:
                self.l.error('파일 수신 실패 %s: %s', file_path, e)
                # 부분 다운로드 실패 시 정리
                if os.path.exists(full_path):
                    os.remove(full_path)
                raise

        self.l.info('버전 %s의 모든 파일 수신 및 검증 완료', version)

    @command(ident='__download_complete__')
    async def _cmd_download_complete(self, cmdr: Commander, body, cid):
        """
        다운로드 완료 알림

        Args:
            cmdr: Commander 인스턴스 (미사용)
            body: 완료 정보 (version 포함)
            cid: 클라이언트 연결 ID (미사용)
        """
        from datetime import datetime

        version = body.get('version')
        self.l.info('다운로드 완료: version=%s', version)

        # 상태 저장
        self._download_status = version
        self._download_error = None

        # sys.argv 저장 (다운로드 완료 후)
        try:
            download_dir = os.path.join(self.svc.path(self._download_path), version)

            saved_args = {
                'argv': sys.argv,
                'version': version,
                'timestamp': datetime.now().isoformat()
            }

            args_file = os.path.join(download_dir, 'saved_args.json')
            with open(args_file, 'w', encoding='utf-8') as f:
                json.dump(saved_args, f, indent=2, ensure_ascii=False)

            self.l.info('sys.argv 저장됨: %s', args_file)
            self.l.debug('저장된 인자: %s', sys.argv)
        except Exception as e:
            self.l.error('sys.argv 저장 실패: %s', e)
            # 저장 실패해도 다운로드는 성공으로 처리 (apply 시 기본값 사용)

        # 🔓 이벤트 설정 (blocking 해제)
        self._download_completed.set()

    @command(ident='__download_failed__')
    async def _cmd_download_failed(self, cmdr: Commander, body, cid):
        """
        다운로드 실패 알림

        Args:
            cmdr: Commander 인스턴스 (미사용)
            body: 실패 정보 (error 포함)
            cid: 클라이언트 연결 ID (미사용)
        """
        error = body.get('error')
        self.l.error('다운로드 실패: %s', error)

        # 에러 저장
        self._download_status = None
        self._download_error = error

        # 🔓 이벤트 설정 (blocking 해제)
        self._download_completed.set()

    @command(ident='__apply_update__')
    async def _cmd_apply_update(self, cmdr: Commander, body, cid):
        """
        원격 업데이트 명령 수신 (서버에서 강제 업데이트)

        서버로부터 강제 업데이트 명령을 받으면 자동으로:
        1. 지정된 버전 다운로드
        2. 재시작 (apply 모드로 전환)

        Args:
            cmdr: Commander 인스턴스 (미사용)
            body: 업데이트 정보
                {
                    'version': str,  # 업데이트할 버전
                    'restart': bool  # 즉시 재시작 여부 (기본: True)
                }
            cid: 클라이언트 연결 ID
        """
        version = body.get('version')
        restart = body.get('restart', True)

        self.l.info('서버로부터 강제 업데이트 명령 수신: version=%s, restart=%s',
                   version, restart)

        try:
            # 1. 버전 다운로드
            self.l.info('버전 %s 다운로드 시작', version)
            success = await self.download_update(version=version, cid=cid)

            if not success:
                raise RuntimeError(f'버전 {version} 다운로드 실패: {self._download_error}')

            self.l.info('버전 %s 다운로드 완료', version)

            # 2. 재시작 (apply 모드로 전환)
            if restart:
                self.l.info('apply 모드로 재시작 중')
                await self.restart_service()
            else:
                self.l.info('다운로드 완료 (재시작 보류)')

        except Exception as e:
            self.l.exception('강제 업데이트 처리 실패')
            # 에러 응답 (선택 사항)
            try:
                await cmdr.send_command('__update_failed__',
                                       {'error': str(e)}, cid)
            except Exception:
                pass  # 에러 응답 실패는 무시

