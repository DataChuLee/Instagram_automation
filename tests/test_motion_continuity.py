import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import render as renderer


class MotionContinuityTests(unittest.TestCase):
    def test_slowed_shot_reaches_its_last_frame_without_freezing(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, target = folder / 'source.mp4', folder / 'target.mp4'
            renderer.run('-f', 'lavfi', '-i', 'testsrc2=s=160x284:r=24:d=2',
                         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', source)
            filter_value = renderer.motion_filter(0, 2, 150, 24, fill='scale=160:284', smooth=True)
            renderer.run('-i', source, '-vf', filter_value, '-an', '-frames:v', 150,
                         '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', target)
            process = subprocess.run([renderer.ffmpeg(), '-hide_banner', '-i', str(target), '-vf',
                'freezedetect=n=-60dB:d=0.12,showinfo', '-f', 'null', '-'], capture_output=True,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            log = process.stderr.decode('utf-8', 'replace')
            self.assertEqual(process.returncode, 0, log[-2000:])
            self.assertNotIn('lavfi.freezedetect.freeze_start', log)
            times = [float(t) for t in re.findall(r'\bn:\s*\d+.*?pts_time:([\d.]+)', log)]
            self.assertEqual(len(times), 150)
            self.assertAlmostEqual(times[-1], 149 / 30, places=4)
            self.assertTrue(all(abs(b - a - 1 / 30) < 0.00002 for a, b in zip(times, times[1:])))
            self.assertNotIn('zoompan', filter_value)

    def test_cut_duration_is_still_exact_when_shortening_a_shot(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source, target = folder / 'source.mp4', folder / 'target.mp4'
            renderer.run('-f', 'lavfi', '-i', 'testsrc2=s=160x284:r=30:d=3',
                         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', source)
            renderer.run('-i', source, '-vf', renderer.motion_filter(0, 3, 45, 30, fill='scale=160:284'),
                         '-an', '-frames:v', 45, '-r', '30', '-c:v', 'libx264', target)
            self.assertAlmostEqual(renderer.video_info(target)[2], 1.5, places=2)
