from threading import Thread

from .log import Level

class PsThread (Thread):
    def __init__(self, service, name, group = None, target = None, args = None, *, daemon = None):
        if args == None:
            super().__init__(group, target, name, daemon=daemon)
        else:
            super().__init__(group, target, name, args, daemon=daemon)
        self.service = service
        self.name = name
        self.service.threads[self.name] = self
        self.service.log(Level.DEBUG, '(%s) makes a new Thread - (%s)' % (self.service.name(), self.name, ))
    
    def start(self):
        self.service.log(Level.DEBUG, '(%s) starts the Thread - (%s)' % (self.service.name(), self.name, ))
        return super().start()
    
    def _delete(self):
        self.service.log(Level.DEBUG, '(%s) stops the Thread - (%s)' % (self.service.name(), self.name, ))
        del(self.service.threads[self.name])
        return super()._delete()