import sys
import json
import os
import threading
import base64

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QRect
from PyQt6.QtGui import QAction, QImage, QPixmap, QPainter, QPen, QColor
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMenuBar, QMessageBox, QPushButton, QVBoxLayout,
    QWidget, QListWidget, QListWidgetItem, QDialog, QFormLayout,
    QDialogButtonBox, QCheckBox, QSpinBox
)

from app.network.client_net import RemoteClient


# ── Connection data file ────────────────────────────────
CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.simple-remote-control')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'connections.json')


def _load_connections() -> list:
    """Load saved connections from JSON file."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    return []


def _save_connections(connections: list):
    """Save connections to JSON file."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(connections, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f'Failed to save connections: {exc}')


# ── Connection Edit Dialog ─────────────────────────────
class ConnectionEditDialog(QDialog):
    def __init__(self, parent=None, name='', host='127.0.0.1', port=8765, token=''):
        super().__init__(parent)
        self.setWindowTitle('Edit Connection')
        self.setMinimumWidth(350)

        layout = QFormLayout(self)
        self.name_edit = QLineEdit(name)
        self.host_edit = QLineEdit(host)
        self.port_edit = QLineEdit(str(port))
        self.token_edit = QLineEdit(token)

        layout.addRow('Name:', self.name_edit)
        layout.addRow('Host:', self.host_edit)
        layout.addRow('Port:', self.port_edit)
        layout.addRow('Token:', self.token_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_data(self):
        return {
            'name': self.name_edit.text().strip(),
            'host': self.host_edit.text().strip(),
            'port': int(self.port_edit.text().strip() or 8765),
            'token': self.token_edit.text().strip(),
        }


# ── Remote Screen Label ────────────────────────────────
class RemoteScreenLabel(QLabel):
    clicked = pyqtSignal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setStyleSheet('background-color: #111; border: 1px solid #666;')
        self.remote_size = (0, 0)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.last_image_size = None
        self._show_cursor = False
        self._cursor_x = -1
        self._cursor_y = -1

    def mousePressEvent(self, event):
        if self.remote_size[0] == 0 or self.remote_size[1] == 0:
            return
        btn = self._get_button(event)
        if btn and self.clicked_callback:
            x, y = self._map_coords(event)
            self.clicked_callback(x, y, btn)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton and self.clicked_callback:
            x, y = self._map_coords(event)
            self.clicked_callback(x, y, 'left')
        elif self._show_cursor and not event.buttons():
            # Sync remote cursor position
            self._cursor_x, self._cursor_y = self._map_coords(event)
            self.update()

    def _get_button(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            return 'left'
        elif event.button() == Qt.MouseButton.RightButton:
            return 'right'
        return None

    def _map_coords(self, event):
        if self.remote_size[0] == 0 or self.remote_size[1] == 0:
            return (0, 0)
        label_w = self.width()
        label_h = self.height()
        x = event.position().x()
        y = event.position().y()
        rel_x = max(0, min(x / label_w, 1.0))
        rel_y = max(0, min(y / label_h, 1.0))
        return (int(rel_x * self.remote_size[0]), int(rel_y * self.remote_size[1]))

    def update_image(self, image_data, width: int, height: int):
        raw = None
        if isinstance(image_data, (bytes, bytearray)):
            raw = bytes(image_data)
        else:
            try:
                raw = base64.b64decode(image_data)
            except Exception:
                self.setText('Invalid image data')
                return

        if raw is None or len(raw) < 200:
            self.setText('Image data too small')
            return

        image = QImage.fromData(raw)
        if image.isNull():
            self.setText('Invalid image data')
            return

        pixmap = QPixmap.fromImage(image)
        self.last_image_size = (pixmap.width(), pixmap.height())
        self.remote_size = (width, height)

        # Draw remote cursor if enabled
        if self._show_cursor and self._cursor_x >= 0:
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(0, 255, 0), 2)
            painter.setPen(pen)
            painter.drawEllipse(self._cursor_x - 5, self._cursor_y - 5, 10, 10)
            painter.drawLine(self._cursor_x - 10, self._cursor_y, self._cursor_x + 10, self._cursor_y)
            painter.drawLine(self._cursor_x, self._cursor_y - 10, self._cursor_x, self._cursor_y + 10)
            painter.end()

        scaled = pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)


# ── Main Window ────────────────────────────────────────
class ClientWindow(QMainWindow):
    image_signal = pyqtSignal(object, int, int)
    ui_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Simple Remote Control - Client')
        self.setMinimumSize(900, 600)
        self.client = None
        self.streaming = False
        self.image_signal.connect(self._on_image_signal)
        self.ui_signal.connect(self._on_ui_signal)
        self.stream_thread = None
        self.stream_stop = threading.Event()

        # Load saved connections
        self.connections = _load_connections()

        # Settings
        self.quality = 60
        self.fps = 45
        self.delay = 50           # ms delay for streaming (higher = less CPU)
        self._last_selected = -1  # index of last used connection

        self._build_menu()
        self._build_ui()

        # Auto-fill last used connection
        self._restore_last_connection()

    def _restore_last_connection(self):
        if not self.connections:
            return
        # Find last used (look for a 'last_used' flag)
        for i, conn in enumerate(self.connections):
            if conn.get('last_used'):
                self._last_selected = i
                break
        if self._last_selected < 0:
            self._last_selected = 0  # fallback to first

        if 0 <= self._last_selected < len(self.connections):
            conn = self.connections[self._last_selected]
            self.host_input.setText(conn.get('host', '127.0.0.1'))
            self.port_input.setText(str(conn.get('port', 8765)))
            self.token_input.setText(conn.get('token', ''))

    # ── Menu ────────────────────────────────────────────
    def _build_menu(self):
        menubar = self.menuBar()

        conn_menu = menubar.addMenu('Connections')
        manage_action = QAction('Manage Connections...', self)
        manage_action.triggered.connect(self._show_connection_manager)
        conn_menu.addAction(manage_action)

        settings_menu = menubar.addMenu('Settings')
        quality_action = QAction('Image Quality...', self)
        quality_action.triggered.connect(self._show_quality_dialog)
        settings_menu.addAction(quality_action)

        fps_action = QAction('Stream FPS...', self)
        fps_action.triggered.connect(self._show_fps_dialog)
        settings_menu.addAction(fps_action)

        delay_action = QAction('Stream Delay...', self)
        delay_action.triggered.connect(self._show_delay_dialog)
        settings_menu.addAction(delay_action)

        cursor_action = QAction('Remote Cursor', self)
        cursor_action.setCheckable(True)
        cursor_action.setChecked(False)
        cursor_action.triggered.connect(
            lambda checked: setattr(self.screen_label, '_show_cursor', checked))
        settings_menu.addAction(cursor_action)

        help_menu = menubar.addMenu('Help')
        about_action = QAction('About', self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self):
        QMessageBox.about(
            self, 'About Simple Remote Control',
            'Simple Remote Control\n\n'
            'Copyright (c) 2024\n\n'
            'MIT License\n\n'
            'Permission is hereby granted, free of charge, to any person '
            'obtaining a copy of this software...'
        )

    def _show_quality_dialog(self):
        value, ok = QInputDialog.getInt(
            self, 'Image Quality', 'JPEG quality (10-95):',
            self.quality, 10, 95, 1)
        if ok:
            self.quality = value

    def _show_fps_dialog(self):
        value, ok = QInputDialog.getInt(
            self, 'Stream FPS', 'Frames per second (1-60):',
            self.fps, 1, 60, 1)
        if ok:
            self.fps = value

    def _show_delay_dialog(self):
        value, ok = QInputDialog.getInt(
            self, 'Stream Delay', 'Delay between frames (ms, 0-500):\n'
            'Lower = smoother but more CPU/bandwidth',
            self.delay, 0, 500, 10)
        if ok:
            self.delay = value

    # ── Connection Manager ──────────────────────────────
    def _show_connection_manager(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Manage Connections')
        dialog.setMinimumSize(450, 350)

        layout = QVBoxLayout(dialog)

        self._conn_list = QListWidget()
        self._refresh_conn_list()
        layout.addWidget(self._conn_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton('Add')
        edit_btn = QPushButton('Edit')
        delete_btn = QPushButton('Delete')
        select_btn = QPushButton('Connect')
        close_btn = QPushButton('Close')

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(delete_btn)
        btn_layout.addWidget(select_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        add_btn.clicked.connect(lambda: self._conn_add())
        edit_btn.clicked.connect(lambda: self._conn_edit())
        delete_btn.clicked.connect(lambda: self._conn_delete())
        select_btn.clicked.connect(lambda: self._conn_select(dialog))
        close_btn.clicked.connect(dialog.accept)

        dialog.exec()

    def _refresh_conn_list(self):
        self._conn_list.clear()
        for i, conn in enumerate(self.connections):
            name = conn.get('name', 'Unnamed')
            host = conn.get('host', '')
            port = conn.get('port', 8765)
            marker = ' ✓' if i == self._last_selected else ''
            item = QListWidgetItem(f'{name}  ({host}:{port}){marker}')
            item.setData(Qt.ItemDataRole.UserRole, i)
            self._conn_list.addItem(item)

    def _conn_add(self):
        dialog = ConnectionEditDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if not data['name'] or not data['host']:
                QMessageBox.warning(self, 'Invalid', 'Name and host are required.')
                return
            self.connections.append(data)
            _save_connections(self.connections)
            self._refresh_conn_list()

    def _conn_edit(self):
        current = self._conn_list.currentItem()
        if not current:
            return
        idx = current.data(Qt.ItemDataRole.UserRole)
        conn = self.connections[idx]
        dialog = ConnectionEditDialog(
            self, conn.get('name', ''), conn.get('host', ''),
            conn.get('port', 8765), conn.get('token', ''))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.connections[idx] = dialog.get_data()
            _save_connections(self.connections)
            self._refresh_conn_list()

    def _conn_delete(self):
        current = self._conn_list.currentItem()
        if not current:
            return
        idx = current.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, 'Delete', 'Delete this connection?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.connections.pop(idx)
            if self._last_selected >= len(self.connections):
                self._last_selected = -1
            _save_connections(self.connections)
            self._refresh_conn_list()

    def _conn_select(self, dialog):
        current = self._conn_list.currentItem()
        if not current:
            return
        idx = current.data(Qt.ItemDataRole.UserRole)
        conn = self.connections[idx]
        self.host_input.setText(conn.get('host', '127.0.0.1'))
        self.port_input.setText(str(conn.get('port', 8765)))
        self.token_input.setText(conn.get('token', ''))

        # Mark as last used
        for c in self.connections:
            c['last_used'] = False
        self.connections[idx]['last_used'] = True
        self._last_selected = idx
        _save_connections(self.connections)

        dialog.accept()
        QMessageBox.information(self, 'Selected',
                                f'Connection "{conn.get("name")}" selected.\nClick Connect to use it.')

    # ── UI ──────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout()
        central.setLayout(ml)

        # Connection row
        cr = QHBoxLayout()
        cr.addWidget(QLabel('Host:'))
        self.host_input = QLineEdit('127.0.0.1')
        cr.addWidget(self.host_input)
        cr.addWidget(QLabel('Port:'))
        self.port_input = QLineEdit('8765')
        self.port_input.setFixedWidth(65)
        cr.addWidget(self.port_input)
        cr.addWidget(QLabel('Token:'))
        self.token_input = QLineEdit('secret-token-123')
        cr.addWidget(self.token_input)
        ml.addLayout(cr)

        # Status
        self.status_label = QLabel('Disconnected')
        self.status_label.setStyleSheet('color: #888; font-weight: bold;')
        ml.addWidget(self.status_label)

        # Buttons
        br = QHBoxLayout()
        self.connect_btn = QPushButton('Connect')
        self.disconnect_btn = QPushButton('Disconnect')
        self.disconnect_btn.setEnabled(False)
        self.refresh_btn = QPushButton('Refresh')
        self.refresh_btn.setEnabled(False)
        self.stream_btn = QPushButton('Start Stream')
        self.stream_btn.setEnabled(False)
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText('Enter text or key, press Enter')
        self.key_input.setEnabled(False)

        br.addWidget(self.connect_btn)
        br.addWidget(self.disconnect_btn)
        br.addWidget(self.refresh_btn)
        br.addWidget(self.stream_btn)
        ml.addLayout(br)

        # Info
        il = QHBoxLayout()
        self.ql = QLabel(f'Q:{self.quality}')
        self.ql.setStyleSheet('color:#555;')
        self.fl = QLabel(f'FPS:{self.fps}')
        self.fl.setStyleSheet('color:#555;')
        self.dl = QLabel(f'Delay:{self.delay}ms')
        self.dl.setStyleSheet('color:#555;')
        il.addWidget(self.ql)
        il.addWidget(self.fl)
        il.addWidget(self.dl)
        il.addStretch()
        ml.addLayout(il)

        # Screen - expand to fill available space
        self.screen_label = RemoteScreenLabel(self)
        self.screen_label.setText('Remote screen will appear here')
        self.screen_label.setMinimumSize(400, 250)
        self.screen_label.clicked_callback = self.on_screen_click
        ml.addWidget(self.screen_label, 1)  # stretch factor 1

        # Key input
        kl = QHBoxLayout()
        kl.addWidget(self.key_input)
        ml.addLayout(kl)

        self.connect_btn.clicked.connect(self.on_connect)
        self.disconnect_btn.clicked.connect(self.on_disconnect)
        self.refresh_btn.clicked.connect(self.on_refresh)
        self.stream_btn.clicked.connect(self.on_toggle_stream)
        self.key_input.returnPressed.connect(self.on_send_key)

    def _set_connected_ui(self, connected: bool):
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.refresh_btn.setEnabled(connected)
        self.stream_btn.setEnabled(connected)
        self.key_input.setEnabled(connected)

    # ── Handlers ────────────────────────────────────────
    def _on_image_signal(self, data, w, h):
        self.screen_label.update_image(data, w, h)

    def _on_ui_signal(self, fn):
        fn()

    def on_connect(self):
        if self.client is not None:
            return
        # Disable button immediately to prevent double-clicks
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText('Connecting...')

        host = self.host_input.text().strip()
        port = int(self.port_input.text().strip())
        token = self.token_input.text().strip()
        self.client = RemoteClient(host, port, token=token)

        def worker():
            try:
                self.client.connect_sync()
                self._invoke_ui(lambda: self._on_connect_success())
            except Exception as exc:
                err = str(exc)
                self.client = None
                self._invoke_ui(lambda e=err: self._on_connect_fail(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_connect_success(self):
        self.status_label.setText('Connected')
        self.status_label.setStyleSheet('color: green; font-weight: bold;')
        self.connect_btn.setText('Connect')
        self._set_connected_ui(True)

    def _on_connect_fail(self, reason):
        self.status_label.setText('Disconnected')
        self.status_label.setStyleSheet('color: #888; font-weight: bold;')
        self.connect_btn.setText('Connect') 
        self.connect_btn.setEnabled(True) 
        QMessageBox.critical(self, 'Connection Failed', f'Failed to connect:\n{reason}')

    def on_disconnect(self):
        if self.client is None:
            return

        def worker():
            try:
                self.stream_stop.set()
                if self.stream_thread is not None:
                    self.stream_thread.join(2)
                self.client.close_sync()
            except Exception:
                pass
            finally:
                self.client = None
                self.streaming = False
                self._invoke_ui(lambda: self._on_disconnect_done())

        threading.Thread(target=worker, daemon=True).start()

    def _on_disconnect_done(self):
        self.status_label.setText('Disconnected')
        self.status_label.setStyleSheet('color: #888; font-weight: bold;')
        self.connect_btn.setText('Connect')
        self._set_connected_ui(False)
        self.stream_btn.setText('Start Stream')
        self.connect_btn.setEnabled(True)

    def on_refresh(self):
        if self.client is None:
            QMessageBox.warning(self, 'Not Connected', 'Connect first.')
            return

        def worker():
            try:
                response = self.client.send_command_sync({
                    'command_type': 'screen_capture',
                    'args': {'quality': self.quality}
                })
                payload = response if isinstance(response, dict) else {}
                if payload.get('error'):
                    self._invoke_ui(lambda e=payload.get('error'):
                        QMessageBox.critical(self, 'Error', f'Server: {e}'))
                    return
                img = payload.get('image') or payload.get('image_bytes')
                w, h = payload.get('width'), payload.get('height')
                if img and w and h:
                    self.image_signal.emit(img, w, h)
                else:
                    self._invoke_ui(lambda:
                        QMessageBox.warning(self, 'No Image', 'No image from server.'))
            except Exception as exc:
                self._invoke_ui(lambda e=str(exc):
                    QMessageBox.critical(self, 'Error', str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_stream_worker(self):
        self.stream_stop.clear()
        delay_s = self.delay / 1000.0
        while not self.stream_stop.is_set() and self.client is not None:
            try:
                response = self.client.send_command_sync({
                    'command_type': 'screen_capture',
                    'args': {'quality': self.quality}
                })
                payload = response if isinstance(response, dict) else {}
                img = payload.get('image') or payload.get('image_bytes')
                w, h = payload.get('width'), payload.get('height')
                if img and w and h:
                    self.image_signal.emit(img, w, h)
                else:
                    break
            except Exception:
                break
            # Use the larger of: 1/fps or delay
            sleep_time = max(1.0 / max(self.fps, 1), delay_s)
            self.stream_stop.wait(sleep_time)

    def on_toggle_stream(self):
        if self.client is None:
            QMessageBox.warning(self, 'Not Connected', 'Connect first.')
            return
        if not self.streaming:
            self.streaming = True
            self.stream_btn.setText('Stop')
            self.stream_stop.clear()
            self.stream_thread = threading.Thread(target=self._refresh_stream_worker, daemon=True)
            self.stream_thread.start()
            self.status_label.setText(f'Streaming ({self.fps}fps, d={self.delay}ms)')
            self.status_label.setStyleSheet('color: #06c; font-weight: bold;')
        else:
            self.streaming = False
            self.stream_btn.setText('Start Stream')
            self.stream_stop.set()
            self.status_label.setText('Connected')
            self.status_label.setStyleSheet('color: green; font-weight: bold;')

    def on_screen_click(self, x: int, y: int, button: str = 'left'):
        if self.client is None:
            return

        def worker():
            try:
                self.client.send_command_sync({
                    'command_type': 'mouse_click',
                    'args': {'button': button, 'x': x, 'y': y}
                })
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def on_send_key(self):
        if self.client is None:
            QMessageBox.warning(self, 'Not Connected', 'Connect first.')
            return
        text = self.key_input.text().strip()
        if not text:
            return

        def worker():
            try:
                ct = 'key_write' if len(text) > 1 else 'key_press'
                args = {'text': text} if ct == 'key_write' else {'key': text}
                self.client.send_command_sync({'command_type': ct, 'args': args})
                self._invoke_ui(lambda: self.key_input.clear())
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _invoke_ui(self, fn):
        self.ui_signal.emit(fn)


def run_client():
    app = QApplication(sys.argv)
    w = ClientWindow()
    w.show()
    sys.exit(app.exec())