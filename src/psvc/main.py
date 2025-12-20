
import logging
import traceback
import os, sys
import asyncio
import signal
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
    """서비스 설정 관리 컴포넌트 (JSON 기반)"""

    def __init__(self, svc, config_file, name='Config'):
        super().__init__(svc, name)

        # 설정 파일 경로 결정
        if config_file is not None:
            original_file = self.svc.path(config_file)
        else:
            original_file = self.svc.path(Service._default_conf_file)

        # INI/JSON 경로 분리
        self._ini_file = original_file
        self._json_file = self._get_json_path(original_file)

        # 설정 로드
        self._config = self._load_config()

    def _get_json_path(self, file_path: str) -> str:
        """설정 파일 경로를 JSON 경로로 변환"""
        if file_path.endswith('.conf'):
            return file_path.replace('.conf', '.json')
        elif file_path.endswith('.ini'):
            return file_path.replace('.ini', '.json')
        else:
            return file_path + '.json'

    def _load_config(self) -> dict:
        """설정 파일 로드 (JSON 우선, 없으면 INI 마이그레이션)"""
        import json

        # 1. JSON 파일이 존재하면 로드
        if os.path.exists(self._json_file):
            try:
                with open(self._json_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                self.l.error('Failed to load JSON config (%s): %s', self._json_file, e)
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
        """INI 파일을 JSON으로 변환"""
        self.l.info('Migrating config: %s -> %s', self._ini_file, self._json_file)

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
        """INI 파일 상단에 마이그레이션 안내 추가"""
        if not os.path.exists(self._ini_file):
            return

        with open(self._ini_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 이미 마크가 있는지 확인
        if '# This file is parsed to' in content:
            return

        # 상단에 안내 추가
        header = f'# This file is parsed to {self._json_file}\n'
        header += '# Please edit the JSON file instead.\n\n'

        with open(self._ini_file, 'w', encoding='utf-8') as f:
            f.write(header + content)

    def _save_config(self, config=None):
        """설정을 JSON 파일로 저장"""
        import json

        if config is None:
            config = self._config

        with open(self._json_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def _parse_value(self, value, dtype=None):
        """값을 지정된 타입으로 파싱

        Args:
            value: 파싱할 값
            dtype: 목표 타입 (None, str, int, float, bool, list, dict 또는 callable)

        Returns:
            파싱된 값
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
        """설정 값을 저장합니다.

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
        """설정 값을 반환합니다.

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
    _default_conf_file = 'psvc.conf'
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
        파이썬 서비스 인스턴스를 생성합니다.
        
        :param self: 서비스 인스턴스
        :param name: 서비스 이름
        :param root_file: 루트 파일 경로
        :param config_file: 설정 파일 경로
        :param level: 로그 레벨
        """
        Component.__init__(self, None, name)
        self._sigterm = asyncio.Event()
        self._loop = None
        self._tasks = []
        self._closers = []
        self._fh = None
        self.status = None

        self._set_root_path(root_file)
        self.config_file = config_file
        self._set_config_file(self.config_file)
        self.args = self._parse_args(sys.argv[1:])

        if self.args.hasattr('config_file') and self.args.config_file is not None:
            self._set_config_file(self.args.config_file)
        self.level = self.args.log_level if self.args.log_level else level

        # 로거 설정
        self._set_logger(self.level)

        # 시작 로그
        self.l.info('='*50)
        if level is None:
            self.l.warning('unused log level, set to INFO, %s', level)
        self.l.info('Service Created %s' % (self))

# == Status ==

    def _parse_args(self, argv=None):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest='mode')
        
        p_run = subparsers.add_parser('run', help='Run the service')
        p_run.add_argument('-l', '--log_level', dest='log_level', help='Log level', default=None)
        p_run.add_argument('-c', '--config_file', dest='config_file', help='Config file path', default=None)
    
        p_build = subparsers.add_parser('build', help='Build the service')
        p_build.add_argument('-f', '--spec_file', dest='spec_file', help='PyInstaller spec file',
                             default=self.get_config(Service._build_spec_file_conf, None, ''))
        p_build.add_argument('-p', '--release_path', dest='release_path', help='Release path',
                             default=self.get_config(Service._build_release_path_conf, None, 'releases'))
        p_build.add_argument('-e', '--exclude-patterns', nargs='*', dest='exclude_patterns', help='Patterns to exclude from the build',
                             default=self.get_config(Service._build_exclude_patterns_conf, None, ['*.conf', '*.log']))
        p_build.add_argument('-v', '--version', dest='version', help='Version to build', required=True, )
        p_build.add_argument('-o', '--pyinstaller-options', nargs='*', dest='pyinstaller_options', help='Additional PyInstaller options as key=value pairs',
                             default=self.get_config(Service._build_pyinstaller_options_conf, None, []))

        p_release = subparsers.add_parser('release', help='Release the service')
        p_release.add_argument('-a', '--approve', action='store_true', help='Approve the release')
        p_release.add_argument('-p','--release_path', dest='release_path', help='Release path',
                             default=self.get_config(Service._build_release_path_conf, None, 'releases'))
        p_release.add_argument('-n', '--release_notes', dest='release_notes', help='Release notes', default=None)
        p_release.add_argument('-r', '--rollback_target', dest='rollback_target', help='Rollback target version', default=None)
        p_release.add_argument('-v', '--version', dest='version', help='Version to release', required=True, ) 

        p_apply = subparsers.add_parser('apply', help='Apply pending updates on startup')
        p_apply.add_argument('--root_file', dest='root_file', help='Root file path', default=None, required=True)
        p_apply.add_argument('--config_file', dest='config_file', help='Config file path', default=None)

        parser.set_defaults(mode='run')
        return parser.parse_args(argv)
   
    def _set_root_path(self, root_file):
        if getattr(sys, 'frozen', False):
            self._root_path = os.path.abspath(os.path.dirname(sys.executable))
        elif root_file:
            self._root_path = os.path.abspath(os.path.dirname(root_file))
        else:
            raise RuntimeError('Root path is not set. Provide root_file in __init__')
    
    def _set_config_file(self, config_file):
        if hasattr(self, '_config'):
            del self._config
        self._config = Config(self, config_file)
        self.version = self.get_config(Service._version_conf, None, '0.0.0')

    def _set_logger(self, level):
        if self.level is None:
            level = self.get_config('PSVC', 'log_level', '')
            d_level = Service._log_levels[level] if level in Service._log_levels else \
                int(level) if level.isdigit() else None
            self.level = d_level if d_level is not None else logging.INFO
        self.log_format = self.get_config(Service._log_conf_path, None, Service._default_log_format)

        # 로그 핸들러 설정
        self._fh = logging.FileHandler(self.path(self.name+'.log'))
        self._fh.setLevel(level)
        self._fh.setFormatter(logging.Formatter(self.log_format))
        logging.basicConfig(level=level, force=True, format=self.log_format)
        self.l = logging.getLogger(name=self.name)
        self.l.addHandler(self._fh)

    def _set_status(self, status: str):
        self.l.info('Status=%s', status)
        self.status = status

    def path(self, path):
        if os.path.isabs(path) or self._root_path is None:
            return path
        return os.path.join(self._root_path, path)
    
# == Config ==

    def set_config(self, section: str, key: str, value):
        self._config.set_config(section, key, value)

    def get_config(self, section: str, key: str, default=None):
        return self._config.get_config(section, key, default)


# == Operation Task Management ==
    
    def append_task(self, loop:asyncio.AbstractEventLoop, coro, name):
        self.l.debug('Append Task - %s', name)
        task = loop.create_task(coro, name=name)
        self._tasks.append(task)
        return task
    
    async def delete_task(self, task: asyncio.Task):
        self.l.debug('Delete Task - %s', task.get_name())
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
        서비스 종료시 호출할 함수를 등록합니다.
        
        :param closer: 종료시 호출할 함수
        :type closer: Callable[..., Any]
        :param args: 함수에 전달할 인자 리스트
        :type args: list[Any]
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
            빌드된 릴리스 디렉토리 경로

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

        self.l.info('Build completed: %s', version_dir)
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
            메타데이터 딕셔너리

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
            self.l.info('Version %s approved', version)

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

        self.l.info('Rolled back from %s to %s', from_version, to_version)

        return {
            'from_version': from_version,
            'to_version': to_version,
            'from_metadata': from_metadata,
            'to_metadata': to_metadata
        }

    def apply(self):
        # TODO : 구현
        pass

# == Running ==
    
    
    def _apply_pending_update(self):
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
        else:
            exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

        # .new 파일 찾기
        updated_count = 0
        for item in os.listdir(exe_dir):
            if item.endswith('.new'):
                new_file = os.path.join(exe_dir, item)
                target_file = new_file[:-4]  # .new 제거

                try:
                    # 기존 파일 백업
                    if os.path.exists(target_file):
                        old_file = target_file + '.old'
                        if os.path.exists(old_file):
                            os.remove(old_file)
                        os.rename(target_file, old_file)
                        self.l.debug('Backed up: %s -> %s', target_file, old_file)

                    # .new 파일을 실제 파일로 교체
                    os.rename(new_file, target_file)
                    self.l.info('Updated: %s', target_file)
                    updated_count += 1

                except Exception as e:
                    self.l.error('Failed to apply update for %s: %s', item, e)

        if updated_count > 0:
            self.l.info('Applied %d pending update(s)', updated_count)

    
    def on(self):
        self.l.info('PyService Start %s', self)

        
        
        if not getattr(sys, 'frozen', False):
            if self.args.mode == 'build':
                self.build(
                    spec_file=self.args.spec_file,
                    release_path=self.args.release_path,
                    version=self.args.version,
                    exclude_patterns=self.args.exclude_patterns
                    , **{k: v for k, v in (opt.split('=', 2) for opt in self.args.pyinstaller_options if '=' in opt)}
                )
                return 0
            elif self.args.mode == 'release':
                self.release(
                    version=self.args.version,
                    approve=self.args.approve,
                    release_path=self.args.release_path,
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
        else:
            if self.args.mode in ('build', 'release'):
                self.l.error('You can not build or Release in released file.')
            else:
                self.l.error('Unknown mode: %s', self.args.mode)
            return 1
        
        self.l.info('PyService Stopped %s', self)
        return 0

    def _run(self):
        # Signal 핸들러 등록
        signal.signal(signal.SIGTERM, self.stop)
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # 메인 서비스 작업 추가
        self.append_task(self._loop, self._service(), 'ServiceWork')
        try:
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))
        except KeyboardInterrupt as i:
            self.l.info('Keyboard Interrupt received. Stopping service...')
        finally:
            # 모든 작업 취소 및 정리
            self.l.info('Cleaning up tasks...')
            for t in self._tasks:
                t.cancel()
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))
        self._loop.close()   

        # 서비스 종료 작업 처리
        try:
            for closer, args in self._closers:
                closer(*args)
        except Exception as e:
            self.l.error('Error during in closer - %s%s: %s', closer.__name__, str(args), e)

    def stop(self, signum=None, frame=None):
        """서비스 중지. signal 핸들러로도 사용 가능"""
        self._sigterm.set()

    async def _service(self):
        self._set_status('Initting')
        try:
            await self.init()
        except asyncio.CancelledError as c:
            self.l.error('Service Cancelled while initting.')
            self.stop()
        except Exception as e:
            self.l.error('== Error occurred while initting. ==')
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
            self.l.error('Service Cancelled while running.')
        except Exception as e:
            self.l.error('== Error occurred while running. ==')
            self.l.error(traceback.format_exc())

        finally:
            self._set_status('Stopping')
            try:
                await self.destroy()
            except Exception as e:
                self.l.error('== Error occurred while destorying. ==')
                self.l.error(traceback.format_exc())
            self._set_status('Stopped')


# == User Defined == 

    async def init(self):
        await asyncio.sleep(0.1)

    @abstractmethod
    async def run(self):
        pass

    async def destroy(self):
        await asyncio.sleep(0.1)


# == Repr ==

    def __repr__(self):
        return '<%s> - %s' % (self.name, self.status)
    
