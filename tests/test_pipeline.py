import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from studio import store
from studio.models import Job, Storyboard
from studio.pipeline import Pipeline


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.patch = patch('studio.store.job_path', lambda _: self.folder)
        self.patch.start()
        self.patch2 = patch('studio.pipeline.job_path', lambda _: self.folder)
        self.patch2.start()
        self.fish, self.drama = AsyncMock(), AsyncMock()
        self.pipeline = Pipeline(self.fish, self.drama)
        self.job = Job(id='b'*32, photos=[{'sha256': 'x', 'file': 'photo.jpg'}],
                       storyboard=Storyboard(scenes=[{'photos': [0], 'text': '숙소'}]),
                       narration={'0': {'state': 'submitted'}})
        self.job.quote = {'id': 'q', 'total': 2, 'plan_hash': store.plan_hash(self.job),
                          'videos': [], 'voices': [{'scene': 0, 'credits': 2}]}
        self.job.approval = {'quote_id': 'q', 'credits': 2}
        store.save(self.job)

    async def asyncTearDown(self):
        self.patch.stop()
        self.patch2.stop()
        self.temp.cleanup()

    async def test_recommend_stops_before_script_so_photos_can_be_enhanced(self):
        job = Job(id='c'*32, workflow_version=2, target_count=2,
                  candidates=[{'id': i, 'file': f'{i}.jpg'} for i in 'abc'])
        store.save(job)
        selection = {'ids': ['c', 'a'], 'reasons': [{'id': 'a', 'reason': '객실'}, {'id': 'c', 'reason': '수영장'}]}
        def select(working, ids):
            working.photos = [{'id': i, 'sha256': i, 'file': f'{i}.jpg'} for i in ids]
            working.photo_order = [0, 1]
            working.storyboard = None
        with patch('studio.pipeline.recommendation.choose', AsyncMock(return_value=selection)),              patch('studio.pipeline.composition.select', side_effect=select),              patch('studio.pipeline.codex.analyze', AsyncMock()) as analyze,              patch('studio.pipeline.enhance.enhance_photo', AsyncMock()) as remake:
            await self.pipeline.recommend(job.id)
            saved = store.read(job.id)
            self.assertIsNone(saved.storyboard)
            self.assertEqual(saved.composition_mode, 'ai')
            self.assertEqual(saved.selection_reasons, {'c': '수영장', 'a': '객실'})
            await self.pipeline.enhance(job.id)
        analyze.assert_not_called()
        self.assertEqual(remake.await_count, 2)

    async def test_uncertain_voice_submission_is_never_repeated(self):
        await self.pipeline.guarded(self.job.id, self.pipeline.generate)
        self.drama.generate.assert_not_called()
        self.assertIn('자동 재요청하지 않습니다', store.read(self.job.id).error)

    async def test_render_only_never_calls_paid_provider(self):
        with patch('studio.pipeline.render', return_value={'file': 'stay-reel.mp4'}) as renderer:
            await self.pipeline.render(self.job.id)
        renderer.assert_called_once()
        self.fish.call.assert_not_called()
        self.drama.generate.assert_not_called()
        self.assertEqual(store.read(self.job.id).state, 'complete')

    async def test_generation_requires_approval(self):
        self.job.approval = None
        store.save(self.job)
        with self.assertRaises(ValueError):
            await self.pipeline.generate(self.job.id)
        self.fish.call.assert_not_called()
        self.drama.generate.assert_not_called()

    async def test_mcp_resume_uses_saved_block_without_another_generation(self):
        self.job.narration['0'].update(project_id='project', block='block', rev='rev')
        store.save(self.job)
        async def recover(record, path, saved):
            await saved({'state': 'completed', 'url': 'https://fish.audio/audio.mp3'})
            path.write_bytes(b'audio')
        self.drama.recover.side_effect = recover
        self.pipeline.render = AsyncMock()
        await self.pipeline.generate(self.job.id)
        self.drama.recover.assert_awaited_once()
        self.drama.generate.assert_not_called()
        self.assertEqual(store.read(self.job.id).narration['0']['file'], 'voice-000.mp3')

    async def test_quote_persists_mcp_references_before_approval(self):
        self.job.narration = {}
        store.save(self.job)
        async def quote(text, name, record, persist):
            await persist({'project_id': 'project', 'block': 'block', 'rev': 'rev'})
            return {'credits': 6, 'balance': 100, 'project_id': 'project', 'block': 'block', 'rev': 'rev'}
        self.drama.quote.side_effect = quote
        await self.pipeline.quote(self.job.id, 'workspace')
        saved = store.read(self.job.id)
        self.assertEqual(saved.narration['0']['block'], 'block')
        self.assertEqual(saved.quote['voices'][0]['project_id'], 'project')
        self.assertEqual(saved.quote['total'], 6)
        self.drama.generate.assert_not_called()

    async def test_legacy_free_quote_does_not_block_reanalysis(self):
        self.job.narration = {'0': {'project_id': 'project', 'block': 'block',
                                  'asset_key': 'prepared', 'text': '숙소'}}
        store.save(self.job)
        with patch('studio.pipeline.codex.analyze', AsyncMock(return_value=self.job.storyboard)):
            await self.pipeline.analyze(self.job.id)
        self.assertEqual(store.read(self.job.id).state, 'uploaded')

    async def test_multi_photo_clip_is_quoted_as_reference_video_of_its_length(self):
        from PIL import Image
        self.job.photos = [{'sha256': str(i), 'file': f'photo-{i}.jpg'} for i in range(3)]
        for i in range(3):
            Image.new('RGB', (360, 640), (i * 80, 20, 50)).save(self.folder / f'photo-{i}.jpg')
        self.job.storyboard = Storyboard(scenes=[{'photos': [0, 1, 2], 'text': '숙소'}],
            motion=[{'photo': 0, 'photos': [0, 1, 2], 'seconds': 5, 'prompt': 'Shot 1, Shot 2, Shot 3'}])
        self.job.narration = {}
        store.save(self.job)
        requests = []
        async def call(name, args):
            if name == 'get_media_model':
                return {'capabilities': {'i2v_ref': {'parameter_schema': {'properties': {
                    'resolution': {'enum': ['720p']}, 'aspect_ratio': {'enum': ['9:16']}, 'duration': {'enum': ['4s', '5s']}}}}}}
            requests.append(args)
            return {'can_generate': True, 'credits': 3600, 'pricing_version': 'test', 'balance': 10000}
        self.fish.call.side_effect = call
        self.fish.upload.side_effect = ['key-0', 'key-1', 'key-2']
        self.drama.quote.return_value = {'credits': 2}
        await self.pipeline.quote(self.job.id, 'test-workspace')
        self.assertEqual(requests[0]['inputs'], [{'role': 'ref', 'object_key': f'key-{i}'} for i in range(3)])
        self.assertEqual(requests[0]['parameters']['duration'], '5s')
        self.assertNotIn('operation', requests[0])
        self.assertEqual(store.read(self.job.id).quote['total'], 3602)

    async def test_quote_uses_only_selected_photos_and_exact_prompts(self):
        from PIL import Image
        self.job.photos = [{'sha256': str(i), 'file': f'photo-{i}.jpg'} for i in range(3)]
        for i in range(3):
            Image.new('RGB', (360, 640), (i * 80, 20, 50)).save(self.folder / f'photo-{i}.jpg')
        self.job.storyboard = Storyboard(scenes=[{'photos': [0, 1, 2], 'text': '숙소'}],
            motion=[{'photo': 1, 'prompt': '물결이 잔잔하게 움직입니다'}, {'photo': 2, 'prompt': 'Slow pan right'}])
        self.job.narration = {}
        store.save(self.job)
        async def call(name, args):
            if name == 'get_media_model':
                return {'capabilities': {'i2v': {'parameter_schema': {'properties': {
                    'resolution': {'enum': ['720p', '1080p']}, 'aspect_ratio': {'enum': ['9:16']}, 'duration': {'enum': ['4s']}}}}}}
            self.assertEqual(name, 'estimate_video_generation')
            return {'can_generate': True, 'credits': 3, 'pricing_version': 'test', 'balance': 100}
        self.fish.call.side_effect = call
        self.fish.upload.return_value = 'test-key'
        self.drama.quote.return_value = {'credits': 2}
        await self.pipeline.quote(self.job.id, 'test-workspace')
        quote = store.read(self.job.id).quote
        self.assertEqual([item['photo'] for item in quote['videos']], [1, 2])
        self.assertEqual([item['request']['prompt'] for item in quote['videos']],
                         ['물결이 잔잔하게 움직입니다', 'Slow pan right'])


class EnhancePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.patches = [patch('studio.store.job_path', lambda _: self.folder),
                        patch('studio.pipeline.job_path', lambda _: self.folder)]
        for item in self.patches:
            item.start()
        self.pipeline = Pipeline(AsyncMock(), AsyncMock())
        self.job = Job(id='c' * 32, workflow_version=2,
                       photos=[{'sha256': f's{i}', 'file': f'photo-{i:03}.jpg'} for i in range(3)])
        store.save(self.job)

    async def asyncTearDown(self):
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def fake(self, outcomes):
        """outcomes maps source file name to None (success) or an exception to raise."""
        self.calls = []
        async def enhance_photo(source, target):
            self.calls.append(source.name)
            outcome = outcomes.get(source.name)
            if outcome:
                raise outcome
            target.write_bytes(b'enhanced')
        return patch('studio.pipeline.enhance.enhance_photo', side_effect=enhance_photo)

    async def test_partial_failure_keeps_original_and_finishes_uploaded(self):
        from studio.enhance import EnhanceError
        with self.fake({'photo-001.jpg': EnhanceError('생성된 이미지가 없습니다.')}):
            await self.pipeline.enhance(self.job.id, None)
        job = store.read(self.job.id)
        self.assertEqual([p['file'] for p in job.photos],
                         ['photo-000-enhanced.jpg', 'photo-001.jpg', 'photo-002-enhanced.jpg'])
        self.assertEqual(job.photos[1]['enhanced']['state'], 'failed')
        self.assertEqual(job.state, 'uploaded')
        self.assertIn('성공 2장', job.message)
        self.assertIn('실패 1장', job.message)

    async def test_usage_limit_stops_and_keeps_finished_photos(self):
        from studio.enhance import UsageLimit
        self.pipeline_limit = UsageLimit('Codex 구독 사용 한도에 도달했습니다.')
        with self.fake({'photo-000.jpg': self.pipeline_limit}):
            await self.pipeline.guarded(self.job.id, self.pipeline.enhance, None)
        job = store.read(self.job.id)
        self.assertEqual(job.state, 'error')
        self.assertIn('사용 한도', job.error)
        self.assertNotIn('enhanced', job.photos[0])
        self.assertFalse(any('enhancing' in p for p in job.photos))

    async def test_photos_are_marked_while_enhancing(self):
        seen = []
        async def enhance_photo(source, target):
            seen.append([p.get('enhancing') for p in store.read(self.job.id).photos])
            target.write_bytes(b'enhanced')
        with patch('studio.pipeline.enhance.enhance_photo', side_effect=enhance_photo):
            await self.pipeline.enhance(self.job.id, [2])
        self.assertEqual(seen, [[None, None, True]])
        self.assertNotIn('enhancing', store.read(self.job.id).photos[2])

    async def test_rerun_skips_enhanced_photos_and_retry_uses_original(self):
        with self.fake({}):
            await self.pipeline.enhance(self.job.id, None)
        with self.fake({}):
            await self.pipeline.enhance(self.job.id, None)
        self.assertEqual(self.calls, [])
        with self.fake({}):
            await self.pipeline.enhance(self.job.id, [1])
        self.assertEqual(self.calls, ['photo-001.jpg'])

    async def test_enhance_refused_after_analysis(self):
        self.job.storyboard = Storyboard(scenes=[{'photos': [0, 1, 2], 'text': '숙소'}])
        store.save(self.job)
        with self.fake({}), self.assertRaises(ValueError):
            await self.pipeline.enhance(self.job.id, None)

    async def test_interrupted_enhancement_returns_to_uploaded(self):
        self.job.state = 'enhancing'
        self.job.photos[0]['enhancing'] = True
        store.save(self.job)
        with patch('studio.store.list_jobs', return_value=[store.read(self.job.id)]):
            store.recover()
        job = store.read(self.job.id)
        self.assertEqual(job.state, 'uploaded')
        self.assertIn('다시', job.message)
        self.assertFalse(any('enhancing' in p for p in job.photos))
