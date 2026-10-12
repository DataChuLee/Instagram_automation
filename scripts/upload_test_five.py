from pathlib import Path
import json
import urllib.request
ROOT = Path(__file__).resolve().parents[1] / 'output/test5_20261009'
for item in json.loads((ROOT / 'uploads.json').read_text(encoding='utf-8')):
    path = ROOT / f"{item['number']:02}_input.jpg"
    request = urllib.request.Request(item['upload_url'], data=path.read_bytes(),
                                    headers=item.get('headers') or {'Content-Type': 'image/jpeg'}, method='PUT')
    with urllib.request.urlopen(request, timeout=90) as response:
        print(item['number'], response.status)
