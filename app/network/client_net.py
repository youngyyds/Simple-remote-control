import asyncio
import threading
import uuid
import websockets
from typing import Callable, Optional

from app.core import protocol


class RemoteClient:
    def __init__(self, host='127.0.0.1', port=8765, token='secret-token-123', on_message: Optional[Callable[[dict], None]] = None):
        self.host = host
        self.port = port
        self.token = token
        self.ws = None
        self._listen_task = None
        self._pending = {}  # id -> asyncio.Future
        self.on_message = on_message
        self._waiting_meta = {}  # id -> metadata for expected binary
        self._waiting_order = []  # ordered ids awaiting binary
        self._loop = None
        self._thread = None
        self._loop_ready = threading.Event()

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
            self._loop_ready.wait(timeout=5.0)

    def connect_sync(self, timeout: float = 10.0):
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(self._connect(), self._loop)
        return future.result(timeout)

    async def _connect(self):
        uri = f'ws://{self.host}:{self.port}'
        self.ws = await websockets.connect(uri, max_size=20 * 1024 * 1024)

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
            raise RuntimeError('handshake failed')

        self._listen_task = asyncio.create_task(self._listen())
        # start heartbeat task
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        return True

    async def _reconnect(self):
        try:
            if self.ws is not None:
                await self._close()
        except Exception:
            pass
        # small backoff
        await asyncio.sleep(0.5)
        return await self._connect()

    async def _heartbeat_loop(self):
        try:
            while True:
                try:
                    hid = str(uuid.uuid4())
                    await self.ws.send(protocol.make_msg('heartbeat', {}, msg_id=hid))
                except Exception:
                    # attempt reconnect
                    try:
                        await self._reconnect()
                    except Exception:
                        # if reconnect fails, wait then try again
                        await asyncio.sleep(1.0)
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            return

    def send_command_sync(self, cmd: dict, timeout: float = 10.0) -> dict:
        if self.ws is None:
            self.connect_sync()
        future = asyncio.run_coroutine_threadsafe(self._send_command(cmd, timeout=timeout), self._loop)
        return future.result(timeout)

    async def _send_command(self, cmd: dict, timeout: float = 10.0) -> dict:
        mid = str(uuid.uuid4())
        fut = self._loop.create_future()
        self._pending[mid] = fut
        try:
            await self.ws.send(protocol.make_msg('command', cmd, msg_id=mid))
        except Exception:
            # try reconnect once then resend
            try:
                await self._connect()
                await self.ws.send(protocol.make_msg('command', cmd, msg_id=mid))
            except Exception as exc:
                self._pending.pop(mid, None)
                raise
        try:
            result = await asyncio.wait_for(fut, timeout)
            return result
        finally:
            self._pending.pop(mid, None)

    async def _listen(self):
        try:
            async for raw in self.ws:
                # raw may be text (str) or bytes
                if isinstance(raw, bytes):
                    # binary frame: associate with earliest waiting id
                    if self._waiting_order:
                        mid = self._waiting_order.pop(0)
                        meta = self._waiting_meta.pop(mid, {})
                        fut = self._pending.get(mid)
                        if fut and not fut.done():
                            # deliver image bytes along with metadata
                            fut.set_result({'image_bytes': raw, 'width': meta.get('width'), 'height': meta.get('height')})
                    continue

                try:
                    msg = protocol.parse_msg(raw)
                except Exception:
                    continue
                mid = msg.get('id')
                mtype = msg.get('type')
                if mtype == 'response' and mid in self._pending:
                    fut = self._pending.get(mid)
                    if fut and not fut.done():
                        fut.set_result(msg.get('payload'))
                    continue
                if mtype == 'response_binary' and mid in self._pending:
                    # store metadata and mark order to expect the next binary frame
                    self._waiting_meta[mid] = msg.get('payload', {})
                    self._waiting_order.append(mid)
                    continue
                if mtype == 'heartbeat':
                    continue
                if self.on_message:
                    self.on_message(msg)
        except websockets.ConnectionClosed:
            return

    def close_sync(self, timeout: float = 5.0):
        if self._loop is None:
            return
        future = asyncio.run_coroutine_threadsafe(self._close(), self._loop)
        future.result(timeout)
        # cancel heartbeat task if present
        try:
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout)
        self._loop = None
        self._thread = None

    async def _close(self):
        if self.ws is not None:
            await self.ws.close()
            self.ws = None
