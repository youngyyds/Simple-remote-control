"""Server GUI for configuring and running the remote control server."""

import sys
import json
import os
import threading

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMenuBar, QMessageBox, QPushButton, QVBoxLayout, QWidget, QTextEdit
)

import asyncio
from app.network.server import run_server as _run_async_server

CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.simple-remote-control')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'server_config.json')


def load_server_config() -> dict:
    defaults = {'token': '', 'port': 8765}
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return {**defaults, **data}
    except Exception:
        pass
    return defaults


def save_server_config(config: dict):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f'Failed to save server config: {exc}')


class ServerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Simple Remote Control - Server')
        self.setMinimumSize(500, 300)

        self.config = load_server_config()
        self._server_task = None
        self._running = False

        self._build_menu()
        self._build_ui()
        self._apply_config()

    def _build_menu(self):
        menubar = self.menuBar()
        help_menu = menubar.addMenu('Help')
        about_action = QAction('About', self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self):
        QMessageBox.about(
            self, 'About Simple Remote Control Server',
            'Simple Remote Control - Server\n\n'
            'MIT License\n\n'
            'Configure token and port, then start the server.'
        )

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        ml = QVBoxLayout()
        central.setLayout(ml)

        # Token
        token_layout = QHBoxLayout()
        token_layout.addWidget(QLabel('Token (secret key):'))
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText('Leave empty for no auth (not recommended)')
        token_layout.addWidget(self.token_input)
        ml.addLayout(token_layout)

        # Port
        port_layout = QHBoxLayout()
        port_layout.addWidget(QLabel('Port:'))
        self.port_input = QLineEdit('8765')
        self.port_input.setFixedWidth(100)
        port_layout.addWidget(self.port_input)
        port_layout.addStretch()
        ml.addLayout(port_layout)

        # Status
        self.status_label = QLabel('Server stopped')
        self.status_label.setStyleSheet('color: #888; font-weight: bold;')
        ml.addWidget(self.status_label)

        # Log
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        ml.addWidget(QLabel('Log:'))
        ml.addWidget(self.log_text)

        # Buttons
        br = QHBoxLayout()
        self.start_btn = QPushButton('Start Server')
        self.stop_btn = QPushButton('Stop Server')
        self.stop_btn.setEnabled(False)
        self.save_btn = QPushButton('Save Config')
        br.addWidget(self.start_btn)
        br.addWidget(self.stop_btn)
        br.addWidget(self.save_btn)
        ml.addLayout(br)

        self.start_btn.clicked.connect(self._start_server)
        self.stop_btn.clicked.connect(self._stop_server)
        self.save_btn.clicked.connect(self._save_config)

    def _apply_config(self):
        self.token_input.setText(self.config.get('token', ''))
        self.port_input.setText(str(self.config.get('port', 8765)))

    def _save_config(self):
        self.config['token'] = self.token_input.text().strip()
        try:
            self.config['port'] = int(self.port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, 'Invalid Port', 'Port must be a number.')
            return
        save_server_config(self.config)
        QMessageBox.information(self, 'Saved', 'Configuration saved.')

    def _start_server(self):
        if self._running:
            return

        token = self.token_input.text().strip()
        if not token:
            reply = QMessageBox.warning(
                self, 'No Token',
                'Token is empty! Anyone can connect to this server.\n\n'
                'Continue anyway?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            QMessageBox.warning(self, 'Invalid Port', 'Port must be a number.')
            return

        # Save token to auth module
        from app.core import auth
        if token:
            auth.VALID_TOKENS = {token}
        else:
            auth.VALID_TOKENS = set()  # Allow all

        # Save config
        self.config['token'] = token
        self.config['port'] = port
        save_server_config(self.config)

        self._running = True
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText(f'Server running on port {port}')
        self.status_label.setStyleSheet('color: green; font-weight: bold;')
        self.log_text.append(f'Starting server on 0.0.0.0:{port}')

        def run_async():
            import asyncio
            try:
                asyncio.run(_run_async_server(host='0.0.0.0', port=port))
            except Exception as exc:
                self._invoke_ui(lambda e=str(exc):
                    self.log_text.append(f'Server error: {e}'))
            finally:
                self._invoke_ui(lambda: self._on_server_stopped())

        threading.Thread(target=run_async, daemon=True).start()

    def _stop_server(self):
        self.log_text.append('Stopping server...')
        os._exit(0)  # Force exit since asyncio can't be easily cancelled

    def _on_server_stopped(self):
        self._running = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText('Server stopped')
        self.status_label.setStyleSheet('color: #888; font-weight: bold;')

    def _invoke_ui(self, fn):
        QTimer.singleShot(0, fn)


def run_server_gui():
    app = QApplication(sys.argv)
    w = ServerWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    run_server_gui()