import unittest

from studio.models import Job, Storyboard
from studio import assets


class CompositionTests(unittest.TestCase):
    def make_job(self):
        return Job(id='a' * 32, photos=[{'sha256': 'one'}, {'sha256': 'two'}],
                   storyboard=Storyboard(scenes=[{'photos': [0], 'text': '객실'},
                                                  {'photos': [1], 'text': '수영장'}]))

    def test_manual_order_rejects_model_reordering(self):
        value = {'scenes': [{'photos': [1, 0], 'text': '숙소'}]}
        with self.assertRaises(ValueError):
            Storyboard.validate_plan(value, 2, 3, expected_order=[0, 1])

    def test_caption_edit_reuses_voice_and_reordering_preserves_mapping(self):
        job = self.make_job()
        job.narration = {'0': {'file': 'room.mp3'}, '1': {'file': 'pool.mp3'}}
        assets.capture(job)
        job.storyboard.scenes.reverse()
        job.storyboard.scenes[0].caption_text = '푸른 수영장'
        assets.restore(job)
        self.assertEqual(job.narration['0']['file'], 'pool.mp3')
        self.assertEqual(job.narration['1']['file'], 'room.mp3')

    def test_narration_edit_invalidates_only_one_voice(self):
        job = self.make_job()
        job.narration = {'0': {'file': 'room.mp3'}, '1': {'file': 'pool.mp3'}}
        assets.capture(job)
        job.storyboard.scenes[0].text = '밝은 객실'
        assets.restore(job)
        self.assertNotIn('0', job.narration)
        self.assertEqual(job.narration['1']['file'], 'pool.mp3')

    def test_explicit_regeneration_bypasses_cache_but_restore_uses_previous(self):
        job = self.make_job()
        job.narration = {'0': {'file': 'room.mp3'}}
        assets.capture(job)
        key = assets.voice_key(job, job.storyboard.scenes[0])
        job.attempts[key] = 1
        assets.restore(job)
        self.assertNotIn('0', job.narration)
        job.attempts[key] = 0
        assets.restore(job)
        self.assertEqual(job.narration['0']['file'], 'room.mp3')

    def test_legacy_roundtrip_keeps_stable_scene_ids(self):
        job = self.make_job()
        restored = Job.model_validate_json(job.model_dump_json())
        self.assertEqual(job.storyboard.scenes[0].id, restored.storyboard.scenes[0].id)

