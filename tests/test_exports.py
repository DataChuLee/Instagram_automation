import io
import math
import struct
import re
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from studio.models import Job, Storyboard
from studio.render import ffmpeg, render, run, publish_preview


def tone(frames):
    # A steady 440Hz tone: narration silence is trimmed away during rendering, so fixtures need audible sound.
    return b''.join(struct.pack('<h', round(8000 * math.sin(2 * math.pi * 440 * i / 48000))) for i in range(frames))


class ExportTests(unittest.TestCase):
    def test_short_motion_holds_last_frame_instead_of_looping(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            run('-f','lavfi','-i','color=c=red:s=1080x1920:r=30:d=0.1',
                '-f','lavfi','-i','color=c=blue:s=1080x1920:r=30:d=0.1',
                '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]',
                '-c:v','libx264','-pix_fmt','yuv420p',folder/'motion.mp4')
            with wave.open(str(folder/'voice.wav'),'wb') as audio:
                audio.setparams((1,2,48000,0,'NONE','not compressed'))
                audio.writeframes(tone(48000))
            job=Job(id='f'*32,photos=[{'sha256':'one'}],
                storyboard=Storyboard(scenes=[{'photos':[0],'text':'객실'}],motion=[{'photo':0,'prompt':'Subtle movement'}]),
                generated={'0':{'file':'motion.mp4'}},narration={'0':{'file':'voice.wav'}})
            with patch('studio.render.job_path',return_value=folder):result=render(job)
            run('-ss','0.82','-i',folder/result['video'],'-frames:v','1',folder/'late.png')
            with Image.open(folder/'late.png') as image:
                red,green,blue=image.convert('RGB').getpixel((500,1000))
            self.assertGreater(blue,200)
            self.assertLess(red,40)

    def test_preview_exports_identical_bytes_and_long_captions_split_into_single_lines(self):
        from studio.assets import render_revision
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            Image.new('RGB', (360, 640), '#228844').save(folder / 'photo.jpg')
            with wave.open(str(folder / 'voice.wav'), 'wb') as audio:
                audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                audio.writeframes(tone(48000))
            caption = '초록빛 정원에서 쉬어가는 하루, 아름다운 객실을 둘러보고 마음에 드는 숙소를 저장해 두세요. ' * 3
            job = Job(id='f'*32, workflow_version=2, photos=[{'file': 'photo.jpg', 'sha256': 'one'}],
                storyboard=Storyboard(scenes=[{'photos': [0], 'text': caption.strip()}]),
                narration={'0': {'file': 'voice.wav'}})
            with patch('studio.render.job_path', return_value=folder):
                job.preview = render(job, preview=True)
                job.preview['revision'] = render_revision(job)
                self.assertFalse((folder / 'stay-reel.mp4').exists())
                before = (folder / job.preview['file']).read_bytes()
                final = publish_preview(job)
            self.assertEqual(before, (folder / final['file']).read_bytes())
            cues = (folder / final['srt']).read_text(encoding='utf-8').strip().split('\n\n')
            self.assertGreater(len(cues), 1)
            self.assertTrue(all(len(cue.splitlines()[2:]) == 1 for cue in cues))
            self.assertEqual((folder / final['script']).read_text(encoding='utf-8-sig').strip(), caption.strip())

    def test_four_exports_share_timeline_and_clean_video_has_no_captions_or_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            Image.new('RGB', (360, 640), '#228844').save(folder / 'photo.jpg')
            with wave.open(str(folder / 'voice.wav'), 'wb') as audio:
                audio.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
                audio.writeframes(tone(24000))
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
            self.assertGreater(video_seconds, 0.45)
            self.assertLess(video_seconds, 0.6)
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
