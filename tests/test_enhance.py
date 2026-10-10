import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from studio import enhance

SESSION = '01a12604-e4f0-75c1-9af2-50baf7898199'


class FakeProcess:
    def __init__(self, home, size=(941, 1672), stderr=None, image=True, hang=False):
        self.home, self.size, self.image, self.hang = home, size, image, hang
        self.stderr = stderr if stderr is not None else f'session id: {SESSION}\n'
        self.prompt = None
        self.killed = False
        self.returncode = 0

    async def communicate(self, data):
        self.prompt = data.decode('utf-8')
        if self.hang:
            await asyncio.sleep(10)
        if self.image:
            folder = self.home / 'generated_images' / SESSION
            folder.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', self.size, 'teal').save(folder / 'exec-1.png')
        return b'', self.stderr.encode('utf-8')

    def kill(self):
        self.killed = True

    async def wait(self):
        return 0


class EnhanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.home = self.root / 'codex'
        self.source = self.root / 'photo-000.jpg'
        Image.new('RGB', (1200, 700), 'orange').save(self.source)
        self.target = self.root / 'photo-000-enhanced.jpg'
        self.patches = [patch('studio.enhance.codex.executable', return_value='codex.exe'),
                        patch('studio.enhance.codex.environment', return_value={'CODEX_HOME': str(self.home)})]
        for item in self.patches:
            item.start()

    async def asyncTearDown(self):
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def run_with(self, process):
        async def spawn(*args, **kwargs):
            self.args = args
            return process
        return patch('studio.enhance.asyncio.create_subprocess_exec', side_effect=spawn)

    async def test_saves_portrait_1080p_and_removes_codex_copy(self):
        process = FakeProcess(self.home)
        with self.run_with(process):
            await enhance.enhance_photo(self.source, self.target)
        with Image.open(self.target) as image:
            self.assertEqual(image.size, (1080, 1920))
            self.assertEqual(image.format, 'JPEG')
        self.assertFalse((self.home / 'generated_images' / SESSION).exists())
        self.assertIn(str(self.source), self.args)
        self.assertIn('read-only', self.args)
        self.assertIn(enhance.prompt().strip(), process.prompt)

    async def test_non_portrait_result_is_center_cropped(self):
        with self.run_with(FakeProcess(self.home, size=(1024, 1024))):
            await enhance.enhance_photo(self.source, self.target)
        with Image.open(self.target) as image:
            self.assertEqual(image.size, (1080, 1920))

    async def test_missing_image_is_an_enhance_error(self):
        with self.run_with(FakeProcess(self.home, image=False)):
            with self.assertRaises(enhance.EnhanceError):
                await enhance.enhance_photo(self.source, self.target)
        self.assertFalse(self.target.exists())

    async def test_unsafe_session_id_is_ignored(self):
        with self.run_with(FakeProcess(self.home, image=False, stderr='session id: ../../x\n')):
            with self.assertRaises(enhance.EnhanceError):
                await enhance.enhance_photo(self.source, self.target)

    async def test_usage_limit_is_distinguished(self):
        with self.run_with(FakeProcess(self.home, image=False, stderr='ERROR: You have hit your usage limit.\n')):
            with self.assertRaises(enhance.UsageLimit):
                await enhance.enhance_photo(self.source, self.target)

    async def test_timeout_kills_codex(self):
        process = FakeProcess(self.home, hang=True)
        with self.run_with(process), patch('studio.enhance.TIMEOUT', 0.01):
            with self.assertRaises(enhance.EnhanceError):
                await enhance.enhance_photo(self.source, self.target)
        self.assertTrue(process.killed)

    async def test_failed_retry_keeps_previous_enhanced_file(self):
        self.target.write_bytes(b'previous')
        with self.run_with(FakeProcess(self.home, image=False)):
            with self.assertRaises(enhance.EnhanceError):
                await enhance.enhance_photo(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b'previous')

    def test_prompt_keeps_signage_and_removes_people(self):
        text = enhance.prompt()
        for phrase in ('9:16', '사람', '간판', '화사'):
            self.assertIn(phrase, text)


class PhotoStateTests(unittest.TestCase):
    def job(self):
        from studio.models import Job
        return Job(id='a' * 32, workflow_version=2,
                   photos=[{'sha256': 's0', 'file': 'photo-000.jpg'}],
                   candidates=[{'id': 's0', 'sha256': 's0', 'file': 'photo-000.jpg'}])

    def test_success_switches_to_enhanced_and_mirrors_candidate(self):
        job = self.job()
        enhance.record(job, 0, file='photo-000-enhanced.jpg')
        photo = job.photos[0]
        self.assertEqual(photo['file'], 'photo-000-enhanced.jpg')
        self.assertEqual(photo['original_file'], 'photo-000.jpg')
        self.assertEqual(photo['enhanced'], {'file': 'photo-000-enhanced.jpg', 'state': 'done', 'active': True})
        self.assertEqual(job.candidates[0]['enhanced'], photo['enhanced'])
        self.assertEqual(job.candidates[0]['file'], 'photo-000.jpg')

    def test_failure_keeps_original_or_previous_enhanced(self):
        job = self.job()
        enhance.record(job, 0, error='생성된 이미지가 없습니다.')
        self.assertEqual(job.photos[0]['file'], 'photo-000.jpg')
        self.assertEqual(job.photos[0]['enhanced']['state'], 'failed')
        enhance.record(job, 0, file='photo-000-enhanced.jpg')
        enhance.record(job, 0, error='시간 초과')
        self.assertEqual(job.photos[0]['file'], 'photo-000-enhanced.jpg')
        self.assertEqual(job.photos[0]['enhanced']['state'], 'done')
        self.assertEqual(job.photos[0]['enhanced']['error'], '시간 초과')

    def test_toggle_between_original_and_enhanced(self):
        job = self.job()
        with self.assertRaises(ValueError):
            enhance.use(job, 0, True)
        enhance.record(job, 0, file='photo-000-enhanced.jpg')
        enhance.use(job, 0, False)
        self.assertEqual(job.photos[0]['file'], 'photo-000.jpg')
        self.assertFalse(job.candidates[0]['enhanced']['active'])
        enhance.use(job, 0, True)
        self.assertEqual(job.photos[0]['file'], 'photo-000-enhanced.jpg')

    def test_files_lists_every_photo_version(self):
        job = self.job()
        enhance.record(job, 0, file='photo-000-enhanced.jpg')
        enhance.use(job, 0, False)
        self.assertEqual(enhance.files(job), {'photo-000.jpg', 'photo-000-enhanced.jpg'})


class CompositionCarryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.patches = [patch('studio.composition.job_path', lambda _: self.folder),
                        patch('studio.recommendation.job_path', lambda _: self.folder)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.temp.cleanup()

    def test_recomposition_keeps_enhanced_choice(self):
        from studio import composition, recommendation
        from studio.models import Job
        for name, color in (('photo-000.jpg', 'red'), ('photo-001.jpg', 'blue'), ('photo-000-enhanced.jpg', 'teal')):
            Image.new('RGB', (600, 400), color).save(self.folder / name)
        job = Job(id='a' * 32, workflow_version=2,
                  photos=[{'sha256': 's0', 'file': 'photo-000.jpg'}, {'sha256': 's1', 'file': 'photo-001.jpg'}])
        job.candidates = recommendation.candidates(job)
        enhance.record(job, 0, file='photo-000-enhanced.jpg')
        composition.select(job, ['s1', 's0'])
        moved = job.photos[1]
        self.assertEqual(moved['file'], 'photo-000-enhanced.jpg')
        self.assertTrue(moved['original_file'].startswith('active-'))
        enhance.use(job, 1, False)
        composition.select(job, ['s0'])
        self.assertTrue(job.photos[0]['file'].startswith('active-'))
        self.assertEqual(job.photos[0]['enhanced']['state'], 'done')

    def test_candidates_built_from_enhanced_photo_point_to_original(self):
        from studio import recommendation
        from studio.models import Job
        job = Job(id='a' * 32, photos=[{'sha256': 's0', 'file': 'photo-000.jpg'}])
        enhance.record(job, 0, file='photo-000-enhanced.jpg')
        self.assertEqual(recommendation.candidates(job)[0]['file'], 'photo-000.jpg')
