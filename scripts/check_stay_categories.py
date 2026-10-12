"""Check category selection in the real UI against an isolated local test API."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.tools/studio-python'), str(ROOT)]
sys.stdout.reconfigure(encoding='utf-8')

from fastapi.testclient import TestClient
from PIL import Image
from playwright.sync_api import sync_playwright
from studio import app as module
from studio import store
from studio.models import Storyboard


with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    Image.new('RGB', (800, 1200), '#228844').save(folder / 'photo.jpg')
    with patch('studio.paths.DATA', folder), patch('studio.store.DATA', folder), \
            patch('studio.store.job_path', lambda i: folder / 'jobs' / i), \
            patch('studio.app.job_path', lambda i: folder / 'jobs' / i), \
            sync_playwright() as playwright:
        client = TestClient(module.app)
        browser = playwright.chromium.launch(headless=True, executable_path=str(
            ROOT / '.tools/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'))
        page = browser.new_page(viewport={'width': 1500, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            request = route.request
            url = urlsplit(request.url)
            if url.path == '/api/connections':
                route.fulfill(json={'codex': True, 'fish': True, 'workspaces': [], 'message': '', 'codex_login': ''})
                return
            if request.method == 'POST' and url.path == '/api/jobs':
                # Chromium interception omits disk-file bytes from multipart bodies.
                assert b'stay-silent' in request.post_data_buffer
                response = client.post(url.path, headers={'X-Studio-Token': module.TOKEN},
                                       data={'domain': 'stay-silent'}, files=[
                                           ('files', ('photo.jpg', (folder / 'photo.jpg').read_bytes(), 'image/jpeg'))])
            else:
                response = client.request(request.method, url.path + ('?' + url.query if url.query else ''),
                                          headers=request.headers, content=request.post_data_buffer)
            if response.status_code >= 400:
                print(request.method, url.path, response.status_code, response.text, flush=True)
            route.fulfill(status=response.status_code, body=response.content,
                          content_type=response.headers.get('content-type', 'application/octet-stream'))

        page.route('**/*', respond)
        page.goto('http://127.0.0.1:8877', wait_until='networkidle')
        tabs = page.locator('#domainTabs button')
        assert tabs.all_text_contents() == ['숙소(음성O)', '숙소(음성X)', '쇼핑']
        assert page.locator('.analysis-controls button').count() == 1
        assert page.locator('#enhance, #analyze').count() == 0
        page.locator('[data-domain=stay-silent]').click()
        assert page.locator('#captionAlign').input_value() == 'left'
        assert page.locator('#posYInput').input_value() == '-30'
        assert page.locator('#speed').is_hidden()
        assert page.locator('.voice-note').is_hidden()
        assert page.locator('#audioDownload').locator('..').is_hidden()
        page.locator('[data-domain=shopping]').click()
        assert 'video/mp4' in page.locator('#files').get_attribute('accept')
        page.locator('[data-domain=stay]').click()
        page.locator('#advancedStyle').evaluate('(el)=>el.open=true')
        assert page.locator('#speed').is_visible()
        page.locator('[data-domain=stay-silent]').click()
        page.reload(wait_until='networkidle')
        assert page.locator('[data-domain=stay-silent]').get_attribute('aria-checked') == 'true'
        page.locator('#advancedStyle').evaluate('(el)=>el.open=true')
        page.locator('#fontSizeInput').fill('20')
        page.locator('#color').fill('#0000ff')
        page.locator('#captionAlign').select_option('right')
        page.locator('#captionPresetName').fill('파랑 20')
        page.locator('#saveCaptionPreset').click()
        page.wait_for_function("captionPresets.length===1")
        assert page.locator('#captionPreset').locator('option').all_text_contents() == ['설정을 선택하세요', '파랑 20']
        page.reload(wait_until='networkidle')
        page.locator('#captionPreset').select_option(label='파랑 20')
        assert page.locator('#fontSizeInput').input_value() == '20'
        assert page.locator('#captionAlign').input_value() == 'right'
        page.locator('#files').set_input_files(str(folder / 'photo.jpg'))
        page.wait_for_function("job?.domain==='stay-silent'||uiError", timeout=10000)
        assert page.evaluate('job?.domain') == 'stay-silent', page.locator('#statusDetail').inner_text()
        assert page.evaluate('job.options.caption.font_size') == 20
        assert page.evaluate('job.options.caption.align') == 'right'
        assert page.locator('[data-domain=stay-silent]').get_attribute('aria-checked') == 'true'
        page.wait_for_function('!sourceBusy')
        assert page.locator('#prepare').is_disabled()
        assert '8' in page.locator('#enhanceHelp').inner_text()
        work = store.read(page.evaluate('job.id'))
        work.photos = [dict(work.photos[0], sha256=str(i)) for i in range(8)]
        work.photo_order = list(range(8))
        work.storyboard = Storyboard(scenes=[{'photos': [i], 'text': '문 열자마자\n프렌치 감성 가득'} for i in range(8)])
        store.save(work)
        page.evaluate("async id=>{await loadJob(id);drawPhotos();drawScript();drawStatus();}", work.id)
        assert page.locator('#prepare').is_enabled()
        with patch('studio.app.codex.login_status', AsyncMock(return_value=True)), \
                patch.object(module.pipeline, 'launch') as launch:
            page.locator('#prepare').click()
            page.wait_for_function('!sourceBusy')
            assert launch.call_count == 1
            assert launch.call_args.args[1].__name__ == 'prepare'
        work.state = 'preparing'
        store.save(work)
        page.evaluate("async id=>{await loadJob(id);drawStatus();}", work.id)
        assert page.locator('#prepare').is_disabled()
        work.state = 'uploaded'
        store.save(work)
        page.evaluate("async id=>{await loadJob(id);drawStatus();}", work.id)
        page.locator('#newJob').click()
        page.wait_for_load_state('networkidle')
        assert page.locator('#captionAlign').input_value() == 'left'
        assert page.locator('#fontSizeInput').input_value() == '64'
        page.locator('#captionPreset').select_option(label='파랑 20')
        assert page.locator('#fontSizeInput').input_value() == '20'
        assert page.locator('#captionAlign').input_value() == 'right'
        page.locator('[data-domain=stay]').click()
        work.domain = 'stay'
        work.photos = work.photos[:4]
        work.photo_order = list(range(4))
        work.storyboard = Storyboard(scenes=[
            {'photos': [0, 1], 'text': '숙소에 이런 물 풍경까지 있다고요? 불빛이 켜진 건물 아래로 수영장이 펼쳐져요.'},
            {'photos': [2, 3], 'text': '나무 사이로 물길이 이어져서 휴양지 분위기를 느끼며 쉬기 좋은 공간이에요.'}])
        store.save(work)
        page.evaluate("async id=>{await loadJob(id);drawPhotos();drawScript();drawStatus();}", work.id)
        assert page.locator('#storyboard .scene').count() == 4
        assert page.evaluate('dirtyScript')
        assert len(store.read(work.id).storyboard.scenes) == 2
        first = page.locator('.caption-cues button').first.inner_text()
        assert page.locator('.caption-cues button').count() > 1
        page.locator('.caption-cues button').nth(1).click()
        page.wait_for_function('selectedCaptionCue===1')
        assert page.locator('.caption-cues button[aria-pressed=true]').inner_text() != first
        page.evaluate("async()=>{await persistEdits();drawScript();drawStatus();}")
        assert len(store.read(work.id).storyboard.scenes) == 4
        page.locator('#newJob').click()
        page.locator('[data-domain=stay-silent]').click()
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert page.locator('[data-domain=stay-silent]').is_visible()
        out = ROOT / '.local/probes'
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / 'stay-categories-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1500, 'height': 1100})
        page.screenshot(path=str(out / 'stay-categories-desktop.png'), full_page=True)
        assert not errors, errors
        browser.close()
        print('Per-photo narration rows, caption cue selection, legacy plan save, unified preparation, presets and mobile layout passed.')
