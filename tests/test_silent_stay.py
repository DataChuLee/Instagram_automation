import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from studio import assets, store
from studio.models import Job, Storyboard
from studio.pipeline import Pipeline


class SilentStayTests(unittest.IsolatedAsyncioTestCase):
    async def test_silent_quote_and_generation_never_request_narration(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            job = Job(id='b' * 32, domain='stay-silent', workflow_version=2,
                      photos=[{'file': 'photo.jpg', 'sha256': str(i)} for i in range(8)],
                      storyboard=Storyboard(scenes=[{'photos': [i], 'text': '조용한 객실에서\n여유로운 하루'} for i in range(8)]))
            fish, drama = AsyncMock(), AsyncMock()
            pipeline = Pipeline(fish, drama)
            pipeline.preview = AsyncMock()
            with patch('studio.store.job_path', return_value=folder), patch('studio.pipeline.job_path', return_value=folder):
                store.save(job)
                await pipeline.quote(job.id, 'workspace')
                quoted = store.read(job.id)
                self.assertEqual(quoted.quote['voices'], [])
                self.assertEqual(quoted.quote['total'], 0)
                drama.quote.assert_not_awaited()
                store.approve(quoted, quoted.quote['id'], 0)
                await pipeline.generate(job.id)
                drama.generate.assert_not_awaited()
                self.assertEqual(store.read(job.id).narration, {})
                self.assertTrue(assets.ready(store.read(job.id), folder))
                pipeline.preview.assert_awaited_once_with(job.id)


class SilentRenderTests(unittest.TestCase):
    def test_silent_preview_exports_video_and_subtitles_without_audio(self):
        from studio.render import publish_preview, render, run
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            Image.new('RGB', (360, 640), '#228844').save(folder / 'photo.jpg')
            job = Job(id='c' * 32, domain='stay-silent', workflow_version=2,
                      photos=[{'file': 'photo.jpg', 'sha256': str(i)} for i in range(8)],
                      storyboard=Storyboard(scenes=[{'photos': [i], 'text': '문 열자마자\n프렌치 감성 가득'
                          if i < 7 else '감성 숙소 찾는다면\n댓글 남겨주세요'} for i in range(8)]))
            with patch('studio.render.job_path', return_value=folder):
                job.preview = render(job, preview=True)
                self.assertFalse(job.preview.get('audio'))
                result = publish_preview(job)
            self.assertTrue((folder / result['srt']).read_text(encoding='utf-8').strip())
            self.assertEqual(result['duration'], 16)
            import json
            report = json.loads((folder / result['verification']).read_text(encoding='utf-8'))
            self.assertEqual([p['frames'] for p in report['timeline']], [60] * 8)
            blocks = (folder / result['srt']).read_text(encoding='utf-8').strip().split('\n\n')
            self.assertEqual(len(blocks), 8)
            self.assertTrue(all(len(block.splitlines()[2:]) == 2 for block in blocks))
            self.assertTrue(blocks[-1].endswith('댓글 남겨주세요'))
            self.assertFalse((folder / 'stay-voice.mp3').exists())
            with self.assertRaises(RuntimeError):
                run('-i', folder / result['file'], '-map', '0:a', '-f', 'null', '-')
