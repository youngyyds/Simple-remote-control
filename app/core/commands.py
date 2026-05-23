import asyncio
import base64
import io
import time
import traceback
from PIL import Image
import mss
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0


def _capture_screen(quality: int = 60) -> dict:
    """Attempt to capture the screen with small retries and try each monitor.

    Args:
        quality: JPEG quality (1-95). Default 60.

    Returns a dict with keys 'image','width','height' on success or {'error': ...} on failure.
    """
    last_exc = None
    attempts = 2
    quality = max(10, min(95, quality))  # clamp to valid range
    for attempt in range(attempts):
        try:
            with mss.mss() as sct:
                monitors = list(sct.monitors)
                # try monitors in order (0 is the virtual full screen, others are physical)
                for monitor in monitors:
                    try:
                        frame = sct.grab(monitor)
                        image = Image.frombytes('RGB', frame.size, frame.rgb)
                        buffer = io.BytesIO()
                        image.save(buffer, format='JPEG', quality=quality, optimize=True)

                        return {
                            'image': base64.b64encode(buffer.getvalue()).decode('ascii'),
                            'width': frame.width,
                            'height': frame.height,
                        }
                    except Exception as inner:
                        last_exc = inner
                        continue
        except Exception as exc:
            last_exc = exc
        # small pause before retry
        time.sleep(0.1)

    # include type and truncated traceback to help debugging
    tb = traceback.format_exception_only(type(last_exc), last_exc) if last_exc is not None else ['unknown error']
    return {'error': f"{''.join(tb).strip()}"}


async def handle_command(data, ws=None):
    """Dispatch incoming command payload to handlers.

    Expected payload format: {'command_type': 'ping'|'echo'|'screen_capture'|'mouse_click'|'mouse_move'|'key_press'|'key_write', 'args': {...}}
    """
    cmd_type = data.get('command_type')
    args = data.get('args', {})

    try:
        if cmd_type == 'ping':
            return {'status': 'ok', 'result': 'pong'}
        elif cmd_type == 'echo':
            return {'status': 'ok', 'result': args}
        elif cmd_type in ('screen_capture', 'screenshot'):
            quality = args.get('quality', 60)
            capture = _capture_screen(quality)
            return {'status': 'ok', 'result': capture}
        elif cmd_type == 'mouse_move':
            x = args.get('x')
            y = args.get('y')
            if x is None or y is None:
                return {'status': 'error', 'result': 'x and y required'}
            pyautogui.moveTo(x, y)
            return {'status': 'ok', 'result': 'mouse moved'}
        elif cmd_type == 'mouse_click':
            button = args.get('button', 'left')
            clicks = int(args.get('clicks', 1))
            x = args.get('x')
            y = args.get('y')
            if x is not None and y is not None:
                pyautogui.click(x=x, y=y, clicks=clicks, button=button)
            else:
                pyautogui.click(clicks=clicks, button=button)
            return {'status': 'ok', 'result': 'mouse clicked'}
        elif cmd_type == 'key_press':
            key = args.get('key')
            if not key:
                return {'status': 'error', 'result': 'key required'}
            pyautogui.press(key)
            return {'status': 'ok', 'result': f'pressed {key}'}
        elif cmd_type == 'key_write':
            text = args.get('text', '')
            if text == '':
                return {'status': 'error', 'result': 'text required'}
            pyautogui.write(text)
            return {'status': 'ok', 'result': f'written {len(text)} chars'}
        else:
            return {'status': 'error', 'result': f'unknown command {cmd_type}'}
    except Exception as exc:
        return {'status': 'error', 'result': str(exc)}
