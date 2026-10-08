"""Loopback-only desktop launcher, also the Windows frozen entry point."""
from pathlib import Path
import argparse
import os
import sys

ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
if (ROOT / 'tools/ms-playwright').exists():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / 'tools/ms-playwright')
elif (ROOT / '.tools/ms-playwright').exists():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.tools/ms-playwright')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    import uvicorn
    from studio.app import app, fish
    fish.base_url = f'http://127.0.0.1:{args.port}'
    if not args.no_browser:
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(fish.base_url)).start()
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
