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
                    'resolution': {'enum': ['1080p']}, 'aspect_ratio': {'enum': ['9:16']}}}}}}
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
