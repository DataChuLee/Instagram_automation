"""Generate sample stay copy with Codex and report rhythm/format checks; no Fish calls."""
import asyncio
import argparse
import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / '.tools/studio-python'), str(ROOT)]
sys.stdout.reconfigure(encoding='utf-8')
from studio import codex
from studio.models import Job


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--domain', choices=['stay', 'stay-silent'])
    args = parser.parse_args()
    photos = sorted((ROOT / 'Data/Test_Data').glob('*.jpg'))
    assert len(photos) >= 10
    output = ROOT / 'output/stay-copy-evaluation'
    output.mkdir(parents=True, exist_ok=True)
    report = []
    # Sequential calls keep the folder patch scoped to each analysis.
    for domain, count in [('stay', 10), ('stay-silent', 8)]:
        if args.domain and domain != args.domain:
            continue
        folder = output / domain
        folder.mkdir(exist_ok=True)
        job = Job(id='f' * 32, domain=domain,
                  photos=[{'file': str(path), 'sha256': path.stem, 'labels': []} for path in photos[:count]])
        with patch('studio.codex.job_path', return_value=folder):
            plan = await codex.analyze(job)
        (folder / 'storyboard.json').write_text(plan.model_dump_json(indent=2), encoding='utf-8')
        for option in plan.script_options:
            if domain == 'stay':
                sentences = re.split(r'(?<=[.?!])\s+', ' '.join(option.texts))
                body = sentences[1:-1] or sentences[1:]
                metric = round(sum(map(len, body)) / max(len(body), 1), 1)
                passed = metric >= 30
                details = {'mean_body_chars': metric, 'total_chars': sum(map(len, option.texts))}
            else:
                passed = all(len(text.splitlines()) == 2 for text in option.texts)
                passed = passed and option.texts[-1].splitlines()[-1] == '댓글 남겨주세요'
                passed = passed and not any('호수' in text or '바다' in text for text in option.texts)
                details = {'scenes': len(option.texts), 'seconds': count * 2}
            report.append({'domain': domain, 'title': option.title, 'passed': passed, **details})
            print(json.dumps(report[-1], ensure_ascii=False), flush=True)
            print('\n'.join(option.texts), flush=True)
    (output / f'{args.domain or "all"}-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    assert all(item['passed'] for item in report), 'Review short body sentences or invalid two-line copy.'


asyncio.run(main())
