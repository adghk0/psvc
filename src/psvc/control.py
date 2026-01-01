# control.py
# 서비스의 중앙 제어를 담당하는 모듈

from psvc.component import Component

class Controller(Component):
    def __init__(self, svc, commander, name='Controller', parent=None):
        super().__init__(svc, name, parent)
        self.commander = commander
        