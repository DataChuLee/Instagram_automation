import tempfile
import unittest
from pathlib import Path

from PIL import Image


class StudioCoreTests(unittest.TestCase):
    def test_caption_default_matches_reference_coordinate(self):
        from studio.models import CaptionStyle
        style = CaptionStyle()
        self.assertEqual(style.center(1080, 1920), (540, 710))
        self.assertEqual(style.font_size, 64)
        self.assertEqual(style.background_opacity, 0.2)

    def test_crop_fills_portrait_without_stretching(self):
        from studio.media import crop_photo
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'landscape.jpg'
            Image.new('RGB', (1600, 900), '#ff3300').save(source)
            result = crop_photo(source, focus_x=0.5, focus_y=0.5)
            self.assertEqual(result.size, (1080, 1920))
            self.assertEqual(result.getpixel((5, 5)), result.getpixel((540, 960)))

    def test_fingerprint_changes_for_motion_but_not_captions(self):
        from studio.models import motion_fingerprint
        self.assertEqual(motion_fingerprint('image-hash', 'Water ripples'),
                         motion_fingerprint('image-hash', 'Water ripples'))
        self.assertNotEqual(motion_fingerprint('image-hash', 'Water ripples'),
                            motion_fingerprint('image-hash', 'Person walks'))

    def test_storyboard_rejects_missing_and_repeated_photos(self):
        from studio.models import Storyboard
        with self.assertRaises(ValueError):
            Storyboard.validate_plan({'scenes': [{'photos': [0], 'text': '숙소입니다'}],
                                     'motion': []}, photo_count=2, max_motion=3)
        with self.assertRaises(ValueError):
            Storyboard.validate_plan({'scenes': [{'photos': [0, 0], 'text': '숙소입니다'}],
                                     'motion': []}, photo_count=2, max_motion=3)

    def test_timing_uses_audio_and_keeps_every_photo(self):
        from studio.media import allocate_frames
        durations = allocate_frames(3.6, [False, True, False], fps=30)
        self.assertEqual(sum(durations), 116)
        self.assertEqual(len(durations), 3)
        self.assertGreater(durations[1], durations[0])
        self.assertTrue(all(value > 0 for value in durations))

    def test_codex_schema_is_strict_for_every_nested_object(self):
        from studio.codex import strict_schema
        from studio.models import Storyboard
        schema = strict_schema(Storyboard.model_json_schema())
        self.assertFalse(schema['additionalProperties'])
        for definition in schema['$defs'].values():
            self.assertFalse(definition['additionalProperties'])
            self.assertEqual(set(definition['required']),set(definition['properties']))


if __name__ == '__main__':
    unittest.main()
