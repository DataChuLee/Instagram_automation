import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

from studio import codex
from studio.models import Job, Storyboard, plan_clips


class StayScriptModeTests(unittest.TestCase):
    def test_silent_prompt_and_plan_use_two_second_single_photo_scenes(self):
        job = Job(id='f' * 32, domain='stay-silent', photos=[{'file': f'{i}.jpg'} for i in range(8)])
        seen = {}
        async def answer(folder, prompt, photos, schema, name):
            seen['prompt'] = prompt
            texts = ['문 열자마자\n프렌치 감성 가득'] * 7 + ['감성 숙소 찾는다면\n저장해주세요']
            return {'scenes': [{'photos': [i], 'text': text} for i, text in enumerate(texts)],
                    'script_options': [{'title': f'후보 {i}', 'texts': texts} for i in range(3)],
                    'motion': [{'photo': clip['photos'][0], 'photos': clip['photos'], 'seconds': clip['seconds'], 'prompt': 'Hard cut.'}
                               for clip in plan_clips(list(range(8)), total=16)],
                    'crop_focus': [{'photo': i, 'x': .5, 'y': .5} for i in range(8)],
                    'motion_recommendations': [{'photo': i, 'recommended': True, 'reason': '선명함'} for i in range(8)]}
        with patch('studio.codex.run_structured', answer), patch('studio.codex.job_path', return_value=Path('.')):
            plan = asyncio.run(codex.analyze(job))
        self.assertEqual(sum(m.seconds for m in plan.motion), 16)
        self.assertEqual(len(plan.scenes), 8)
        for option in plan.script_options:
            self.assertEqual(option.texts[-1].splitlines()[-1], '댓글 남겨주세요')
        self.assertEqual(plan.scenes[-1].text.splitlines()[-1], '댓글 남겨주세요')
        self.assertIn('2초', seen['prompt'])
        self.assertNotIn('6~12자', seen['prompt'])
        self.assertIn('물 풍경', seen['prompt'])

    def test_voice_prompt_uses_connected_sentences_instead_of_fragments(self):
        prompt = codex.skill('stay')
        self.assertNotIn('조각 문장', prompt)
        self.assertIn('자연스럽게', prompt)
        self.assertIn('방문을 열면', prompt)

    def test_silent_plan_rejects_grouped_photos_and_more_than_two_lines(self):
        good = {'scenes': [{'photos': [i], 'text': '사진의 매력\n짧은 한 줄'} for i in range(8)]}
        plan = Storyboard.model_validate(good)
        plan.validate_silent(8)
        self.assertEqual(plan.scenes[-1].text.splitlines()[-1], '댓글 남겨주세요')
        plan.scenes[0].photos = [0, 1]
        with self.assertRaises(ValueError):
            plan.validate_silent(8)
        plan = Storyboard.model_validate(good)
        plan.scenes[0].text = '첫째\n둘째\n셋째'
        with self.assertRaises(ValueError):
            plan.validate_silent(8)
