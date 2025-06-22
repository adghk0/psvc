import time

from pyservice import ServerService

if __name__ == '__main__':
    ps_server = ServerService(__file__, './server.conf')
    ps_server.command('start')
    
    while ps_server.is_alive:
        time.sleep(0.1)