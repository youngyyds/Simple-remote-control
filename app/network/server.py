import asyncio
import websockets
from app.core.commands import handle_command
from app.core import protocol
from app.core.auth import require_token, AuthError

async def handler(ws):
    addr = ws.remote_address
    print('Client connected:', addr)
    try:
        # ---- Handshake ----
        raw = await ws.recv()
        try:
            msg = protocol.parse_msg(raw)
        except Exception:
            await ws.send(protocol.make_msg('error', {'message': 'invalid handshake'}))
            await ws.close()
            return

        if msg.get('type') != 'handshake' or msg.get('version') != protocol.VERSION:
            await ws.send(protocol.make_msg('error', {'message': 'version mismatch'}))
            await ws.close()
            return

        try:
            require_token(msg.get('payload', {}))
        except AuthError as exc:
            await ws.send(protocol.make_msg('error', {'message': str(exc)}))
            await ws.close()
            return

        await ws.send(protocol.make_msg('handshake_ack', {'accepted': True}, msg_id=msg.get('id')))

        # ---- Command loop ----
        async for raw in ws:
            try:
                data = protocol.parse_msg(raw)
            except Exception:
                await ws.send(protocol.make_msg('error', {'message': 'invalid json'}))
                continue

            mtype = data.get('type')
            if mtype == 'heartbeat':
                await ws.send(protocol.make_msg('heartbeat', {}, msg_id=data.get('id')))
                continue

            if mtype == 'command':
                payload = data.get('payload', {})
                try:
                    response = await handle_command(payload, ws)
                except Exception as exc:
                    print('Command error:', exc)
                    await ws.send(protocol.make_msg('response', {'status': 'error', 'result': str(exc)}, msg_id=data.get('id')))
                else:
                    # response is already in {'status':'ok','result':...} format
                    out = response.get('result') if response.get('status') == 'ok' else {'error': response.get('result')}
                    await ws.send(protocol.make_msg('response', out, msg_id=data.get('id')))
                continue

            await ws.send(protocol.make_msg('error', {'message': 'unknown type'}, msg_id=data.get('id')))

    except websockets.ConnectionClosed:
        print('Client disconnected:', addr)
    finally:
        # Clean up mouse state for this client
        from app.core.commands import _mouse_state
        _mouse_state.pop(ws, None)

async def run_server(host='0.0.0.0', port=8765):
    print(f'Starting server on {host}:{port}')
    async with websockets.serve(handler, host, port, max_size=20*1024*1024):
        await asyncio.Future()