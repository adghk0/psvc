import logging
import itertools
import weakref

class Component:
    """
    컴포넌트 기본 클래스

    Service와 다른 컴포넌트들의 기반이 되는 계층형 컴포넌트 시스템입니다.
    부모-자식 관계를 통해 컴포넌트 트리를 구성합니다.
    """

    def __init__(self, svc, name, parent=None):
        """
        컴포넌트 초기화

        Args:
            svc: 서비스 인스턴스 (None이면 독립 컴포넌트)
            name: 컴포넌트 이름
            parent: 부모 컴포넌트 (None이면 svc가 부모)
        """
        if svc == None:
            self.svc = None
            self.name = name
        else:
            self.svc = svc
            self.name = svc.name+'-'+name
            self.l = logging.getLogger(name=self.name)
            self.l: logging.Logger
            if self.svc._fh:
                self.l.addHandler(self.svc._fh)
        self._component_index = itertools.count(1)
        self._components = weakref.WeakValueDictionary()
        self._parent_index = None
        self._parent = None

        # TODO : 컴포넌트 생명주기 훅(on_attach/on_detach)을 도입해 자식이 자원을 안전하게 해제할 수 있도록 한다 @codex
        if self.svc is None:
            return
        owner = parent if parent is not None else self.svc
        owner.append_child(self)

    def append_child(self, component):
        """
        자식 컴포넌트 추가

        자식 컴포넌트를 약한 참조로 관리하여 메모리 누수를 방지합니다.

        Args:
            component: 추가할 자식 컴포넌트
        """
        # TODO : 다단계 서비스에서 디버깅을 돕도록 부모 경로를 로그 메시지에 포함하는 계층형 로깅 컨텍스트를 추가한다 @codex
        index = next(self._component_index)
        self._components[index] = component
        component._parent_index = index
        component._parent = self

    def delete_child(self, index):
        """
        자식 컴포넌트 제거

        Args:
            index: 제거할 자식 컴포넌트의 인덱스
        """
        # TODO : 비활성 서비스나 부모에 붙으려 할 때 경고/로그를 남겨 고아 컴포넌트가 생기지 않도록 방지 장치를 추가한다 @codex
        if index in self._components:
            del self._components[index]

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
            self._parent = None
            self._parent_index = None
            
    def __repr__(self):
        """
        컴포넌트 문자열 표현

        계층 구조를 반영한 경로 형식으로 표현합니다.

        Returns:
            str: 컴포넌트 경로 문자열 (예: "Parent/<Child>")
        """
        if self._parent is None:
            return '<%s>' % (self.name,)
        else:
            return '%s/<%s>' % (self._parent, self.name)
