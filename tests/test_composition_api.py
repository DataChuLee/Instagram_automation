import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from studio import app, assets, store
from studio.models import Job, Storyboard


class CompositionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.patches = [patch(f'studio.{m}.job_path', lambda i: self.folder / i)
                        for m in ('app', 'store', 'composition', 'recommendation')]
        for p in self.patches: p.start()
        self.client = TestClient(app.app)
        self.headers = {'X-Studio-Token': app.TOKEN}
        self.job = Job(id='a'*32, workflow_version=2, photo_order=[0, 1],
            photos=[{'file': f'p{i}.jpg', 'sha256': str(i), 'name': '사진'} for i in range(2)],
            storyboard=Storyboard(scenes=[{'photos': [0], 'text': '객실'}, {'photos': [1], 'text': '정원'}]),
            narration={'0': {'file': 'one.mp3'}, '1': {'file': 'two.mp3'}})
        store.save(self.job)
        for p in self.job.photos: Image.new('RGB', (400, 500), 'green').save(self.folder / self.job.id / p['file'])
        for name in ('one.mp3', 'two.mp3'): (self.folder / self.job.id / name).write_bytes(b'ready')

    def tearDown(self):
        self.client.close()
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def post(self, suffix, value):
        return self.client.post(f'/api/jobs/{self.job.id}/{suffix}', headers=self.headers, json=value)

    def test_caption_edit_keeps_voice_but_narration_edit_requires_only_its_voice(self):
        plan = self.job.storyboard.model_dump()
        plan['scenes'][0]['caption_text'] = '짧은 화면 자막'
        response = self.post('storyboard', plan)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(store.read(self.job.id).narration, {'0': dict(file='one.mp3', asset_key=assets.cache_key(self.job, assets.voice_key(self.job,self.job.storyboard.scenes[0]))), '1': dict(file='two.mp3',asset_key=assets.cache_key(self.job,assets.voice_key(self.job,self.job.storyboard.scenes[1])))})
        plan['scenes'][0]['text'] = '다른 대본'
        self.assertEqual(self.post('storyboard', plan).status_code, 200)
        saved = store.read(self.job.id)
        self.assertNotIn('0', saved.narration)
        self.assertEqual(saved.narration['1']['file'], 'two.mp3')

    def test_order_change_preserves_scene_voice_identity_and_is_atomic_on_invalid_order(self):
        response = self.client.post('/api/composition', headers=self.headers,
            json={'job_id': self.job.id, 'mode': 'manual', 'order': [1, 0]})
        self.assertEqual(response.status_code, 200, response.text)
        saved = store.read(self.job.id)
        self.assertEqual(saved.photo_order, [1, 0])
        self.assertEqual(saved.narration['0']['file'], 'two.mp3')
        response = self.client.post('/api/composition', headers=self.headers,
            json={'job_id': self.job.id, 'mode': 'manual', 'order': [1, 1]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(store.read(self.job.id).photo_order, [1, 0])

    def test_forced_retry_and_restore_do_not_buy_media_and_invalidate_old_approval(self):
        response = self.post('media-attempt', {'kind': 'voice', 'index': 0})
        self.assertEqual(response.status_code, 200, response.text)
        saved = store.read(self.job.id)
        self.assertNotIn('0', saved.narration)
        self.assertIsNone(saved.approval)
        response = self.post('media-attempt', {'kind': 'voice', 'index': 0, 'restore': 0})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(store.read(self.job.id).narration['0']['file'], 'one.mp3')

    def test_candidates_can_be_added_after_analysis_without_changing_the_active_plan(self):
        image = io.BytesIO()
        Image.new('RGB', (400, 500), 'red').save(image, format='JPEG')
        response = self.client.post(f'/api/jobs/{self.job.id}/candidates', headers=self.headers,
            files=[('files', ('new.jpg', image.getvalue(), 'image/jpeg'))])
        self.assertEqual(response.status_code, 200, response.text)
        saved = store.read(self.job.id)
        self.assertEqual(len(saved.candidates), 3)
        self.assertEqual(saved.storyboard, self.job.storyboard)

    def test_outstanding_submission_blocks_selection_and_forced_retry(self):
        self.job.narration['0'] = {'state': 'submitted'}
        store.save(self.job)
        self.assertEqual(self.post('media-attempt', {'kind': 'voice', 'index': 0}).status_code, 400)
        self.assertEqual(self.client.post('/api/composition', headers=self.headers,
            json={'job_id': self.job.id, 'mode': 'manual', 'order': [1,0]}).status_code, 400)

    def test_invalid_candidate_does_not_publish_any_candidate_in_batch(self):
        image = io.BytesIO()
        Image.new('RGB', (400, 500), 'red').save(image, format='JPEG')
        response = self.client.post(f'/api/jobs/{self.job.id}/candidates', headers=self.headers,
            files=[('files', ('good.jpg', image.getvalue(), 'image/jpeg')),
                   ('files', ('bad.jpg', b'not an image', 'image/jpeg'))])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(store.read(self.job.id).candidates, [])
        self.assertEqual(list((self.folder / self.job.id).glob('candidate-*.jpg')), [])

    def test_interleaved_order_keeps_existing_voice_and_reassigns_visual_slots(self):
        self.job.photos.append({'file': 'p2.jpg', 'sha256': '2', 'name': '사진'})
        self.job.photo_order = [0,1,2]
        self.job.storyboard.scenes[0].photos = [0,1]
        self.job.storyboard.scenes[1].photos = [2]
        store.save(self.job)
        response = self.client.post('/api/composition', headers=self.headers,
            json={'job_id': self.job.id, 'mode': 'manual', 'order': [0,2,1]})
        self.assertEqual(response.status_code, 200, response.text)
        saved = store.read(self.job.id)
        self.assertEqual([p for s in saved.storyboard.scenes for p in s.photos], [0,2,1])
        self.assertEqual(saved.narration['0']['file'], 'one.mp3')
        self.assertEqual(saved.narration['1']['file'], 'two.mp3')
        self.assertIn('확인', saved.message)
