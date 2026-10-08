"""Decode the deliverable, check timing, and extract actual output frames."""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/python'))
import imageio_ffmpeg

ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
output = ROOT / 'output'
video = output / 'stay_reel.mp4'
story = json.loads((output / 'storyboard.json').read_text(encoding='utf-8'))
reader = imageio_ffmpeg.read_frames(str(video))
metadata = next(reader)
reader.close()
assert metadata['size'] == (1080, 1920), metadata
assert abs(metadata['fps'] - 30) < 0.01, metadata
assert abs(metadata['duration'] - story['duration']) < 0.15, metadata
used = [p for scene in story['scenes'] for p in scene['images']]
assert sorted(used) == list(range(17)), used
last_end = 0
for scene in story['scenes']:
    assert abs(scene['start'] - last_end) < 1e-6
    assert scene['duration'] >= scene['audio_duration']
    last_end = scene['start'] + scene['duration']
result = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-xerror',
                         '-i', str(video), '-map', '0:v:0', '-map', '0:a:0',
                         '-f', 'null', '-'], capture_output=True)
assert result.returncode == 0, result.stderr.decode(errors='replace')
frames, seconds = imageio_ffmpeg.count_frames_and_secs(str(video))
assert frames == round(story['duration'] * 30), (frames, story['duration'])
sheet = Image.new('RGB', (1350, 1000), '#181818')
draw = ImageDraw.Draw(sheet)
for i, scene in enumerate(story['scenes']):
    time = scene['start'] + min(0.35, scene['audio_duration'] / 2)
    path = output / 'render' / f'verified_{i:02}.jpg'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(time),
                    '-i', str(video), '-frames:v', '1', str(path)], check=True)
    with Image.open(path) as image:
        thumb = ImageOps.contain(image, (260, 462))
    x, y = (i % 5) * 270, (i // 5) * 500
    sheet.paste(thumb, (x, y + 28))
    draw.text((x + 8, y + 8), f'{i+1} / {time:.2f}s', fill='white')
sheet.save(output / 'preview.jpg', quality=92)
report = dict(width=1080, height=1920, fps=30, frames=frames, duration=seconds,
              full_decode='passed', audio_stream='present', photos_used=17,
              voice=story['voice_title'], credits_charged=sum(s['credits_charged'] for s in story['scenes']))
(output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=True, indent=2))
