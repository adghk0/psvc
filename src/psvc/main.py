
import logging
import traceback
import os, sys
import asyncio
import signal
import subprocess
from pathlib import Path

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import configparser
import json
import argparse

from .comp import Component
from .builder import Builder


class Config(Component):
    """
    서비스 설정 관리 컴포넌트 (JSON 기반)

    INI 파일에서 JSON으로 자동 마이그레이션하며, 타입 변환을 지원합니다.
    """

    def __init__(self, svc, config_file, name='Config'):
        """
        Config 초기화

        Args:
            svc: 서비스 인스턴스
            config_file: 설정 파일 경로
            name: 컴포넌트 이름
        """
        super().__init__(svc, name)

        # 설정 파일 경로 결정
        if config_file is not None:
            original_file = self.svc.path(config_file)
        else:
            original_file = self.svc.path(Service._default_conf_file)

        # INI/JSON 경로 분리
        self._ini_file = original_file
        self._config_file = self._get_json_path(original_file)

        # 설정 로드
        self._config = self._load_config()

    def _get_json_path(self, file_path: str) -> str:
        """
        설정 파일 경로를 JSON 경로로 변환

        Args:
            file_path: 원본 설정 파일 경로

        Returns:
            str: JSON 파일 경로
        """
        if file_path.endswith('.conf'):
            return file_path.replace('.conf', '.json')
        elif file_path.endswith('.ini'):
            return file_path.replace('.ini', '.json')
        elif file_path.endswith('.json'):
            return file_path
        else:
            return file_path + '.json'

    def _load_config(self) -> dict:
        """
        설정 파일 로드 (JSON 우선, 없으면 INI 마이그레이션)

        Returns:
            dict: 로드된 설정 딕셔너리
        """
        import json

        self.l.info('설정 파일 로드: %s', self._config_file)
        # 1. JSON 파일이 존재하면 로드ㅈ
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                self.l.error('JSON 설정 파일 로드 실패 (%s): %s', self._config_file, e)
                # JSON 파싱 실패 시 INI에서 재생성 시도
                if os.path.exists(self._ini_file):
                    return self._migrate_from_ini()
                return {}

        # 2. INI 파일이 존재하면 마이그레이션
        if os.path.exists(self._ini_file):
            return self._migrate_from_ini()
        # 3. 둘 다 없으면 빈 설정
        return {}
    
        

    def _migrate_from_ini(self) -> dict:
        """
        INI 파일을 JSON으로 변환

        Returns:
            dict: 변환된 설정 딕셔너리
        """
        self.l.info('설정 파일 마이그레이션 중: %s -> %s', self._ini_file, self._config_file)

        parser = configparser.ConfigParser()
        parser.read(self._ini_file, encoding='utf-8')

        # INI를 dict로 변환
        config = {}
        for section in parser.sections():
            config[section] = dict(parser.items(section))

        # JSON으로 저장
        self._save_config(config)

        # INI 파일에 마이그레이션 안내 추가
        self._mark_ini_as_migrated()

        return config

    def _mark_ini_as_migrated(self):
        """
        INI 파일 상단에 마이그레이션 안내 추가

        JSON으로 마이그레이션되었음을 INI 파일 상단에 표시합니다.
        """
        if not os.path.exists(self._ini_file):
            return

        with open(self._ini_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 이미 마크가 있는지 확인
        if '# This file is parsed to' in content:
            return

        # 상단에 안내 추가
        header = f'# This file is parsed to {self._config_file}\n'
        header += '# Please edit the JSON file instead.\n\n'

        with open(self._ini_file, 'w', encoding='utf-8') as f:
            f.write(header + content)

    def _save_config(self, config=None):
        """
        설정을 JSON 파일로 저장

        Args:
            config: 저장할 설정 딕셔너리 (None이면 현재 설정 저장)
        """
        import json

        if config is None:
            config = self._config

        with open(self._config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def _parse_value(self, value, dtype=None):
        """
        값을 지정된 타입으로 파싱

        Args:
            value: 파싱할 값
            dtype: 목표 타입 (None, str, int, float, bool, list, dict 또는 callable)

        Returns:
            파싱된 값

        Raises:
            ValueError: 타입 변환 실패 시
        """
        # 타입 지정이 없으면 원본 반환
        if dtype is None:
            return value

        # 기본 타입 변환
        type_converters = {
            str: lambda v: str(v),
            int: lambda v: int(v),
            float: lambda v: float(v),
        }

        if dtype in type_converters:
            return type_converters[dtype](value)

        # bool 타입 처리 (문자열 "true", "false" 등 지원)
        if dtype == bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ('true', '1', 'yes', 'on')
            return bool(value)

        # list 타입 처리 (쉼표 구분 문자열 지원)
        if dtype == list:
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [item.strip() for item in value.split(',') if item.strip()]
            return list(value)

        # dict 타입 처리
        if dtype == dict:
            if isinstance(value, dict):
                return value
            raise ValueError(f'Cannot convert {type(value).__name__} to dict')

        # 사용자 정의 타입 (callable)
        return dtype(value)

    def set_config(self, section: str, key: str, value, dtype=None):
        """
        설정 값을 저장합니다.

        Args:
            section: 섹션 이름
            key: 키 이름
            value: 설정 값
            dtype: 데이터 타입 (str, int, float, bool, list, dict 또는 callable)
        """
        # 섹션이 없으면 생성
        if section not in self._config:
            self._config[section] = {}

        # 타입 변환 후 저장
        self._config[section][key] = self._parse_value(value, dtype)
        self._save_config()

    def get_config(self, section: str, key: str = None, default=None, dtype=None):
        """
        설정 값을 반환합니다.

        Args:
            section: 섹션 이름 (또는 'section\\key' 형식)
            key: 키 이름 (None이면 섹션 전체 반환)
            default: 기본값 (없을 경우 자동으로 설정)
            dtype: 데이터 타입 (str, int, float, bool, list, dict 또는 callable)

        Returns:
            설정 값 (key가 None이면 섹션 dict)

        Raises:
            KeyError: 섹션 또는 키가 없고 default도 None인 경우
        """
        # 하위 호환성: 'section\\key' 형식 지원
        if key is None and '\\' in section:
            section, key = section.split('\\', 1)

        # 섹션 없음
        if section not in self._config:
            if default is not None and key is not None:
                self.set_config(section, key, default, dtype)
                return self._parse_value(default, dtype)
            raise KeyError(f'Section does not exist: {section}')

        # 섹션 전체 반환
        if key is None:
            return self._config[section]

        # 키 없음
        if key not in self._config[section]:
            if default is not None:
                self.set_config(section, key, default, dtype)
                return self._parse_value(default, dtype)
            raise KeyError(f'Config does not exist: {section}\\{key}')

        # 값 반환 (타입 변환)
        return self._parse_value(self._config[section][key], dtype)
    

class Service(Component, ABC):
    """
    서비스 기본 클래스

    비동기 작업 관리, 설정 파일 처리, 빌드/릴리스 기능을 제공하는
    추상 베이스 클래스입니다. 사용자는 이 클래스를 상속하여
    init(), run(), destroy() 메서드를 구현해야 합니다.
    """
    _default_conf_file = 'psvc.json'
    _version_conf = 'PSVC\\version'
    _log_conf_path = 'PSVC\\log_format'
    _default_log_format = '%(asctime)s : %(name)s [%(levelname)s] %(message)s - %(lineno)s'
    _log_levels = {
            'CRITICAL': logging.CRITICAL,
            'ERROR': logging.ERROR,
            'WARNING': logging.WARNING,
            'INFO': logging.INFO,
            'DEBUG': logging.DEBUG,
            'NOTSET': logging.NOTSET,
        }

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
        self._tasks = []
        self._closers = []
        self._fh = None
        self.status = None
        self.level = 0

        self._set_root_path(root_file)
        self.config_file = config_file
        self._set_config_file(self.config_file)
        self.args = self._parse_args(sys.argv[1:])

        if hasattr(self.args, 'config_file') and self.args.config_file is not None:
            self._set_config_file(self.args.config_file)
        self.level = self.args.log_level if hasattr(self.args, 'log_level') and self.args.log_level else level

        # 로거 설정
        self._set_logger(self.level)

        # 시작 로그
        self.l.info('='*50)
        self.l.info('서비스 생성됨 %s' % (self))

# == Status ==

    def _parse_args(self, argv=None):
        """
        명령행 인자 파싱

        Args:
            argv: 명령행 인자 리스트 (None이면 sys.argv[1:] 사용)

        Returns:
            argparse.Namespace: 파싱된 인자
        """
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest='mode')
        
        p_run = subparsers.add_parser('run', help='Run the service')
        p_run.add_argument('-l', '--log_level', dest='log_level', help='Log level', default=None)
        p_run.add_argument('-c', '--config_file', dest='config_file', help='Config file path', default=None)
    
        p_build = subparsers.add_parser('build', help='Build the service')
        p_build.add_argument('-f', '--spec_file', dest='spec_file', help='PyInstaller spec file',
                             default=None)
        p_build.add_argument('-p', '--release_path', dest='release_path', help='Release path',
                             default=None)
        p_build.add_argument('-e', '--exclude-patterns', nargs='*', dest='exclude_patterns', help='Patterns to exclude from the build',
                             default=None)
        p_build.add_argument('-v', '--version', dest='version', help='Version to build', required=True, )
        p_build.add_argument('-o', '--pyinstaller-options', nargs='*', dest='pyinstaller_options', help='Additional PyInstaller options as key=value pairs',
                             default=None)

        p_release = subparsers.add_parser('release', help='Release the service')
        p_release.add_argument('-a', '--approve', action='store_true', help='Approve the release')
        p_release.add_argument('-p','--release_path', dest='release_path', help='Release path',
                             default=None)
        p_release.add_argument('-n', '--release_notes', dest='release_notes', help='Release notes', default=None)
        p_release.add_argument('-r', '--rollback_target', dest='rollback_target', help='Rollback target version', default=None)
        p_release.add_argument('-v', '--version', dest='version', help='Version to release', required=True, ) 

        p_apply = subparsers.add_parser('apply', help='Apply pending updates on startup')
        p_apply.add_argument('--root_file', dest='root_file', help='Root file path', default=None, required=True)
        p_apply.add_argument('--config_file', dest='config_file', help='Config file path', default=None)

        parser.set_defaults(mode='run')
        return parser.parse_args(argv)
   
    def _set_root_path(self, root_file):
        """
        루트 경로 설정

        Args:
            root_file: 루트 파일 경로

        Raises:
            RuntimeError: root_file이 None이고 frozen 상태가 아닐 때
        """
        if getattr(sys, 'frozen', False):
            self._root_path = os.path.abspath(os.path.dirname(sys.executable))
        elif root_file:
            self._root_path = os.path.abspath(os.path.dirname(root_file))
        else:
            raise RuntimeError('Root path is not set. Provide root_file in __init__')
    
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

    def _set_logger(self, level):
        """
        로거 설정

        Args:
            level: 로그 레벨
        """
        if self.level is None:
            level = self.get_config('PSVC', 'log_level', '')

        if type(level) == str:
            d_level = Service._log_levels[level] if level in Service._log_levels else \
                int(level) if level.isdigit() else None
            if d_level is None:
                d_level = logging.INFO
            self.level = d_level

        self.log_format = self.get_config(Service._log_conf_path, None, Service._default_log_format)

        # 로그 핸들러 설정
        self._fh = logging.FileHandler(self.path(self.name+'.log'))
        self._fh.setLevel(self.level)
        self._fh.setFormatter(logging.Formatter(self.log_format))
        logging.basicConfig(level=self.level, force=True, format=self.log_format)
        self.l = logging.getLogger(name=self.name)
        self.l.addHandler(self._fh)

        for comp in self._components.values():
            comp.set_logger(self.get_logger(comp.name))
    
    def get_logger(self, name: str) -> logging.Logger:
        """
        하위 컴포넌트용 로거 반환

        Args:
            name: 하위 컴포넌트 이름

        Returns:
            logging.Logger: 하위 컴포넌트용 로거
        """
        logger = logging.getLogger(name=name)
        logger.setLevel(self.level)
        if self._fh:
            logger.addHandler(self._fh)
        return logger
    
    def _set_status(self, status: str):
        """
        서비스 상태 설정

        Args:
            status: 상태 문자열 (Initting, Running, Stopping, Stopped)
        """
        self.l.info('status: ---- %s ----', status)
        self.status = status

    def path(self, path):
        """
        상대 경로를 절대 경로로 변환

        Args:
            path: 상대 또는 절대 경로

        Returns:
            str: 절대 경로
        """
        if os.path.isabs(path) or self._root_path is None:
            return path
        return os.path.join(self._root_path, path)
    
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
        self.l.debug('작업 추가 - %s', name)
        task = loop.create_task(coro, name=name)
        self._tasks.append(task)
        return task

    async def delete_task(self, task: asyncio.Task):
        """
        비동기 작업 삭제

        Args:
            task: 삭제할 태스크

        Raises:
            RuntimeError: 현재 실행 중인 태스크를 삭제하려 할 때
        """
        self.l.debug('작업 삭제 - %s', task.get_name())
        if task in self._tasks and not task.done():
            if task is asyncio.current_task():
                raise RuntimeError('Cannot delete the current running task')
            
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._tasks.remove(task)

    def append_closer(self, closer: Callable[..., Any], args: list[Any]) -> None:
        """
        서비스 종료 시 호출할 함수 등록

        Args:
            closer: 종료 시 호출할 함수
            args: 함수에 전달할 인자 리스트

        Raises:
            TypeError: closer가 callable이 아니거나 args가 list/tuple이 아닐 때
        """
        if not callable(closer):
            raise TypeError("closer is not callable.")
        if not isinstance(args, (list, tuple)):
            raise TypeError("args must be a list or tuple.")
        self._closers.append((closer, list(args)))


# == Build & Release ==
    _build_spec_file_conf = 'PSVC-build\\spec_file'
    _build_release_path_conf = 'PSVC-build\\release_path'
    _build_exclude_patterns_conf = 'PSVC-build\\exclude_patterns'
    _build_pyinstaller_options_conf = 'PSVC-build\\pyinstaller_options'
    
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

        Example:
            service = MyService('MyApp', __file__)
            service.build(version='1.0.0', spec_file='my_app.spec')
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

        Example:
            # 정보 확인
            service.release(version='1.0.0')

            # 승인 처리
            service.release(
                version='1.0.0',
                approve=True,
                release_notes='Bug fixes and improvements'
            )
        """
        if self._root_path is None:
            raise RuntimeError('Root path is not set. Provide root_file in __init__')

        if release_path:
            base_path = Path(release_path)
        else:
            base_path = Path(self._root_path) / 'releases'

        version_dir = base_path / version
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
        if approve:
            print(f"\n=== Approving {self.name} v{version} ===")

            metadata['status'] = 'approved'

            if release_notes:
                metadata['release_notes'] = release_notes

            if rollback_target:
                metadata['rollback_target'] = rollback_target

            # 저장
            with open(status_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            print(f"✓ Version {version} has been approved")
            self.l.info('버전 %s 승인됨', version)

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
            dict: 롤백 정보 (from_version, to_version, 메타데이터 포함)

        Raises:
            RuntimeError: root_path가 설정되지 않았을 때
            FileNotFoundError: 버전을 찾을 수 없을 때

        Example:
            # 1.0.0에 문제가 있어서 0.9.5로 롤백
            service.rollback(from_version='1.0.0', to_version='0.9.5')
        """
        if self._root_path is None:
            raise RuntimeError('Root path is not set. Provide root_file in __init__')

        if release_path:
            base_path = Path(release_path)
        else:
            base_path = Path(self._root_path) / 'releases'

        print(f"\n=== Rolling back from v{from_version} to v{to_version} ===")

        # 1. from_version을 deprecated 처리
        from_dir = base_path / from_version
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
        to_dir = base_path / to_version
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

        self.l.info('%s에서 %s로 롤백됨', from_version, to_version)

        return {
            'from_version': from_version,
            'to_version': to_version,
            'from_metadata': from_metadata,
            'to_metadata': to_metadata
        }

    def apply(self, root_file=None, config_file=None):
        """
        다운로드된 버전을 root_path로 복사 (자기 자신 교체)

        업데이트 시퀀스의 핵심 단계:
        1. saved_args.json에서 버전 정보 및 원래 실행 인자 로드
        2. 다운로드된 파일들을 root_path로 복사
        3. 권한 복구 (Linux)
        4. run 모드로 재시작

        Args:
            root_file: 루트 파일 경로 (미사용, 호환성 유지)
            config_file: 설정 파일 경로 (미사용, 호환성 유지)
        """
        import shutil

        self.l.info('apply 모드 시작: 업데이트 적용 중')

        # 1. update_path 확인
        update_path_conf = 'PSVC\\update_path'
        update_path = self.get_config(update_path_conf, None, 'updates')
        full_update_path = self.path(update_path)

        if not os.path.exists(full_update_path):
            self.l.error('업데이트 경로가 존재하지 않음: %s', full_update_path)
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
            self.l.error('saved_args.json을 찾을 수 없음 (업데이트 파일 없음)')
            raise FileNotFoundError('업데이트할 버전을 찾을 수 없음')

        # 3. saved_args.json 로드
        with open(saved_args_path, 'r', encoding='utf-8') as f:
            saved_args = json.load(f)

        version = saved_args.get('version', 'unknown')
        original_argv = saved_args.get('argv', [])
        timestamp = saved_args.get('timestamp', '')

        self.l.info('업데이트 적용: 버전 %s (생성: %s)', version, timestamp)
        self.l.info('저장된 인자: %s', original_argv)

        # 4. 파일 복사 (version_dir의 모든 파일 → root_path)
        deployed_count = 0

        for root, _, files in os.walk(version_dir):
            for file_name in files:
                # saved_args.json은 복사하지 않음
                if file_name == 'saved_args.json':
                    continue

                src_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(src_path, version_dir)
                dest_path = os.path.join(self._root_path, rel_path)

                # 디렉토리 생성
                dest_dir = os.path.dirname(dest_path)
                if dest_dir:
                    os.makedirs(dest_dir, exist_ok=True)

                # 파일 복사 (메타데이터 보존)
                self.l.info('복사: %s → %s', rel_path, dest_path)
                shutil.copy2(src_path, dest_path)

                # 권한 복구 (Linux)
                if sys.platform != 'win32':
                    src_stat = os.stat(src_path)
                    os.chmod(dest_path, src_stat.st_mode)

                deployed_count += 1

        self.l.info('버전 %s에 대해 %d개 파일 배포 완료', version, deployed_count)

        # 5. 검증 (기본적인 파일 존재 확인)
        if deployed_count == 0:
            self.l.error('배포된 파일이 없음 - 업데이트 실패')
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

            self.l.info('run 모드로 재시작: %s', run_args)
            subprocess.Popen(run_args, start_new_session=(sys.platform != 'win32'))

        try:
            start_run_mode(sys.executable, original_argv)
            self.l.info('apply 완료, 프로세스 종료')
        except Exception as e:
            self.l.error('재시작 실패: %s', e)
            raise

        # apply 프로세스 종료
        sys.exit(0)


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
                # Resolve defaults from config only when in build mode
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
                # Resolve defaults from config only when in release mode
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
            self._run(
                
            )
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

        # 메인 서비스 작업 추가
        self.append_task(self._loop, self._service(), 'ServiceWork')
        try:
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))
        except KeyboardInterrupt as i:
            self.l.info('키보드 인터럽트 수신됨. 서비스 중지 중...')
        finally:
            # 모든 작업 취소 및 정리
            self.l.info('작업 정리 중...')
            for t in self._tasks:
                t.cancel()
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))
        self._loop.close()   

        # 서비스 종료 작업 처리
        try:
            for closer, args in self._closers:
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
    
