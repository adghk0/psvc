import logging
import itertools

class Component:
    def __init__(self, svc, name):
        if svc == None:
            self.svc = None
            self.name = name
        else:
            self.svc = svc
            self.name = svc.name+'-'+name
            self.l = logging.getLogger(name=self.name)
            self.l: logging.Logger
            self.svc.append_component(self)
        self._component_index = itertools.count(1)
        self._components = {}

    def append_component(self, component):
        index = next(self._component_index)
        self._components[index] = component

    def delete_component(self, index):
        del(self._components[index])

    def __repr__(self):
        return '<%s>' % (self.name,)
