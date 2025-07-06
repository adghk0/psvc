
import sys, time

from pyservice import Service, ServerService

config_file = './server.conf'

if __name__ == '__main__':
    if len(sys.argv) == 1 or sys.argv[1] == 'PyService':
        s = Service(__file__, config_file)
    elif sys.argv[1] == 'PsServer':
        s = ServerService(__file__, config_file, 'PsServer')

    while s.status != 'Dead':
            time.sleep(0.1)
