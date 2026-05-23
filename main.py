import sys

def run_server_gui():
    from app.ui.server_gui import run_server_gui as _run
    _run()

def run_client():
    from app.ui.client import run_client
    run_client()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'server':
        run_server_gui()
    else:
        run_client()
