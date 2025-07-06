import os
import datetime

from .file import ps_path, mkdir


class Level:
    SYSTEM = 0
    ERROR = 1
    WARN = 2
    INFO = 3
    DEBUG = 4
    INT = [
        'SYSTEM',
        'ERROR',
        'WARN',
        'INFO',
        'DEBUG',
    ]


class Logger:    
    def __init__(self, service, dir, level=Level.DEBUG, time_format='%Y-%m-%d %H:%M:%S.%f'):
        self.service = service
        self.log_file = ps_path(self.service, self.service.log_path, self.service.name+'.txt')
        self.level = level
        self.dir = dir
        self.time_format = time_format

    def log_raw(self, msg, file):
        mkdir(os.path.dirname(file))
        with open(file, 'a') as f:
            f.write(msg)
        print(msg, end='')

    def log(self, level: int , msg: str, file=None):
        time = datetime.datetime.now().strftime(self.time_format)
        if level <= self.level:
            if file == None:
                file = self.log_file
            else:
                file = ps_path(self.service, self.service.log_path, file+'.txt')
            self.log_raw('%s [%7s] %10s %s\n' % (time, Level.INT[level], self.service.name, msg), file)
