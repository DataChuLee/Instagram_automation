"""Smoke-test the portable executable from another cwd without paid calls."""
import io
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
import sys
import shutil
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
parser = argparse.ArgumentParser()
parser.add_argument('--live', action='store_true', help='Also refresh the public listing in the bundled browser')
args = parser.parse_args()
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
from PIL import Image

folder = ROOT / 'dist/StayStudio'
probe = ROOT / '.local/probes/frozen'
probe.mkdir(parents=True, exist_ok=True)
collection_id = 'c' * 32
collection_root = probe / 'data/collections' / collection_id
source = ROOT / 'Data/accommodations/9816'
collection_root.mkdir(parents=True, exist_ok=True)
shutil.copytree(source / 'images', collection_root / 'images', dirs_exist_ok=True)
shutil.copy2(source / 'manifest.json', collection_root / 'manifest.json')
env = os.environ.copy()
env['STAY_STUDIO_DATA'] = str(probe / 'data')
log = (probe / 'server.log').open('wb')
process = subprocess.Popen([str(folder / 'StayStudio.exe'), '--no-browser', '--port', '8767'],
    cwd=probe, env=env, stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
base = 'http://127.0.0.1:8767'
try:
    for attempt in range(40):
        if process.poll() is not None:
            raise RuntimeError('Frozen server exited; inspect local probe log')
        try:
            with urllib.request.urlopen(base, timeout=2) as response:
                html = response.read().decode()
            break
        except OSError:
            time.sleep(0.5)
    else:
        raise RuntimeError('Frozen server startup timeout')
    assert 'stay' in html
    token = re.search(r'name="studio-token" content="([^"]+)"', html).group(1)
    def api(path, value=None):
        request = urllib.request.Request(base + path, None if value is None else json.dumps(value).encode(),
            headers={'Content-Type': 'application/json', 'X-Studio-Token': token})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    image = io.BytesIO()
    Image.new('RGB', (360, 640), '#557766').save(image, format='JPEG')
    boundary = 'STUDIO-FROZEN-PROBE'
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
        'filename="probe.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode()
    body += image.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
    request = urllib.request.Request(base+'/api/jobs', body,
        {'X-Studio-Token': token, 'Content-Type': 'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request) as response:
        job = json.load(response)
    request = urllib.request.Request(base+'/api/jobs/'+job['id']+'/preview',
        json.dumps({'photo': 0, 'text': '숙소 미리보기', 'caption': job['options']['caption']}).encode(),
        {'X-Studio-Token': token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request) as response:
        preview = Image.open(io.BytesIO(response.read()))
        assert preview.size == (1080,1920)
    for executable in ('tools/ffmpeg.exe', 'tools/codex-runtime/bin/codex.exe'):
        path = folder / '_internal' / executable
        result = subprocess.run([str(path), '-version' if 'ffmpeg' in executable else '--version'],
            cwd=probe, env=env, capture_output=True, timeout=15)
        assert result.returncode == 0, executable
    assert list((folder/'_internal/tools/ms-playwright').glob('chromium-*/chrome-win64/chrome.exe'))
    print('Frozen EXE: independent cwd, upload, 1080x1920 caption preview, bundled FFmpeg/Codex/Chromium passed')
    gallery = api('/api/collections/' + collection_id)
    assert len(gallery['photos']) == 56
    job = api('/api/jobs/import', {'collection_id': collection_id,
                                 'photos': [p['id'] for p in gallery['photos'][:6]], 'job_id': job['id']})
    assert len(job['photos']) == 7
    assert job['sources'][0]['name'] == '여수 돌산 더 호텔 수'
    job_root = probe / 'data/jobs' / job['id']
    saved = json.loads((job_root / 'job.json').read_text(encoding='utf-8'))
    saved['options']['max_motion'] = 0
    (job_root / 'job.json').write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
    edited = api(f"/api/jobs/{job['id']}/storyboard", {
        'scenes': [{'photos': list(range(7)), 'text': '숙소에서 보내는 하루'}],
        'motion': [{'photo': i, 'prompt': '  물결이 잔잔하게 움직여요  '} for i in range(7)]})
    assert len(edited['storyboard']['motion']) == 7
    assert edited['storyboard']['motion'][-1] == {'photo': 6, 'prompt': '물결이 잔잔하게 움직여요'}
    assert edited['quote'] is None and edited['state'] == 'uploaded'
    api(f"/api/jobs/{job['id']}/style", {'max_motion': 7})
    api(f"/api/jobs/{job['id']}/storyboard", {'scenes': [{'photos': list(range(7)), 'text': '숙소에서 보내는 하루'}]})
    print('Frozen EXE: all seven photos as motion with AI count zero and prompt trimming passed', flush=True)
    with wave.open(str(job_root / 'fixture.wav'), 'wb') as voice:
        voice.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        voice.writeframes(b'\0\0' * 24000)
    saved = json.loads((job_root / 'job.json').read_text(encoding='utf-8'))
    saved['narration'] = {'0': {'file': 'fixture.wav', 'source': 'local smoke-test fixture'}}
    (job_root / 'job.json').write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
    assert (folder/'_internal/studio/skills/stay-shortform/SKILL.md').is_file()
    api(f"/api/jobs/{job['id']}/preview-video", {})
    for _ in range(120):
        job = api('/api/jobs/' + job['id'])
        if job['state'] not in {'uploaded', 'previewing'}:
            break
        time.sleep(0.5)
    assert job['state'] == 'preview_ready', job.get('error')
    before = (job_root/job['preview']['file']).read_bytes()
    api(f"/api/jobs/{job['id']}/render", {})
    for _ in range(40):
        job = api('/api/jobs/' + job['id'])
        if job['state'] == 'complete': break
        time.sleep(0.25)
    assert job['state'] == 'complete', job.get('error')
    assert before == (job_root/'stay-reel.mp4').read_bytes()
    for name in ['stay-reel.mp4', 'stay-video.mp4', 'stay-script.txt', 'stay-reel.srt', 'stay-voice.mp3']:
        with urllib.request.urlopen(f"{base}/api/jobs/{job['id']}/files/{name}") as response:
            assert 'attachment' in response.headers['Content-Disposition']
            assert response.read()
    assert (folder / '_internal/studio/web/app.js').read_bytes() == (ROOT / 'studio/web/app.js').read_bytes()
    print('Frozen EXE: collection gallery/import, saved-media render and all output downloads passed', flush=True)
    if args.live:
        gallery = api('/api/collections', {'url': 'https://www.yeogi.com/domestic-accommodations/9816'})
        for _ in range(120):
            if gallery['status'] != 'in_progress':
                break
            time.sleep(1)
            gallery = api('/api/collections/' + gallery['id'])
        assert gallery['status'] in {'complete', 'partial'} and gallery['photos'], gallery.get('error')
        print(f"Frozen EXE: real listing refresh with bundled browser passed ({len(gallery['photos'])} unique photos)", flush=True)
finally:
    process.terminate()
    process.wait(timeout=20)
    log.close()
