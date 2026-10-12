import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from studio import codex
from studio.models import Job, Storyboard, plan_clips


def job(count=10):
    return Job(id='script-options', workflow_version=2, photo_order=list(range(count)),
               photos=[{'file': f'{i}.jpg', 'labels': []} for i in range(count)])


def answer(count=10, options=3, scenes=2):
    order = list(range(count))
    groups = [order[:count // 2], order[count // 2:]][:scenes]
    return {
        'scenes': [{'id': '', 'photos': photos, 'text': '모델이 쓴 문장.'} for photos in groups],
        'script_options': [{'title': f'후보{n}', 'texts': [f'후보{n} 장면{i}.' for i in range(len(groups))]}
                           for n in range(options)],
        'script_choice': 2,
        'motion': [{'photo': clip['photos'][0], 'prompt': 'Shot 1 slow push.', 'photos': clip['photos'], 'seconds': 4}
                   for clip in plan_clips(order)],
        'crop_focus': [{'photo': i, 'x': 0.5, 'y': 0.5} for i in order],
        'motion_recommendations': [{'photo': i, 'recommended': True, 'reason': '좋음', 'prompt': '', 'explanation': ''}
                                   for i in order],
        'selection_reasons': {},
    }


class ScriptOptionTests(unittest.TestCase):
    def analyze(self, value):
        with patch('studio.codex.run_structured', AsyncMock(return_value=value)), \
             patch('studio.codex.job_path', return_value=__import__('pathlib').Path('.')):
            return asyncio.run(codex.analyze(job()))

    def test_analysis_keeps_three_candidates_and_starts_with_the_first(self):
        plan = self.analyze(answer())
        self.assertEqual([o.title for o in plan.script_options], ['후보0', '후보1', '후보2'])
        self.assertEqual(plan.script_choice, 0)
        self.assertEqual([s.text for s in plan.scenes], ['후보0 장면0.'] * 5 + ['후보0 장면1.'] * 5)
        self.assertEqual([s.photos for s in plan.scenes], [[i] for i in range(10)])

    def test_analysis_rejects_too_few_or_misaligned_candidates(self):
        with self.assertRaisesRegex(ValueError, '부족'):
            self.analyze(answer(options=2))
        broken = answer()
        broken['script_options'][1]['texts'].pop()
        with self.assertRaisesRegex(ValueError, '장면 수'):
            self.analyze(broken)

    def test_saved_choice_must_point_to_an_aligned_candidate(self):
        value = answer()
        value['script_choice'] = 1
        self.assertEqual(Storyboard.validate_plan(value, 10, 10).script_choice, 1)
        value['script_choice'] = 3
        with self.assertRaisesRegex(ValueError, '후보 번호'):
            Storyboard.validate_plan(value, 10, 10)
        value['script_choice'] = 0
        value['script_options'][0]['texts'][0] = '  '
        with self.assertRaisesRegex(ValueError, '빈 문장'):
            Storyboard.validate_plan(value, 10, 10)

    def test_plans_without_candidates_still_load(self):
        value = answer()
        del value['script_options'], value['script_choice']
        self.assertEqual(Storyboard.validate_plan(value, 10, 10).script_options, [])

    def test_skill_carries_the_few_shot_examples(self):
        text = codex.skill()
        for phrase in ('대본 후보 3개', '여기 한국 맞아요?', '여기 찜질방 맞아?', '사계절 내내 미온수'):
            self.assertIn(phrase, text)


if __name__ == '__main__':
    unittest.main()
