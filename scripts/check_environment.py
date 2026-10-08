"""Report capabilities without reading credentials."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.tools/python'))
modules = ['fastapi', 'uvicorn', 'pydantic', 'httpx', 'PIL', 'playwright', 'mcp',
           'multipart', 'PyInstaller', 'pytest', 'imageio_ffmpeg']
print(json.dumps({'python': sys.version, 'modules': {name: bool(importlib.util.find_spec(name))
    for name in modules}, 'codex': shutil.which('codex'), 'node': shutil.which('node')}, indent=2))
