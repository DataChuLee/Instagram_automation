"""Opt-in Codex-only evaluation; never contacts Fish or generates paid media."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / '.tools/studio-python')]
from studio import codex
from studio.models import Job
from studio.paths import job_path

CASES = [[3, 15, 11, 8], [0, 1, 2], [7, 8, 9], [13, 14, 15, 16],
         [10, 11, 12], [3, 4, 5, 6], [8], [15], [11, 3, 15], [3, 7, 15, 11, 8]]


async def main(count):
    if not await codex.login_status():
        raise RuntimeError('Codex ChatGPT login is required for live evaluation.')
    originals = sorted((ROOT / 'Data/Test_Data').glob('*.jpg'))
    results = []
    for number, indices in enumerate(CASES[:count], 1):
        job = Job(id=uuid.uuid4().hex, workflow_version=2)
        folder = job_path(job.id)
        folder.mkdir(parents=True, exist_ok=True)
        for index in indices:
            photo = originals[index]
            shutil.copy2(photo, folder / photo.name)
            job.photos.append({'file': photo.name, 'sha256': hashlib.sha256(photo.read_bytes()).hexdigest()})
        job.photo_order = list(range(len(indices)))
        print(f'Case {number}/{count}: analyzing {len(indices)} photos', flush=True)
        try:
            plan = await codex.analyze(job)
            if any(not s.text.rstrip().endswith(('.', '?', '!')) for s in plan.scenes):
                raise ValueError('Incomplete narration sentence')
            if any('호수' in s.text or '바다' in s.text or '강변' in s.text or '전용' in s.text for s in plan.scenes):
                raise ValueError('Unsupported geographic/private-facility claim in unlabeled photo set')
            results.append({'case': number, 'job': job.id, 'source_indices': indices, 'plan': plan.model_dump(), 'structural_pass': True})
            print(f'Case {number}: PASS; motion {len(plan.motion)}', flush=True)
        except Exception as error:
            results.append({'case': number, 'job': job.id, 'error': str(error), 'structural_pass': False})
            print(f'Case {number}: FAIL {error}', flush=True)
        output = ROOT / '.local/probes/shortform-evaluation.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'results': results, 'human_score': None,
            'note': 'Structural evaluation only. Independent human marketing score remains to be recorded.'}, ensure_ascii=False, indent=2), encoding='utf-8')
    if any(not r['structural_pass'] for r in results):
        raise RuntimeError('Some evaluation cases failed; inspect .local/probes/shortform-evaluation.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--cases', type=int, choices=range(1, 11), default=10)
    asyncio.run(main(parser.parse_args().cases))
