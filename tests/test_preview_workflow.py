import tempfile
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from studio import assets, store
from studio.models import Job, Storyboard
from studio.pipeline import Pipeline


class PreviewWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_candidate_upload_rechecks_job_after_async_read(self):
        from studio import app
        import io
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            job=Job(id='a'*32,workflow_version=2,photos=[{'sha256':'one'}],
                storyboard=Storyboard(scenes=[{'photos':[0],'text':'객실'}]))
            started,release=asyncio.Event(),asyncio.Event()
            image=io.BytesIO()
            Image.new('RGB',(400,500),'green').save(image,format='JPEG')
            async def read(limit):
                started.set()
                await release.wait()
                return image.getvalue()
            file=AsyncMock()
            file.filename='candidate.jpg'
            file.read.side_effect=read
            with patch('studio.store.job_path',return_value=folder),patch('studio.app.job_path',return_value=folder):
                store.save(job)
                task=asyncio.create_task(app.append_candidates(job.id,[file]))
                await started.wait()
                job.narration={'0':{'state':'submitted'}}
                store.save(job)
                release.set()
                with self.assertRaises(ValueError):await task
                self.assertEqual(store.read(job.id).narration['0']['state'],'submitted')

    async def test_failed_motion_unlocks_explicit_retry_without_resubmitting(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            job = Job(id='a'*32, workflow_version=2, photos=[{'sha256': 'one'}],
                storyboard=Storyboard(scenes=[{'photos': [0], 'text': '객실'}], motion=[{'photo':0,'prompt':'Slow pan'}]),
                generated={'0':{'generation_id':'failed-id','state':'submitted'}})
            job.quote={'id':'q','total':0,'videos':[],'voices':[], 'plan_hash':store.plan_hash(job)}
            job.approval={'quote_id':'q','credits':0}
            with patch('studio.store.job_path',return_value=folder),patch('studio.pipeline.job_path',return_value=folder):
                store.save(job)
                pipeline=Pipeline(AsyncMock(),AsyncMock())
                pipeline.fish.call.return_value={'status':'failed'}
                with self.assertRaises(RuntimeError):await pipeline.generate(job.id)
                saved=store.read(job.id)
                self.assertEqual(saved.generated['0']['state'],'failed')
                self.assertFalse(assets.pending(saved))
                pipeline.fish.call.assert_awaited_once_with('get_generation_status',{'generation_id':'failed-id'})

    async def test_voice_recovery_reserves_job_and_preserves_completed_history(self):
        from studio import app
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            job=Job(id='a'*32,workflow_version=2,photos=[{'sha256':'one'}],
                storyboard=Storyboard(scenes=[{'photos':[0],'text':'객실'}]),
                narration={'0':{'file':'old.mp3','state':'completed'}}, result={'file':'old-export.mp4'})
            started=asyncio.Event()
            release=asyncio.Event()
            async def read(limit):
                started.set()
                await release.wait()
                return b'new voice'
            file=AsyncMock()
            file.read.side_effect=read
            pipeline=Pipeline(AsyncMock(),AsyncMock())
            with patch('studio.store.job_path',return_value=folder),patch('studio.app.job_path',return_value=folder),patch('studio.app.pipeline',pipeline),patch('studio.render.run'):
                store.save(job)
                task=asyncio.create_task(app.recover_voice(job.id,0,file))
                await started.wait()
                try:
                    with self.assertRaises(ValueError):pipeline.launch(job.id,pipeline.generate)
                finally:release.set()
                await task
                saved=store.read(job.id)
                self.assertIsNone(saved.result)
                key=assets.voice_key(saved,saved.storyboard.scenes[0])
                self.assertEqual(saved.assets[key+':0']['file'],'old.mp3')
                self.assertEqual(saved.attempts[key],1)
                self.assertFalse(pipeline.busy(job.id))
    async def test_voices_are_made_while_motion_is_still_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            job = Job(id='a'*32, workflow_version=2, photos=[{'sha256': 'one'}],
                storyboard=Storyboard(scenes=[{'photos': [0], 'text': '객실'}], motion=[{'photo': 0, 'prompt': 'Slow pan'}]),
                generated={'0': {'generation_id': 'g1', 'state': 'submitted', 'asset_key': 'k'}})
            job.quote = {'id': 'q', 'total': 2, 'videos': [], 'voices': [{'scene': 0, 'credits': 2}], 'plan_hash': store.plan_hash(job)}
            job.approval = {'quote_id': 'q', 'credits': 2}
            pipeline = Pipeline(AsyncMock(), AsyncMock())
            # The clip only finishes once a voice has been made, which needs both to run at once.
            async def call(name, args):
                if name == 'get_generation_status':
                    return {'status': 'completed' if pipeline.drama.generate.await_count else 'running'}
                return {'media': {'url': 'https://example.com/clip.mp4'}}
            pipeline.fish.call.side_effect = call
            pipeline.preview = AsyncMock()
            real_sleep = asyncio.sleep
            with patch('studio.store.job_path', return_value=folder), patch('studio.pipeline.job_path', return_value=folder), \
                 patch('studio.pipeline.video_size', return_value=(1080, 1920)), \
                 patch('studio.pipeline.asyncio.sleep', lambda seconds: real_sleep(0)):
                store.save(job)
                await pipeline.generate(job.id)
                saved = store.read(job.id)
            self.assertTrue(saved.generated['0']['file'])
            self.assertTrue(saved.narration['0']['file'])
            pipeline.preview.assert_awaited_once_with(job.id)

    async def test_generation_stops_at_preview_and_does_not_export(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'voice.mp3').write_bytes(b'ready')
            job = Job(id='a'*32, workflow_version=2, photos=[{'sha256': 'one'}],
                storyboard=Storyboard(scenes=[{'photos': [0], 'text': '객실'}]),
                narration={'0': {'file': 'voice.mp3'}})
            job.quote = {'id': 'q', 'total': 0, 'videos': [], 'voices': [], 'plan_hash': store.plan_hash(job)}
            job.approval = {'quote_id': 'q', 'credits': 0}
            with patch('studio.store.job_path', return_value=folder), patch('studio.pipeline.job_path', return_value=folder):
                store.save(job)
                pipeline = Pipeline(AsyncMock(), AsyncMock())
                pipeline.preview = AsyncMock()
                pipeline.render = AsyncMock()
                await pipeline.generate(job.id)
                pipeline.preview.assert_awaited_once_with(job.id)
                pipeline.render.assert_not_called()

    async def test_free_preview_requires_all_current_assets_without_paid_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            job = Job(id='a'*32, workflow_version=2, photos=[{'sha256': 'one'}],
                      storyboard=Storyboard(scenes=[{'photos': [0], 'text': '객실'}]))
            with patch('studio.store.job_path', return_value=folder), patch('studio.pipeline.job_path', return_value=folder):
                store.save(job)
                pipeline = Pipeline(AsyncMock(), AsyncMock())
                with self.assertRaises(ValueError):
                    await pipeline.preview(job.id)
                pipeline.fish.call.assert_not_called()
                pipeline.drama.generate.assert_not_called()

    async def test_existing_voice_is_not_quoted_again(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'voice.mp3').write_bytes(b'ready')
            job = Job(id='a'*32, workflow_version=2, photos=[{'sha256': 'one'}],
                storyboard=Storyboard(scenes=[{'photos': [0], 'text': '객실'}]),
                narration={'0': {'file': 'voice.mp3'}})
            with patch('studio.store.job_path', return_value=folder), patch('studio.pipeline.job_path', return_value=folder):
                store.save(job)
                pipeline = Pipeline(AsyncMock(), AsyncMock())
                await pipeline.quote(job.id, 'workspace')
                self.assertEqual(store.read(job.id).quote['total'], 0)
                pipeline.drama.quote.assert_not_called()
