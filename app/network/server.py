import asyncio
import json
import websockets

from app.core.commands import handle_command
from app.core import protocol
from app.core.auth import require_token, AuthError
import base64


async def handler(ws):
    ws.max_size = 20 * 1024 * 1024  # 20MB for receiving oversized messages
    addr = ws.remote_address
    print('Client connected:', addr)
    try:
        # expect initial handshake
        raw = await ws.recv()
        try:
            msg = protocol.parse_msg(raw)
        except Exception:
            await ws.send(protocol.make_msg('error', {'message': 'invalid handshake'}))
            await ws.close()
            return

        if msg.get('type') != 'handshake' or msg.get('version') != protocol.VERSION:
            await ws.send(protocol.make_msg('error', {'message': 'version-mismatch'}))
            await ws.close()
            return

        try:
            require_token(msg.get('payload', {}))
        except AuthError as exc:
            await ws.send(protocol.make_msg('error', {'message': str(exc)}))
            await ws.close()
            return

        # accept handshake
        await ws.send(protocol.make_msg('handshake_ack', {'accepted': True}, msg_id=msg.get('id')))

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
                    response_payload = await handle_command(payload, ws)
                except Exception as exc:
                    print('Error handling command:', exc)
                    await ws.send(protocol.make_msg('response', {'status': 'error', 'result': str(exc)}, msg_id=data.get('id')))
                else:
                    # Normalize response: if handler returned {'status','result'}, unwrap the inner result for client convenience
                    out_payload = response_payload
                    if isinstance(response_payload, dict) and 'status' in response_payload and 'result' in response_payload:
                        if response_payload.get('status') == 'ok':
                            out_payload = response_payload.get('result')
                        else:
                            out_payload = {'error': response_payload.get('result')}

                    # debug log for capture commands
                    try:
                        if payload.get('command_type') in ('screen_capture', 'screenshot'):
                            if isinstance(out_payload, dict):
                                print('Screen capture requested; sending payload keys:', list(out_payload.keys()))
                                if 'error' in out_payload:
                                    print('Screen capture error detail:', out_payload.get('error'))
                            else:
                                print('Screen capture requested; sending payload type:', type(out_payload))
                    except Exception:
                        pass

                    # For screen capture commands, log payload keys for debugging
                    if payload.get('command_type') in ('screen_capture', 'screenshot') and isinstance(out_payload, dict):
                        img_key = 'image' if 'image' in out_payload else ('image_bytes' if 'image_bytes' in out_payload else 'none')
                        b64_len = len(out_payload.get('image', '')) if 'image' in out_payload else 0
                        print(f'Sending screen capture: img_key={img_key} base64_len={b64_len} {out_payload.get("width")}x{out_payload.get("height")}', flush=True)
                        if 'error' in out_payload:
                            print(f'  ERROR: {out_payload["error"]}', flush=True)

                    await ws.send(protocol.make_msg('response', out_payload, msg_id=data.get('id')))
                continue

            # unknown type
            await ws.send(protocol.make_msg('error', {'message': 'unknown type'}, msg_id=data.get('id')))
    except websockets.ConnectionClosed:
        print('Client disconnected:', addr)


async def run_server(host='0.0.0.0', port=8765):
    print(f'Starting server on {host}:{port}')
    async with websockets.serve(handler, host, port, max_size=20 * 1024 * 1024):
        await asyncio.Future()  # run forever
