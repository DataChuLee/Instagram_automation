"""Codex image_generation remake of stay photos: sharper, people removed, 9:16 portrait, brighter."""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

from PIL import UnidentifiedImageError

from . import codex
from .media import crop_photo

SKILL = codex.SKILLS / 'SKILL_ENHANCE.md'
TIMEOUT = 300  # One photo took 40-90 s in the 2026-10-10 test.
CONCURRENCY = 4


class EnhanceError(RuntimeError):
    pass


class UsageLimit(EnhanceError):
    pass


def prompt():
    return SKILL.read_text(encoding='utf-8')


async def enhance_photo(source: Path, target: Path):
    """Writes the remade photo to `target` as a 1080x1920 JPEG; leaves `target` untouched on failure."""
    env = codex.environment()
    args = [codex.executable(), 'exec', '--sandbox', 'read-only', '--skip-git-repo-check',
            '--ephemeral', '--ignore-user-config', '--ignore-rules', '-C', str(target.parent),
            '-i', str(source), '-']
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    try:
        _, stderr = await asyncio.wait_for(process.communicate(prompt().encode('utf-8')), TIMEOUT)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise EnhanceError('변환 시간이 초과되었습니다.')
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise
    log = stderr.decode('utf-8', 'replace')
    if 'usage limit' in log.lower():
        raise UsageLimit('Codex 구독 사용 한도에 도달했습니다. 한도가 초기화된 뒤 다시 눌러 주세요.')
    # Codex exec runs read-only, so the image lands in CODEX_HOME rather than the job folder.
    match = re.search(r'session id:\s*([0-9A-Za-z-]+)\s', log)
    folder = Path(env['CODEX_HOME']) / 'generated_images' / match.group(1) if match else None
    images = sorted(folder.glob('*.png'), key=lambda p: p.stat().st_mtime) if folder and folder.is_dir() else []
    if not images:
        raise EnhanceError('생성된 이미지가 없습니다.')
    try:
        image = await asyncio.to_thread(crop_photo, images[-1])
        temporary = target.with_name(f'.{target.name}.tmp')
        image.save(temporary, format='JPEG', quality=96)
        temporary.replace(target)
    except (OSError, UnidentifiedImageError) as error:
        raise EnhanceError('생성된 이미지를 읽지 못했습니다.') from error
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def mirror(job, photo):
    """v2 compositions rebuild photos from candidates, so they carry the enhancement too."""
    for candidate in job.candidates:
        if candidate.get('id') == photo['sha256']:
            candidate['enhanced'] = dict(photo['enhanced'])


def record(job, index, file=None, error=None):
    photo = job.photos[index]
    photo.pop('enhancing', None)
    photo.setdefault('original_file', photo['file'])
    previous = photo.get('enhanced') or {}
    if file:
        photo['enhanced'] = {'file': file, 'state': 'done', 'active': True}
        photo['file'] = file
    elif previous.get('state') == 'done':
        photo['enhanced'] = dict(previous, error=error)
    else:
        photo['enhanced'] = {'state': 'failed', 'error': error}
    mirror(job, photo)


def settle(job):
    """Clears in-progress marks left by a stopped or interrupted run."""
    for photo in job.photos:
        photo.pop('enhancing', None)


def use(job, index, active: bool):
    photo = job.photos[index]
    enhanced = photo.get('enhanced') or {}
    if enhanced.get('state') != 'done':
        raise ValueError('고화질 변환이 끝난 사진만 전환할 수 있습니다.')
    enhanced['active'] = active
    photo['file'] = enhanced['file'] if active else photo['original_file']
    mirror(job, photo)


def files(job):
    names = set()
    for photo in job.photos:
        names |= {photo['file'], photo.get('original_file'), (photo.get('enhanced') or {}).get('file')}
    return names - {None}
