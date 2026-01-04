import asyncio
import json
import inspect
from typing import TYPE_CHECKING

from .component import Component
from .network import EndPoint

if TYPE_CHECKING:
    from .main import Service

def command(_func=None, *, ident=None):
    """
    사용 형태:

        @command
        async def ping(cmdr, body, serial):
            ...

        @command(ident="PING")
        async def ping(cmdr, body, serial):
            ...

        # 인스턴스 메서드로도 사용 가능
        class MyComponent(Component):
            @command(ident="test")
            async def my_cmd(self, cmdr, body, serial):
                ...

    강제 조건(@command 사용 시):
      - async 함수이어야 함
      - 일반 함수: 인자 3개 (cmdr, body, serial)
      - 인스턴스 메서드: 인자 4개 (self, cmdr, body, serial)
    """
    def decorator(func):
        sig = inspect.signature(func)
        params = list(sig.parameters.values())

        # 인스턴스 메서드 여부 확인 (첫 파라미터가 'self'인지)
        is_method = len(params) > 0 and params[0].name == 'self'

        # 파라미터 개수 검증
        if is_method:
            # 인스턴스 메서드: self + (cmdr, body, serial) = 4개
            if len(params) != 4:
                raise TypeError(
                    f"Command method '{func.__name__}' must have 4 parameters: "
                    "(self, cmdr, body, serial)"
                )
        else:
            # 일반 함수: (cmdr, body, serial) = 3개
            if len(params) != 3:
                raise TypeError(
                    f"Command function '{func.__name__}' must have 3 parameters: "
                    "(cmdr, body, serial)"
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
    """
    명령 기반 통신 관리자

    Socket 위에서 JSON 명령어 기반 통신을 제공합니다.
    """

    def __init__(self, svc: 'Service', name='Commander', parent=None):
        """
        Commander 초기화

        Args:
            svc: 서비스 인스턴스
            name: 컴포넌트 이름
            parent: 부모 컴포넌트
        """
        super().__init__(svc, name, parent)
        
        self._endpoint = EndPoint(self.svc, name=name+'-EndPoint', parent=self)

        self._en = json.JSONEncoder()
        self._de = json.JSONDecoder()
        self._cmds = {}
        self._handle_lock = asyncio.Lock()
        self._call_stack = []
        self._task = self.svc.append_task(asyncio.get_running_loop(), self._receive(), name+'-Recv')
        self.l.debug('새 Commander 연결됨 (Endpoint 기반)')

    def endpoint(self):
        """
        내부 Endpoint 인스턴스 반환

        Returns:
            EndPoint: 내부 Endpoint 인스턴스
        """
        return self._endpoint

    def sock(self):
        """
        내부 Endpoint 인스턴스 반환 (Backwards compatibility)

        Note:
            이 메서드는 하위 호환성을 위해 제공됩니다.
            새 코드에서는 endpoint() 메서드를 사용하세요.

        Returns:
            EndPoint: 내부 Endpoint 인스턴스
        """
        return self._endpoint

    # == Setting ==

    async def bind(self, addr: str, port: int) -> int:
        """
        서버로 바인딩

        Args:
            addr: 바인딩할 주소
            port: 포트 번호

        Returns:
            int: 서버 소켓 serial 번호
        """
        return await self._endpoint.bind(addr, port)

    async def connect(self, addr: str, port: int) -> int:
        """
        서버에 연결하고 serial 반환

        Args:
            addr: 서버 주소
            port: 포트 번호

        Returns:
            int: 데이터 소켓 serial 번호
        """
        return await self._endpoint.connect(addr, port)

    def set_command(self, *cmd_funcs, ident=None):
        """
        명령 함수 등록

        Args:
            *cmd_funcs: @command로 장식된 async 함수들 또는 동일한 형식의 async 함수들
            ident: 명령 식별자 (단일 함수 등록 시에만 사용 가능)
                   None이면 @command(ident="...") 값을 우선 사용하고,
                   없으면 함수명을 ident로 사용

        Returns:
            str | tuple: 함수 1개 등록 시 ident (str), 여러 개 등록 시 ident 튜플

        Raises:
            ValueError: 함수가 하나도 없거나, 여러 함수에 ident를 지정했을 때
            TypeError: 함수가 callable이 아니거나, 파라미터 개수가 맞지 않을 때
        """
        if not cmd_funcs:
            raise ValueError('최소 하나의 명령 함수가 필요합니다.')
        
        if len(cmd_funcs) > 1 and ident is not None:
            raise ValueError('ident는 단일 명령 함수에만 사용할 수 있습니다.')

        registered = []
        for func in cmd_funcs:
            if not callable(func):
                raise TypeError('명령은 callable이어야 합니다.')

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
                raise ValueError('Ident가 충돌합니다. (%s)' % (cur_ident, ))

            # 핸들러 생성
            # 바인딩된 메서드는 self가 자동 전달되므로 (cmdr, body, serial)만 전달
            # 일반 함수는 Commander 인스턴스를 cmdr로 전달
            async def handler(body, serial, _func=func):
                try:
                    return await _func(self, body, serial)
                except Exception as e:
                    raise

            self._cmds[cur_ident] = handler
            registered.append(cur_ident)

        return registered[0] if len(registered) == 1 else tuple(registered)
    
    @property
    def call_stack(self):
        """
        현재 호출 스택

        Returns:
            tuple: 호출 중인 명령 ident의 튜플
        """
        return tuple(self._call_stack)
    

    # == Execute ==

    async def _execute(self, ident, body, serial):
        """
        명령 실행 (내부용)

        Args:
            ident: 명령 식별자
            body: 명령 본문
            serial: 소켓 serial 번호

        Raises:
            KeyError: 명령을 찾을 수 없을 때
        """
        self._call_stack.append(ident)
        try:
            handler = self._cmds[ident]
        except KeyError:
            self._call_stack.pop()
            raise KeyError('명령을 찾을 수 없음: %s' % (ident, ))

        try:
            return await handler(body, serial)
        finally:
            self._call_stack.pop()

    async def call(self, ident, body, serial):
        """
        명령 호출

        Args:
            ident: 명령 식별자
            body: 명령 본문
            serial: 소켓 serial 번호

        Returns:
            명령 핸들러의 반환값
        """
        if not self._call_stack:
            async with self._handle_lock:
                return await self._execute(ident, body, serial)
        else:
            return await self._execute(ident, body, serial)

    async def call_header(self, cmd_header, serial):
        """
        명령 헤더로부터 명령 호출

        Args:
            cmd_header: 명령 헤더 딕셔너리 (_ident, _body 포함)
            serial: 소켓 serial 번호

        Returns:
            명령 핸들러의 반환값
        """
        ident = cmd_header['_ident']
        body = cmd_header['_body']
        return await self.call(ident, body, serial)
    

    # == Communication ==

    async def send_command(self, cmd_ident, body, serial):
        """
        명령 전송

        Args:
            cmd_ident: 명령 식별자
            body: 명령 본문
            serial: 소켓 serial 번호
        """
        cmd_header = {
            '_ident': cmd_ident,
            '_body': body,
        }
        await self._endpoint.send_str(self._en.encode(cmd_header), serial)

    async def _receive(self):
        """
        명령 수신 루프 (내부용)

        Endpoint로부터 명령을 수신하고 처리합니다.
        """
        try:
            while True:
                serial, msg = await self._endpoint.recv_any()
                msg = msg.decode()
                cmd_header = self._de.decode(msg)
                await self.call_header(cmd_header, serial)
        except asyncio.CancelledError:
            pass
        finally:
            await self._endpoint.close_all()
