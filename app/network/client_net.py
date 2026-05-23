import asyncio
import threading
import uuid
import websockets

from app.core import protocol

class RemoteClient:
    def __init__(self, host='127.0.0.1', port=8765, token='secret-token-123'):
        self.host = host
        self.port = port
        self.token = token
        self.ws = None
        self._loop = None
        self._thread = None
        self._loop_ready = threading.Event()
        self._pending = {}

    def _start_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        self._loop.run_forever()

    def _ensure_loop(self):
        if self._loop is None or self._thread is None or not self._thread.is_alive():
            self._loop_ready.clear()
            self._thread = threading.Thread(target=self._start_loop, daemon=True)
            self._thread.start()
            self._loop_ready.wait(5.0)

    def connect_sync(self, timeout: float = 10.0):
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        return future.result(timeout)

    async def _connect(self):
        uri = f'ws://{self.host}:{self.port}'
        self.ws = await websockets.connect(uri, max_size=20*1024*1024)
        hid = str(uuid.uuid4())
        await self.ws.send(
            protocol.make_msg(
                'handshake',
                {'client_id': 'client', 'capabilities': [], 'token': self.token},
                msg_id=hid,
            )
        )
        raw = await self.ws.recv()
        msg = protocol.parse_msg(raw)
        if msg.get('type') != 'handshake_ack':
            raise RuntimeError(f'handshake failed: {msg}')
        asyncio.create_task(self._listen())
        return True

    async def _listen(self):
        try:
            async for raw in self.ws:
                if isinstance(raw, bytes):
                    continue
                msg = protocol.parse_msg(raw)
                mid = msg.get('id')
                if msg.get('type') == 'response' and mid in self._pending:
                    fut = self._pending.pop(mid)
                    if not fut.done():
                        fut.set_result(msg.get('payload'))
        except:
            pass

    # Blocking command with timeout (for reliable delivery)
    def send_command_sync(self, cmd: dict, timeout: float = 5.0) -> dict:
        if self.ws is None:
            self.connect_sync()
        future = asyncio.run_coroutine_threadsafe(self._send_command(cmd, timeout), self._loop)
        return future.result(timeout)

    # Short‑timeout version for mouse moves/clicks (fails fast)
    def send_command_sync_short(self, cmd: dict, timeout: float = 0.2) -> dict:
        try:
            return self.send_command_sync(cmd, timeout=timeout)
        except Exception:
            return {}

    async def _send_command(self, cmd: dict, timeout: float) -> dict:
        mid = str(uuid.uuid4())
        fut = self._loop.create_future()
        self._pending[mid] = fut
        try:
            await self.ws.send(protocol.make_msg('command', cmd, msg_id=mid))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(mid, None)

    def close_sync(self, timeout: float = 5.0):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._close(), self._loop).result(timeout)
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread:
                self._thread.join(timeout)
            self._loop = None
            self._thread = None

    async def _close(self):
        if self.ws:
            await self.ws.close()
            self.ws = None