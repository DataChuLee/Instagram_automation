import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from PIL import Image

from studio.models import Job


class RecommendationTests(unittest.IsolatedAsyncioTestCase):
    def test_output_schema_includes_properties_for_empty_metadata_object(self):
        from studio.codex import strict_schema
        from studio.models import Storyboard
        schema = strict_schema(Storyboard.model_json_schema())
        self.assertEqual(schema['properties']['selection_reasons']['properties'], {})

    async def test_candidates_after_sixty_are_evaluated_and_selected(self):
        from studio import recommendation
        job = Job(id='a' * 32, target_count=1,
                  candidates=[{'id': str(i), 'file': 'x.jpg', 'name': str(i)} for i in range(65)])
        batches = []
        async def execute(folder, prompt, photos, schema, name):
            if name.startswith('batch-'):
                ids = [c['id'] for c in job.candidates[len(batches)*24:(len(batches)+1)*24]]
                batches.append(ids)
                return {'photos': [{'id': i, 'category': '객실', 'room': '', 'facts': ['침대'],
                                   'quality': 4, 'reason': '선명한 객실'} for i in ids]}
            return {'ids': ['64'], 'reasons': [{'id': '64', 'reason': '대표 객실'}]}
        with tempfile.TemporaryDirectory() as directory, \
             patch('studio.recommendation.job_path', return_value=Path(directory)), \
             patch('studio.recommendation.candidate_path', return_value=Path(directory) / 'x.jpg'), \
             patch('studio.recommendation.codex.run_structured', side_effect=execute), \
             patch('studio.recommendation.runtime_identity', return_value='test'):
            Image.new('RGB', (300, 300)).save(Path(directory) / 'x.jpg')
            result = await recommendation.choose(job)
        self.assertEqual(result['ids'], ['64'])
        self.assertEqual([len(b) for b in batches], [24, 24, 17])

    async def test_model_cannot_return_unknown_or_repeated_candidates(self):
        from studio import recommendation
        job = Job(id='a' * 32, target_count=2,
                  candidates=[{'id': 'a', 'file': 'x.jpg'}, {'id': 'b', 'file': 'x.jpg'}])
        assessment = {'photos': [{'id': i, 'category': '객실', 'room': '', 'facts': [],
                                  'quality': 4, 'reason': '사진'} for i in ['a', 'b']]}
        for ids in [['a', 'a'], ['a', 'unknown']]:
            with tempfile.TemporaryDirectory() as directory, \
                 patch('studio.recommendation.job_path', return_value=Path(directory)), \
                 patch('studio.recommendation.candidate_path', return_value=Path(directory) / 'x.jpg'), \
                 patch('studio.recommendation.runtime_identity', return_value='test'), \
                 patch('studio.recommendation.codex.run_structured', new=AsyncMock(side_effect=[assessment, {'ids': ids, 'reasons': []}])):
                Image.new('RGB', (300, 300)).save(Path(directory) / 'x.jpg')
                with self.assertRaises(ValueError):
                    await recommendation.choose(job)
