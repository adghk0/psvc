"""아키텍처 리스크 완화 변경 검증 테스트"""

import json
import logging
import subprocess
import sys
from types import SimpleNamespace

from psvc.component import Component
from psvc.main import Service
from psvc.manage import service_install


class DummyService(Service):
    """테스트용 서비스"""

    async def run(self):
        pass


class HookTrackingComponent(Component):
    """attach/detach 생명주기 훅 호출 추적용 컴포넌트"""

    def __init__(self, svc, name='HookTrackingComponent', parent=None):
        self.attach_count = 0
        self.detach_count = 0
        self.last_attach_parent = None
        self.last_detach_parent = None
        super().__init__(svc, name, parent=parent)

    def on_attach(self, parent):
        self.attach_count += 1
        self.last_attach_parent = parent

    def on_detach(self, parent):
        self.detach_count += 1
        self.last_detach_parent = parent


def _make_args(**overrides):
    defaults = {
        'mode': 'run',
        'log_level': None,
        'config_file': None,
        'spec_file': None,
        'release_path': None,
        'exclude_patterns': None,
        'version': '1.0.0',
        'pyinstaller_options': None,
        'approve': False,
        'release_notes': None,
        'rollback_target': None,
        'root_file': None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_service_uses_configured_log_level(temp_dir):
    """설정 파일의 log_level이 서비스 초기화에 반영되어야 한다."""
    config_file = temp_dir / 'test.json'
    config_data = {
        'PSVC': {
            'version': '1.0.0',
            'log_level': 'DEBUG'
        }
    }
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False)

    service = DummyService('TestService', str(temp_dir / '__init__.py'), str(config_file))
    assert service.level == 'DEBUG'


def test_component_lifecycle_hooks_are_called(temp_dir):
    """컴포넌트 재부착 시 detach/attach 훅이 순차 호출되어야 한다."""
    service = DummyService('TestService', str(temp_dir / '__init__.py'))
    parent = Component(service, 'Parent')
    child = HookTrackingComponent(service, 'Child')

    assert child.attach_count == 1
    assert child._parent is service

    child.attach(parent)

    assert child.detach_count == 1
    assert child.last_detach_parent is service
    assert child.attach_count == 2
    assert child.last_attach_parent is parent
    assert child._parent is parent


def test_component_detach_clears_parent_and_calls_hook(temp_dir):
    """명시적 detach 호출 시 부모 참조 정리와 detach 훅 호출이 보장되어야 한다."""
    service = DummyService('TestService', str(temp_dir / '__init__.py'))
    child = HookTrackingComponent(service, 'Child')

    assert child._parent is service
    assert child.attach_count == 1
    assert child.detach_count == 0

    child.detach()

    assert child._parent is None
    assert child._parent_index is None
    assert child.detach_count == 1
    assert child.last_detach_parent is service


def test_build_mode_parses_pyinstaller_options_safely(temp_dir):
    """build 모드에서 pyinstaller_options는 key=value 항목만 안전하게 파싱되어야 한다."""
    service = DummyService('TestService', str(temp_dir / '__init__.py'))
    service.args = _make_args(
        mode='build',
        version='1.2.3',
        spec_file='service.spec',
        release_path='out/releases',
        exclude_patterns=['*.tmp'],
        pyinstaller_options=['clean=true', 'name=svc=v2', 'invalid', 123, '=skip'],
    )

    captured = {}

    def fake_build(**kwargs):
        captured.update(kwargs)

    service.build = fake_build
    assert service._run_build_mode() == 0

    assert captured['spec_file'] == 'service.spec'
    assert captured['release_path'] == 'out/releases'
    assert captured['version'] == '1.2.3'
    assert captured['exclude_patterns'] == ['*.tmp']
    assert captured['clean'] == 'true'
    assert captured['name'] == 'svc=v2'
    assert '' not in captured


def test_service_on_dispatches_each_mode_to_dedicated_runner(temp_dir, monkeypatch):
    """on()은 mode별 전용 실행기로 위임되어야 한다."""
    service = DummyService('TestService', str(temp_dir / '__init__.py'))

    calls = []

    def fake_build_mode():
        calls.append('build')
        return 0

    def fake_release_mode():
        calls.append('release')
        return 0

    def fake_apply_mode():
        calls.append('apply')
        return 0

    def fake_service_mode():
        calls.append('run')
        return 0

    monkeypatch.setattr(service, '_run_build_mode', fake_build_mode)
    monkeypatch.setattr(service, '_run_release_mode', fake_release_mode)
    monkeypatch.setattr(service, '_run_apply_mode', fake_apply_mode)
    monkeypatch.setattr(service, '_run_service_mode', fake_service_mode)

    for mode in ('build', 'release', 'apply', 'run'):
        service.args = _make_args(mode=mode)
        assert service.on() == 0

    assert calls == ['build', 'release', 'apply', 'run']


def test_service_on_blocks_build_or_release_in_frozen_mode(temp_dir, monkeypatch):
    """frozen 실행 파일에서는 build/release 모드를 차단해야 한다."""
    service = DummyService('TestService', str(temp_dir / '__init__.py'))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)

    service.args = _make_args(mode='build')
    assert service.on() == 2

    service.args = _make_args(mode='release')
    assert service.on() == 2


def test_service_on_unknown_mode_returns_error(temp_dir):
    """알 수 없는 모드는 종료 코드 1을 반환해야 한다."""
    service = DummyService('TestService', str(temp_dir / '__init__.py'))
    service.args = _make_args(mode='unknown-mode')
    assert service.on() == 1


def test_windows_service_install_uses_argv_call(monkeypatch):
    """Windows 서비스 설치는 shell 문자열이 아닌 argv 리스트로 호출되어야 한다."""
    captured = {}

    def fake_check_call(cmd, *args, **kwargs):
        captured['cmd'] = cmd
        captured['kwargs'] = kwargs
        return 0

    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(subprocess, 'check_call', fake_check_call)

    service_install('TestService', '.', logging.getLogger('test'))

    assert isinstance(captured['cmd'], list)
    assert captured['cmd'][:3] == ['sc', 'create', 'TestService']
    assert 'shell' not in captured['kwargs']
