import sys, os
import time
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pyservice import Service


class TestService (Service):
    def init(self):
        self.cnt = 0
        self.descnt = 0
    
    def name(self):
        return 'TestService'
        
    def run(self):
        print(self.cnt)
        self.cnt += 1
        time.sleep(1)
    
    def destory(self):
        if self.descnt < 3:
            print('descnt', self.descnt)
            self.descnt += 1
            return True
        else:
            return None



if __name__ == '__main__':
    ts = TestService(os.path.abspath(os.path.join(os.path.dirname(__file__),'test_ps.conf')))

    
    while ts.is_ready or ts.is_run:
        pass
