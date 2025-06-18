import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from kjutil import timeout
from time import sleep

@timeout(2)
def test_func():
    sleep(3)
    print('good')

test_func()