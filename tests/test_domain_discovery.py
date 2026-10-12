import asyncio
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from studio import app as module
from studio import codex, domains, store
from studio.models import Job, plan_clips

BUILTIN = Path(__file__).resolve().parents[1] / 'studio/skills'


def food(target, base=None, **changes):
    """A photo-based 'food' domain made by copying the stay folder into `target` and renaming it."""
    folder = target / 'food-shortform'
    shutil.copytree((base or target) / 'stay-shortform', folder)
    value = json.loads((folder / 'domain.json').read_text(encoding='utf-8'))
    value.update(id='food', label='맛집', order=15, min_media=4, version='3',
                 object_types=[{'name': 'Restaurant', 'label': '식당', 'links': [{'name': 'menus', 'target': 'Menu'}]},
                               {'name': 'Menu', 'label': '메뉴', 'properties': [{'name': 'price', 'label': '가격', 'source': 'user'}]}],
                 links_from_system=[{'type': 'Photo', 'name': 'shows', 'target': 'Restaurant | Menu'}],
                 features={'link_collection': False, 'enhance': False, 'ai_composition': False},
                 ui={'noun': '메뉴 사진', 'upload_title': '맛집 사진을 넣어 주세요'})
    value.update(changes)
    (folder / 'domain.json').write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    (folder / 'SKILL_TEXT.md').write_text('# 맛집 쇼츠 대본\n맛집 전용 규칙.', encoding='utf-8')
    return folder


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.skills, self.data = root / 'skills', root / 'data'
        shutil.copytree(BUILTIN, self.skills)
        (self.data / 'domains').mkdir(parents=True)
        self.patches = [patch('studio.domains.SKILLS', self.skills), patch('studio.paths.DATA', self.data)]
        for item in self.patches:
            item.start()
        domains.reload()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        domains.reload()
        self.temp.cleanup()

    def test_a_new_folder_becomes_a_domain_in_order(self):
        food(self.skills)
        domains.reload()
        self.assertEqual(domains.ids(), ['stay', 'stay-silent', 'food', 'shopping'])
        dish = domains.load('food')
        self.assertEqual((dish.media, dish.min_media, dish.version), ('photo', 4, '3'))
        self.assertEqual(dish.words()['noun'], '메뉴 사진')  # Domain ui overrides the media default.
        self.assertEqual(dish.words()['unit'], '장')
        block = domains.schema_block(dish)
        for name in ('Restaurant', 'Menu', 'Photo (사진)', 'MotionClip', 'shows → Restaurant | Menu'):
            self.assertIn(name, block)

    def test_new_photo_domain_uses_its_skill_and_min_media(self):
        food(self.skills)
        domains.reload()
        def job(count):
            return Job(id='a' * 32, domain='food', workflow_version=2, photo_order=list(range(count)),
                       photos=[{'file': f'{i}.jpg', 'labels': []} for i in range(count)])
        seen = {}
        async def fake(folder, prompt, photos, schema, name):
            seen['prompt'] = prompt
            order = list(range(4))
            return {'scenes': [{'id': '', 'photos': order, 'text': '가.'}],
                    'script_options': [{'title': 't', 'texts': ['가.']}] * 3, 'script_choice': 0,
                    'motion': [{'photo': c['photos'][0], 'prompt': 'p', 'photos': c['photos'], 'seconds': 4} for c in plan_clips(order)],
                    'crop_focus': [{'photo': i, 'x': .5, 'y': .5} for i in order],
                    'motion_recommendations': [{'photo': i, 'recommended': True, 'reason': 'r', 'prompt': '', 'explanation': ''} for i in order],
                    'selection_reasons': {}}
        with patch('studio.codex.run_structured', fake), patch('studio.codex.job_path', return_value=Path('.')):
            plan = asyncio.run(codex.analyze(job(4)))
            with self.assertRaisesRegex(ValueError, '최소 4장'):
                asyncio.run(codex.analyze(job(3)))
        self.assertIn('맛집 전용 규칙', seen['prompt'])
        self.assertTrue(seen['prompt'].startswith('<ontology-schema domain="food" version="3">'))
        self.assertEqual(plan.provenance['domain'], 'food')
        self.assertEqual(plan.provenance['version'], '3')
        self.assertFalse(plan.provenance['overridden'])

    def test_broken_folders_are_reported_and_left_out(self):
        food(self.skills)
        (self.skills / 'food-shortform/SKILL_MOTION.md').unlink()
        problems = domains.reload()
        self.assertNotIn('food', domains.ids())
        self.assertIn('SKILL_MOTION.md', problems['food'])
        with self.assertRaisesRegex(ValueError, 'SKILL_MOTION.md'):
            domains.load('food')
        shutil.rmtree(self.skills / 'food-shortform')
        food(self.skills, object_types=[{'name': 'Menu', 'label': '메뉴', 'links': [{'name': 'shop', 'target': 'Restarant'}]},
                                        {'name': 'Scene', 'label': '장면'}])
        problems = domains.reload()
        self.assertIn('Restarant', problems['food'])
        self.assertIn('Scene은 엔진이 정의하는 타입', problems['food'])
        self.assertEqual(domains.ids(), ['stay', 'stay-silent', 'shopping'])  # The other kinds still load.

    def test_data_folder_adds_and_overrides_file_by_file(self):
        food(self.data / 'domains', self.skills)  # A kind added without touching the app's own folders.
        override = self.data / 'domains/shopping-shortform'
        override.mkdir()
        (override / 'SKILL_TEXT.md').write_text('# 내 쇼핑 대본 규칙', encoding='utf-8')
        domains.reload()
        self.assertIn('food', domains.ids())
        shopping = domains.load('shopping')
        self.assertEqual(shopping.skill('SKILL_TEXT.md'), '# 내 쇼핑 대본 규칙')
        self.assertIn('상품 영상 편집', shopping.skill('SKILL_EDIT.md'))  # Still the built-in file.
        self.assertEqual(shopping.media, 'video')
        record = domains.record(shopping, ['x'], ['SKILL_TEXT.md', 'SKILL_EDIT.md'])
        self.assertTrue(record['overridden'])
        self.assertFalse(domains.record(shopping, ['x'], ['SKILL_EDIT.md'])['overridden'])

    def test_few_photo_domains_keep_every_clip_within_the_model_limit(self):
        from studio.models import MAX_CLIP_SECONDS
        for count in range(2, 20):
            clips = plan_clips(list(range(count)))
            self.assertTrue(all(4 <= c['seconds'] <= MAX_CLIP_SECONDS for c in clips), (count, clips))
            self.assertEqual([p for c in clips for p in c['photos']], list(range(count)))
        food(self.skills, min_media=1)
        self.assertIn('min_media가 2 이상', domains.reload()['food'])

    def test_broken_override_falls_back_to_the_builtin_domain(self):
        override = self.data / 'domains/shopping-shortform'
        override.mkdir()
        (override / 'domain.json').write_text(json.dumps({'id': 'shopping', 'media': 'photo'}), encoding='utf-8')
        problems = domains.reload()
        self.assertEqual(domains.load('shopping').media, 'video')
        self.assertIn('기본값을 사용해요', problems['shopping'])


class DiscoveryApiTests(DiscoveryTests):
    def setUp(self):
        super().setUp()
        folder = self.data
        self.api_patches = [patch('studio.app.job_path', lambda i: folder / 'jobs' / i),
                            patch('studio.store.job_path', lambda i: folder / 'jobs' / i),
                            patch('studio.store.DATA', folder), patch('studio.app.codex.login_status', return_value=False)]
        for item in self.api_patches:
            item.start()
        self.client = TestClient(module.app)
        self.headers = {'X-Studio-Token': module.TOKEN}

    def tearDown(self):
        self.client.close()
        for item in self.api_patches:
            item.stop()
        super().tearDown()

    def upload(self, domain):
        data = io.BytesIO()
        Image.new('RGB', (800, 600), 'orange').save(data, format='JPEG')
        return self.client.post('/api/jobs', headers=self.headers, data={'domain': domain},
                                files=[('files', ('p.jpg', data.getvalue(), 'image/jpeg'))])

    def test_api_lists_new_domain_with_words_and_creates_its_jobs(self):
        food(self.skills)
        domains.reload()
        listed = self.client.get('/api/domains', headers=self.headers).json()
        self.assertEqual([d['id'] for d in listed], ['stay', 'stay-silent', 'food', 'shopping'])
        dish = next(d for d in listed if d['id'] == 'food')
        self.assertEqual((dish['ui']['noun'], dish['ui']['heading'], dish['facts'][0]['key']), ('메뉴 사진', '사진 & 이야기', 'price'))
        self.assertEqual(next(d for d in listed if d['id'] == 'shopping')['ui']['heading'], '영상 & 이야기')
        created = self.upload('food')
        self.assertEqual(created.json()['domain'], 'food')

    def test_job_of_a_removed_domain_reports_clearly(self):
        food(self.skills)
        domains.reload()
        job_id = self.upload('food').json()['id']
        shutil.rmtree(self.skills / 'food-shortform')
        domains.reload()
        response = self.client.get(f'/api/jobs/{job_id}', headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn('이 영상 종류(food)가 없어', response.text)
        listed = self.client.get('/api/jobs', headers=self.headers).json()
        self.assertEqual([j['domain'] for j in listed], ['food'])  # The list still shows it.


if __name__ == '__main__':
    unittest.main()
