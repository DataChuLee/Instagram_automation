from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from .models import Job, stable_hash
from .paths import DATA, initialize, job_path

LOCK = threading.RLock()


def save(job: Job):
    with LOCK:
        folder = job_path(job.id)
        folder.mkdir(parents=True, exist_ok=True)
        temporary = folder / 'job.tmp'
        temporary.write_text(job.model_dump_json(indent=2), encoding='utf-8')
        temporary.replace(folder / 'job.json')


def read(job_id: str) -> Job:
    with LOCK:
        return Job.model_validate_json((job_path(job_id) / 'job.json').read_text(encoding='utf-8'))


def create(photos, options=None):
    initialize()
    job = Job(id=uuid.uuid4().hex, photos=photos, **({'options': options} if options else {}))
    save(job)
    return job


def list_jobs():
    initialize()
    result = []
    for path in sorted((DATA / 'jobs').glob('*/job.json'), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            result.append(Job.model_validate_json(path.read_text(encoding='utf-8')))
        except (ValueError, OSError):
            continue
    return result


def recover():
    for job in list_jobs():
        if job.state in {'analyzing', 'recommending', 'quoting', 'generating', 'rendering', 'previewing'}:
            job.state = 'interrupted'
            job.message = '중단된 작업입니다. 저장된 생성 결과로 이어서 진행할 수 있습니다.'
            save(job)


def approve(job: Job, quote_id: str, credits: int):
    quote = job.quote
    if not quote or quote_id != quote['id'] or credits != quote['total']:
        raise ValueError('견적이 바뀌었습니다. 최신 크레딧 금액을 확인해 주세요.')
    if quote['plan_hash'] != plan_hash(job):
        raise ValueError('대본이나 움직임 설정이 변경되었습니다. 견적을 다시 받아 주세요.')
    if job.state != 'awaiting_approval':
        raise ValueError('승인할 수 있는 작업 상태가 아닙니다.')
    job.approval = {'quote_id': quote_id, 'credits': credits,
                    'time': datetime.now(timezone.utc).isoformat()}
    save(job)


def plan_hash(job):
    value = {'photos': [p['sha256'] for p in job.photos],
             'storyboard': job.storyboard.model_dump() if job.storyboard else None,
             'attempts': job.attempts}
    if not job.default_video():
        # Only non-default choices join the hash so quotes approved before model selection stay valid.
        value['video'] = job.video_choice()
    return stable_hash(value)


def generation_allowed(job):
    if not job.quote or not job.approval or job.approval['quote_id'] != job.quote['id']:
        raise ValueError('생성 전에 크레딧 사용 승인이 필요합니다.')
    if job.quote['plan_hash'] != plan_hash(job):
        raise ValueError('승인 후 생성 설정이 바뀌었습니다.')
