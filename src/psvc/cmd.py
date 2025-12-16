import asyncio
import json
import inspect

from .comp import Component
from .main import Service
from .network import Socket

def command(_func=None, *, ident=None):
    """
    사용 형태:

        @command
        async def ping(cmdr, body, cid):
            ...

        @command(ident="PING")
        async def ping(cmdr, body, cid):
            ...

        # 인스턴스 메서드로도 사용 가능
        class MyComponent(Component):
            @command(ident="test")
            async def my_cmd(self, cmdr, body, cid):
                ...

    강제 조건(@command 사용 시):
      - async 함수이어야 함
      - 일반 함수: 인자 3개 (cmdr, body, cid)
      - 인스턴스 메서드: 인자 4개 (self, cmdr, body, cid)
    """
    def decorator(func):
        sig = inspect.signature(func)
        params = list(sig.parameters.values())

        # 인스턴스 메서드 여부 확인 (첫 파라미터가 'self'인지)
        is_method = len(params) > 0 and params[0].name == 'self'

        # 파라미터 개수 검증
        if is_method:
            # 인스턴스 메서드: self + (cmdr, body, cid) = 4개
            if len(params) != 4:
                raise TypeError(
                    f"Command method '{func.__name__}' must have 4 parameters: "
                    "(self, cmdr, body, cid)"
                )
        else:
            # 일반 함수: (cmdr, body, cid) = 3개
            if len(params) != 3:
                raise TypeError(
                    f"Command function '{func.__name__}' must have 3 parameters: "
                    "(cmdr, body, cid)"
                )

        # async 함수 강제
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"Command function '{func.__name__}' must be async "
                "(use 'async def')."
            )

        # Commander.set_command에서 인식할 메타데이터
        setattr(func, "_psvc_command", True)
        setattr(func, "_psvc_ident", ident)
        setattr(func, "_psvc_is_method", is_method)
        return func

    # @command  혹은  @command(ident="...") 둘 다 지원
    if _func is None:
        return decorator
    return decorator(_func)


class Commander(Component):
    def __init__(self, svc: Service, name='Commander', parent=None):
        super().__init__(svc, name, parent)
        self._sock = Socket(self.svc, name+'-Sock', parent=self)
        self._en = json.JSONEncoder()
        self._de = json.JSONDecoder()
        self._cmds = {}
        self._handle_lock = asyncio.Lock()
        self._call_stack = []
        self._task = self.svc.append_task(asyncio.get_running_loop(), self._receive(), name+'-Res')
        self.l.debug('new Commander attached')

    def sock(self):
        return self._sock

    # == Setting ==

    async def bind(self, addr: str, port: int):
        await self._sock.bind(addr, port)

    async def connect(self, addr: str, port: int):
        """서버에 연결하고 cid 반환"""
        return await self._sock.connect(addr, port)

    def set_command(self, *cmd_funcs, ident=None):
        """
        cmd_funcs:
            - @command 로 장식된 async 함수들
            - 또는 동일한 형식의 async 함수들

        ident:
            - 단일 함수 등록 시에만 사용 가능
            - None 이면:
                - @command(ident="...") 값을 우선 사용
                - 없으면 함수명을 ident로 사용

        return:
            - 함수 1개 등록: ident (str)
            - 함수 여러 개 등록: ident 튜플 (tuple[str, ...])
        """
        if not cmd_funcs:
            raise ValueError('At least one command function is required.')
        
        if len(cmd_funcs) > 1 and ident is not None:
            raise ValueError('ident can be used only with a single command function.')

        registered = []
        for func in cmd_funcs:
            if not callable(func):
                raise TypeError('Command must be callable.')

            # 바인딩된 메서드(bound method)인지 확인
            is_bound_method = inspect.ismethod(func)

            sig = inspect.signature(func)
            params = list(sig.parameters.values())

            # 파라미터 개수 검증
            # 바인딩된 메서드는 self가 이미 제외된 상태로 시그니처에 나타남
            expected_params = 3
            if not is_bound_method and len(params) > 0 and params[0].name == 'self':
                # 언바운딩 메서드 (데코레이터 시점)
                expected_params = 4

            if len(params) != expected_params:
                raise TypeError(
                    f"Command function '{func.__name__}' must have {expected_params} parameters, "
                    f"got {len(params)}"
                )

            if not inspect.iscoroutinefunction(func):
                raise TypeError(
                    f"Command function '{func.__name__}' must be async "
                    "(use 'async def')."
                )

            # ident 결정
            if ident is not None:
                cur_ident = ident
            else:
                dec_ident = getattr(func, "_psvc_ident", None)
                if dec_ident:
                    cur_ident = dec_ident
                else:
                    cur_ident = getattr(func, '__name__', repr(func))

            if cur_ident in self._cmds:
                raise ValueError('Ident is collided. (%s)' % (cur_ident, ))

            # 핸들러 생성
            # 바인딩된 메서드는 self가 자동 전달되므로 (cmdr, body, cid)만 전달
            # 일반 함수는 Commander 인스턴스를 cmdr로 전달
            async def handler(body, cid, _func=func):
                try:
                    return await _func(self, body, cid)
                except Exception as e:
                    raise

            self._cmds[cur_ident] = handler
            registered.append(cur_ident)

        return registered[0] if len(registered) == 1 else tuple(registered)
    
    @property
    def call_stack(self):
        return tuple(self._call_stack)
    

    # == Execute ==

    async def _execute(self, ident, body, cid):
        self._call_stack.append(ident)
        try:
            handler = self._cmds[ident]
        except KeyError:
            self._call_stack.pop()
            raise KeyError('Command not found: %s' % (ident, ))
        
        try:
            return await handler(body, cid)
        finally:
            self._call_stack.pop()

    async def call(self, ident, body, cid):
        if not self._call_stack:
            async with self._handle_lock:
                return await self._execute(ident, body, cid)
        else:
            return await self._execute(ident, body, cid)
    
    async def call_header(self, cmd_header, cid):
        ident = cmd_header['_ident']
        body = cmd_header['_body']
        return await self.call(ident, body, cid)
    

    # == Communication ==

    async def send_command(self, cmd_ident, body, cid):
        cmd_header = {
            '_ident': cmd_ident,
            '_body': body,
        }
        await self._sock.send_str(self._en.encode(cmd_header), cid)
       
    async def _receive(self):
        try:
            while True:
                cid, msg = await self._sock.recv()
                msg = msg.decode()
                cmd_header = self._de.decode(msg)
                await self.call_header(cmd_header, cid)
        except asyncio.CancelledError:
            pass
        finally:
            await self._sock.detach()
