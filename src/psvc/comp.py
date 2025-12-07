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

        if parent is None and self != self.svc:
            self.svc.append_child(self)
        else:
            self._parent.append_child(self)

    def append_child(self, component):
        index = next(self._component_index)
        self._components[index] = component
        component._parent_index = index
        component._parent = self

    def delete_child(self, index):
        if index in self._components:
            del self._components[index]

    def attach(self, parent):
        parent.append_child(self)

    def detach(self):
        if self._parent is not None and self._parent_index is not None:
            self._parent.delete_child(self._parent_index)
            self._parent = None
            self._parent_index = None

    def __repr__(self):
        if self._parent is None:
            return '<%s>' % (self.name,)
        else:
            return '%s/<%s>' % (self._parent, self.name)
