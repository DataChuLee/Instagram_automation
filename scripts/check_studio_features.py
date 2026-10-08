"""Exercise the new UI with saved public photos and narration in an isolated data directory."""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

probe = ROOT / '.local/probes/features'
data = probe / 'data'
collection_id = 'c' * 32
collection_root = data / 'collections' / collection_id
collection_root.mkdir(parents=True, exist_ok=True)
source = ROOT / 'Data/accommodations/9816'
shutil.copytree(source / 'images', collection_root / 'images', dirs_exist_ok=True)
shutil.copy2(source / 'manifest.json', collection_root / 'manifest.json')
environment = os.environ.copy()
environment['STAY_STUDIO_DATA'] = str(data)
environment['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.tools/ms-playwright')
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = environment['PLAYWRIGHT_BROWSERS_PATH']
port = 8768
base = f'http://127.0.0.1:{port}'
log = (probe / 'server.log').open('wb')
process = subprocess.Popen([sys.executable, str(ROOT / 'launch.py'), '--no-browser', '--port', str(port)],
    cwd=probe, env=environment, stdout=log, stderr=log,
    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
try:
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError('Test server exited; inspect .local/probes/features/server.log')
        try:
            with urllib.request.urlopen(base, timeout=2) as response:
                html = response.read().decode()
            break
        except OSError:
            time.sleep(0.3)
    else:
        raise RuntimeError('Test server failed to start')
    token = re.search(r'name="studio-token" content="([^"]+)"', html).group(1)

    def api(path, value=None):
        request = urllib.request.Request(base + path, None if value is None else json.dumps(value).encode(),
            headers={'Content-Type': 'application/json', 'X-Studio-Token': token})
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=playwright.chromium.executable_path)
        page = browser.new_page(viewport={'width': 1500, 'height': 1100}, accept_downloads=True)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script(f"localStorage.setItem('stayCollection','{collection_id}')")
        page.goto(base, wait_until='networkidle')
        if page.locator('#settings').evaluate('(el)=>el.open'):
            page.locator('#closeSettings').click()
        assert page.locator('#exportDownloads').is_visible()
        assert page.locator('.export-card').count() == 4
        assert page.locator('#downloadMissing').inner_text() == '생성 후 다운로드'
        assert page.locator('#download').is_hidden()
        page.wait_for_function("document.querySelectorAll('#collectionGrid input').length===56")
        page.locator('#collectionGrid input:not([disabled])').nth(0).check()
        page.locator('#collectionGrid input:not([disabled])').nth(1).check()
        page.locator('#importPhotos').click()
        page.wait_for_function("document.querySelectorAll('#photoGrid button').length===2")
        page.wait_for_function("!document.querySelector('#newJob').disabled && !document.querySelector('#sourceNames').hidden")
        assert '여수 돌산 더 호텔 수' in page.locator('#sourceNames').inner_text()
        photo = sorted((ROOT / 'Data/Test_Data').glob('*.jpg'))[0]
        page.locator('#files').set_input_files(str(photo))
        page.wait_for_function("document.querySelectorAll('#photoGrid button').length===3")
        page.wait_for_function("!document.querySelector('#newJob').disabled")
        # Uploading the identical file a second time must keep all three photos.
        page.locator('#files').set_input_files(str(photo))
        page.wait_for_function("document.querySelector('#files').value==='' && !document.querySelector('#newJob').disabled")
        assert page.locator('#photoGrid button').count() == 3
        print('56-photo gallery, selection, lodging name, attachment append and deduplication passed', flush=True)
        latest = api('/api/jobs')[0]
        job = api('/api/jobs/' + latest['id'])
        api(f"/api/jobs/{job['id']}/storyboard", {'scenes': [{'photos': [0, 1, 2], 'text': '숙소에서 만나는 편안한 하루'}]})
        # Saved narration only: no login, estimate or paid generation is triggered.
        job_path = data / 'jobs' / job['id']
        shutil.copy2(ROOT / 'output/audio/00.mp3', job_path / 'voice-000.mp3')
        saved = json.loads((job_path / 'job.json').read_text(encoding='utf-8'))
        saved['narration'] = {'0': {'file': 'voice-000.mp3', 'source': 'saved test fixture'}}
        (job_path / 'job.json').write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
        page.locator('#history button').first.click()
        page.wait_for_function("document.querySelectorAll('#storyboard textarea').length===1")
        assert page.locator('#files').is_disabled()
        assert page.locator('#storyboard textarea').is_disabled()
        page.locator('#rerender').click()
        page.wait_for_function("!document.querySelector('#audioDownload').hidden", timeout=180000)
        assert page.locator('.export-card').count() == 4
        job = api('/api/jobs/' + job['id'])
        assert job['state'] == 'complete', job.get('error')
        for selector in ['download', 'videoDownload', 'scriptDownload', 'subtitleDownload', 'audioDownload']:
            assert page.locator('#' + selector).is_visible(), selector
            with page.expect_download() as download:
                page.locator('#' + selector).click()
            artifact = download.value
            assert artifact.failure() is None
            destination = probe / artifact.suggested_filename
            artifact.save_as(destination)
            assert destination.stat().st_size > 0
        print('Saved-media rerender, four output cards and all five file downloads passed', flush=True)
        page.screenshot(path=str(probe / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(probe / 'mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        assert not errors, errors
        # Legacy jobs show only files that actually exist, then can be upgraded by rerender.
        saved = json.loads((job_path / 'job.json').read_text(encoding='utf-8'))
        for name in ['stay-video.mp4', 'stay-voice.mp3', 'stay-script.txt']:
            (job_path / name).rename(job_path / (name + '.saved'))
        saved['result'] = {'file': 'stay-reel.mp4', 'srt': 'stay-reel.srt'}
        (job_path / 'job.json').write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
        page.locator('#history button').first.click()
        page.wait_for_function("document.querySelector('#videoDownload').hidden && !document.querySelector('#download').hidden")
        assert page.locator('#subtitleDownload').is_visible()
        assert not page.locator('#audioDownload').is_visible()
        print('Mobile layout, no JavaScript errors and legacy download availability passed', flush=True)
        browser.close()
finally:
    process.terminate()
    process.wait(timeout=20)
    log.close()
