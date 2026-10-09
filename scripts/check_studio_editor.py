"""Exercise caption numeric controls and manual motion editing without paid calls."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

probe = ROOT / '.local/probes/editor'
data = probe / 'data'
collection_id = 'd' * 32
collection = data / 'collections' / collection_id
collection.mkdir(parents=True, exist_ok=True)
source = ROOT / 'Data/accommodations/9816'
shutil.copytree(source / 'images', collection / 'images', dirs_exist_ok=True)
shutil.copy2(source / 'manifest.json', collection / 'manifest.json')
env = os.environ.copy()
env['STAY_STUDIO_DATA'] = str(data)
env['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.tools/ms-playwright')
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = env['PLAYWRIGHT_BROWSERS_PATH']
log = (probe / 'server.log').open('wb')
process = subprocess.Popen([sys.executable, str(ROOT / 'launch.py'), '--no-browser', '--port', '8769'],
    cwd=probe, env=env, stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
base = 'http://127.0.0.1:8769'
try:
    for _ in range(50):
        try:
            html = urllib.request.urlopen(base, timeout=2).read().decode()
            break
        except OSError:
            time.sleep(.3)
    else:
        raise RuntimeError('Editor test server failed to start')
    token = re.search(r'name="studio-token" content="([^"]+)"', html).group(1)
    def api(path, value=None):
        request = urllib.request.Request(base + path, None if value is None else json.dumps(value).encode(),
            {'Content-Type': 'application/json', 'X-Studio-Token': token})
        return json.load(urllib.request.urlopen(request, timeout=20))
    gallery = api('/api/collections/' + collection_id)
    job = api('/api/jobs/import', {'collection_id': collection_id, 'photos': [p['id'] for p in gallery['photos'][:10]]})
    api('/api/jobs/' + job['id'] + '/storyboard', {'scenes': [{'photos': list(range(10)), 'text': '숙소에서 쉬는 하루'}],
        'motion': [{'photo': 0, 'prompt': 'AI suggested slow pan'}]})
    job_file = data / 'jobs' / job['id'] / 'job.json'
    record = json.loads(job_file.read_text(encoding='utf-8'))
    record['options']['max_motion'] = 0
    record['state'] = 'awaiting_approval'
    record['quote'] = {'id': 'old', 'total': 1, 'videos': [], 'voices': []}
    job_file.write_text(json.dumps(record), encoding='utf-8')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=playwright.chromium.executable_path)
        page = browser.new_page(viewport={'width': 1500, 'height': 1100})
        errors, previews, quotes = [], [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: previews.append(request.post_data_json) if request.url.endswith('/preview') else None)
        page.route('**/api/connections', lambda route: route.fulfill(json={'codex': True, 'fish': True,
            'codex_login': '', 'message': '', 'workspaces': [{'workspace_id': 'test', 'workspace_name': 'Test'}]}))
        def quote_route(route):
            quotes.append(route.request.post_data_json)
            route.fulfill(json={'ok': True})
        page.route('**/quote', quote_route)
        held_styles = []
        hold = {'style': False}
        def style_route(route):
            if hold['style']:
                held_styles.append(route)
            else:
                route.continue_()
        page.route('**/style', style_route)
        page.goto(base, wait_until='networkidle')
        (probe / 'loaded.html').write_text(page.content(), encoding='utf-8')
        page.locator('#historyPanel summary').click()
        page.locator('#history button').first.click()
        page.wait_for_function("document.querySelectorAll('#motionGrid input').length===10")
        page.locator('#motionEditor summary').click()
        page.locator('#advancedStyle summary').click()
        assert page.locator('#motionGrid input').nth(0).is_checked()
        assert page.locator('#motionPrompts textarea').input_value() == 'AI suggested slow pan'
        assert page.locator('#quoteBox').is_visible()
        assert page.locator('#motion').get_attribute('type') == 'hidden'
        assert not page.locator('#motion').is_visible()
        assert page.locator('#fontSizeValue, #posYValue, #posXValue').count() == 0
        for selector, value in [('fontSizeInput', '72'), ('posYInput', '-12.5'), ('posXInput', '4.5')]:
            page.locator('#' + selector).fill(value)
            assert page.locator('#' + selector.removesuffix('Input')).input_value() == value
        page.wait_for_function("document.querySelector('#preview').src.startsWith('blob:')")
        page.wait_for_timeout(400)
        assert previews[-1]['caption']['font_size'] == 72
        assert previews[-1]['caption']['y'] == -12.5
        assert previews[-1]['caption']['x'] == 4.5
        before = len(previews)
        page.locator('#fontSizeInput').fill('121')
        assert page.locator('#fontSizeError').is_visible()
        assert page.locator('#saveStyle').is_disabled()
        assert page.locator('#approve').is_disabled()
        page.wait_for_timeout(300)
        assert len(previews) == before
        page.locator('#fontSizeInput').fill('')
        assert page.locator('#quote').is_disabled()
        page.locator('#fontSizeInput').fill('72')
        page.locator('#posXInput').fill('0.2')
        assert page.locator('#posXError').is_visible()
        page.locator('#posX').evaluate("el=>{el.value='-3.5';el.dispatchEvent(new Event('input',{bubbles:true}));}")
        assert page.locator('#posXInput').input_value() == '-3.5'
        page.locator('#saveStyle').click()
        page.wait_for_function("document.querySelector('#statusTitle').textContent.includes('변경 사항을 저장') && !document.querySelector('#newJob').disabled")
        assert api('/api/jobs/' + job['id'])['options']['caption']['x'] == -3.5
        page.locator('#motionGrid input').nth(0).uncheck()
        page.locator('#motionGrid input').nth(1).check()
        page.locator('#motionGrid input').nth(2).check()
        page.locator('#motionPrompts textarea').nth(0).fill('물결만 잔잔하게 움직여 주세요')
        page.locator('#motionPrompts textarea').nth(1).fill('Slow camera pan to the right')
        assert page.locator('#quoteBox').is_hidden()
        page.locator('#saveStyle').click()
        page.wait_for_function("document.querySelector('#statusTitle').textContent.includes('변경 사항을 저장') && !document.querySelector('#newJob').disabled")
        assert page.locator('#motionPrompts textarea').nth(0).input_value() == '물결만 잔잔하게 움직여 주세요'
        assert page.locator('#quoteBox').is_hidden()
        page.locator('#motionPrompts textarea').nth(0).fill('   ')
        assert page.locator('#quote').is_disabled()
        assert page.locator('#savePlan').is_disabled()
        page.locator('#motionPrompts textarea').nth(0).fill('물결만 잔잔하게 움직여 주세요')
        hold['style'] = True
        with page.expect_response(lambda response: response.url.endswith('/quote')):
            page.locator('#quote').click()
            for _ in range(30):
                page.wait_for_timeout(100)
                if held_styles:
                    break
            assert held_styles, 'Quote style request did not arrive'
            assert page.locator('#motionGrid input').nth(1).is_disabled()
            assert page.locator('#motionPrompts textarea').nth(0).is_disabled()
            assert page.locator('#fontSizeInput').is_disabled()
            assert page.locator('#newJob').is_disabled()
            hold['style'] = False
            held_styles.pop().continue_()
        page.wait_for_function("document.querySelector('#planNotice').textContent==='' && !document.querySelector('#newJob').disabled")
        saved = api('/api/jobs/' + job['id'])
        assert [m['photo'] for m in saved['storyboard']['motion']] == [1, 2]
        assert saved['storyboard']['motion'][0]['prompt'] == '물결만 잔잔하게 움직여 주세요'
        assert saved['quote'] is None and saved['approval'] is None
        assert quotes and quotes[-1]['workspace'] == 'test'
        page.locator('#history button').first.click()
        page.wait_for_function("document.querySelectorAll('#motionPrompts textarea').length===2")
        assert page.locator('#fontSizeInput').input_value() == '72'
        assert page.locator('#posYInput').input_value() == '-12.5'
        record = json.loads(job_file.read_text(encoding='utf-8'))
        record['state'] = 'awaiting_approval'
        record['quote'] = {'id': 'new', 'total': 3, 'videos': [], 'voices': []}
        job_file.write_text(json.dumps(record), encoding='utf-8')
        page.locator('#history button').first.click()
        page.wait_for_function("!document.querySelector('#quoteBox').hidden")
        approved = []
        def approval_route(route):
            approved.append(route.request.post_data_json)
            route.fulfill(json={'ok': True})
        page.route('**/approve', approval_route)
        hold['style'] = True
        with page.expect_response(lambda response: response.url.endswith('/approve')):
            page.locator('#approve').click()
            for _ in range(30):
                page.wait_for_timeout(100)
                if held_styles:
                    break
            assert held_styles
            assert page.locator('#motionPrompts textarea').nth(0).is_disabled()
            assert page.locator('#motionGrid input').nth(3).is_disabled()
            assert page.locator('#history button').first.is_disabled()
            assert page.locator('#fontSizeInput').is_disabled()
            hold['style'] = False
            held_styles.pop().continue_()
        assert approved == [{'quote_id': 'new', 'expected_credits': 3}]
        page.wait_for_function("!document.querySelector('#motionGrid input').disabled")
        for index in [3, 4, 5]:
            page.locator('#motionGrid input').nth(index).check()
        assert page.locator('#motionGrid input').nth(6).is_enabled()
        for index in [0, 6, 7, 8, 9]:
            page.locator('#motionGrid input').nth(index).check()
        page.locator('#savePlan').click()
        page.wait_for_function("document.querySelector('#planNotice').textContent==='' && !document.querySelector('#newJob').disabled")
        assert len(api('/api/jobs/' + job['id'])['storyboard']['motion']) == 10
        page.screenshot(path=str(probe / 'desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(probe / 'mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        for index in range(10):
            page.locator('#motionGrid input').nth(index).uncheck()
        page.locator('#savePlan').click()
        page.wait_for_function("document.querySelector('#planNotice').textContent==='' && !document.querySelector('#newJob').disabled")
        assert api('/api/jobs/' + job['id'])['storyboard']['motion'] == []
        record = json.loads(job_file.read_text(encoding='utf-8'))
        record['generated'] = {'1': {'idempotency_key': 'pending'}}
        job_file.write_text(json.dumps(record), encoding='utf-8')
        page.locator('#history button').first.click()
        page.wait_for_function("document.querySelector('#motionGrid input').disabled")
        assert all(item.is_disabled() for item in page.locator('#storyboard textarea').all())
        assert not errors, errors
        print('Numeric sync/validation/persistence; photos 2+3 prompts; quote/approval locks; all 10 photos selected; submitted lock; mobile passed')
        browser.close()
finally:
    process.terminate()
    process.wait(timeout=20)
    log.close()
