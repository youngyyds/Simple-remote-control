import sys
import threading
import base64

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.network.client_net import RemoteClient


class RemoteScreenLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setStyleSheet('background-color: #111; border: 1px solid #666;')
        self.remote_size = (0, 0)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.last_image_size = None
        self.clicked_callback = None

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton) and self.clicked_callback:
            self._emit_click(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.clicked_callback:
            self._emit_click(event)

    def _emit_click(self, event):
        if self.remote_size[0] == 0 or self.remote_size[1] == 0:
            return
        label_w = self.width()
        label_h = self.height()
        x = event.position().x()
        y = event.position().y()
        rel_x = max(0, min(x / label_w, 1.0))
        rel_y = max(0, min(y / label_h, 1.0))
        remote_x = int(rel_x * self.remote_size[0])
        remote_y = int(rel_y * self.remote_size[1])
        button = 'left' if event.button() == Qt.MouseButton.LeftButton else 'right'
        self.clicked_callback(remote_x, remote_y, button)

    def update_image(self, image_data: str, width: int, height: int):
        import tempfile, os
        # image_data may be a base64 string or raw bytes; handle both
        raw = None

        input_type = type(image_data).__name__
        input_len = len(image_data) if isinstance(image_data, (str, bytes, bytearray)) else '?'
        try:
            if hasattr(self.window(), 'log'):
                self.window().log(f'update_image: type={input_type} len={input_len} w={width} h={height}')
        except Exception:
            pass

        if isinstance(image_data, (bytes, bytearray)):
            raw = bytes(image_data)
            try:
                if hasattr(self.window(), 'log'):
                    self.window().log(f'  -> bytes branch, raw={len(raw)} bytes')
            except Exception:
                pass
        else:
            try:
                # check if it looks like base64 before trying to decode
                try:
                    if hasattr(self.window(), 'log'):
                        is_b64_like = isinstance(image_data, str) and len(image_data) > 100 and image_data[:50].isalnum() or '/' in image_data[:50]
                        self.window().log(f'  -> string branch, is_b64_like={is_b64_like} first50="{image_data[:50]}"')
                except Exception:
                    pass
                raw = base64.b64decode(image_data)
                try:
                    if hasattr(self.window(), 'log'):
                        self.window().log(f'  -> base64 decode OK: {len(raw)} bytes')
                except Exception:
                    pass
            except Exception as exc:
                try:
                    if hasattr(self.window(), 'log'):
                        self.window().log(f'  -> base64 decode FAILED: {exc}')
                except Exception:
                    pass
                # dump for inspection
                try:
                    tf = tempfile.NamedTemporaryFile(delete=False, suffix='.bin')
                    tf.write(image_data.encode('utf-8') if isinstance(image_data, str) else image_data)
                    tf.close()
                    if hasattr(self.window(), 'log'):
                        self.window().log(f'Wrote raw payload to {tf.name}')
                except Exception:
                    pass
                self.setText('Invalid image data (decode)')
                return

        if raw is None or len(raw) < 200:
            try:
                if hasattr(self.window(), 'log'):
                    self.window().log(f'Image data too small: {0 if raw is None else len(raw)} bytes')
            except Exception:
                pass
            try:
                if raw is not None:
                    tf = tempfile.NamedTemporaryFile(delete=False, suffix='.jpg')
                    tf.write(raw)
                    tf.close()
                    if hasattr(self.window(), 'log'):
                        self.window().log(f'Wrote small image to {tf.name} ({len(raw)} bytes)')
            except Exception:
                pass
            self.setText('Invalid image data (too small)')
            return

        image = QImage.fromData(raw)
        if image.isNull():
            try:
                if hasattr(self.window(), 'log'):
                    self.window().log('QImage.fromData returned null image')
            except Exception:
                pass
            # Write raw to temp jpg for inspection
            try:
                tf = tempfile.NamedTemporaryFile(delete=False, suffix='_debug.jpg')
                tf.write(raw)
                tf.close()
                if hasattr(self.window(), 'log'):
                    self.window().log(f'Wrote invalid-image to {tf.name} ({len(raw)} bytes)')
                    # Also check file size on disk
                    file_size = os.path.getsize(tf.name)
                    self.window().log(f'  File on disk: {file_size} bytes')
            except Exception:
                pass
            self.setText('Invalid image data (decode)')
            return

        pixmap = QPixmap.fromImage(image)
        self.last_image_size = (pixmap.width(), pixmap.height())
        self.remote_size = (width, height)
        scaled = pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)
        try:
            if hasattr(self.window(), 'log'):
                self.window().log(f'Image displayed ({pixmap.width()}x{pixmap.height()})')
        except Exception:
            pass


class ClientWindow(QMainWindow):
    # Signal to safely update screen image from any thread
    image_signal = pyqtSignal(object, int, int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Simple Remote Control - Client')
        self.client = None
        self.streaming = False
        # Connect signal to the UI-thread-safe slot
        self.image_signal.connect(self._on_image_signal)
        self.stream_thread = None
        self.stream_stop = threading.Event()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout()
        central.setLayout(main_layout)

        self.host_input = QLineEdit('127.0.0.1')
        self.port_input = QLineEdit('8765')
        self.token_input = QLineEdit('secret-token-123')
        self.status = QLabel('Disconnected')
        self.screen_label = RemoteScreenLabel(self)
        self.screen_label.setText('Remote screen image will appear here')
        self.screen_label.setFixedSize(800, 450)

        self.connect_btn = QPushButton('Connect')
        self.disconnect_btn = QPushButton('Disconnect')
        self.refresh_btn = QPushButton('Refresh Screen')
        self.stream_btn = QPushButton('Start Stream')
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText('Enter text or key and press Enter')
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        self.screen_label.clicked_callback = self.on_screen_click

        form_layout = QHBoxLayout()
        form_layout.addWidget(QLabel('Host'))
        form_layout.addWidget(self.host_input)
        form_layout.addWidget(QLabel('Port'))
        form_layout.addWidget(self.port_input)
        form_layout.addWidget(QLabel('Token'))
        form_layout.addWidget(self.token_input)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.connect_btn)
        button_layout.addWidget(self.disconnect_btn)
        button_layout.addWidget(self.refresh_btn)
        button_layout.addWidget(self.stream_btn)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.key_input)

        main_layout.addLayout(form_layout)
        main_layout.addWidget(self.status)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(self.screen_label)
        main_layout.addLayout(input_layout)
        main_layout.addWidget(QLabel('Log'))
        main_layout.addWidget(self.log_text)

        self.connect_btn.clicked.connect(self.on_connect)
        self.disconnect_btn.clicked.connect(self.on_disconnect)
        self.refresh_btn.clicked.connect(self.on_refresh)
        self.stream_btn.clicked.connect(self.on_toggle_stream)
        self.key_input.returnPressed.connect(self.on_send_key)

    def log(self, message: str):
        self.log_text.append(message)

    def _on_image_signal(self, image_data, width, height):
        """Slot called in UI thread via signal to safely update screen image."""
        self.screen_label.update_image(image_data, width, height)

    def _on_server_message(self, msg: dict):
        # Called from network thread; marshal to UI thread for logging
        try:
            self._invoke_ui(lambda: self.log(f'Server push: {msg}'))
        except Exception:
            pass

    def _invoke_ui(self, fn):
        QTimer.singleShot(0, fn)

    def on_connect(self):
        if self.client is not None:
            self.log('Already connected')
            return

        host = self.host_input.text().strip()
        port = int(self.port_input.text().strip())
        token = self.token_input.text().strip()
        self.client = RemoteClient(host, port, token=token, on_message=self._on_server_message)

        def worker():
            try:
                self.client.connect_sync()
                self._invoke_ui(lambda: self.status.setText('Connected'))
                self.log('Connected to server')
            except Exception as exc:
                self.client = None
                self._invoke_ui(lambda: self.status.setText(f'Connect failed: {exc}'))
                self.log(f'Connect failed: {exc}')

        threading.Thread(target=worker, daemon=True).start()

    def on_disconnect(self):
        if self.client is None:
            self.log('No connection to disconnect')
            return

        def worker():
            try:
                self.stream_stop.set()
                if self.stream_thread is not None:
                    self.stream_thread.join(2)
                self.client.close_sync()
                self._invoke_ui(lambda: self.status.setText('Disconnected'))
                self.log('Disconnected')
            except Exception as exc:
                self.log(f'Disconnect failed: {exc}')
            finally:
                self.client = None
                self.streaming = False
                self._invoke_ui(lambda: self.stream_btn.setText('Start Stream'))

        threading.Thread(target=worker, daemon=True).start()

    def on_refresh(self):
        if self.client is None:
            self.log('Connect before refreshing screen')
            return

        def worker():
            try:
                response = self.client.send_command_sync({'command_type': 'screen_capture', 'args': {}})
                # server sends payload directly; normalize for backward compatibility
                payload = response if isinstance(response, dict) else {}
                # if server returned an explicit error, log it
                if isinstance(payload, dict) and payload.get('error'):
                    self.log(f"Server capture error: {payload.get('error')}")
                    return
                # support either base64 'image' or binary 'image_bytes'
                image_data = payload.get('image') if payload.get('image') is not None else payload.get('image_bytes')
                width = payload.get('width')
                height = payload.get('height')

                if image_data is not None and width and height:
                    try:
                        self.image_signal.emit(image_data, width, height)
                        self.log('Screen refreshed')
                    except Exception as exc:
                        self.log(f'Image update failed: {exc} -- payload keys: {list(payload.keys())}')
                else:
                    self.log(f'No image returned from server, payload: {payload}')
            except Exception as exc:
                self.log(f'Screen refresh failed: {exc}')

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_stream_worker(self):
        self.stream_stop.clear()
        while not self.stream_stop.is_set() and self.client is not None:
            try:
                response = self.client.send_command_sync({'command_type': 'screen_capture', 'args': {}})
                payload = response if isinstance(response, dict) else {}
                # support either base64 'image' or binary 'image_bytes'
                image_data = payload.get('image') if payload.get('image') is not None else payload.get('image_bytes')
                width = payload.get('width')
                height = payload.get('height')

                # debug logging
                ptype = type(payload).__name__
                pkeys = list(payload.keys()) if isinstance(payload, dict) else 'N/A'
                dtype = type(image_data).__name__ if image_data is not None else 'None'
                dsize = len(image_data) if image_data is not None and hasattr(image_data, '__len__') else 'N/A'

                if image_data is not None and width and height:
                    self.log(f'Stream frame: type={dtype} size={dsize} {width}x{height}')
                    self.image_signal.emit(image_data, width, height)
                else:
                    self.log(f'Stream frame missing data: payload_type={ptype} keys={pkeys} image_type={dtype}')
            except Exception as exc:
                self.log(f'Stream failed: {exc}')
                break
            self.stream_stop.wait(0.2)

    def on_toggle_stream(self):
        if self.client is None:
            self.log('Connect before starting stream')
            return

        if not self.streaming:
            self.streaming = True
            self.stream_btn.setText('Stop Stream')
            self.stream_stop.clear()
            self.stream_thread = threading.Thread(target=self._refresh_stream_worker, daemon=True)
            self.stream_thread.start()
            self.log('Screen stream started')
        else:
            self.streaming = False
            self.stream_btn.setText('Start Stream')
            self.stream_stop.set()
            self.log('Screen stream stopped')

    def on_screen_click(self, x: int, y: int, button: str = 'left'):
        if self.client is None:
            self.log('Connect before clicking on screen')
            return

        def worker():
            try:
                response = self.client.send_command_sync({'command_type': 'mouse_click', 'args': {'button': button, 'x': x, 'y': y}})
                # response may be a plain value or a dict
                result = response if not isinstance(response, dict) else (response.get('result') if 'result' in response else response)
                self.log(f'Screen click sent ({button}): {result}')
            except Exception as exc:
                self.log(f'Screen click failed: {exc}')

        threading.Thread(target=worker, daemon=True).start()

    def on_send_key(self):
        if self.client is None:
            self.log('Connect before sending keyboard events')
            return

        text = self.key_input.text().strip()
        if not text:
            self.log('Enter text or key to send')
            return

        def worker():
            try:
                cmd_type = 'key_write' if len(text) > 1 else 'key_press'
                args = {'text': text} if cmd_type == 'key_write' else {'key': text}
                response = self.client.send_command_sync({'command_type': cmd_type, 'args': args})
                result = response if not isinstance(response, dict) else (response.get('result') if 'result' in response else response)
                self.log(f'Keyboard command: {result}')
                self._invoke_ui(lambda: self.key_input.clear())
            except Exception as exc:
                self.log(f'Keyboard send failed: {exc}')

        threading.Thread(target=worker, daemon=True).start()


def run_client():
    app = QApplication(sys.argv)
    w = ClientWindow()
    w.show()
    sys.exit(app.exec())
