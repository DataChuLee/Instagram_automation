from pathlib import Path
import sys
import json
import re
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
with urllib.request.urlopen('http://127.0.0.1:8766/api/connections',timeout=15) as response:
    value=json.load(response)
print({key:value.get(key) for key in ('codex','fish','drama_open','codex_busy','fish_busy')})
message=value.get('message','')
print('Connection:', message.split('?')[0][:1000])
login=value.get('codex_login','')
print('Codex:',re.sub(r'https?://\S+', '[official login URL]',login)[:700])
