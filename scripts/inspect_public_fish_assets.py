"""Download only public JS assets to confirm editor UI contracts, no login/generation."""
from pathlib import Path
import re
import sys
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
html=(ROOT / '.local/probes/fish-editor.html').read_text(encoding='utf-8')
links=re.findall(r'(?:href|src)="([^\"]+\.js[^\"]*)"',html)
links=list(dict.fromkeys(link for link in links if any(term in link.lower() for term in ('text-to-speech','tts','voice','credit','drama','beta-','pricing-config','billing-','task-','usage-units','use-audio-download','long-text-studio-prompt'))))
out=ROOT / '.local/probes/public-js'
out.mkdir(parents=True,exist_ok=True)
for link in links:
    url=link if link.startswith('https://') else 'https://beta.fish.audio'+link
    name=url.split('/')[-1].split('?')[0]
    if (out / name).exists():continue
    with urllib.request.urlopen(url,timeout=40) as response:data=response.read()
    (out / name).write_bytes(data)
    print(name,len(data),flush=True)
