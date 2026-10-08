from pathlib import Path
import json
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
record=json.loads((ROOT / '.local/probes/upload-check.json').read_text(encoding='utf-8'))
data=(ROOT / '.local/jobs/dddddddddddddddddddddddddddddddd/render/photo-003.jpg').read_bytes()
request=urllib.request.Request(record['upload_url'],data=data,headers=record['headers'],method=record['method'])
with urllib.request.urlopen(request,timeout=60) as response:
    print('Photo upload completed:',response.status)
