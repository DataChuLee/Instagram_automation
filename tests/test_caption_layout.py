import unittest
from studio.media import caption_image
from studio.models import CaptionStyle


class CaptionLayoutTests(unittest.TestCase):
    def test_multiline_alignment_changes_the_shorter_line(self):
        bounds = []
        for align in ('left', 'center', 'right'):
            layer = caption_image('문 열자마자\n프렌치 감성 가득', CaptionStyle(
                font_size=64, align=align, color='#FFFFFF', outline=0, shadow=0, background_opacity=0))
            box = layer.getbbox()
            top_line = layer.crop((0, box[1], 1080, (box[1] + box[3]) // 2))
            bounds.append(top_line.getbbox()[0])
        self.assertLess(bounds[0], bounds[1])
        self.assertLess(bounds[1], bounds[2])

    def test_lower_left_two_lines_fit_in_frame(self):
        layer = caption_image('감성 숙소 찾는다면\n댓글 남겨주세요', CaptionStyle(
            font_size=70, align='left', x=-35, y=-30, outline=0, shadow=0, background_opacity=0))
        left, top, right, bottom = layer.getbbox()
        self.assertGreaterEqual(left, 60)
        self.assertLessEqual(right, 1020)
        self.assertGreater(top, 1300)
        self.assertLess(bottom, 1800)
