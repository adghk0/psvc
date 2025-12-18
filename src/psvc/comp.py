import logging
import itertools
import weakref

class Component:
    def __init__(self, svc, name, parent=None):
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
        # TODO : 다단계 서비스에서 디버깅을 돕도록 부모 경로를 로그 메시지에 포함하는 계층형 로깅 컨텍스트를 추가한다 @codex
        index = next(self._component_index)
        self._components[index] = component
        component._parent_index = index
        component._parent = self

    def delete_child(self, index):
        # TODO : 비활성 서비스나 부모에 붙으려 할 때 경고/로그를 남겨 고아 컴포넌트가 생기지 않도록 방지 장치를 추가한다 @codex
        if index in self._components:
            del self._components[index]

    def attach(self, parent):
        parent.append_child(self)

    def detach(self):
        """현재 부모로부터 컴포넌트를 분리합니다."""
        if self._parent is not None and self._parent_index is not None:
            self._parent.delete_child(self._parent_index)
            self._parent = None
            self._parent_index = None
            
    def __repr__(self):
        if self._parent is None:
            return '<%s>' % (self.name,)
        else:
            return '%s/<%s>' % (self._parent, self.name)
