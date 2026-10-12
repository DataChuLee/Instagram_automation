import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from studio import app as module
from studio import store


class SavedStyleAndExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        folder = self.folder = Path(self.temp.name)
        self.patches = [patch('studio.app.job_path', lambda i: folder / i),
                        patch('studio.store.job_path', lambda i: folder / i),
                        patch('studio.paths.DATA', folder),
                        patch('studio.app.codex.login_status', return_value=False)]
        for item in self.patches:
            item.start()
        self.client = TestClient(module.app)
        self.headers = {'X-Studio-Token': module.TOKEN}

    def tearDown(self):
        self.client.close()
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def upload(self):
        data = io.BytesIO()
        Image.new('RGB', (800, 600), 'orange').save(data, format='JPEG')
        response = self.client.post('/api/jobs', headers=self.headers, files=[('files', ('p.jpg', data.getvalue(), 'image/jpeg'))])
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_new_job_starts_from_last_saved_caption_style(self):
        first = self.upload()
        self.assertEqual(first['options']['caption']['font_size'], 64)
        style = {'caption': {'font_size': 90, 'x': 5, 'y': -10, 'color': '#FF0000', 'outline': 3,
                             'background_opacity': 0.5, 'shadow': 0}, 'speed': 1.1}
        response = self.client.post(f'/api/jobs/{first["id"]}/style', headers=self.headers, json=style)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/style').json()['caption'], style['caption'])
        second = self.upload()
        self.assertEqual(second['options']['caption'], style['caption'])
        self.assertEqual(second['options']['speed'], 1.1)

    def test_broken_saved_style_falls_back_to_defaults(self):
        (self.folder / 'style.json').write_text('{oops', encoding='utf-8')
        self.assertEqual(self.upload()['options']['caption']['font_size'], 64)

    def test_previous_files_stay_downloadable_after_edits(self):
        job = self.upload()
        folder = self.folder / job['id']
        status = lambda: self.client.get(f'/api/jobs/{job["id"]}', headers=self.headers).json()['export_files']
        self.assertEqual(status(), {})
        # Preview only: its prefixed files are offered under the plain names.
        saved = store.read(job['id'])
        saved.preview = {'file': 'preview-a-stay-reel.mp4', 'audio': 'preview-a-stay-voice.mp3'}
        store.save(saved)
        for name in saved.preview.values():
            (folder / name).write_bytes(b'x')
        self.assertEqual(status(), {'stay-reel.mp4': 'preview-a-stay-reel.mp4', 'stay-voice.mp3': 'preview-a-stay-voice.mp3'})
        # A later final export (result cleared by an edit afterwards) wins over the older preview.
        (folder / 'stay-reel.mp4').write_bytes(b'y')
        later = time.time() + 5
        os.utime(folder / 'stay-reel.mp4', (later, later))
        self.assertEqual(status()['stay-reel.mp4'], 'stay-reel.mp4')
        self.assertEqual(self.client.get(f'/api/jobs/{job["id"]}/files/preview-a-stay-voice.mp3', headers=self.headers).status_code, 200)


if __name__ == '__main__':
    unittest.main()
