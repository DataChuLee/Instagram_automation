"""Keep this program's pending login link across a development server restart."""
from pathlib import Path
import json
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
with urllib.request.urlopen('http://127.0.0.1:8766/api/connections',timeout=15) as response:
    value=json.load(response)
path=ROOT / '.local/auth/codex-login-message.txt'
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(value.get('codex_login',''),encoding='utf-8')
print('Pending local login display preserved; no tokens copied')
