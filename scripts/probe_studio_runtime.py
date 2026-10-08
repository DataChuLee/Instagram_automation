from pathlib import Path
import sys
import inspect
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT / '.tools/studio-python'))
sys.stdout.reconfigure(encoding='utf-8')
from studio.fish import protect, Fish
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import AuthorizationCodeResult
from mcp.client.streamable_http import streamable_http_client
print('OAuth:',inspect.signature(OAuthClientProvider))
print('Transport:',inspect.signature(streamable_http_client))
assert protect(protect(b'local-test'),True)==b'local-test'
print('DPAPI roundtrip passed')
import asyncio
from studio.codex import login_status, executable
print('Codex:',executable())
print('ChatGPT login:',asyncio.run(login_status()))
from studio.app import app
print('FastAPI app ready')
