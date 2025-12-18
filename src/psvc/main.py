import logging
from abc import ABC, abstractmethod
import traceback
import os
import sys
import asyncio, aiofiles
import signal
import configparser
import json
from pathlib import Path

from .comp import Component
from .builder import Builder


_version_conf = 'PSVC\\version'
_default_conf_path = 'psvc.conf'

class Config(Component):
    def __init__(self, svc, config_file, name='Config'):
        super().__init__(svc, name)
        self._config = configparser.ConfigParser()
        if config_file is not None:
            self._config_file = self.svc.path(config_file)
        else:
            self._config_file = self.svc.path(_default_conf_path)
        self._config.read(self._config_file)

    def set_config(self, section: str, key: str, value):
        if section not in self._config:
            self._config.add_section(section)
        self._config.set(section, key, value)
        if self._config_file:
            with open(self._config_file, 'w') as af:
                self._config.write(af)

    def get_config(self, section: str, key: str, default=None):
        if key is None and '\\' in section:
            section, key = section.split('\\', 1)
        try:
            sec = self._config[section]
        except KeyError:
            if default is None or key is None:
                raise KeyError('Section is not exist %s\\' % (section))
            else:
                self.set_config(section, key, default)
                return default
        if key is None:
            return sec
        elif key not in sec:
            if default is None:
                raise KeyError('Config is not exist %s\\%s' % (section, key))
            else:
                self.set_config(section, key, default)
                return default
        return sec[key]
    

class Service(Component, ABC):
    _log_format = '%(asctime)s : %(name)s [%(levelname)s] %(message)s - %(lineno)s'

    def __init__(self, name='Service', root_file=None, config_file=None, level=logging.INFO):
        Component.__init__(self, None, name)
        self._sigterm = asyncio.Event()
        self._loop = None
        self._tasks = []
        self._closers = []
        self._fh = None
        self.status = None
        self.level = level
        
        self.set_root_path(root_file)
        self.set_logger(self.level)
        self.l.info('=======================START=======================')
        self._config_file = config_file
        self._config = Config(self, self._config_file)
        self.version = self.get_config(_version_conf, None, '0.0')

# == Setting == 
    
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

    def append_closer(self, closer, args: list):
        self._closers.append((closer, args))

# == Status ==

    def set_status(self, status: str):
        self.l.info('Status=%s', status)
        self.status = status

    def set_logger(self, level):
        self._fh = logging.FileHandler(self.path(self.name+'.log'))
        self._fh.setLevel(level)
        self._fh.setFormatter(logging.Formatter(Service._log_format))
        logging.basicConfig(level=level, force=True,
                            format=Service._log_format)
        self.l = logging.getLogger(name=self.name)
        self.l.addHandler(self._fh)

    def set_root_path(self, root_file):
        if not os.path.basename(sys.executable).startswith('python'):
            self._root_path = os.path.abspath(os.path.dirname(sys.executable))
        elif root_file:
            self._root_path = os.path.abspath(os.path.dirname(root_file))
        else:
            self._root_path = None

    def path(self, path):
        if os.path.isabs(path) or self._root_path is None:
            return path
        return os.path.join(self._root_path, path)

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

# == Config ==

    def set_config(self, section: str, key: str, value):
        self._config.set_config(section, key, value)

    def get_config(self, section: str, key: str, default=None):
        return self._config.get_config(section, key, default)


# == Running ==

    def _apply_pending_update(self):
        """
        대기 중인 업데이트 적용 (Windows .new 파일 처리)

        재시작 시 .new 파일이 있으면 자동으로 교체합니다.
        Windows 환경에서 실행 중 파일 잠금 문제 해결용.
        """
        if sys.platform != 'win32':
            return  # Linux는 직접 덮어쓰기 사용

        # 현재 실행 파일 디렉토리
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
        # 대기 중인 업데이트 적용 (Windows .new 파일 처리)
        self._apply_pending_update()

        signal.signal(signal.SIGTERM, self.stop)
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self.l.info('PyService Start %s', self)
        self.append_task(self._loop, self._service(), 'ServiceWork')
        try:
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))
        except KeyboardInterrupt as i:
            self.l.info('Stopping by KeyBoardInterrupt')
        finally:
            for t in self._tasks:
                t.cancel()
            self._loop.run_until_complete(asyncio.gather(*self._tasks, return_exceptions=True))
        self._loop.close()

        for closer, args in self._closers:
            closer(*args)

    def stop(self, signum=None, frame=None):
        """서비스 중지. signal 핸들러로도 사용 가능"""
        self._sigterm.set()

    async def _service(self):
        self.set_status('Initting')
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
                self.set_status('Running')
                while not self._sigterm.is_set():
                    await self.run()
        except asyncio.CancelledError as c:
            self.l.error('Service Cancelled while running.')
        except Exception as e:
            self.l.error('== Error occurred while running. ==')
            self.l.error(traceback.format_exc())

        finally:
            self.set_status('Stopping')
            try:
                await self.destroy()
            except Exception as e:
                self.l.error('== Error occurred while destorying. ==')
                self.l.error(traceback.format_exc())
            self.set_status('Stopped')

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
