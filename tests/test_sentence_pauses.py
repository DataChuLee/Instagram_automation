import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from studio.render import PHRASE_PAUSE, SENTENCE_PAUSE, pace_pauses, sentences

RATE = 48000


def write(path, parts):
    """parts: (seconds, loud) pairs written as a stereo 16-bit wav."""
    frames = b''
    for seconds, loud in parts:
        for i in range(round(seconds * RATE)):
            value = round(8000 * math.sin(2 * math.pi * 440 * i / RATE)) if loud else 0
            frames += struct.pack('<hh', value, value)
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((2, 2, RATE, 0, 'NONE', 'not compressed'))
        audio.writeframes(frames)


def runs(path):
    """Lengths of alternating loud/quiet runs in 10ms blocks, first run loud."""
    with wave.open(str(path)) as audio:
        data = audio.readframes(audio.getnframes())
    samples = struct.unpack(f'<{len(data)//2}h', data)
    step = RATE // 100 * 2
    blocks = [max(map(abs, samples[i:i + step])) >= 328 for i in range(0, len(samples), step)]
    result, current, count = [], blocks[0], 0
    for value in blocks:
        if value == current:
            count += 1
        else:
            result.append(round(count / 100, 2)); current, count = value, 1
    return result + [round(count / 100, 2)]


class SentencePauseTests(unittest.TestCase):
    def test_sentences_split_at_end_marks_only(self):
        self.assertEqual(sentences('여기 한국 맞아요? 진짜 미쳤어요, 대박. 저장해 두세요!'),
                         ['여기 한국 맞아요?', '진짜 미쳤어요, 대박.', '저장해 두세요!'])

    def test_sentence_breaks_get_a_breath_and_phrase_pauses_stay_short(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'in.wav', Path(folder) / 'out.wav'
            # lead silence, sentence 1, long pause (sentence end), phrase, short pause (comma), phrase, tail
            write(source, [(0.3, False), (0.5, True), (0.6, False), (0.4, True), (0.2, False), (0.3, True), (1.0, False)])
            spans = pace_pauses(source, target, breaks=1)
            self.assertEqual(runs(target), [0.5, SENTENCE_PAUSE, 0.4, PHRASE_PAUSE, 0.3, SENTENCE_PAUSE])
            self.assertEqual([tuple(round(v, 2) for v in span) for span in spans], [(0, 0.5), (0.75, 1.53)])

    def test_pauses_are_stretched_by_speed_so_atempo_lands_on_target(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'in.wav', Path(folder) / 'out.wav'
            write(source, [(0.5, True), (0.6, False), (0.5, True)])
            spans = pace_pauses(source, target, breaks=1, scale=1.2)
            self.assertAlmostEqual(runs(target)[1], round(SENTENCE_PAUSE * 1.2, 2), delta=0.011)
            self.assertAlmostEqual(spans[1][0] - spans[0][1], SENTENCE_PAUSE, delta=0.011)

    def test_scene_ending_mid_sentence_gets_only_a_phrase_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'in.wav', Path(folder) / 'out.wav'
            write(source, [(0.5, True), (0.7, False)])
            pace_pauses(source, target, breaks=0, tail=PHRASE_PAUSE)
            self.assertEqual(runs(target), [0.5, PHRASE_PAUSE])

    def test_pause_shorter_than_the_cap_is_kept_as_is(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'in.wav', Path(folder) / 'out.wav'
            write(source, [(0.5, True), (0.05, False), (0.5, True)])
            self.assertEqual(len(pace_pauses(source, target, breaks=0)), 1)
            self.assertEqual(runs(target)[:3], [0.5, 0.05, 0.5])


if __name__ == '__main__':
    unittest.main()
