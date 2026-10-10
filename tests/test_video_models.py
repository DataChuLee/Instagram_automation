import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from PIL import Image

from studio import app, assets, store, video_models
from studio.models import Job, Storyboard
from studio.render import render, run, video_size


def detail(**props):
    return {'description': 'model', 'capabilities': {'i2v': {'parameter_schema': {'properties':
            {k: {'enum': v} for k, v in props.items()}}}}}


SEEDANCE = detail(aspect_ratio=['16:9', '9:16'], resolution=['480p', '720p', '1080p'], duration=['4s', '5s'])
CATALOG = [dict(option, description='', traits=[]) for option in video_models.options('seedance-2.0', SEEDANCE)]


class OptionTests(unittest.TestCase):
    def test_only_720p_to_1080p_vertical_options_are_offered(self):
        self.assertEqual([(o['parameters'], o['native']) for o in video_models.options('seedance-2.0', SEEDANCE)],
            [({'aspect_ratio': '9:16', 'duration': '4s', 'resolution': '720p'}, False),
             ({'aspect_ratio': '9:16', 'duration': '4s', 'resolution': '1080p'}, True)])

    def test_shortest_duration_of_at_least_four_seconds_is_used(self):
        options = video_models.options('wan', detail(aspect_ratio=['9:16'], resolution=['768P', '480P', '1080P'], duration=['10s', '5s', '3s']))
        self.assertEqual([o['parameters'] for o in options],
            [{'aspect_ratio': '9:16', 'duration': '5s', 'resolution': '768P'},
             {'aspect_ratio': '9:16', 'duration': '5s', 'resolution': '1080P'}])

    def test_models_without_explicit_9_16_resolution_are_excluded(self):
        self.assertEqual(video_models.options('kling', detail(duration=['5s'])), [])
        self.assertEqual(video_models.options('minimax', detail(resolution=['768P', '1080P'], duration=['5s'])), [])
        self.assertEqual(video_models.options('wide', detail(aspect_ratio=['16:9'], resolution=['1080p'])), [])
        self.assertEqual(video_models.options('small', detail(resolution=['480p'])), [])


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.patches = [patch(f'studio.{m}.job_path', lambda i: self.folder / i) for m in ('app', 'store')]
        self.patches.append(patch('studio.video_models.catalog', AsyncMock(return_value=CATALOG)))
        for p in self.patches: p.start()
        self.client = TestClient(app.app)
        self.headers = {'X-Studio-Token': app.TOKEN}
        self.job = Job(id='b'*32, workflow_version=2, photos=[{'file': 'p.jpg', 'sha256': 'one'}], photo_order=[0],
            video_model='seedance-2.0', video_parameters=CATALOG[1]['parameters'],
            storyboard=Storyboard(scenes=[{'photos': [0], 'text': '객실'}], motion=[{'photo': 0, 'prompt': 'Water ripples'}]))
        motion = self.job.storyboard.motion[0]
        self.job.generated = {'0': {'file': 'seedance.mp4'}}
        assets.capture(self.job)
        self.default_key = assets.cache_key(self.job, assets.motion_key(self.job, motion))
        store.save(self.job)

    def tearDown(self):
        self.client.close()
        for p in self.patches: p.stop()
        self.temp.cleanup()

    def choose(self, parameters, model='seedance-2.0'):
        return self.client.post(f'/api/jobs/{self.job.id}/video-model', headers=self.headers,
                                json={'model': model, 'parameters': parameters})

    def test_switching_model_requires_new_motion_and_switching_back_reuses_the_clip(self):
        before = store.plan_hash(store.read(self.job.id))
        response = self.choose(CATALOG[0]['parameters'])
        self.assertEqual(response.status_code, 200, response.text)
        saved = store.read(self.job.id)
        self.assertEqual(saved.video_parameters['resolution'], '720p')
        self.assertEqual(saved.generated, {})
        self.assertNotEqual(store.plan_hash(saved), before)
        self.assertEqual(self.choose(CATALOG[1]['parameters']).status_code, 200)
        saved = store.read(self.job.id)
        self.assertEqual(saved.generated['0']['file'], 'seedance.mp4')
        self.assertEqual(store.plan_hash(saved), before)

    def test_unlisted_model_or_parameters_are_rejected(self):
        self.assertEqual(self.choose({'resolution': '480p'}).status_code, 400)
        self.assertEqual(self.choose(CATALOG[1]['parameters'], model='unknown').status_code, 400)
        self.assertEqual(store.read(self.job.id).video_model, 'seedance-2.0')


class UpscaleTests(unittest.TestCase):
    def test_720p_motion_is_upscaled_but_smaller_clip_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            run('-f', 'lavfi', '-i', 'color=c=blue:s=720x1280:r=30:d=0.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', folder / 'motion.mp4')
            with wave.open(str(folder / 'voice.wav'), 'wb') as audio:
                audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\0\0' * 48000)
            job = Job(id='c'*32, photos=[{'sha256': 'one'}],
                storyboard=Storyboard(scenes=[{'photos': [0], 'text': '객실'}], motion=[{'photo': 0, 'prompt': 'Subtle movement'}]),
                generated={'0': {'file': 'motion.mp4'}}, narration={'0': {'file': 'voice.wav'}})
            with patch('studio.render.job_path', return_value=folder):
                result = render(job)
                self.assertEqual(video_size(folder / result['video']), (1080, 1920))
                run('-f', 'lavfi', '-i', 'color=c=blue:s=480x854:r=30:d=0.5', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', folder / 'motion.mp4')
                with self.assertRaisesRegex(RuntimeError, '720p'):
                    render(job)
