"""Per-job timings, independent of job snapshots and paid request state."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps

CURRENT = ContextVar('performance_run', default=None)
PARENT = ContextVar('performance_parent', default=None)
LOCK = threading.Lock()
LOGGER = logging.getLogger(__name__)


@contextmanager
def span(stage, **details):
    session = CURRENT.get()
    if session is None:
        yield
        return
    span_id = uuid.uuid4().hex
    parent_id = PARENT.get()
    token = PARENT.set(span_id)
    started = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat()
    status = 'ok'
    try:
        yield
    except BaseException as error:
        status = 'cancelled' if isinstance(error, asyncio.CancelledError) else 'error'
        raise
    finally:
        seconds = time.perf_counter() - started
        PARENT.reset(token)
        row = dict(run_id=session['id'], span_id=span_id, parent_id=parent_id,
                   stage=stage, started_at=timestamp,
                   offset_seconds=round(started - session['start'], 6),
                   seconds=round(seconds, 6), status=status, details=details)
        try:
            with LOCK:
                session['folder'].mkdir(parents=True, exist_ok=True)
                with (session['folder'] / 'performance.jsonl').open('a', encoding='utf-8') as output:
                    output.write(json.dumps(row, ensure_ascii=False) + '\n')
        except OSError:
            LOGGER.warning('Could not save performance timing for stage %s', stage)


@contextmanager
def run(folder, stage):
    """Nested operations retain one run ID; tasks and to_thread inherit context."""
    if CURRENT.get() is not None:
        with span(stage):
            yield
        return
    token = CURRENT.set(dict(id=uuid.uuid4().hex, folder=folder, start=time.perf_counter()))
    parent = PARENT.set(None)
    try:
        with span(stage):
            yield
    finally:
        PARENT.reset(parent)
        CURRENT.reset(token)


def operation(function):
    @wraps(function)
    async def measured(self, job_id, *args, **kwargs):
        # Resolve through the operation's module to use the same job storage location.
        folder = function.__globals__['job_path'](job_id)
        with run(folder, function.__name__):
            return await function(self, job_id, *args, **kwargs)
    return measured


async def wait(stage, awaitable, **details):
    with span(stage, **details):
        return await awaitable


def measured(stage):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            with span(stage):
                return function(*args, **kwargs)
        return wrapped
    return decorate


def report(folder):
    """Report observed intervals; nested/parallel stage totals must not be added."""
    path = folder / 'performance.jsonl'
    if not path.exists():
        return {'runs': [], 'note': '시간 기록이 없습니다. 계측 적용 후 실행한 작업부터 기록됩니다.'}
    sessions = {}
    with path.open(encoding='utf-8') as source:
        for line in source:
            try:
                row = json.loads(line)
                sessions.setdefault(row['run_id'], []).append(row)
            except (ValueError, KeyError):
                continue  # A truncated last line must not hide previous measurements.
    runs = []
    for run_id, rows in sessions.items():
        root = next((row for row in rows if row['parent_id'] is None), None)
        stages = {}
        for row in rows:
            entry = stages.setdefault(row['stage'], {'stage': row['stage'], 'count': 0, 'seconds': 0})
            entry['count'] += 1
            entry['seconds'] += row['seconds']
        for entry in stages.values():
            entry['seconds'] = round(entry['seconds'], 3)
        runs.append({'run_id': run_id, 'operation': root['stage'] if root else 'in_progress',
                     'status': root['status'] if root else 'in_progress_or_interrupted',
                     'started_at': min(row['started_at'] for row in rows),
                     'wall_seconds': round(root['seconds'], 3) if root else None,
                     'stages': sorted(stages.values(), key=lambda item: item['seconds'], reverse=True),
                     'intervals': sorted(rows, key=lambda item: item['offset_seconds'])})
    return {'runs': sorted(runs, key=lambda item: item['started_at']),
            'note': '구간은 중첩·병렬 실행됩니다. 단계 합계를 전체 시간으로 더하지 마세요. '
                    'poll_wait는 확인 간격과 외부 서버의 생성 대기를 포함하며 정확한 서버 생성 시간이 아닙니다. '
                    'voice.generate는 요청 검증·제출·결과 대기·다운로드를 포함합니다.'}
