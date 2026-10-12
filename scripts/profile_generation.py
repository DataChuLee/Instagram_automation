"""Read recorded timings or benchmark local rendering using saved media, without Fish calls."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.tools/studio-python'))

from studio import performance, store
from studio.paths import job_path
from studio.render import render


def ready(job):
    folder = job_path(job.id)
    return bool(job.storyboard and all(
        record.get('file') and (folder / record['file']).is_file()
        for record in [*(job.narration.get(str(i), {}) for i in range(len(job.storyboard.scenes))),
                       *(job.generated.get(str(m.photo), {}) for m in job.storyboard.motion)]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_id', nargs='?')
    parser.add_argument('--list-ready', action='store_true')
    parser.add_argument('--benchmark-render', action='store_true', help='Copy active inputs and measure a local render. No AI requests.')
    args = parser.parse_args()
    if args.list_ready:
        for job in store.list_jobs():
            if ready(job):
                print(job.id, job.state, 'photos=', len(job.photos), 'scenes=', len(job.storyboard.scenes),
                      'motions=', len(job.storyboard.motion))
        return
    if not args.job_id:
        parser.error('job_id is required unless --list-ready is used')
    job = store.read(args.job_id)
    folder = job_path(job.id)
    if args.benchmark_render:
        if not ready(job):
            parser.error('Saved narration/motion inputs are incomplete; this tool will not generate paid media.')
        destination = ROOT / 'output/performance' / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + job.id)
        destination.mkdir(parents=True)
        records = (job.photos
                   + [job.narration[str(i)] for i in range(len(job.storyboard.scenes))]
                   + [job.generated[str(m.photo)] for m in job.storyboard.motion])
        for filename in {record['file'] for record in records if record.get('file')}:
            relative = Path(filename)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe media path')
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(folder / relative, target)
        print('Benchmark folder:', destination, flush=True)
        with performance.run(destination, 'local_render_benchmark'):
            result = render(job, progress=lambda message: print(message, flush=True), folder=destination)
        folder = destination
        (folder / 'benchmark.json').write_text(json.dumps(
            {'source_job': job.id, 'photos': len(job.photos), 'scenes': len(job.storyboard.scenes),
             'motions': len(job.storyboard.motion), 'result': result}, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = performance.report(folder)
    if args.benchmark_render:
        (folder / 'performance-report.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    if not summary['runs']:
        print('No timing records yet. New pipeline operations will be recorded after restarting the server.')
        return
    for run in summary['runs']:
        print(f"\n{run['operation']} [{run['status']}] wall={run['wall_seconds']}s")
        for stage in run['stages']:
            print(f"  {stage['stage']:<28} {stage['seconds']:>10.3f}s  count={stage['count']}")
    print('\nStage times overlap: do not add nested/parallel durations. poll_wait includes provider wait and detection delay.')


if __name__ == '__main__':
    main()
