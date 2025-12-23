"""
릴리스 서버 모듈

빌드된 버전을 제공하고 클라이언트의 업데이트 요청을 처리합니다.
"""

import os
import sys
import subprocess
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from .component import Component
from .cmd import Commander, command

if TYPE_CHECKING:
    from .main import Service


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

    def __init__(self, svc: 'Service', commander: Commander, name='Releaser', parent=None):
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


class ReleaseManager:
    """
    릴리스 관리 클래스

    빌드된 버전의 승인, 롤백, 적용 기능을 제공합니다.
    """

    def __init__(self, service_name: str, root_path: str, release_path: str = None, logger=None):
        """
        ReleaseManager 초기화

        Args:
            service_name: 서비스 이름
            root_path: 서비스 루트 경로
            release_path: 릴리스 경로 (기본: {root_path}/releases)
            logger: 로거 인스턴스
        """
        self.service_name = service_name
        self.root_path = root_path
        self.release_path = Path(release_path) if release_path else Path(root_path) / 'releases'
        self.logger = logger

    def approve(
        self,
        version: str,
        release_notes: str = None,
        rollback_target: str = None
    ) -> dict:
        """
        버전 승인

        Args:
            version: 승인할 버전
            release_notes: 릴리스 노트
            rollback_target: 롤백 대상 버전

        Returns:
            dict: 메타데이터 딕셔너리

        Raises:
            FileNotFoundError: 버전을 찾을 수 없을 때
        """
        version_dir = self.release_path / version
        status_file = version_dir / 'status.json'

        if not status_file.exists():
            raise FileNotFoundError(
                f"Version {version} not found. "
                f"Build it first using service.build()"
            )

        # 메타데이터 읽기
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        # 승인 처리
        print(f"\n=== Approving {self.service_name} v{version} ===")

        metadata['status'] = 'approved'

        if release_notes:
            metadata['release_notes'] = release_notes

        if rollback_target:
            metadata['rollback_target'] = rollback_target

        # 저장
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        print(f"✓ Version {version} has been approved")
        if self.logger:
            self.logger.info('버전 %s 승인됨', version)

        return metadata

    def get_info(self, version: str) -> dict:
        """
        버전 정보 조회

        Args:
            version: 조회할 버전

        Returns:
            dict: 메타데이터 딕셔너리

        Raises:
            FileNotFoundError: 버전을 찾을 수 없을 때
        """
        version_dir = self.release_path / version
        status_file = version_dir / 'status.json'

        if not status_file.exists():
            raise FileNotFoundError(f"Version {version} not found")

        # 메타데이터 읽기
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        # 정보 출력
        print(f"\n=== Release Information ===")
        print(f"  Version: {metadata['version']}")
        print(f"  Status: {metadata['status']}")
        print(f"  Build time: {metadata['build_time']}")
        print(f"  Platform: {metadata['platform']}")
        print(f"  Files: {len(metadata['files'])} files")
        print(f"  Total size: {sum(f['size'] for f in metadata['files']) / 1024 / 1024:.2f} MB")

        if metadata.get('release_notes'):
            print(f"  Release notes: {metadata['release_notes']}")

        if metadata.get('rollback_target'):
            print(f"  Rollback target: {metadata['rollback_target']}")

        return metadata

    def rollback(
        self,
        from_version: str,
        to_version: str
    ) -> dict:
        """
        버전 롤백 (문제 버전 deprecated 처리)

        Args:
            from_version: 문제가 있는 버전 (deprecated 처리)
            to_version: 되돌릴 버전

        Returns:
            dict: 롤백 정보 (from_version, to_version, 메타데이터 포함)

        Raises:
            FileNotFoundError: 버전을 찾을 수 없을 때
        """
        print(f"\n=== Rolling back from v{from_version} to v{to_version} ===")

        # 1. from_version을 deprecated 처리
        from_dir = self.release_path / from_version
        from_status_file = from_dir / 'status.json'

        if not from_status_file.exists():
            raise FileNotFoundError(f"Version {from_version} not found")

        with open(from_status_file, 'r', encoding='utf-8') as f:
            from_metadata = json.load(f)

        from_metadata['status'] = 'deprecated'
        from_metadata['rollback_target'] = to_version

        with open(from_status_file, 'w', encoding='utf-8') as f:
            json.dump(from_metadata, f, indent=2, ensure_ascii=False)

        print(f"  ✓ Version {from_version} marked as deprecated")

        # 2. to_version 확인
        to_dir = self.release_path / to_version
        to_status_file = to_dir / 'status.json'

        if not to_status_file.exists():
            raise FileNotFoundError(f"Rollback target {to_version} not found")

        with open(to_status_file, 'r', encoding='utf-8') as f:
            to_metadata = json.load(f)

        if to_metadata['status'] != 'approved':
            print(f"  Warning: Target version {to_version} is not approved")
            print(f"  Current status: {to_metadata['status']}")

        print(f"  ✓ Rollback target {to_version} is available")
        print(f"\nRollback completed. Clients will use v{to_version}")

        if self.logger:
            self.logger.info('%s에서 %s로 롤백됨', from_version, to_version)

        return {
            'from_version': from_version,
            'to_version': to_version,
            'from_metadata': from_metadata,
            'to_metadata': to_metadata
        }

    @staticmethod
    def apply(root_path: str, config_getter, logger):
        """
        다운로드된 버전을 root_path로 복사 (자기 자신 교체)

        업데이트 시퀀스의 핵심 단계:
        1. saved_args.json에서 버전 정보 및 원래 실행 인자 로드
        2. 다운로드된 파일들을 root_path로 복사
        3. 권한 복구 (Linux)
        4. run 모드로 재시작

        Args:
            root_path: 서비스 루트 경로
            config_getter: config 값을 가져오는 함수
            logger: 로거 인스턴스
        """
        logger.info('apply 모드 시작: 업데이트 적용 중')

        # 1. update_path 확인
        update_path_conf = 'PSVC\\update_path'
        update_path = config_getter(update_path_conf, None, 'updates')
        full_update_path = os.path.join(root_path, update_path) if not os.path.isabs(update_path) else update_path

        if not os.path.exists(full_update_path):
            logger.error('업데이트 경로가 존재하지 않음: %s', full_update_path)
            raise FileNotFoundError(f'업데이트 경로 없음: {full_update_path}')

        # 2. 최신 다운로드 버전 찾기 (saved_args.json이 있는 디렉토리)
        version_dir = None
        saved_args_path = None

        for entry in os.listdir(full_update_path):
            potential_dir = os.path.join(full_update_path, entry)
            potential_args_file = os.path.join(potential_dir, 'saved_args.json')

            if os.path.isdir(potential_dir) and os.path.exists(potential_args_file):
                version_dir = potential_dir
                saved_args_path = potential_args_file
                break

        if not version_dir or not saved_args_path:
            logger.error('saved_args.json을 찾을 수 없음 (업데이트 파일 없음)')
            raise FileNotFoundError('업데이트할 버전을 찾을 수 없음')

        # 3. saved_args.json 로드
        with open(saved_args_path, 'r', encoding='utf-8') as f:
            saved_args = json.load(f)

        version = saved_args.get('version', 'unknown')
        original_argv = saved_args.get('argv', [])
        timestamp = saved_args.get('timestamp', '')

        logger.info('업데이트 적용: 버전 %s (생성: %s)', version, timestamp)
        logger.info('저장된 인자: %s', original_argv)

        # 4. 파일 복사 (version_dir의 모든 파일 → root_path)
        deployed_count = 0

        for root, _, files in os.walk(version_dir):
            for file_name in files:
                # saved_args.json은 복사하지 않음
                if file_name == 'saved_args.json':
                    continue

                src_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(src_path, version_dir)
                dest_path = os.path.join(root_path, rel_path)

                # 디렉토리 생성
                dest_dir = os.path.dirname(dest_path)
                if dest_dir:
                    os.makedirs(dest_dir, exist_ok=True)

                # 파일 복사 (메타데이터 보존)
                logger.info('복사: %s → %s', rel_path, dest_path)
                shutil.copy2(src_path, dest_path)

                # 권한 복구 (Linux)
                if sys.platform != 'win32':
                    src_stat = os.stat(src_path)
                    os.chmod(dest_path, src_stat.st_mode)

                deployed_count += 1

        logger.info('버전 %s에 대해 %d개 파일 배포 완료', version, deployed_count)

        # 5. 검증 (기본적인 파일 존재 확인)
        if deployed_count == 0:
            logger.error('배포된 파일이 없음 - 업데이트 실패')
            raise RuntimeError('업데이트 파일이 비어있음')

        # 6. run 모드로 재시작
        def start_run_mode(executable, original_argv):
            """run 모드로 재시작"""
            # original_argv[0]은 프로그램 경로
            # mode가 'apply'인 경우 제거하고 기본 run 모드로 실행
            run_args = [executable]

            # 원래 인자에서 mode 관련 부분 제거
            skip_next = False
            for arg in original_argv[1:]:  # argv[0]은 프로그램 경로
                if skip_next:
                    skip_next = False
                    continue

                if arg in ('apply', 'build', 'release'):
                    # mode 인자는 제외
                    continue
                elif arg in ('--root_file', '--config_file', '--version_dir'):
                    # 다음 인자도 건너뛰기
                    skip_next = True
                    continue

                run_args.append(arg)

            logger.info('run 모드로 재시작: %s', run_args)
            subprocess.Popen(run_args, start_new_session=(sys.platform != 'win32'))

        try:
            start_run_mode(sys.executable, original_argv)
            logger.info('apply 완료, 프로세스 종료')
        except Exception as e:
            logger.error('재시작 실패: %s', e)
            raise

        # apply 프로세스 종료
        sys.exit(0)
