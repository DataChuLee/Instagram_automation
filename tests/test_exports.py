import io
import re
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from studio.models import Job, Storyboard
from studio.render import ffmpeg, render, run


class ExportTests(unittest.TestCase):
    def test_four_exports_share_timeline_and_clean_video_has_no_captions_or_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            Image.new('RGB', (360, 640), '#228844').save(folder / 'photo.jpg')
            with wave.open(str(folder / 'voice.wav'), 'wb') as audio:
                audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\0\0' * 24000)
            job = Job(id='f' * 32, photos=[{'file': 'photo.jpg'}],
                      storyboard=Storyboard(scenes=[{'photos': [0], 'text': '초록빛 쉼표'}]),
                      narration={'0': {'file': 'voice.wav'}})
            with patch('studio.render.job_path', return_value=folder):
                result = render(job)
            self.assertEqual(set(['file', 'video', 'audio', 'script', 'srt']) - result.keys(), set())
            for key in ['file', 'video', 'audio', 'script', 'srt']:
                self.assertTrue((folder / result[key]).is_file(), key)
            self.assertIn('초록빛 쉼표', (folder / result['script']).read_text(encoding='utf-8-sig'))
            srt = (folder / result['srt']).read_text(encoding='utf-8')
            self.assertIn('00:00:00,000 -->', srt)
            for key in ['file', 'video', 'audio']:
                run('-i', folder / result[key], '-f', 'null', '-')
            def probe(key):
                return subprocess.run([ffmpeg(), '-hide_banner', '-i', str(folder / result[key])],
                    capture_output=True).stderr.decode('utf-8', 'replace')
            clean = probe('video')
            full = probe('file')
            self.assertNotIn('Audio:', clean)
            self.assertIn('Audio:', full)
            self.assertIn('1080x1920', clean)
            self.assertEqual(re.search(r'Duration: ([\d:.]+)', clean).group(1),
                             re.search(r'Duration: ([\d:.]+)', full).group(1))
            video_seconds = float(re.search(r'Duration: 00:00:([\d.]+)', clean).group(1))
            subtitle_seconds = float(re.search(r'--> 00:00:(\d+,\d+)', srt).group(1).replace(',', '.'))
            self.assertLess(abs(video_seconds - subtitle_seconds), 0.034)
            self.assertGreater(video_seconds, 0.65)
            self.assertLess(video_seconds, 0.85)
            # Clean solid-color frame stays uniform at the caption location; final has text.
            def frame(key):
                output = folder / (key + '.png')
                run('-i', folder / result[key], '-frames:v', '1', output)
                with Image.open(output) as image:
                    return image.crop((200, 650, 880, 780)).convert('RGB')
            self.assertLess(max(high - low for low, high in frame('video').getextrema()), 10)
            self.assertGreater(max(high - low for low, high in frame('file').getextrema()), 100)


if __name__ == '__main__':
    unittest.main()
