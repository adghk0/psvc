"""
서비스 관리 모듈

명령행 인자 파싱, 작업 관리, OS 서비스 설치/제거 기능을 제공합니다.
"""

import os
import sys
import argparse
import asyncio
import subprocess
from pathlib import Path
from collections.abc import Callable
from typing import Any


def parse_args(argv=None):
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
    p_run.add_argument('--install', action='store_true', help='Install as OS service', default=False)
    p_run.add_argument('--uninstall', action='store_true', help='Uninstall OS service', default=False)

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


class TaskManager:
    """
    비동기 작업 관리 클래스
    """

    def __init__(self, logger):
        """
        TaskManager 초기화

        Args:
            logger: 로거 인스턴스
        """
        self.l = logger
        self._tasks = []
        self._closers = []

    def append_task(self, loop: asyncio.AbstractEventLoop, coro, name):
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

    def get_tasks(self):
        """태스크 리스트 반환"""
        return self._tasks

    def get_closers(self):
        """Closer 리스트 반환"""
        return self._closers


def service_install(service_name: str, root_path: str, logger) -> None:
    """
    현재 실행 파일을 OS 서비스에 등록

    Windows  : sc.exe 사용
    Linux    : systemd unit 생성 (/etc/systemd/system)
    기타 OS : 미지원 (로그만 출력)

    Args:
        service_name: 서비스 이름
        root_path: 서비스 루트 경로
        logger: 로거 인스턴스
    """
    exe = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
    exe = os.path.abspath(exe)

    logger.info('서비스 설치 시도: name=%s, exe=%s', service_name, exe)

    system = sys.platform
    try:
        if system == 'win32':
            # sc create "Name" binPath= "c:\path\psvc.exe run" start= auto
            cmd = [
                'sc', 'create', service_name,
                'binPath=', f'"{exe}" run',
                'start=', 'auto'
            ]
            logger.debug('Windows service install command: %s', cmd)
            subprocess.check_call(cmd)

        elif system.startswith('linux'):
            unit_name = f'{service_name}.service'
            unit_path = Path('/etc/systemd/system') / unit_name

            unit_text = f"""[Unit]
Description={service_name} (PyService)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart={exe} run
WorkingDirectory={root_path}
Restart=always
RestartSec=5
User={os.getenv("USER", "root")}
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
"""

            logger.debug('systemd unit write: %s', unit_path)
            with open(unit_path, 'w', encoding='utf-8') as f:
                f.write(unit_text)

            subprocess.check_call(['systemctl', 'daemon-reload'])
            subprocess.check_call(['systemctl', 'enable', '--now', unit_name])

        else:
            logger.error('현재 플랫폼에서는 service install이 지원되지 않습니다: %s', system)
            return

        logger.info('서비스 설치 완료: %s', service_name)

    except PermissionError:
        logger.error('서비스 설치 실패: 권한 부족 (관리자/루트 권한 필요)')
    except subprocess.CalledProcessError as e:
        logger.error('서비스 설치 실패 (명령 오류): %s', e)
    except Exception as e:
        logger.error('서비스 설치 중 예외 발생: %s', e)


def service_uninstall(service_name: str, logger) -> None:
    """
    OS 서비스에서 제거

    Args:
        service_name: 서비스 이름
        logger: 로거 인스턴스
    """
    logger.info('서비스 제거 시도: name=%s', service_name)

    system = sys.platform
    try:
        if system == 'win32':
            cmd = ['sc', 'delete', service_name]
            logger.debug('Windows service delete command: %s', cmd)
            subprocess.check_call(cmd)

        elif system.startswith('linux'):
            unit_name = f'{service_name}.service'
            unit_path = Path('/etc/systemd/system') / unit_name

            # disable & stop
            subprocess.call(['systemctl', 'disable', '--now', unit_name])
            if unit_path.exists():
                unit_path.unlink()
                logger.info('systemd unit 파일 삭제: %s', unit_path)

            subprocess.check_call(['systemctl', 'daemon-reload'])

        else:
            logger.error('현재 플랫폼에서는 service uninstall이 지원되지 않습니다: %s', system)
            return

        logger.info('서비스 제거 완료: %s', service_name)

    except PermissionError:
        logger.error('서비스 제거 실패: 권한 부족 (관리자/루트 권한 필요)')
    except subprocess.CalledProcessError as e:
        logger.error('서비스 제거 실패 (명령 오류): %s', e)
    except Exception as e:
        logger.error('서비스 제거 중 예외 발생: %s', e)
