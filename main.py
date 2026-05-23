import sys

def run_server():
    import asyncio
    from app.network.server import run_server as _run
    asyncio.run(_run())

def run_client():
    from app.ui.client import run_client
    run_client()

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'server':
        run_server()
    else:
        run_client()
