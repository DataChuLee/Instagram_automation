import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from studio import performance, store
from studio.models import Job, Storyboard
from studio.pipeline import Pipeline


class ParallelPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.patches = [patch('studio.store.job_path', return_value=self.folder),
                        patch('studio.pipeline.job_path', return_value=self.folder)]
        for item in self.patches:
            item.start()
        self.fish, self.drama = AsyncMock(), AsyncMock()
        self.pipeline = Pipeline(self.fish, self.drama)
        self.pipeline.preview = AsyncMock()
        self.job = Job(id='e' * 32, workflow_version=2,
                       photos=[{'sha256': str(i), 'file': f'{i}.jpg'} for i in range(10)])
        store.save(self.job)

    async def asyncTearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def approve(self, texts):
        self.job.storyboard = Storyboard(scenes=[{'photos': [i], 'text': text} for i, text in enumerate(texts)])
        self.job.quote = {'id': 'q', 'total': len(texts), 'videos': [],
                          'voices': [{'scene': i, 'credits': 1} for i in range(len(texts))],
                          'plan_hash': store.plan_hash(self.job)}
        self.job.approval = {'quote_id': 'q', 'credits': len(texts)}
        store.save(self.job)

    async def test_prepare_overlaps_analysis_and_enhance_without_lost_photo_updates(self):
        analyzing = asyncio.Event()
        enhancing = asyncio.Event()
        async def remake(source, target, domain):
            enhancing.set()
            await asyncio.wait_for(analyzing.wait(), 2)
            target.write_bytes(b'portrait')
        async def analyze(job, removing_people=False):
            self.assertTrue(removing_people)
            analyzing.set()
            await asyncio.wait_for(enhancing.wait(), 2)
            self.assertEqual(job.photos[0]['file'], '0.jpg')
            return Storyboard(scenes=[{'photos': list(range(10)), 'text': '객실과 수영장'}],
                              crop_focus=[{'photo': 0, 'x': .9, 'y': .1}])
        with patch('studio.pipeline.enhance.enhance_photo', side_effect=remake), \
                patch('studio.pipeline.codex.analyze', side_effect=analyze):
            await self.pipeline.prepare(self.job.id)
        saved = store.read(self.job.id)
        self.assertEqual(saved.state, 'uploaded')
        self.assertEqual(saved.storyboard.scenes[0].text, '객실과 수영장')
        self.assertTrue(all(p['enhanced']['state'] == 'done' for p in saved.photos))
        self.assertEqual(saved.storyboard.crop_focus[0].x, .5)
        self.assertEqual(saved.storyboard.crop_focus[0].y, .5)

    async def test_analysis_failure_still_saves_completed_enhancements(self):
        async def remake(source, target, domain):
            await asyncio.sleep(0)
            target.write_bytes(b'portrait')
        with patch('studio.pipeline.enhance.enhance_photo', side_effect=remake), \
                patch('studio.pipeline.codex.analyze', side_effect=RuntimeError('analysis failed')):
            await self.pipeline.guarded(self.job.id, self.pipeline.prepare)
        saved = store.read(self.job.id)
        self.assertEqual(saved.error, 'analysis failed')
        self.assertTrue(all(p.get('enhanced', {}).get('state') == 'done' for p in saved.photos))
        self.assertIsNone(saved.storyboard)

    async def test_prepare_can_replace_an_existing_unpaid_storyboard(self):
        self.job.storyboard = Storyboard(scenes=[{'photos': list(range(10)), 'text': '기존 대본'}])
        self.job.quote = {'id': 'old', 'total': 0, 'videos': [], 'voices': []}
        store.save(self.job)
        async def remake(source, target, domain):
            target.write_bytes(b'portrait')
        new_plan = Storyboard(scenes=[{'photos': list(range(10)), 'text': '새로운 자연스러운 대본'}])
        with patch('studio.pipeline.enhance.enhance_photo', side_effect=remake), \
                patch('studio.pipeline.codex.analyze', AsyncMock(return_value=new_plan)):
            await self.pipeline.prepare(self.job.id)
        saved = store.read(self.job.id)
        self.assertEqual(saved.storyboard.scenes[0].text, '새로운 자연스러운 대본')
        self.assertTrue(all(p['enhanced']['state'] == 'done' for p in saved.photos))
        self.assertIsNone(saved.quote)
        self.assertTrue(saved.versions)

    async def test_prepare_rejects_paid_media_before_resetting_the_storyboard(self):
        self.job.storyboard = Storyboard(scenes=[{'photos': list(range(10)), 'text': '기존 대본'}])
        self.job.generated = {'0': {'generation_id': 'paid-request'}}
        store.save(self.job)
        with self.assertRaises(ValueError):
            await self.pipeline.prepare(self.job.id)
        self.assertEqual(store.read(self.job.id).storyboard.scenes[0].text, '기존 대본')

    async def test_voices_overlap_keep_distinct_records_and_resume_without_repurchase(self):
        self.approve(['객실', '수영장', '정원', '조식'])
        started, active, peak = [], 0, 0
        both = asyncio.Event()
        async def generate(text, credits, path, saved, request):
            nonlocal active, peak
            started.append(text)
            active += 1
            peak = max(peak, active)
            await saved({'state': 'submitted', 'project_id': text, 'block': text})
            if active >= 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)
            await asyncio.sleep(.01)
            path.write_bytes(text.encode())
            await saved({'state': 'completed', 'url': 'https://example.com/' + text})
            active -= 1
        self.drama.generate.side_effect = generate
        await self.pipeline.generate(self.job.id)
        saved = store.read(self.job.id)
        self.assertGreaterEqual(peak, 2)
        self.assertLessEqual(peak, 3)
        for index, text in enumerate(['객실', '수영장', '정원', '조식']):
            record = saved.narration[str(index)]
            self.assertEqual(record['project_id'], text)
            self.assertEqual((self.folder / record['file']).read_bytes(), text.encode())
        await self.pipeline.generate(self.job.id)
        self.assertEqual(len(started), 4)

    async def test_voice_failure_drains_other_requests_and_keeps_recovery_references(self):
        self.approve(['실패', '성공'])
        async def generate(text, credits, path, saved, request):
            await saved({'state': 'submitted', 'project_id': text, 'block': text})
            if text == '실패':
                raise TimeoutError('response lost')
            await asyncio.sleep(.01)
            path.write_bytes(b'done')
            await saved({'state': 'completed'})
        self.drama.generate.side_effect = generate
        await self.pipeline.guarded(self.job.id, self.pipeline.generate)
        saved = store.read(self.job.id)
        self.assertEqual(saved.state, 'error')
        self.assertEqual(saved.narration['0']['state'], 'submitted')
        self.assertEqual(saved.narration['0']['block'], '실패')
        self.assertTrue((self.folder / saved.narration['1']['file']).is_file())
        self.pipeline.preview.assert_not_called()

    async def test_identical_voice_assets_are_generated_once(self):
        self.approve(['객실', '객실'])
        async def generate(text, credits, path, saved, request):
            await saved({'state': 'submitted', 'project_id': text, 'block': text})
            await asyncio.sleep(.01)
            path.write_bytes(b'voice')
        self.drama.generate.side_effect = generate
        await self.pipeline.generate(self.job.id)
        saved = store.read(self.job.id)
        self.assertEqual(self.drama.generate.await_count, 1)
        self.assertEqual(saved.narration['0']['file'], saved.narration['1']['file'])

    async def test_identical_voice_failure_preserves_shared_asset_recovery_state(self):
        from studio import assets
        self.approve(['객실', '객실'])
        key = assets.cache_key(self.job, assets.voice_key(self.job, self.job.storyboard.scenes[0]))
        self.job.narration = {str(i): {'asset_key': key, 'text': '객실', 'project_id': 'p', 'block': 'b'}
                              for i in range(2)}
        store.save(self.job)
        async def generate(text, credits, path, saved, request):
            await saved({'state': 'submitted', 'project_id': 'p', 'block': 'b'})
            raise TimeoutError('response lost')
        self.drama.generate.side_effect = generate
        await self.pipeline.guarded(self.job.id, self.pipeline.generate)
        saved = store.read(self.job.id)
        self.assertEqual(saved.narration['0']['state'], 'submitted')
        self.assertEqual(next(iter(saved.assets.values()))['state'], 'submitted')
        self.assertEqual(saved.narration['1']['state'], 'submitted')
        async def recover(record, path, persist):
            await persist({'state': 'completed', 'url': 'https://example.com/audio.mp3'})
            path.write_bytes(b'recovered')
        self.drama.recover.side_effect = recover
        await self.pipeline.generate(self.job.id)
        recovered = store.read(self.job.id)
        self.assertEqual(self.drama.generate.await_count, 1)
        self.assertEqual(self.drama.recover.await_count, 1)
        self.assertEqual(recovered.narration['0']['file'], recovered.narration['1']['file'])

    async def test_motion_results_overlap_and_failure_does_not_discard_other_downloads(self):
        self.approve(['객실'])
        self.job.storyboard = Storyboard(scenes=[{'photos': [0], 'text': '객실'}],
                                         motion=[{'photo': i, 'prompt': 'slow pan'} for i in range(2)])
        self.job.generated = {str(i): {'generation_id': str(i), 'state': 'submitted',
                                      'asset_key': f'motion-{i}'} for i in range(2)}
        self.job.narration = {'0': {'file': 'voice.mp3'}}
        (self.folder / 'voice.mp3').write_bytes(b'voice')
        self.job.quote['plan_hash'] = store.plan_hash(self.job)
        store.save(self.job)
        both = asyncio.Event()
        checked = set()
        async def call(name, args):
            generation = args['generation_id']
            if name == 'get_generation_status':
                checked.add(generation)
                if len(checked) == 2:
                    both.set()
                await asyncio.wait_for(both.wait(), 2)
                return {'status': 'failed' if generation == '0' else 'completed'}
            if name == 'get_generation_result':
                return {'media': {'url': 'https://example.com/video.mp4'}}
            self.fail('Unexpected request: ' + name)
        async def download(url, path):
            await asyncio.sleep(.01)
            path.write_bytes(b'video')
        self.fish.call.side_effect = call
        self.fish.download.side_effect = download
        with patch('studio.pipeline.video_size', return_value=(720, 1280)):
            await self.pipeline.guarded(self.job.id, self.pipeline.generate)
        saved = store.read(self.job.id)
        self.assertEqual(saved.generated['0']['state'], 'failed')
        self.assertEqual((self.folder / saved.generated['1']['file']).read_bytes(), b'video')
        self.assertEqual(saved.state, 'error')

    async def test_partial_enhance_failure_keeps_original_crop_and_successful_plan(self):
        from studio.enhance import EnhanceError
        async def remake(source, target, domain):
            if source.name == '0.jpg':
                raise EnhanceError('image failed')
            target.write_bytes(b'portrait')
        plan = Storyboard(scenes=[{'photos': list(range(10)), 'text': '객실'}],
                          crop_focus=[{'photo': 0, 'x': .8, 'y': .2}, {'photo': 1, 'x': .9, 'y': .1}])
        with patch('studio.pipeline.enhance.enhance_photo', side_effect=remake), \
                patch('studio.pipeline.codex.analyze', return_value=plan):
            await self.pipeline.prepare(self.job.id)
        saved = store.read(self.job.id)
        self.assertEqual(saved.photos[0]['file'], '0.jpg')
        self.assertEqual(saved.storyboard.crop_focus[0].x, .8)
        self.assertEqual(saved.storyboard.crop_focus[1].x, .5)
        self.assertIn('실패 1장', saved.message)

    async def test_prepare_rejects_submitted_voice_before_starting_ai(self):
        self.approve(['객실'])
        self.job.narration = {'0': {'state': 'submitted', 'project_id': 'paid-project', 'block': 'paid-block'}}
        store.save(self.job)
        with patch('studio.pipeline.codex.analyze', AsyncMock()) as analyze, \
                patch('studio.pipeline.enhance.enhance_photo', AsyncMock()) as remake:
            with self.assertRaises(ValueError):
                await self.pipeline.prepare(self.job.id)
        analyze.assert_not_called()
        remake.assert_not_called()

    async def test_restart_clears_combined_work_marks_and_preserves_finished_images(self):
        self.job.state = 'preparing'
        self.job.photos[0]['enhancing'] = True
        self.job.photos[1]['enhanced'] = {'state': 'done', 'file': 'enhanced.jpg', 'active': True}
        self.job.photos[1]['file'] = 'enhanced.jpg'
        store.save(self.job)
        with patch('studio.store.list_jobs', return_value=[self.job]):
            store.recover()
        saved = store.read(self.job.id)
        self.assertEqual(saved.state, 'uploaded')
        self.assertNotIn('enhancing', saved.photos[0])
        self.assertEqual(saved.photos[1]['file'], 'enhanced.jpg')


class ParallelRenderTests(unittest.TestCase):
    def test_encoding_failure_joins_workers_before_returning(self):
        from studio import render
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'finished.mp4'
            started = threading.Event()
            def encode(name):
                if name == 'failure':
                    if not started.wait(3):
                        raise AssertionError('Second worker never started')
                    raise RuntimeError('encode failed')
                started.set()
                target.write_bytes(b'finished')
            with patch('studio.render.run', side_effect=encode):
                with self.assertRaisesRegex(RuntimeError, 'encode failed'):
                    render.encode_clips([('failure',), ('success',)], lambda _: None, workers=2)
            self.assertEqual(target.read_bytes(), b'finished')

    def test_encoding_overlaps_with_bounded_workers_and_retains_timing_context(self):
        from studio import render
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            barrier = threading.Barrier(2)
            active, peak = 0, 0
            lock = threading.Lock()
            def encode(path):
                nonlocal active, peak
                with performance.span('test.encode'):
                    with lock:
                        active += 1
                        peak = max(active, peak)
                    barrier.wait(timeout=3)
                    path.write_text(path.name)
                    with lock:
                        active -= 1
            outputs = [folder / f'{i}.mp4' for i in range(4)]
            with patch('studio.render.run', side_effect=encode), performance.run(folder, 'render'):
                render.encode_clips([(p,) for p in outputs], lambda _: None, workers=2)
            self.assertEqual(peak, 2)
            self.assertEqual([p.read_text() for p in outputs], [f'{i}.mp4' for i in range(4)])
            runs = performance.report(folder)['runs']
            self.assertEqual(len(runs), 1)
            self.assertEqual(next(s['count'] for s in runs[0]['stages'] if s['stage'] == 'test.encode'), 4)


class PrepareAPITests(unittest.TestCase):
    def test_prepare_checks_inputs_and_launches_combined_work_with_saved_options(self):
        from fastapi.testclient import TestClient
        from studio import app
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            job = Job(id='f' * 32, workflow_version=2,
                      photos=[{'sha256': str(i), 'file': f'{i}.jpg'} for i in range(10)])
            with patch('studio.store.job_path', return_value=folder), \
                    patch('studio.app.codex.login_status', return_value=True), \
                    patch.object(app.pipeline, 'launch') as launch:
                store.save(job)
                with TestClient(app.app) as client:
                    headers = {'X-Studio-Token': app.TOKEN}
                    response = client.post(f'/api/jobs/{job.id}/prepare', headers=headers, json={'speed': 1.2})
                    self.assertEqual(response.status_code, 202, response.text)
                    launch.assert_called_once_with(job.id, app.pipeline.prepare)
                    self.assertEqual(store.read(job.id).options.speed, 1.2)
                    launch.reset_mock()
                    with patch.object(app.pipeline, 'busy', return_value=True):
                        self.assertEqual(client.post(f'/api/jobs/{job.id}/prepare', headers=headers, json={}).status_code, 400)
                    job.photos = job.photos[:1]
                    store.save(job)
                    self.assertEqual(client.post(f'/api/jobs/{job.id}/prepare', headers=headers, json={}).status_code, 400)
                    launch.assert_not_called()
