"""Browser + real FFmpeg verification with local fixtures, no paid provider calls."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '.tools/studio-python')]
from PIL import Image
from playwright.sync_api import sync_playwright
from studio import assets
from studio.models import Job, Storyboard
from studio.render import run

probe = ROOT / '.local/probes/composition'
data = probe / 'data'
identifier = 'e'*32
folder = data / 'jobs' / identifier
folder.mkdir(parents=True, exist_ok=True)
job = Job(id=identifier, workflow_version=2, photo_order=[0,1,2],
    photos=[{'file': f'p{i}.jpg', 'name': f'사진 {i+1}', 'sha256': str(i)} for i in range(3)],
    storyboard=Storyboard(scenes=[{'photos': [i], 'text': f'장면 {i+1}'} for i in range(3)],
        motion=[{'photo': 0, 'prompt': 'Preserve the original scene; slow subtle water ripples.'}],
        motion_recommendations=[{'photo': i, 'recommended': i==0, 'reason': '물결 적합' if i==0 else '정지 권장', 'prompt': '', 'explanation': ''} for i in range(3)]),
    generated={'0': {'file': 'motion.mp4', 'state': 'completed', 'photo_sha': '0', 'prompt': 'Preserve the original scene; slow subtle water ripples.'}},
    narration={str(i): {'file': f'voice{i}.wav', 'state': 'completed', 'text': f'장면 {i+1}'} for i in range(3)})
for i, color in enumerate(['green', 'orange', 'blue']):
    Image.new('RGB', (400, 700), color).save(folder / f'p{i}.jpg')
    with wave.open(str(folder / f'voice{i}.wav'), 'wb') as voice:
        voice.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        voice.writeframes(b'\0\0' * 24000)
run('-f','lavfi','-i','color=c=green:s=1080x1920:r=30:d=0.2','-c:v','libx264','-pix_fmt','yuv420p',folder/'motion.mp4')
assets.capture(job)
job.candidates=[dict(p, id=p['sha256']) for p in job.photos]
(folder/'job.json').write_text(job.model_dump_json(), encoding='utf-8')
env=os.environ.copy()
env['STAY_STUDIO_DATA']=str(data)
env['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.tools/ms-playwright')
os.environ['PLAYWRIGHT_BROWSERS_PATH']=env['PLAYWRIGHT_BROWSERS_PATH']
log=(probe/'server.log').open('wb')
process=subprocess.Popen([sys.executable,str(ROOT/'launch.py'),'--no-browser','--port','8771'],
    env=env,cwd=ROOT,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
base='http://127.0.0.1:8771'
try:
    for _ in range(50):
        try:
            html=urllib.request.urlopen(base,timeout=2).read().decode();break
        except OSError: time.sleep(.2)
    else: raise RuntimeError('Preview test server did not start')
    token=re.search(r'name="studio-token" content="([^"]+)"',html).group(1)
    def read():return json.load(urllib.request.urlopen(base+'/api/jobs/'+identifier))
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1500,'height':1100})
        errors,paid,recommendations=[],[],[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:paid.append(r.url) if r.url.endswith(('/quote','/approve')) else None)
        page.route('**/api/connections',lambda route:route.fulfill(json={'codex':True,'fish':True,'workspaces':[],'codex_login':'','message':''}))
        page.goto(base,wait_until='networkidle')
        page.locator('#historyPanel summary').click()
        page.locator('#history button').first.click()
        page.wait_for_function("document.querySelectorAll('#storyboard textarea').length===6")
        assert page.locator('#previewVideo').is_enabled()
        page.locator('#previewVideo').click()
        page.wait_for_function("!document.querySelector('#exportFinal').disabled",timeout=90000)
        page.wait_for_function("document.querySelector('#video').readyState>=1")
        assert page.locator('#video').is_visible()
        assert page.locator('#video').evaluate('v=>v.videoWidth===1080&&v.videoHeight===1920&&v.controls')
        original=read()
        preview_bytes=(folder/original['preview']['file']).read_bytes()
        page.locator('#exportFinal').click()
        page.wait_for_function("!document.querySelector('#download').hidden",timeout=15000)
        assert preview_bytes==(folder/'stay-reel.mp4').read_bytes()
        page.get_by_role('textbox',name='1번 장면 화면 자막').fill('음성과 별도인 새 자막')
        assert page.locator('#exportFinal').is_disabled()
        page.locator('#savePlan').click()
        page.wait_for_function("document.querySelector('#planNotice').textContent==='' && !document.querySelector('#newJob').disabled")
        assert read()['narration']['0']['file']=='voice0.wav'
        assert page.locator('#previewVideo').is_enabled()
        page.get_by_role('button',name='1번 사진 뒤으로 이동').click()
        page.wait_for_function("document.querySelector('#statusTitle').textContent.includes('사진 순서')")
        assert read()['photo_order']==[1,0,2]
        assert read()['narration']['0']['file']=='voice1.wav'
        assert page.locator('#captionText').input_value()=='자막 2'
        assert page.locator('#photoGrid .selected').get_attribute('aria-label')=='1번 사진 선택'
        page.get_by_role('button',name='이 음성 다시 생성').first.click()
        page.wait_for_function("!document.querySelector('#previewVideo').disabled===false")
        assert '0' not in read()['narration']
        page.get_by_role('button',name='결과 복원').first.click()
        page.wait_for_function("!document.querySelector('#previewVideo').disabled")
        assert read()['narration']['0']['file']=='voice1.wav'
        page.locator('#cropEditor summary').click()
        page.locator('#cropX').evaluate("el=>{el.value='0.3';el.dispatchEvent(new Event('input',{bubbles:true}));}")
        page.wait_for_function("!document.querySelector('#cropPreview').hidden")
        page.locator('#savePlan').click()
        page.wait_for_function("document.querySelector('#planNotice').textContent==='' && !document.querySelector('#newJob').disabled")
        assert next(f for f in read()['storyboard']['crop_focus'] if f['photo']==1)['x']==0.3
        page.locator('input[name=compositionMode][value=ai]').check()
        assert page.locator('#aiControls').is_visible()
        def recommend(route):
            recommendations.append(route.request.post_data_json)
            route.fulfill(json=read())
        page.route('**/api/composition',recommend)
        page.locator('#targetCount').fill('2')
        page.locator('#recommend').click()
        page.wait_for_function("document.querySelector('#statusTitle').textContent.length>0")
        page.wait_for_timeout(500)
        assert recommendations[-1]['mode']=='ai' and recommendations[-1]['target_count']==2
        page.screenshot(path=str(probe/'desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(probe/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
        assert not errors,errors
        assert not paid,paid
        browser.close()
    print('PASS: 1080p motion/audio/captions preview, identical export, delta edit, sorting, retry/restore, AI controls, desktop/mobile; zero paid requests.')
finally:
    process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    log.close()
