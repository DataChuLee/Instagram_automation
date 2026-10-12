import unittest
from studio.models import Storyboard


class PhotoScenesTests(unittest.TestCase):
    def test_expanding_preserves_all_words_order_and_three_candidates(self):
        texts = ['숙소에 이런 물 풍경까지 있다고요? 불빛이 켜진 건물 아래로 수영장이 펼쳐져 휴양지 분위기가 물씬 나요.',
                 '넓은 물 풍경 앞에 나무 사이로 굽이치는 물길이 이어져서 내려다보는 구도도 근사해요.']
        plan = Storyboard(scenes=[{'photos': [0, 1], 'text': texts[0]}, {'photos': [2, 3], 'text': texts[1]}],
                          script_options=[{'title': str(i), 'texts': texts} for i in range(3)])
        expanded = plan.per_photo()
        self.assertEqual([s.photos for s in expanded.scenes], [[0], [1], [2], [3]])
        self.assertEqual(' '.join(s.text for s in expanded.scenes), ' '.join(texts))
        self.assertTrue(all(len(o.texts) == 4 for o in expanded.script_options))
        self.assertEqual(' '.join(expanded.script_options[2].texts), ' '.join(texts))
        self.assertEqual(expanded.per_photo(), expanded)
        self.assertEqual(len(plan.scenes), 2)

    def test_too_few_words_keep_each_photo_editable(self):
        expanded = Storyboard(scenes=[{'photos': [0, 1], 'text': '수영장'}]).per_photo()
        self.assertEqual(len(expanded.scenes), 2)
        self.assertTrue(all(s.text for s in expanded.scenes))
