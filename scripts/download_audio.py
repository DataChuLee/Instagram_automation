import json
from pathlib import Path
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
story = json.loads((root / 'output/storyboard.json').read_text(encoding='utf-8'))
for scene in story['scenes']:
    target = root / scene['audio']
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size > 1000:
        continue
    with urlopen(scene['audio_url'], timeout=60) as response:
        data = response.read()
    target.write_bytes(data)
    print(target.name, len(data), flush=True)
