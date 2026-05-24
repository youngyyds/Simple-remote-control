import asyncio
import base64
import io
import traceback
from PIL import Image
import mss
import win32api
import win32con
import win32gui
import ctypes
from ctypes import wintypes

# ---------- def SendInput ----------
ULONG_PTR = wintypes.WPARAM
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [("type", wintypes.DWORD),
                ("_input", _INPUT)]

def send_mouse_input(dwFlags, dx=0, dy=0, dwData=0):
    """Send mouse input (SendInput)"""
    inp = INPUT()
    inp.type = 0  # INPUT_MOUSE
    inp.mi.dx = dx
    inp.mi.dy = dy
    inp.mi.mouseData = dwData
    inp.mi.dwFlags = dwFlags
    inp.mi.time = 0
    inp.mi.dwExtraInfo = 0
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

# ---------- functions ----------
_mouse_state = {}

async def _bring_window_to_foreground(x, y):
    hwnd = win32gui.WindowFromPoint((x, y))
    if hwnd:
        foreground = win32gui.GetForegroundWindow()
        if foreground != hwnd:
            win32gui.SetForegroundWindow(hwnd)
            await asyncio.sleep(0.05)
            current = win32api.GetCursorPos()
            win32api.SetCursorPos((current[0]+1, current[1]))
            await asyncio.sleep(0.01)
            win32api.SetCursorPos((current[0], current[1]))
            await asyncio.sleep(0.01)
    return hwnd

def _set_cursor_pos(x, y):
    win32api.SetCursorPos((x, y))

def _key_event(vk_code, is_down):
    flags = 0 if is_down else win32con.KEYEVENTF_KEYUP
    win32api.keybd_event(vk_code, 0, flags, 0)

async def _capture_screen(quality=60):
    """get screen capture as base64-encoded JPEG; retry once if fails (may fail due to transient GDI issues)"""
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
        await asyncio.sleep(0.1)
    tb = traceback.format_exception_only(type(last_exc), last_exc) if last_exc else ['unknown']
    return {'error': ''.join(tb).strip()}

# ---------- commands ----------
async def handle_command(data: dict, ws=None):
    cmd_type = data.get('command_type')
    args = data.get('args', {})

    try:
        if cmd_type == 'ping':
            return {'status': 'ok', 'result': 'pong'}
        elif cmd_type == 'echo':
            return {'status': 'ok', 'result': args}
        elif cmd_type in ('screen_capture', 'screenshot'):
            return {'status': 'ok', 'result': await _capture_screen(args.get('quality', 60))}
        elif cmd_type == 'mouse_move':
            x, y = args.get('x'), args.get('y')
            if x is None or y is None:
                return {'status': 'error', 'result': 'x and y required'}
            _set_cursor_pos(x, y)
            return {'status': 'ok', 'result': 'mouse moved'}
        elif cmd_type == 'mouse_down':
            btn = args.get('button', 'left')
            x, y = args.get('x'), args.get('y')
            if x is not None and y is not None:
                await _bring_window_to_foreground(x, y) 
                _set_cursor_pos(x, y)
                await asyncio.sleep(0.005)
            if btn == 'left':
                send_mouse_input(win32con.MOUSEEVENTF_LEFTDOWN)
            elif btn == 'right':
                send_mouse_input(win32con.MOUSEEVENTF_RIGHTDOWN)
            elif btn == 'middle':
                send_mouse_input(win32con.MOUSEEVENTF_MIDDLEDOWN)
            else:
                return {'status': 'error', 'result': f'unknown button {btn}'}
            await asyncio.sleep(0.01)
            return {'status': 'ok', 'result': 'mouse down'}
        elif cmd_type == 'mouse_up':
            btn = args.get('button', 'left')

            if btn == 'left':
                send_mouse_input(win32con.MOUSEEVENTF_LEFTUP)
            elif btn == 'right':
                send_mouse_input(win32con.MOUSEEVENTF_RIGHTUP)
            elif btn == 'middle':
                send_mouse_input(win32con.MOUSEEVENTF_MIDDLEUP)
            else:
                return {'status': 'error', 'result': f'unknown button {btn}'}
            await asyncio.sleep(0.02)
            return {'status': 'ok', 'result': 'mouse up'}
        elif cmd_type == 'mouse_click':
            btn = args.get('button', 'left')
            clicks = int(args.get('clicks', 1))
            x, y = args.get('x'), args.get('y')
            if x is not None and y is not None:
                await _bring_window_to_foreground(x, y) 
                _set_cursor_pos(x, y)
                await asyncio.sleep(0.005)
            if btn == 'left':
                down = win32con.MOUSEEVENTF_LEFTDOWN
                up = win32con.MOUSEEVENTF_LEFTUP
            elif btn == 'right':
                down = win32con.MOUSEEVENTF_RIGHTDOWN
                up = win32con.MOUSEEVENTF_RIGHTUP
            elif btn == 'middle':
                down = win32con.MOUSEEVENTF_MIDDLEDOWN
                up = win32con.MOUSEEVENTF_MIDDLEUP
            else:
                return {'status': 'error', 'result': f'unknown button {btn}'}
            for _ in range(clicks):
                send_mouse_input(down)
                await asyncio.sleep(0.01)
                send_mouse_input(up)
                await asyncio.sleep(0.07)  
            return {'status': 'ok', 'result': f'{clicks} click(s)'}
        elif cmd_type == 'key_press':
            key = args.get('key')
            if not key:
                return {'status': 'error', 'result': 'key required'}
            vk = _key_to_vk(key)
            if vk is None:
                return {'status': 'error', 'result': f'unsupported key {key}'}
            _key_event(vk, True)
            await asyncio.sleep(0.01)
            _key_event(vk, False)
            return {'status': 'ok', 'result': f'pressed {key}'}
        elif cmd_type == 'key_write':
            text = args.get('text', '')
            if not text:
                return {'status': 'error', 'result': 'text required'}
            for ch in text:
                vk = _char_to_vk(ch)
                if vk:
                    _key_event(vk, True)
                    await asyncio.sleep(0.005)
                    _key_event(vk, False)
                    await asyncio.sleep(0.005)
            return {'status': 'ok', 'result': f'written {len(text)} chars'}
        else:
            return {'status': 'error', 'result': f'unknown command {cmd_type}'}
    except Exception as exc:
        return {'status': 'error', 'result': str(exc)}

def _key_to_vk(key: str) -> int:
    mapping = {
        'enter': win32con.VK_RETURN, 'return': win32con.VK_RETURN,
        'space': win32con.VK_SPACE, 'tab': win32con.VK_TAB,
        'esc': win32con.VK_ESCAPE, 'escape': win32con.VK_ESCAPE,
        'backspace': win32con.VK_BACK, 'delete': win32con.VK_DELETE,
        'up': win32con.VK_UP, 'down': win32con.VK_DOWN,
        'left': win32con.VK_LEFT, 'right': win32con.VK_RIGHT,
        'home': win32con.VK_HOME, 'end': win32con.VK_END,
        'page_up': win32con.VK_PRIOR, 'page_down': win32con.VK_NEXT,
        'ctrl': win32con.VK_CONTROL, 'alt': win32con.VK_MENU, 'shift': win32con.VK_SHIFT,
    }
    if key.lower() in mapping:
        return mapping[key.lower()]
    if len(key) == 1 and key.isalnum():
        return ord(key.upper())
    return None

def _char_to_vk(ch: str) -> int:
    if ch.isalnum():
        return ord(ch.upper())
    return None