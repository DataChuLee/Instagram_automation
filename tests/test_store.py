import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import store
from studio.models import Job, Storyboard


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch('studio.store.job_path', lambda job_id: Path(self.temp.name) / job_id)
        self.patch.start()
        self.job = Job(id='a' * 32, photos=[{'sha256': 'hash'}],
                       storyboard=Storyboard(scenes=[{'photos': [0], 'text': '숙소입니다'}]),
                       state='awaiting_approval')
        self.job.quote = {'id': 'q1', 'total': 100, 'plan_hash': store.plan_hash(self.job)}

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_approval_requires_exact_quote(self):
        for quote_id, amount in [('old', 100), ('q1', 101)]:
            with self.assertRaises(ValueError):
                store.approve(self.job, quote_id, amount)
        store.approve(self.job, 'q1', 100)
        store.generation_allowed(self.job)

    def test_caption_edit_keeps_approval_but_script_edit_invalidates(self):
        store.approve(self.job, 'q1', 100)
        self.job.options.caption.font_size = 72
        store.generation_allowed(self.job)
        self.job.storyboard.scenes[0].text = '수영장이 있습니다'
        with self.assertRaises(ValueError):
            store.generation_allowed(self.job)

    def test_atomic_roundtrip_retains_pending_submission(self):
        self.job.generated['0'] = {'state': 'submitted', 'idempotency_key': 'stable'}
        store.save(self.job)
        restored = store.read(self.job.id)
        self.assertEqual(restored.generated['0']['idempotency_key'], 'stable')
