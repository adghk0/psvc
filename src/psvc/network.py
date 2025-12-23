import os
import asyncio
import aiofiles
import itertools
import contextlib
import struct
from typing import Tuple, TYPE_CHECKING

from .component import Component

if TYPE_CHECKING:
    from .main import Service


class Socket(Component):
    """
    비동기 소켓 통신 컴포넌트

    TCP 소켓 기반 바이너리 통신을 제공합니다.
    """
    _max_size = 64 * 1024

    def __init__(self, svc: 'Service', name='Socket', parent=None, callback=None, callback_end=None):
        """
        Socket 초기화

        Args:
            svc: 서비스 인스턴스
            name: 컴포넌트 이름
            parent: 부모 컴포넌트
            callback: 연결 시작 시 호출될 콜백
            callback_end: 연결 종료 시 호출될 콜백
        """
        super().__init__(svc, name, parent)
        self._gen = itertools.count(1)
        self._conns = {}
        self._recvs = {}
        self._data_available = asyncio.Event()
        self._handle_task = None
        self._client_cid = None  # 클라이언트 모드에서 사용할 cid
        self.callback = callback
        self.callback_end = callback_end
        self.l.debug('새 Socket 연결됨')
               
    async def bind(self, addr:str, port:int):
        """
        서버로 바인딩

        Args:
            addr: 바인딩할 주소
            port: 포트 번호
        """
        self.server = await asyncio.start_server(self._handler, host=addr, port=port)
        addrs = ", ".join(str(sock.getsockname()) for sock in self.server.sockets)
        self.l.debug('%s에서 서비스 중', addrs)
        self._handle_task = self.svc.append_task(asyncio.get_running_loop(), self._serv(), self.name)

    async def server_join(self):
        """서버 종료 대기"""
        await self.server.wait_closed()

    async def _serv(self):
        """서버 실행 루프 (내부용)"""
        try:
            self.server: asyncio.Server
            await self.server.serve_forever()
        except asyncio.CancelledError:
            self.l.error('소켓이 취소됨')
        finally:
            self.server.close()
            await self.server.wait_closed()

    async def connect(self, addr, port):
        """
        서버에 연결하고 cid 반환

        Args:
            addr: 서버 주소
            port: 포트 번호

        Returns:
            int: 연결 ID

        Raises:
            TimeoutError: 타임아웃 내에 연결되지 않음
        """
        r, w = await asyncio.open_connection(addr, port)
        # 클라이언트 모드에서는 cid를 미리 할당
        self._client_cid = next(self._gen)
        # 핸들러 시작 (내부에서 _add_connection 호출)
        self._handle_task = self.svc.append_task(
            asyncio.get_running_loop(),
            self._handler(r, w),
            self.name
        )
        # 연결이 등록될 때까지 대기 (최대 1초)
        for _ in range(100):
            if self._client_cid in self._conns:
                break
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError('타임아웃 내에 연결이 설정되지 않음')

        return self._client_cid

    async def _add_connection(self, cid, reader, writer):
        """
        연결 추가 (내부용)

        Args:
            cid: 연결 ID
            reader: StreamReader
            writer: StreamWriter
        """
        peer = writer.get_extra_info("peername")
        self.l.debug('새 연결 %s', peer)
        self._conns[cid] = (peer, reader, writer)
        self._recvs[cid] = asyncio.Queue()
        if self.callback:
            await self.callback(cid)

    async def _del_connection(self, cid):
        """
        연결 제거 (내부용)

        Args:
            cid: 연결 ID
        """
        del(self._conns[cid])
        del(self._recvs[cid])
        if self.callback_end:
            await self.callback_end(cid)

    async def _handler(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        연결 핸들러 (내부용)

        Args:
            reader: StreamReader
            writer: StreamWriter
        """
        # 클라이언트 모드면 미리 할당된 cid 사용, 서버 모드면 새로 생성
        if self._client_cid is not None:
            cid = self._client_cid
        else:
            cid = next(self._gen)
        await self._add_connection(cid, reader, writer)
        try:
            while True:
                raw = await reader.readexactly(4)
                try:
                    (size, ) = struct.unpack('!I', raw)
                except struct.error:
                    raise ValueError('잘못된 헤더 데이터')

                if size <= 0 or size > Socket._max_size:
                    raise ValueError('잘못된 헤더 길이')

                buf = await reader.readexactly(size)
                await self._recvs[cid].put(buf)
                self._data_available.set()

                buf_debug = buf[0:min(len(buf), 20)]
                self.l.debug('%d로부터 %s (%d) 수신' % (cid, buf_debug, len(buf)))
        except asyncio.CancelledError:
            pass
        except asyncio.IncompleteReadError:
            self.l.info('연결 종료됨 (%d)' % (cid))
        finally:
            writer.close()
            await self._del_connection(cid)
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _send(self, msg: bytes, cid: int) -> None:
        """
        메시지 전송 (내부용)

        Args:
            msg: 전송할 바이트 데이터
            cid: 연결 ID
        """
        _, _, writer = self._conns[cid]
        writer: asyncio.StreamWriter
        mv = memoryview(msg)
        i, n = 0, len(mv)

        while i < n:
            size = min(Socket._max_size, n-i)
            buf = mv[i:i+size]
            writer.write(struct.pack('!I', size))
            writer.write(buf)
            await writer.drain()
            i += size

        msg_debug = msg[0:min(len(msg), 20)]
        self.l.debug('%d로 %s (%d) 전송' % (cid, msg_debug, len(msg)))

    async def recv(self, cid=None) -> Tuple[int, bytes]:
        """
        메시지 수신

        Args:
            cid: 연결 ID (None이면 모든 연결에서 수신)

        Returns:
            Tuple[int, bytes]: (연결 ID, 수신된 데이터)
        """
        if cid is None:
            while True:
                for check_cid, queue in self._recvs.items():
                    try:
                        data = queue.get_nowait()
                        return check_cid, data
                    except asyncio.QueueEmpty:
                        continue
                self._data_available.clear()
                await self._data_available.wait()
        else:
            data = await self._recvs[cid].get()
            return cid, data

    async def send(self, msg: bytes, cid: int) -> None:
        """
        메시지 전송

        Args:
            msg: 전송할 바이트 데이터
            cid: 연결 ID

        Raises:
            ValueError: 빈 메시지 전송 시도
        """
        if len(msg) <= 0:
            raise ValueError('빈 메시지를 전송할 수 없음')
        await self._send(msg, cid)

    async def recv_str(self, cid: int) -> str:
        """
        문자열 수신

        Args:
            cid: 연결 ID

        Returns:
            str: 수신된 문자열
        """
        _, msg = await self.recv(cid)
        return msg.decode()

    async def send_str(self, string: str, cid: int) -> None:
        """
        문자열 전송

        Args:
            string: 전송할 문자열
            cid: 연결 ID
        """
        await self.send(string.encode(), cid)

    async def recv_file(self, path: os.PathLike, cid: int) -> None:
        """
        파일 수신

        Args:
            path: 저장할 파일 경로
            cid: 연결 ID

        Raises:
            Exception: 파일 데이터 불일치
        """
        try:
            fsize = int(await self.recv_str(cid))
            rsize = 0
            async with aiofiles.open(path, 'wb') as af:
                while rsize < fsize:
                    _, chunk = await self.recv(cid)
                    rsize += len(chunk)
                    await af.write(chunk)
                    if rsize > fsize:
                        raise Exception('파일 데이터 불일치')
        except ValueError as ve:
            self.l.error('값 오류')

    async def send_file(self, path: os.PathLike, cid: int) -> None:
        """
        파일 전송

        Args:
            path: 전송할 파일 경로
            cid: 연결 ID
        """
        fsize = os.path.getsize(path)
        await self.send_str(str(fsize), cid)
        async with aiofiles.open(path, 'rb') as af:
            while True:
                chunk = await af.read(self._max_size)
                if chunk:
                    await self.send(chunk, cid)
                else:
                    break

    async def detach(self):
        """핸들러 태스크 종료"""
        if self._handle_task:
            await self.svc.delete_task(self._handle_task)
        self._handle_task = None
