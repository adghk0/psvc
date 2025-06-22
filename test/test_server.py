import sys, os
import time
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pyservice import ServerService

if __name__ == '__main__':
    ts = ServerService(os.path.abspath(os.path.join(os.path.dirname(__file__),'test_server.conf')))

    
    while ts.is_ready or ts.is_run:
        pass
