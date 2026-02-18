import os
import asyncio
import aiofiles
import contextlib
import struct
from enum import Enum
from typing import TYPE_CHECKING

from .component import Component

if TYPE_CHECKING:
    from .main import Service


class SocketMode(Enum):
    """Socket operation mode"""
    DATA = "data"       # Data transmission socket
    SERVER = "server"   # Server listening socket


class Socket(Component):
    """
    비동기 소켓 통신 컴포넌트

    TCP 소켓 기반 바이너리 통신을 제공합니다.
    DATA 모드: 단일 전송 통로
    SERVER 모드: 클라이언트 접속 대기 및 콜백 처리
    """
    _max_size = 64 * 1024

    def __init__(self, svc: 'Service', serial: int, mode: SocketMode,
                 name: str = None, parent=None,
                 reader: asyncio.StreamReader = None,
                 writer: asyncio.StreamWriter = None):
        """
        Socket 초기화

        Args:
            svc: 서비스 인스턴스
            serial: 소켓 시리얼 번호
            mode: SocketMode.DATA 또는 SocketMode.SERVER
            name: 컴포넌트 이름 (None이면 자동 생성)
            parent: 부모 컴포넌트
            reader: StreamReader (DATA 모드용)
            writer: StreamWriter (DATA 모드용)
        """
        # Auto-generate name if not provided
        if name is None:
            name = f'Socket-{serial}'

        super().__init__(svc, name, parent)

        # Common attributes
        self.serial = serial
        self.mode = mode
        self._closed = asyncio.Event()

        # DATA mode attributes
        if mode == SocketMode.DATA:
            self._reader = reader
            self._writer = writer
            self._recv_queue = asyncio.Queue()
            self._peer = writer.get_extra_info("peername") if writer else None
            self._handle_task = None
            self.l.debug('새 데이터 소켓 생성 (serial=%d, peer=%s)' % (serial, self._peer))

        # SERVER mode attributes
        elif mode == SocketMode.SERVER:
            self.server = None
            self._accept_callback = None
            self._server_task = None
            self.l.debug('새 서버 소켓 생성 (serial=%d)' % serial)

        if isinstance(parent, EndPoint):
            self.endpoint = parent

    # Class methods for creating sockets
    @classmethod
    def create_data_socket(cls, svc: 'Service', serial: int,
                          reader: asyncio.StreamReader,
                          writer: asyncio.StreamWriter,
                          parent=None) -> 'Socket':
        """
        Create data socket from existing reader/writer

        Args:
            svc: Service instance
            serial: Socket serial number
            reader: StreamReader
            writer: StreamWriter
            parent: Parent component

        Returns:
            Socket: New DATA mode socket
        """
        socket = cls(svc, serial, SocketMode.DATA, parent=parent,
                    reader=reader, writer=writer)
        return socket

    @classmethod
    def create_server_socket(cls, svc: 'Service', serial: int,
                            accept_callback: callable,
                            parent=None) -> 'Socket':
        """
        Create server socket

        Args:
            svc: Service instance
            serial: Socket serial number
            accept_callback: Callback for new connections
            parent: Parent component

        Returns:
            Socket: New SERVER mode socket
        """
        socket = cls(svc, serial, SocketMode.SERVER, parent=parent)
        socket._accept_callback = accept_callback
        return socket

    # DATA mode methods
    async def start(self):
        """Start the data socket handler task (DATA mode only)"""
        if self.mode != SocketMode.DATA:
            raise RuntimeError("start() only for DATA mode")
        self._handle_task = self.svc.append_task(
            asyncio.get_running_loop(),
            self._data_handler(),
            self.name
        )

    async def _data_handler(self):
        """Handle single connection data reception (DATA mode)"""
        try:
            while True:
                # Read 4-byte header
                raw = await self._reader.readexactly(4)
                try:
                    (size,) = struct.unpack('!I', raw)
                except struct.error:
                    raise ValueError('잘못된 헤더 데이터')

                if size <= 0 or size > Socket._max_size:
                    raise ValueError('잘못된 헤더 길이')

                # Read body
                buf = await self._reader.readexactly(size)
                await self._recv_queue.put(buf)

                # Notify parent Endpoint if present
                if isinstance(self._parent, EndPoint):
                    self._parent._recv_event.set()

                buf_debug = buf[0:min(len(buf), 20)]
                self.l.debug('serial=%d로부터 %s (%d) 수신' % (self.serial, buf_debug, len(buf)))
        except asyncio.CancelledError:
            pass
        except asyncio.IncompleteReadError:
            self.l.info('연결 종료됨 (serial=%d)' % self.serial)
        finally:
            await self._close_connection()

    async def _close_connection(self):
        """Internal connection close handler (DATA mode)"""
        if self._writer:
            self._writer.close()
            with contextlib.suppress(Exception):
                await self._writer.wait_closed()
        self._closed.set()

    async def recv(self) -> bytes:
        """
        Receive message from this socket (DATA mode only)

        Returns:
            bytes: Received data
        """
        if self.mode != SocketMode.DATA:
            raise RuntimeError("recv() only for DATA mode")
        return await self._recv_queue.get()

    async def send(self, msg: bytes) -> None:
        """
        Send message through this socket (DATA mode only)

        Args:
            msg: Message bytes

        Raises:
            ValueError: Empty message
        """
        if self.mode != SocketMode.DATA:
            raise RuntimeError("send() only for DATA mode")
        if len(msg) <= 0:
            raise ValueError('빈 메시지를 전송할 수 없음')
        await self._send(msg)

    async def _send(self, msg: bytes) -> None:
        """Internal send implementation (DATA mode)"""
        mv = memoryview(msg)
        i, n = 0, len(mv)

        while i < n:
            size = min(Socket._max_size, n-i)
            buf = mv[i:i+size]
            self._writer.write(struct.pack('!I', size))
            self._writer.write(buf)
            await self._writer.drain()
            i += size

        msg_debug = msg[0:min(len(msg), 20)]
        self.l.debug('serial=%d로 %s (%d) 전송' % (self.serial, msg_debug, len(msg)))

    async def recv_str(self) -> str:
        """
        Receive string (DATA mode only)

        Returns:
            str: Received string
        """
        msg = await self.recv()
        return msg.decode()

    async def send_str(self, string: str) -> None:
        """
        Send string (DATA mode only)

        Args:
            string: String to send
        """
        await self.send(string.encode())

    async def send_file(self, path: os.PathLike) -> None:
        """
        Send file (DATA mode only)

        Args:
            path: File path to send
        """
        if self.mode != SocketMode.DATA:
            raise RuntimeError("send_file() only for DATA mode")
        fsize = os.path.getsize(path)
        await self.send_str(str(fsize))
        async with aiofiles.open(path, 'rb') as af:
            while True:
                chunk = await af.read(self._max_size)
                if chunk:
                    await self.send(chunk)
                else:
                    break

    async def recv_file(self, path: os.PathLike) -> None:
        """
        Receive file (DATA mode only)

        Args:
            path: File path to save

        Raises:
            Exception: File data mismatch
        """
        if self.mode != SocketMode.DATA:
            raise RuntimeError("recv_file() only for DATA mode")
        try:
            fsize = int(await self.recv_str())
            rsize = 0
            async with aiofiles.open(path, 'wb') as af:
                while rsize < fsize:
                    chunk = await self.recv()
                    rsize += len(chunk)
                    await af.write(chunk)
                    if rsize > fsize:
                        raise Exception('파일 데이터 불일치')
        except ValueError as ve:
            self.l.error('값 오류')

    @property
    def peer(self) -> tuple:
        """Get peer address (DATA mode only)"""
        if self.mode != SocketMode.DATA:
            raise RuntimeError("peer property only for DATA mode")
        return self._peer

    @property
    def is_closed(self) -> bool:
        """Check if socket is closed"""
        return self._closed.is_set()

    # SERVER mode methods
    async def bind(self, addr: str, port: int):
        """
        Bind as server socket (SERVER mode only)

        Args:
            addr: Binding address
            port: Port number
        """
        if self.mode != SocketMode.SERVER:
            raise RuntimeError("bind() only for SERVER mode")

        self.server = await asyncio.start_server(
            self._accept_handler, host=addr, port=port
        )
        addrs = ", ".join(str(sock.getsockname()) for sock in self.server.sockets)
        self.l.debug('%s에서 서비스 중 (serial=%d)', addrs, self.serial)

        # Start server task
        self._server_task = self.svc.append_task(
            asyncio.get_running_loop(),
            self._server_loop(),
            self.name
        )

    async def _server_loop(self):
        """Server execution loop (SERVER mode)"""
        try:
            await self.server.serve_forever()
        except asyncio.CancelledError:
            self.l.info('서버 취소됨 (serial=%d)' % self.serial)
        finally:
            self.server.close()
            await self.server.wait_closed()

    async def _accept_handler(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter):
        """
        Handle new client connection (SERVER mode)

        Args:
            reader: Client StreamReader
            writer: Client StreamWriter
        """
        # Invoke callback to create data socket
        if self._accept_callback:
            await self._accept_callback(reader, writer)
        else:
            # No callback - close connection
            self.l.warning('서버 소켓에 콜백이 없음, 연결 종료')
            writer.close()
            await writer.wait_closed()

    # Common methods
    async def close(self):
        """Close socket (both DATA and SERVER modes)"""
        if self.mode == SocketMode.DATA:
            self._closed.set()
            if self._handle_task:
                await self.svc.delete_task(self._handle_task)
            if self._writer:
                self._writer.close()
                with contextlib.suppress(Exception):
                    await self._writer.wait_closed()
        elif self.mode == SocketMode.SERVER:
            if self._server_task:
                await self.svc.delete_task(self._server_task)
            if self.server:
                self.server.close()
                await self.server.wait_closed()


class EndPoint(Component):
    """
    소켓 통신 종단 클래스

    서버 소켓과 데이터 소켓을 통합 관리합니다.
    """
    def __init__(self, svc: 'Service', name='EndPoint', parent=None):
        super().__init__(svc, name, parent)

        # Socket management
        self._sockets = {}         # {serial: Socket} - all sockets
        self._server_sockets = {}  # {serial: Socket} - server sockets only
        self._data_sockets = {}    # {serial: Socket} - data sockets only

        # Receive aggregation
        self._recv_event = asyncio.Event()  # Signal when any socket has data

    # Connection methods
    async def bind(self, addr: str, port: int) -> int:
        """
        Bind server socket

        Args:
            addr: Binding address
            port: Port number

        Returns:
            int: Server socket serial number
        """
        # Get serial from Service
        serial = self.svc.next_socket_serial()

        # Create server socket with callback
        server_socket = Socket.create_server_socket(
            self.svc,
            serial,
            accept_callback=self._on_client_connect,
            parent=self
        )

        # Register socket
        self._sockets[serial] = server_socket
        self._server_sockets[serial] = server_socket

        # Bind
        await server_socket.bind(addr, port)

        self.l.info('서버 소켓 %d 바인딩 완료 (%s:%d)', serial, addr, port)
        return serial

    async def _on_client_connect(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter):
        """
        Callback when server socket accepts new client

        Creates new data socket and adds to managed sockets

        Args:
            reader: Client StreamReader
            writer: Client StreamWriter
        """
        # Get serial for new data socket
        serial = self.svc.next_socket_serial()

        # Create data socket
        data_socket = Socket.create_data_socket(
            self.svc,
            serial,
            reader,
            writer,
            parent=self
        )

        # Register socket
        self._sockets[serial] = data_socket
        self._data_sockets[serial] = data_socket

        # Start data handler
        await data_socket.start()

        peer = writer.get_extra_info("peername")
        self.l.info('새 데이터 소켓 %d 연결됨 (%s)', serial, peer)

        # Signal recv_any that new socket available
        self._recv_event.set()

    async def connect(self, addr: str, port: int) -> int:
        """
        Connect to remote server

        Args:
            addr: Server address
            port: Port number

        Returns:
            int: Data socket serial number
        """
        # Get serial
        serial = self.svc.next_socket_serial()

        # Open connection
        reader, writer = await asyncio.open_connection(addr, port)

        # Create data socket
        data_socket = Socket.create_data_socket(
            self.svc,
            serial,
            reader,
            writer,
            parent=self
        )

        # Register socket
        self._sockets[serial] = data_socket
        self._data_sockets[serial] = data_socket

        # Start data handler
        await data_socket.start()

        self.l.info('%s:%d에 연결됨 (소켓 serial=%d)', addr, port, serial)
        return serial

    # Data reception methods
    async def recv_any(self) -> tuple[int, bytes]:
        """
        Receive from any data socket (poll all sockets)

        Returns:
            tuple[int, bytes]: (socket serial, received data)
        """
        while True:
            # Poll all data sockets for available data
            for serial, socket in list(self._data_sockets.items()):
                try:
                    # Non-blocking check if data available
                    data = socket._recv_queue.get_nowait()
                    return serial, data
                except asyncio.QueueEmpty:
                    # Check if socket closed
                    if socket.is_closed:
                        # Remove from tracked sockets
                        await self._remove_socket(serial)
                    continue

            # No data available, wait for signal
            self._recv_event.clear()
            await self._recv_event.wait()

    async def recv(self, serial: int) -> bytes:
        """
        Receive from specific socket

        Args:
            serial: Socket serial number

        Returns:
            bytes: Received data
        """
        socket = self._data_sockets.get(serial)
        if not socket:
            raise KeyError(f'Socket {serial} not found')
        return await socket.recv()

    async def send(self, msg: bytes, serial: int) -> None:
        """
        Send to specific socket

        Args:
            msg: Message bytes
            serial: Socket serial number
        """
        socket = self._data_sockets.get(serial)
        if not socket:
            raise KeyError(f'Socket {serial} not found')
        await socket.send(msg)

    async def send_str(self, string: str, serial: int) -> None:
        """
        Send string to socket

        Args:
            string: String to send
            serial: Socket serial number
        """
        socket = self._data_sockets.get(serial)
        if not socket:
            raise KeyError(f'Socket {serial} not found')
        await socket.send_str(string)

    async def recv_str(self, serial: int) -> str:
        """
        Receive string from socket

        Args:
            serial: Socket serial number

        Returns:
            str: Received string
        """
        socket = self._data_sockets.get(serial)
        if not socket:
            raise KeyError(f'Socket {serial} not found')
        return await socket.recv_str()

    async def send_file(self, path: os.PathLike, serial: int) -> None:
        """
        Send file to socket

        Args:
            path: File path to send
            serial: Socket serial number
        """
        socket = self._data_sockets.get(serial)
        if not socket:
            raise KeyError(f'Socket {serial} not found')
        await socket.send_file(path)

    async def recv_file(self, path: os.PathLike, serial: int) -> None:
        """
        Receive file from socket

        Args:
            path: File path to save
            serial: Socket serial number
        """
        socket = self._data_sockets.get(serial)
        if not socket:
            raise KeyError(f'Socket {serial} not found')
        await socket.recv_file(path)

    # Socket management methods
    def get_socket(self, serial: int) -> Socket:
        """
        Get socket by serial number

        Args:
            serial: Socket serial number

        Returns:
            Socket: Socket instance
        """
        socket = self._sockets.get(serial)
        if not socket:
            raise KeyError(f'Socket {serial} not found')
        return socket

    def get_data_sockets(self) -> dict[int, Socket]:
        """
        Get all data sockets

        Returns:
            dict[int, Socket]: Dictionary of data sockets
        """
        return dict(self._data_sockets)

    def get_server_sockets(self) -> dict[int, Socket]:
        """
        Get all server sockets

        Returns:
            dict[int, Socket]: Dictionary of server sockets
        """
        return dict(self._server_sockets)

    async def close_socket(self, serial: int):
        """
        Close specific socket

        Args:
            serial: Socket serial number
        """
        socket = self._sockets.get(serial)
        if socket:
            await socket.close()
            await self._remove_socket(serial)

    async def _remove_socket(self, serial: int):
        """
        Remove socket from tracking

        Args:
            serial: Socket serial number
        """
        if serial in self._sockets:
            del self._sockets[serial]
        if serial in self._data_sockets:
            del self._data_sockets[serial]
        if serial in self._server_sockets:
            del self._server_sockets[serial]

        self.l.debug('소켓 %d 제거됨', serial)

    async def close_all(self):
        """Close all sockets"""
        for serial in list(self._sockets.keys()):
            await self.close_socket(serial)

