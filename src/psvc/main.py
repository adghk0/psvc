
import logging
import traceback
import os, sys
import asyncio
import signal

from abc import ABC, abstractmethod

from .component import Component
from .builder import Builder
from .config import Config
from .manage import parse_args, TaskManager, service_install, service_uninstall
from .release import ReleaseManager


class Service(Component, ABC):
    """
    서비스 기본 클래스

    비동기 작업 관리, 설정 파일 처리, 빌드/릴리스 기능을 제공하는
    추상 베이스 클래스입니다. 사용자는 이 클래스를 상속하여
    init(), run(), destroy() 메서드를 구현해야 합니다.
    """
    _version_conf = 'PSVC\\version'
    # Build & Release 설정 경로
    _build_spec_file_conf = 'PSVC-build\\spec_file'
    _build_release_path_conf = 'PSVC-build\\release_path'
    _build_exclude_patterns_conf = 'PSVC-build\\exclude_patterns'
    _build_pyinstaller_options_conf = 'PSVC-build\\pyinstaller_options'

    def __init__(self, name='Service', root_file=None, config_file=None, level=None):
        """
        서비스 초기화

        Args:
            name: 서비스 이름
            root_file: 루트 파일 경로 (보통 __file__)
            config_file: 설정 파일 경로
            level: 로그 레벨

        Raises:
            RuntimeError: root_file이 제공되지 않았을 때
        """
        Component.__init__(self, None, name)
        self._sigterm = asyncio.Event()
        self._loop = None
        self._fh = None
        self.status = None
        self.level = level or 'INFO'
        self.config_file = config_file or Config._default_conf_file

        self._set_root_path(root_file)
        self._set_config_file(self.config_file)
        self.args = parse_args(sys.argv[1:])

        # 설정 파일이 명령행 인자로 제공되었으면 적용 파일 변경
        if hasattr(self.args, 'config_file') and self.args.config_file is not None:
            self._set_config_file(self.args.config_file)

        # 로거 설정
        args_level = self.args.log_level if hasattr(self.args, 'log_level') and self.args.log_level else None
        conf_level = self.get_config('PSVC', 'log_level', '') if self.get_config('PSVC', 'log_level', '') == '' else None
        self.level = args_level or conf_level or level or 'INFO'
        self.make_logger(self.level)

        # 자식 컴포넌트들에 file_handler 추가 (Config 등)
        # TODO : Component-make_logger에서 처리
        for comp in self._components.values():
            if comp.file_handler is None and hasattr(self, 'file_handler'):
                comp.file_handler = self.file_handler
                if hasattr(comp, 'l') and comp.l:
                    comp.l.addHandler(self.file_handler)

        # TaskManager 초기화
        self._task_manager = TaskManager(self.l)

        # 시작 로그
        self.l.info('='*50)
        self.l.info('서비스 생성됨 %s' % (self))

# == Status ==

    def _set_config_file(self, config_file):
        """
        설정 파일 설정 및 버전 로드

        Args:
            config_file: 설정 파일 경로
        """
        if hasattr(self, '_config'):
            del self._config
        self._config = Config(self, config_file)
        self.version = self.get_config(Service._version_conf, None, '0.0.0')


    def _set_status(self, status: str):
        """
        서비스 상태 설정

        Args:
            status: 상태 문자열 (Initting, Running, Stopping, Stopped)
        """
        self.l.info('status: ---- %s ----', status)
        self.status = status

# == Config ==

    def set_config(self, section: str, key: str, value):
        """
        설정 값 저장

        Args:
            section: 섹션 이름
            key: 키 이름
            value: 설정 값
        """
        self._config.set_config(section, key, value)

    def get_config(self, section: str, key: str, default=None):
        """
        설정 값 가져오기

        Args:
            section: 섹션 이름
            key: 키 이름
            default: 기본값

        Returns:
            설정 값
        """
        return self._config.get_config(section, key, default)


# == Operation Task Management ==

    def append_task(self, loop:asyncio.AbstractEventLoop, coro, name):
        """
        비동기 작업 추가

        Args:
            loop: 이벤트 루프
            coro: 코루틴
            name: 작업 이름

        Returns:
            asyncio.Task: 생성된 태스크
        """
        return self._task_manager.append_task(loop, coro, name)

    async def delete_task(self, task: asyncio.Task):
        """
        비동기 작업 삭제

        Args:
            task: 삭제할 태스크

        Raises:
            RuntimeError: 현재 실행 중인 태스크를 삭제하려 할 때
        """
        await self._task_manager.delete_task(task)

    def append_closer(self, closer, args):
        """
        서비스 종료 시 호출할 함수 등록

        Args:
            closer: 종료 시 호출할 함수
            args: 함수에 전달할 인자 리스트
        """
        self._task_manager.append_closer(closer, args)

    def service_install(self, service_name: str | None = None) -> None:
        """
        현재 실행 파일을 OS 서비스에 등록

        Args:
            service_name: 서비스 이름 (None이면 self.name 사용)
        """
        svc_name = service_name or self.name
        service_install(svc_name, self._root_path, self.l)

    def service_uninstall(self, service_name: str | None = None) -> None:
        """
        OS 서비스에서 제거

        Args:
            service_name: 서비스 이름 (None이면 self.name 사용)
        """
        svc_name = service_name or self.name
        service_uninstall(svc_name, self.l)

# == Build & Release ==

    def build(
        self,
        version: str,
        spec_file: str = None,
        release_path: str = None,
        exclude_patterns: list = None,
        **pyinstaller_options
    ):
        """
        PyInstaller로 실행 파일 빌드

        Args:
            version: Semantic version (예: "1.0.0")
            spec_file: PyInstaller spec 파일 경로
            release_path: 릴리스 저장 경로 (기본: {root_path}/releases)
            exclude_patterns: 제외할 파일 패턴 (기본: ['*.conf', '*.log'])
            **pyinstaller_options: PyInstaller 추가 옵션

        Returns:
            Path: 빌드된 릴리스 디렉토리 경로

        Raises:
            RuntimeError: root_path가 설정되지 않았을 때
            BuildError: 빌드 실패 시
        """
        if self._root_path is None:
            raise RuntimeError('Root path is not set. Provide root_file in __init__')

        builder = Builder(
            service_name=self.name,
            root_path=self._root_path,
            release_path=release_path
        )

        version_dir = builder.build(
            version=version,
            spec_file=spec_file,
            exclude_patterns=exclude_patterns,
            **pyinstaller_options
        )

        self.l.info('빌드 완료: %s', version_dir)
        return version_dir

    def release(
        self,
        version: str,
        approve: bool = False,
        release_path: str = None,
        release_notes: str = None,
        rollback_target: str = None
    ):
        """
        릴리스 관리 (승인/정보 확인)

        Args:
            version: 대상 버전
            approve: True면 승인 처리, False면 정보만 표시
            release_path: 릴리스 경로 (기본: {root_path}/releases)
            release_notes: 릴리스 노트
            rollback_target: 롤백 대상 버전

        Returns:
            dict: 메타데이터 딕셔너리

        Raises:
            RuntimeError: root_path가 설정되지 않았을 때
            FileNotFoundError: 버전을 찾을 수 없을 때
        """
        if self._root_path is None:
            raise RuntimeError('Root path is not set. Provide root_file in __init__')

        manager = ReleaseManager(
            service_name=self.name,
            root_path=self._root_path,
            release_path=release_path,
            logger=self.l
        )

        if approve:
            return manager.approve(version, release_notes, rollback_target)
        else:
            return manager.get_info(version)

    def rollback(
        self,
        from_version: str,
        to_version: str,
        release_path: str = None
    ):
        """
        버전 롤백 (문제 버전 deprecated 처리)

        Args:
            from_version: 문제가 있는 버전 (deprecated 처리)
            to_version: 되돌릴 버전
            release_path: 릴리스 경로

        Returns:
            dict: 롤백 정보

        Raises:
            RuntimeError: root_path가 설정되지 않았을 때
            FileNotFoundError: 버전을 찾을 수 없을 때
        """
        if self._root_path is None:
            raise RuntimeError('Root path is not set. Provide root_file in __init__')

        manager = ReleaseManager(
            service_name=self.name,
            root_path=self._root_path,
            release_path=release_path,
            logger=self.l
        )

        return manager.rollback(from_version, to_version)

    def apply(self, root_file=None, config_file=None):
        """
        다운로드된 버전을 root_path로 복사 (자기 자신 교체)

        Args:
            root_file: 루트 파일 경로 (미사용, 호환성 유지)
            config_file: 설정 파일 경로 (미사용, 호환성 유지)
        """
        ReleaseManager.apply(self._root_path, self.get_config, self.l)


# == Running ==

    def on(self):
        """
        서비스 시작

        명령행 인자에 따라 빌드/릴리스/실행 모드로 동작합니다.

        Returns:
            int: 종료 코드 (0: 성공, 1: 실패)
        """
        self.l.info('PyService 시작 %s', self)

        if not getattr(sys, 'frozen', False):
            if self.args.mode == 'build':
                # TODO : 빌드 모드에 대한 세부 작업을 builder 모듈로 이동한다
                spec_file = self.args.spec_file if self.args.spec_file is not None else \
                            self.get_config(Service._build_spec_file_conf, None, '')
                release_path = self.args.release_path if self.args.release_path is not None else \
                               self.get_config(Service._build_release_path_conf, None, 'releases')
                exclude_patterns = self.args.exclude_patterns if self.args.exclude_patterns is not None else \
                                   self.get_config(Service._build_exclude_patterns_conf, None, ['*.conf', '*.log'])
                pyinstaller_options = self.args.pyinstaller_options if self.args.pyinstaller_options is not None else \
                                      self.get_config(Service._build_pyinstaller_options_conf, None, [])

                self.build(
                    spec_file=spec_file,
                    release_path=release_path,
                    version=self.args.version,
                    exclude_patterns=exclude_patterns,
                    **{k: v for k, v in (opt.split('=', 2) for opt in pyinstaller_options if '=' in opt)}
                )
                return 0
            elif self.args.mode == 'release':
                # TODO : 릴리스 모드에 대한 세부 작업을 release 모듈로 이동한다
                release_path = self.args.release_path if self.args.release_path is not None else \
                               self.get_config(Service._build_release_path_conf, None, 'releases')

                self.release(
                    version=self.args.version,
                    approve=self.args.approve,
                    release_path=release_path,
                    release_notes=self.args.release_notes,
                    rollback_target=self.args.rollback_target
                )
                return 0

        if self.args.mode == 'apply':
            self.apply(
                root_file=self.args.root_file,
                config_file=self.args.config_file
            )
        elif self.args.mode == 'run':
            self._run()
        elif self.args.mode in ('build', 'release'):
            self.l.error('릴리스된 파일에서는 빌드 또는 릴리스할 수 없습니다.')
            return 2
        else:
            self.l.error('알 수 없는 모드: %s', self.args.mode)
            return 1

        self.l.info('PyService 중지됨 %s', self)
        return 0

    def _run(self):
        """
        서비스 실행 루프

        이벤트 루프를 생성하고 서비스를 실행합니다.
        """
        # Signal 핸들러 등록
        signal.signal(signal.SIGTERM, self.stop)
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        if self.args.install:
            self.service_install()
            return
        elif self.args.uninstall:
            self.service_uninstall()
            return

        # 메인 서비스 작업 추가
        self.append_task(self._loop, self._service(), 'ServiceWork')
        tasks = self._task_manager.get_tasks()

        try:
            self._loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        except KeyboardInterrupt as i:
            self.l.info('키보드 인터럽트 수신됨. 서비스 중지 중...')
        finally:
            # 모든 작업 취소 및 정리
            self.l.info('작업 정리 중...')
            for t in tasks:
                t.cancel()
            self._loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        self._loop.close()

        # 서비스 종료 작업 처리
        try:
            for closer, args in self._task_manager.get_closers():
                closer(*args)
        except Exception as e:
            self.l.error('closer 실행 중 오류 - %s%s: %s', closer.__name__, str(args), e)

    def stop(self, signum=None, frame=None):
        """
        서비스 중지

        signal 핸들러로도 사용 가능합니다.

        Args:
            signum: 시그널 번호 (선택)
            frame: 프레임 객체 (선택)
        """
        self._sigterm.set()

    async def _service(self):
        """
        서비스 메인 루프

        init() -> run() -> destroy() 순서로 실행합니다.
        """
        self._set_status('Initting')
        try:
            await self.init()
        except asyncio.CancelledError as c:
            self.l.error('초기화 중 서비스가 취소됨.')
            self.stop()
        except Exception as e:
            self.l.error('== 초기화 중 오류 발생 ==')
            self.l.error(traceback.format_exc())
            self.stop()
        finally:
            pass

        try:
            if not self._sigterm.is_set():
                self._set_status('Running')
                while not self._sigterm.is_set():
                    await self.run()
        except asyncio.CancelledError as c:
            pass # 서비스 취소 처리
        except Exception as e:
            self.l.error('== 실행 중 오류 발생 ==')
            self.l.error(traceback.format_exc())

        finally:
            self._set_status('Stopping')
            try:
                await self.destroy()
            except Exception as e:
                self.l.error('== 종료 중 오류 발생 ==')
                self.l.error(traceback.format_exc())
            self._set_status('Stopped')


# == User Defined ==

    async def init(self):
        """
        서비스 초기화

        서비스 시작 시 호출됩니다. 하위 클래스에서 오버라이드하여 사용합니다.
        """
        await asyncio.sleep(0.1)

    @abstractmethod
    async def run(self):
        """
        서비스 메인 로직

        서비스 실행 중 반복적으로 호출됩니다.
        하위 클래스에서 반드시 구현해야 합니다.
        """
        pass

    async def destroy(self):
        """
        서비스 종료 처리

        서비스 종료 시 호출됩니다. 하위 클래스에서 오버라이드하여 사용합니다.
        """
        await asyncio.sleep(0.1)


# == Repr ==

    def __repr__(self):
        """
        서비스 문자열 표현

        Returns:
            str: 서비스 이름과 상태 (예: "<MyService> - Running")
        """
        return '<%s> - %s' % (self.name, self.status)

