import logging
import itertools
import weakref
import os
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from .main import Service

class Component:
    """
    컴포넌트 기본 클래스

    Service와 다른 컴포넌트들의 기반이 되는 계층형 컴포넌트 시스템입니다.
    부모-자식 관계를 통해 컴포넌트 트리를 구성합니다.
    """
    # Logger 설정 경로
    _log_conf_path = 'PSVC\\log_format'
    # Logger 기본 포맷
    _default_log_format = '%(asctime)s : %(name)s [%(levelname)s] %(message)s - %(lineno)s'
    # log level 매핑
    _log_levels = {
        'CRITICAL': logging.CRITICAL,
        'ERROR': logging.ERROR,
        'WARNING': logging.WARNING,
        'INFO': logging.INFO,
        'DEBUG': logging.DEBUG,
        'NOTSET': logging.NOTSET,
    }

    def __init__(self, svc: 'Service', name, parent=None):
        """
        컴포넌트 초기화

        Args:
            svc: 서비스 인스턴스 (None이면 독립 컴포넌트)
            name: 컴포넌트 이름
            parent: 부모 컴포넌트 (None이면 svc가 부모)
        """
        if svc is None:
            self.svc = None
            self.name = name
            self._root_path = None
        else:
            self.svc = svc
            self.name = svc.name+'-'+name
            self._root_path = getattr(svc, '_root_path', None)
            # svc.level이 있으면 사용, 없으면 INFO 사용
            level = getattr(svc, 'level', 'INFO')
            self.make_logger(level)
        
        self._component_index = itertools.count(1)
        self._components = weakref.WeakValueDictionary()
        self._parent_index = None
        self._parent = None

        # TODO : 컴포넌트 생명주기 훅(on_attach/on_detach)을 도입해 자식이 자원을 안전하게 해제할 수 있도록 한다 @codex
        if self.svc is None:
            return
        owner = parent if parent is not None else self.svc
        # owner가 append_child 메서드를 가지고 있으면 자식으로 추가
        if hasattr(owner, 'append_child'):
            owner.append_child(self)

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

    # == Logging Methods ==    
    @staticmethod
    def log_level(level) -> int:
        """
        로그 레벨 변환

        Returns:
            int: 로그 레벨 (logging 모듈 상수)
        """
        if type(level) == str:
            d_level = Component._log_levels[level] if level in Component._log_levels else \
                int(level) if level.isdigit() else None
            if d_level is None:
                d_level = logging.INFO
            return d_level
        elif type(level) == int:
            return level
        else:
            raise ValueError('로그 레벨이 올바르지 않습니다.')
    
    def make_logger(self, level) -> logging.Logger:
        """
        로거 생성

        Args:
            level: 로그 레벨

        Returns:
            logging.Logger: 생성된 로거 인스턴스
        """
        if self.svc is None:
            log_format = self.get_config(Component._log_conf_path, None, Component._default_log_format)
            logging.basicConfig(level=level, force=True, format=log_format)
            self.file_handler = logging.FileHandler(self.path(self.name+'.log'))
            self.file_handler.setLevel(level)
            self.file_handler.setFormatter(logging.Formatter(log_format))
        else:
            # Service의 file_handler가 아직 없으면 나중에 추가
            self.file_handler = getattr(self.svc, 'file_handler', None)

        level = Component.log_level(level)
        logger = logging.getLogger(name=self.name)

        # file_handler가 있으면 추가
        if self.file_handler:
            logger.addHandler(self.file_handler)

        self.l = logger

        return logger

    # == Config Proxy Methods ==
    def set_config(self, section: str, key: str, value):
        if self.svc is not None:
            self.svc.set_config(section, key, value)
        
    def get_config(self, section: str, key: str, default=None):
        if self.svc is not None:
            return self.svc.get_config(section, key, default)
        return default
    
    # == Component Hierarchy Management ===
    def append_child(self, component):
        """
        자식 컴포넌트 추가

        자식 컴포넌트를 약한 참조로 관리하여 메모리 누수를 방지합니다.

        Args:
            component: 추가할 자식 컴포넌트
        """
        # TODO : 다단계 서비스에서 디버깅을 돕도록 부모 경로를 로그 메시지에 포함하는 계층형 로깅 컨텍스트를 추가한다 @codex
        if component._parent is self:
            return

        if component._parent is not None:
            component.detach()

        index = next(self._component_index)
        self._components[index] = component
        component._parent_index = index
        component._parent = self
        component.on_attach(self)

    def delete_child(self, index):
        """
        자식 컴포넌트 제거

        Args:
            index: 제거할 자식 컴포넌트의 인덱스
        """
        # TODO : 비활성 서비스나 부모에 붙으려 할 때 경고/로그를 남겨 고아 컴포넌트가 생기지 않도록 방지 장치를 추가한다 @codex
        component = self._components.get(index)
        if component is None:
            return

        del self._components[index]
        component._parent = None
        component._parent_index = None
        component.on_detach(self)

    def attach(self, parent):
        """
        부모 컴포넌트에 연결

        Args:
            parent: 연결할 부모 컴포넌트
        """
        parent.append_child(self)

    def detach(self):
        """
        부모 컴포넌트로부터 분리

        현재 부모로부터 컴포넌트를 분리하고 부모 참조를 제거합니다.
        """
        if self._parent is not None and self._parent_index is not None:
            self._parent.delete_child(self._parent_index)

    def on_attach(self, parent):
        """
        부모에 attach될 때 호출되는 생명주기 훅

        Args:
            parent: attach된 부모 컴포넌트
        """
        pass

    def on_detach(self, parent):
        """
        부모에서 detach될 때 호출되는 생명주기 훅

        Args:
            parent: detach되기 전 부모 컴포넌트
        """
        pass
            
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

    def __repr__(self):
        """
        컴포넌트 문자열 표현

        계층 구조를 반영한 경로 형식으로 표현합니다.

        Returns:
            str: 컴포넌트 경로 문자열 (예: "Parent/<Child>")
        """
        cls = self.__class__.__name__
        if self.name == cls:
            display_name = f'<{cls}>'
        else:
            display_name = f'<{cls}:{self.name}>'

        if self._parent is None:
            return display_name
        else:
            return '%s/%s' % (self._parent, display_name)
