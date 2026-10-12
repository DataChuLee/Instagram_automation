"""Read-only freeze detection on a rendered video and its reported photo boundaries."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.tools/studio-python'), str(ROOT)]
sys.stdout.reconfigure(encoding='utf-8')
from studio.render import ffmpeg

parser = argparse.ArgumentParser()
parser.add_argument('video', type=Path)
parser.add_argument('--motion-changes', action='store_true')
args = parser.parse_args()
result = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(args.video), '-an', '-vf',
    'scale=320:-2,freezedetect=n=-60dB:d=0.12', '-f', 'null', '-'], capture_output=True,
    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
text = result.stderr.decode('utf-8', 'replace')
holds = [line.strip() for line in text.splitlines() if 'lavfi.freezedetect.' in line]
report = args.video.parent / 'verification.json'
if report.is_file():
    timeline = json.loads(report.read_text(encoding='utf-8'))['timeline']
    print('Photo boundaries:', [round(p['start'], 3) for p in timeline])
print('Freeze events:', holds)
assert result.returncode == 0, text[-2000:]
if args.motion_changes:
    from PIL import Image, ImageChops, ImageStat
    raw = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(args.video), '-an', '-vf',
        'scale=160:284,format=gray', '-f', 'rawvideo', '-'], capture_output=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert raw.returncode == 0
    size, previous, changes = 160 * 284, None, []
    boundaries = [p['start'] for p in timeline] if report.is_file() else []
    for index in range(len(raw.stdout) // size):
        frame = Image.frombytes('L', (160, 284), raw.stdout[index * size:(index + 1) * size])
        seconds = index / 30
        if previous is not None and all(abs(seconds - cut) > .1 for cut in boundaries):
            change = ImageStat.Stat(ImageChops.difference(frame, previous)).mean[0]
            changes.append((round(seconds, 3), round(change, 3)))
        previous = frame
    print('Largest changes within a photo:', sorted(changes, key=lambda p: p[1], reverse=True)[:5])
    print('Decoded frames:', len(raw.stdout) // size)
