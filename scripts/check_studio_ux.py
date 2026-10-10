"""UX regression checks against an isolated local app; no provider generation."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '.tools/studio-python')]
sys.stdout.reconfigure(encoding='utf-8')
from PIL import Image
from playwright.sync_api import sync_playwright
from studio.models import Job, Storyboard
from studio import assets


class StudioUXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = ROOT / '.local/probes/ux-check'
        cls.probe.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=cls.probe)
        cls.data = Path(cls.temp.name)
        cls.ids = ['a' * 32, 'b' * 32]
        cls.original_jobs = {}
        for identifier in cls.ids:
            folder = cls.data / 'jobs' / identifier
            folder.mkdir(parents=True)
            photos = []
            for i, color in enumerate(['green', 'blue']):
                Image.new('RGB', (600, 900), color).save(folder / f'p{i}.jpg')
                photos.append({'file': f'p{i}.jpg', 'name': f'사진 {i+1}', 'sha256': f'{identifier}-{i}'})
            record = Job(id=identifier, workflow_version=2, photos=photos, photo_order=[0, 1],
                storyboard=Storyboard(scenes=[{'photos': [i], 'text': f'대본 {i+1}'} for i in range(2)]))
            (folder / 'job.json').write_text(record.model_dump_json(), encoding='utf-8')
            cls.original_jobs[identifier] = record.model_dump_json()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.base = f'http://127.0.0.1:{port}'
        env = os.environ.copy()
        env['STAY_STUDIO_DATA'] = str(cls.data)
        cls.log = (cls.probe / 'server.log').open('wb')
        cls.server = subprocess.Popen([sys.executable, str(ROOT / 'launch.py'), '--no-browser', '--port', str(port)],
            cwd=ROOT, env=env, stdout=cls.log, stderr=cls.log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for _ in range(60):
            try:
                urllib.request.urlopen(cls.base, timeout=1).close()
                break
            except OSError:
                time.sleep(.2)
        else:
            raise RuntimeError('UX test server did not start')
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True, executable_path=str(ROOT / '.tools/ms-playwright/chromium-1243/chrome-win64/chrome.exe'))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.log.close()
        cls.temp.cleanup()

    def setUp(self):
        for identifier, contents in self.original_jobs.items():
            (self.data / 'jobs' / identifier / 'job.json').write_text(contents, encoding='utf-8')
        self.page = self.browser.new_page(viewport={'width':1366, 'height':768})
        self.errors = []
        self.page.on('pageerror', lambda e: self.errors.append(str(e)))
        self.page.route('**/api/connections', lambda r: r.fulfill(json={'codex':True, 'fish':True, 'workspaces':[{'workspace_id':'test','workspace_name':'테스트 계정'}], 'codex_login':'', 'message':''}))
        self.page.goto(self.base, wait_until='networkidle')
        self.page.evaluate('(id)=>selectJob(id)', self.ids[0])

    def tearDown(self):
        self.page.close()
        self.assertEqual(self.errors, [])

    def dismiss_dialogs(self):
        dialogs = []
        def dismiss(dialog):
            dialogs.append(dialog.type)
            dialog.dismiss()
        self.page.on('dialog', dismiss)
        return dialogs

    def test_new_job_cancel_preserves_unsaved_script(self):
        field = self.page.get_by_role('textbox', name='1번 장면 대본', exact=True)
        field.fill('아직 저장하지 않은 이야기')
        dialogs = self.dismiss_dialogs()
        self.page.locator('#newJob').click()
        self.assertEqual(dialogs, ['confirm'])
        self.assertEqual(field.input_value(), '아직 저장하지 않은 이야기')

    def test_preview_steps_between_photos_with_buttons_and_keys(self):
        position = self.page.locator('#photoPosition')
        self.page.wait_for_function('document.querySelector("#photoPosition").textContent.includes("사진 1 / 2")')
        self.assertEqual(position.text_content(), '장면 1 · 사진 1 / 2')
        self.assertTrue(self.page.locator('#prevPhoto').is_disabled())
        self.page.locator('#nextPhoto').click()
        self.assertEqual(position.text_content(), '장면 2 · 사진 2 / 2')
        self.assertEqual(self.page.locator('#captionText').input_value(), '대본 2')
        self.assertTrue(self.page.locator('#nextPhoto').is_disabled())
        self.page.locator('#captionText').focus()
        self.page.keyboard.press('ArrowLeft')
        self.assertEqual(position.text_content(), '장면 2 · 사진 2 / 2')
        self.page.locator('#captionText').blur()
        self.page.keyboard.press('ArrowLeft')
        self.assertEqual(position.text_content(), '장면 1 · 사진 1 / 2')
        self.assertEqual(self.page.locator('#captionText').input_value(), '대본 1')

    def test_home_navigation_warns_once_and_cancel_keeps_edits(self):
        self.page.locator('#fontSizeInput').fill('79')
        dialogs = self.dismiss_dialogs()
        self.page.locator('.brand').click()
        self.assertEqual(dialogs, ['beforeunload'])
        self.assertEqual(self.page.locator('#fontSizeInput').input_value(), '79')

    def test_history_cancel_preserves_unsaved_style(self):
        self.page.locator('#fontSizeInput').fill('78')
        dialogs = self.dismiss_dialogs()
        self.page.evaluate('(id)=>selectJob(id)', self.ids[1])
        self.assertEqual(dialogs, ['confirm'])
        self.assertEqual(self.page.locator('#fontSizeInput').input_value(), '78')

    def test_one_save_persists_caption_and_style(self):
        self.page.locator('#captionText').fill('새 화면 자막')
        self.page.locator('#fontSizeInput').fill('72')
        self.page.locator('#saveStyle').click()
        self.page.wait_for_timeout(400)
        saved = self.page.request.get(self.base + '/api/jobs/' + self.ids[0]).json()
        self.assertEqual(saved['storyboard']['scenes'][0]['text'], '새 화면 자막')
        self.assertEqual(saved['options']['caption']['font_size'], 72)
        self.assertFalse(self.page.evaluate('dirtyScript || dirtyStyle'))

    def test_failed_save_keeps_draft_and_navigation_protection(self):
        self.page.locator('#captionText').fill('저장 실패 후에도 남아야 하는 자막')
        self.page.locator('#fontSizeInput').fill('76')
        self.page.route('**/storyboard', lambda r: r.fulfill(status=500, json={'detail':'저장 실패 테스트'}))
        self.page.locator('#saveStyle').click()
        self.page.wait_for_function('document.querySelector("#status").classList.contains("error")')
        dialogs = self.dismiss_dialogs()
        self.page.locator('#newJob').click()
        self.assertEqual(dialogs, ['confirm'])
        self.assertEqual(self.page.locator('#captionText').input_value(), '저장 실패 후에도 남아야 하는 자막')
        self.assertEqual(self.page.locator('#fontSizeInput').input_value(), '76')

    def test_next_action_displays_quote_without_spending_credits(self):
        submitted = []
        self.page.on('request', lambda r: submitted.append(r.url) if r.url.endswith('/approve') else None)
        self.page.evaluate('''() => {job.state='awaiting_approval';job.quote={id:'test',total:18,videos:[],voices:[]};drawStatus();}''')
        self.page.locator('#nextAction').click()
        self.assertEqual(submitted, [])
        self.assertTrue(self.page.locator('#quoteBox').is_visible())
        self.assertTrue(self.page.locator('#approve').evaluate('(e)=>e===document.activeElement'))

    def test_new_job_accept_resets_previous_preview_and_style(self):
        self.page.locator('#fontSizeInput').fill('90')
        self.page.on('dialog', lambda d: d.accept())
        self.page.locator('#newJob').click()
        self.assertEqual(self.page.locator('#fontSizeInput').input_value(), '64')
        self.assertTrue(self.page.locator('#previewEmpty').is_visible())
        self.assertFalse(self.page.locator('#preview').is_visible())
        self.assertEqual(self.page.locator('#video').get_attribute('src'), None)

    def test_history_loading_locks_editing_until_response_arrives(self):
        held = []
        self.page.route('**/api/jobs/' + self.ids[1], lambda r: held.append(r))
        self.page.evaluate('(id)=>{selectJob(id);}', self.ids[1])
        self.page.wait_for_timeout(300)
        self.assertTrue(held)
        self.assertTrue(self.page.locator('#newJob').is_disabled())
        self.assertTrue(self.page.locator('#fontSizeInput').is_disabled())
        held.pop().continue_()
        self.page.wait_for_function('!document.querySelector("#newJob").disabled')

    def test_automatic_save_locks_editing_during_photo_reorder(self):
        held = []
        self.page.locator('#captionText').fill('이동 전에 저장할 자막')
        self.page.route('**/storyboard', lambda r: held.append(r))
        self.page.get_by_role('button', name='1번 사진 뒤으로 이동').click()
        self.page.wait_for_timeout(300)
        self.assertTrue(held)
        self.assertTrue(self.page.locator('#captionText').is_disabled())
        self.assertTrue(self.page.locator('#newJob').is_disabled())
        held.pop().continue_()
        self.page.wait_for_function('!document.querySelector("#newJob").disabled')

    def test_caption_editor_waits_for_a_scene_before_accepting_edits(self):
        self.page.evaluate('()=>{job.storyboard=null;drawScript();drawStatus();}')
        self.assertTrue(self.page.locator('#captionText').is_disabled())

    def test_failed_metadata_refresh_cannot_export_an_old_style(self):
        record = Job.model_validate_json(self.original_jobs[self.ids[0]])
        record.state = 'preview_ready'
        record.preview = {'file':'previous.mp4','duration':7,'revision':assets.render_revision(record)}
        (self.data / 'jobs' / record.id / 'job.json').write_text(record.model_dump_json(), encoding='utf-8')
        self.page.evaluate('(id)=>selectJob(id)', record.id)
        self.assertTrue(self.page.locator('#exportFinal').is_enabled())
        self.page.locator('#fontSizeInput').fill('80')
        self.page.route('**/api/jobs/' + record.id, lambda r: r.fulfill(status=500, json={'detail':'metadata refresh failed'}))
        self.page.locator('#saveStyle').click()
        self.page.wait_for_function('document.querySelector("#status").classList.contains("error")')
        self.assertTrue(self.page.locator('#exportFinal').is_disabled())

    def test_selected_photo_preview_is_available_after_video_generation(self):
        # Represent a previously generated video; image preview must still work.
        self.page.evaluate('''() => {job.result={file:'previous.mp4'};showVideo();}''')
        previous = self.page.locator('#preview').get_attribute('src')
        self.page.get_by_role('button', name='2번 사진 선택', exact=True).click()
        self.page.wait_for_function('old=>{const image=document.querySelector("#preview");return !image.hidden&&image.src!==old&&image.naturalWidth===1080}', arg=previous)
        self.assertTrue(self.page.locator('#preview').is_visible())
        self.assertFalse(self.page.locator('#video').is_visible())
        self.assertEqual(self.page.locator('#captionText').input_value(), '대본 2')

    def test_status_and_next_action_remain_visible_while_scrolling(self):
        self.assertEqual(self.page.locator('#nextAction').count(), 1)
        self.page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
        rect = self.page.locator('#status').bounding_box()
        self.assertGreaterEqual(rect['y'], 0)
        self.assertLess(rect['y'] + rect['height'], 768)
        self.assertTrue(self.page.locator('#nextAction').is_visible())
        self.page.evaluate('window.scrollTo(0,0)')
        self.page.screenshot(path=str(self.probe / 'desktop.png'), full_page=True)
        self.page.screenshot(path=str(self.probe / 'desktop-viewport.png'))
        self.page.set_viewport_size({'width':390,'height':844})
        self.page.evaluate('window.scrollTo(0,document.body.scrollHeight)')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 390)
        rect = self.page.locator('#status').bounding_box()
        self.assertGreaterEqual(rect['y'], 0)
        self.assertLess(rect['y'] + rect['height'], 844)
        self.page.evaluate('window.scrollTo(0,0)')
        self.page.screenshot(path=str(self.probe / 'mobile.png'), full_page=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
