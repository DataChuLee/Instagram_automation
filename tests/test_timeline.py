import unittest
import importlib.util
from pathlib import Path


class TimelineTests(unittest.TestCase):
    def load_renderer(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/render_video.py'
        self.assertTrue(path.exists(), 'renderer must exist')
        spec = importlib.util.spec_from_file_location('render_video', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_audio_is_never_cut_and_all_photo_frames_are_accounted_for(self):
        m = self.load_renderer()
        for seconds, photos in [(2.013, 3), (4.997, 2), (1.2, 1)]:
            frames = m.scene_frames(seconds, photos)
            self.assertEqual(sum(m.split_frames(frames, photos)), frames)
            self.assertGreaterEqual(frames / 30, seconds + 0.12)
            self.assertGreaterEqual(min(m.split_frames(frames, photos)), 27)

    def test_srt_rounding_carries_to_next_minute(self):
        m = self.load_renderer()
        self.assertEqual(m.srt_time(59.9996), '00:01:00,000')


if __name__ == '__main__':
    unittest.main()
