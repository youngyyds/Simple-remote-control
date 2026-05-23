import asyncio
import json
import websockets
from pynput.mouse import Controller, Button
from pynput.keyboard import Controller as KeyboardController

mouse = Controller()
keyboard = KeyboardController()

BUTTON_MAP = {'left': Button.left, 'right': Button.right, 'middle': Button.middle}

async def handler(websocket):
    print("Client connected")
    async for message in websocket:
        try:
            data = json.loads(message)
            cmd = data.get('command_type')
            args = data.get('args', {})
            print(f"Received: {cmd} {args}")

            if cmd == 'mouse_move':
                x = args.get('x')
                y = args.get('y')
                if x is not None and y is not None:
                    mouse.position = (x, y)
                    await websocket.send(json.dumps({'status': 'ok'}))
            elif cmd == 'mouse_down':
                btn = BUTTON_MAP.get(args.get('button', 'left'))
                if btn:
                    mouse.press(btn)
                    await asyncio.sleep(0.01)
                    await websocket.send(json.dumps({'status': 'ok'}))
            elif cmd == 'mouse_up':
                btn = BUTTON_MAP.get(args.get('button', 'left'))
                if btn:
                    mouse.release(btn)
                    await asyncio.sleep(0.01)
                    await websocket.send(json.dumps({'status': 'ok'}))
            elif cmd == 'mouse_click':
                btn = BUTTON_MAP.get(args.get('button', 'left'))
                clicks = args.get('clicks', 1)
                x = args.get('x')
                y = args.get('y')
                if x is not None and y is not None:
                    mouse.position = (x, y)
                for _ in range(clicks):
                    mouse.click(btn)
                    await asyncio.sleep(0.05)
                await websocket.send(json.dumps({'status': 'ok'}))
            elif cmd == 'key_press':
                key = args.get('key')
                if key:
                    keyboard.press(key)
                    keyboard.release(key)
                    await websocket.send(json.dumps({'status': 'ok'}))
            else:
                await websocket.send(json.dumps({'status': 'error', 'msg': 'unknown command'}))
        except Exception as e:
            print(f"Error: {e}")
            await websocket.send(json.dumps({'status': 'error', 'msg': str(e)}))

async def main():
    async with websockets.serve(handler, "0.0.0.0", 8765):
        print("Test server running on ws://0.0.0.0:8765")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())