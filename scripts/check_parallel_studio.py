"""Exercise the combined preparation UI on isolated data with no external AI calls."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.tools/ms-playwright')


def serve(directory, port):
    os.environ['STAY_STUDIO_DATA'] = directory
    import uvicorn
    from PIL import Image
    from studio import app, store
    from studio.models import Job, Storyboard
    from studio.paths import job_path

    job = Job(id='d' * 32, workflow_version=2, composition_mode='manual',
              photos=[{'sha256': str(i), 'file': f'{i}.jpg', 'name': f'Photo {i}'} for i in range(10)])
    store.save(job)
    for index in range(10):
        Image.new('RGB', (800, 600), (index * 20, 100, 180)).save(job_path(job.id) / f'{index}.jpg')
    release, analyzed, enhanced = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def login():
        return True

    async def remake(source, target, domain):
        enhanced.set()
        await asyncio.wait_for(analyzed.wait(), 10)
        await release.wait()
        Image.new('RGB', (1080, 1920), 'teal').save(target)

    async def analyze(work, removing_people=False):
        assert removing_people
        analyzed.set()
        await asyncio.wait_for(enhanced.wait(), 10)
        await release.wait()
        return Storyboard(scenes=[{'photos': list(range(10)), 'text': '테스트 숙소의 객실과 수영장입니다.'}],
                          script_options=[{'title': f'후보 {i}', 'texts': ['테스트 숙소의 객실과 수영장입니다.']}
                                          for i in range(1, 4)],
                          crop_focus=[{'photo': i, 'x': .8, 'y': .3} for i in range(10)])

    async def no_external(*args, **kwargs):
        raise AssertionError('External provider calls are forbidden in this probe')

    @app.app.post('/api/probe/finish')
    async def finish():
        assert analyzed.is_set() and enhanced.is_set()
        release.set()
        return {'ok': True}

    app.codex.login_status = login
    app.codex.analyze = analyze
    app.enhance.enhance_photo = remake
    app.fish.call = no_external
    app.connection.update(fish=True, workspaces=[])
    uvicorn.run(app.app, host='127.0.0.1', port=port, log_level='error')


def check():
    from playwright.sync_api import sync_playwright, expect
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    artifacts = ROOT / 'output/parallel-ui-check'
    artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='stay-parallel-') as directory, \
            (artifacts / 'server.log').open('wb') as log:
        process = subprocess.Popen([sys.executable, __file__, '--serve', directory, '--port', str(port)],
                                   cwd=ROOT, stdout=log, stderr=log,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        base = f'http://127.0.0.1:{port}'
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError('Probe server stopped; see server.log')
                try:
                    urllib.request.urlopen(base, timeout=1).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('Probe server startup timeout')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                context.tracing.start(screenshots=True, snapshots=True)
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                try:
                    page.goto(base)
                    page.get_by_text('이전 작업 불러오기', exact=True).click()
                    page.locator('#history').get_by_role('button').click()
                    prepare = page.get_by_role('button', name='고화질 + 대본 함께 만들기 ↗', exact=True)
                    expect(prepare).to_be_enabled()
                    expect(page.locator('#nextAction')).to_have_text('고화질 + 대본 함께 만들기 →')
                    page.screenshot(path=str(artifacts / 'before.png'), full_page=True)
                    prepare.click()
                    page.wait_for_function("job?.state === 'preparing'")
                    expect(prepare).to_be_disabled()
                    assert page.locator('#analyze, #enhance').count() == 0
                    page.evaluate("api('/api/probe/finish', {})")
                    page.wait_for_function("job?.state === 'uploaded' && Boolean(job.storyboard)")
                    saved = page.evaluate('job')
                    assert all(photo['enhanced']['state'] == 'done' for photo in saved['photos'])
                    assert len(saved['storyboard']['script_options']) == 3
                    assert all(focus['x'] == .5 for focus in saved['storyboard']['crop_focus'])
                    expect(prepare).to_be_enabled()
                    page.screenshot(path=str(artifacts / 'after.png'), full_page=True)
                    page.set_viewport_size({'width': 390, 'height': 844})
                    page.screenshot(path=str(artifacts / 'mobile.png'), full_page=True)
                    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                    assert not errors, errors
                    print(json.dumps({'ok': True, 'enhanced_photos': 10, 'script_options': 3,
                                      'page_errors': errors, 'paid_calls': 0}))
                except Exception:
                    page.screenshot(path=str(artifacts / 'failure.png'), full_page=True)
                    print(json.dumps({'page_errors': errors,
                                      'history': page.locator('#history').inner_text(),
                                      'jobs': page.request.get(base + '/api/jobs').json()}, ensure_ascii=True))
                    raise
                finally:
                    context.tracing.stop(path=str(artifacts / 'trace.zip'))
                    browser.close()
        finally:
            process.terminate()
            process.wait(timeout=15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        check()
