import asyncio
import base64
import io
import time
import traceback
from PIL import Image
import mss
from pynput.mouse import Controller as MouseController, Button
from pynput.keyboard import Controller as KeyboardController, Key

# Global controllers (created once)
mouse = MouseController()
keyboard = KeyboardController()

# Button mapping
BUTTON_MAP = {
    'left': Button.left,
    'right': Button.right,
    'middle': Button.middle,
}

# Mouse state per client (to avoid repeated down/up)
_mouse_state = {}  # ws -> {'left': bool, 'right': bool, 'middle': bool}

def _capture_screen(quality: int = 60) -> dict:
    """Capture screen with mss, return base64 JPEG and dimensions."""
    last_exc = None
    quality = max(10, min(95, quality))
    for attempt in range(2):
        try:
            with mss.mss() as sct:
                for monitor in sct.monitors:
                    try:
                        frame = sct.grab(monitor)
                        img = Image.frombytes('RGB', frame.size, frame.rgb)
                        buffer = io.BytesIO()
                        img.save(buffer, format='JPEG', quality=quality, optimize=True)
                        return {
                            'image': base64.b64encode(buffer.getvalue()).decode('ascii'),
                            'width': frame.width,
                            'height': frame.height,
                        }
                    except Exception as e:
                        last_exc = e
                        continue
        except Exception as e:
            last_exc = e
        time.sleep(0.1)
    tb = traceback.format_exception_only(type(last_exc), last_exc) if last_exc else ['unknown']
    return {'error': ''.join(tb).strip()}

async def handle_command(data: dict, ws=None):
    """Dispatch commands using pynput."""
    cmd_type = data.get('command_type')
    args = data.get('args', {})

    try:
        if cmd_type == 'ping':
            return {'status': 'ok', 'result': 'pong'}
        elif cmd_type == 'echo':
            return {'status': 'ok', 'result': args}
        elif cmd_type in ('screen_capture', 'screenshot'):
            quality = args.get('quality', 60)
            return {'status': 'ok', 'result': _capture_screen(quality)}
        elif cmd_type == 'mouse_move':
            x = args.get('x')
            y = args.get('y')
            if x is None or y is None:
                return {'status': 'error', 'result': 'x and y required'}
            mouse.position = (x, y)
            return {'status': 'ok', 'result': 'mouse moved'}
        elif cmd_type == 'mouse_down':
            button_name = args.get('button', 'left')
            button = BUTTON_MAP.get(button_name)
            if not button:
                return {'status': 'error', 'result': f'unknown button {button_name}'}
            # Update state
            if ws:
                if ws not in _mouse_state:
                    _mouse_state[ws] = {'left': False, 'right': False, 'middle': False}
                if _mouse_state[ws].get(button_name, False):
                    return {'status': 'ok', 'result': 'already down'}
                _mouse_state[ws][button_name] = True
            # Move to position if provided
            x = args.get('x')
            y = args.get('y')
            if x is not None and y is not None:
                mouse.position = (x, y)
                await asyncio.sleep(0.005)  # ensure move is processed before click
            mouse.press(button)
            await asyncio.sleep(0.01)  # small delay for system
            return {'status': 'ok', 'result': 'mouse down'}
        elif cmd_type == 'mouse_up':
            button_name = args.get('button', 'left')
            button = BUTTON_MAP.get(button_name)
            if not button:
                return {'status': 'error', 'result': f'unknown button {button_name}'}
            if ws and ws in _mouse_state:
                _mouse_state[ws][button_name] = False
            mouse.release(button)
            await asyncio.sleep(0.02)           # ensure OS processes the release
            # Some applications (like desktop) need a second release to be sure
            mouse.release(button)
            await asyncio.sleep(0.01)
            return {'status': 'ok', 'result': 'mouse up'}
        elif cmd_type == 'mouse_click':
            button_name = args.get('button', 'left')
            clicks = int(args.get('clicks', 1))
            x = args.get('x')
            y = args.get('y')
            button = BUTTON_MAP.get(button_name)
            if not button:
                return {'status': 'error', 'result': f'unknown button {button_name}'}
            if x is not None and y is not None:
                mouse.position = (x, y)
                await asyncio.sleep(0.005)   # settle position for desktop
            for i in range(clicks):
                mouse.click(button)
                # Slightly longer gap between clicks for desktop double‑click
                await asyncio.sleep(0.07)
            return {'status': 'ok', 'result': f'{clicks} click(s)'}
        elif cmd_type == 'key_press':
            key = args.get('key')
            if not key:
                return {'status': 'error', 'result': 'key required'}
            # Try to map special keys (e.g., 'enter', 'space')
            special_keys = {
                'enter': Key.enter, 'return': Key.enter,
                'space': Key.space, 'tab': Key.tab,
                'esc': Key.esc, 'escape': Key.esc,
                'backspace': Key.backspace, 'delete': Key.delete,
                'up': Key.up, 'down': Key.down, 'left': Key.left, 'right': Key.right,
                'home': Key.home, 'end': Key.end, 'page_up': Key.page_up, 'page_down': Key.page_down,
            }
            if key.lower() in special_keys:
                keyboard.press(special_keys[key.lower()])
                keyboard.release(special_keys[key.lower()])
            else:
                keyboard.press(key)
                keyboard.release(key)
            return {'status': 'ok', 'result': f'pressed {key}'}
        elif cmd_type == 'key_write':
            text = args.get('text', '')
            if text == '':
                return {'status': 'error', 'result': 'text required'}
            keyboard.type(text)
            return {'status': 'ok', 'result': f'written {len(text)} chars'}
        else:
            return {'status': 'error', 'result': f'unknown command {cmd_type}'}
    except Exception as exc:
        return {'status': 'error', 'result': str(exc)}