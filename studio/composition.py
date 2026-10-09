"""Candidate selection remains independent from the active, ordered timeline."""
import hashlib
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from . import assets, recommendation
from .paths import job_path


def select(job, ids):
    if not isinstance(ids, list) or not 1 <= len(ids) <= 60 or any(not isinstance(i, str) for i in ids):
        raise ValueError('구성에 사용할 사진은 1~60장입니다.')
    pool = {p['id']: p for p in job.candidates}
    if len(set(ids)) != len(ids) or not set(ids) <= pool.keys():
        raise ValueError('중복되거나 존재하지 않는 후보 사진입니다.')
    folder = job_path(job.id)
    folder.mkdir(parents=True, exist_ok=True)
    photos, total = [], 0
    with tempfile.TemporaryDirectory(prefix='.composition-', dir=folder) as temporary:
        staging = Path(temporary)
        for identifier in ids:
            candidate = pool[identifier]
            source = recommendation.candidate_path(job, candidate)
            total += source.stat().st_size
            if source.stat().st_size > 20 * 1024**2 or total > 300 * 1024**2:
                raise ValueError('사진당 20MB, 선택 사진 전체 300MB 이내로 구성해 주세요.')
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            name = f'active-{digest}.jpg'
            with Image.open(source) as original:
                image = ImageOps.exif_transpose(original).convert('RGB')
                if min(image.size) < 300:
                    raise ValueError('사진의 짧은 변은 300px 이상이어야 합니다.')
                image.save(staging / name, quality=97)
            photos.append(dict(candidate, file=name, sha256=candidate.get('sha256', identifier),
                               width=image.width, height=image.height))
        assets.capture(job)
        assets.checkpoint(job)
        for photo in photos:
            (staging / photo['file']).replace(folder / photo['file'])
    job.photos = photos
    job.photo_order = list(range(len(photos)))
    job.storyboard = None
    assets.restore(job)
    assets.invalidate(job)
    job.workflow_version = 2


def reorder(job, order):
    if not isinstance(order, list) or any(type(i) is not int for i in order) or sorted(order) != list(range(len(job.photos))):
        raise ValueError('사진 순서가 올바르지 않습니다.')
    assets.capture(job)
    assets.checkpoint(job)
    job.photo_order = order
    if job.storyboard:
        # Keep scene narration and identity; reorder complete scenes or photos within a scene.
        positions = {p: i for i, p in enumerate(order)}
        for scene in job.storyboard.scenes:
            scene.photos.sort(key=positions.get)
        job.storyboard.scenes.sort(key=lambda s: min(positions[p] for p in s.photos))
        flattened = [p for s in job.storyboard.scenes for p in s.photos]
        if flattened != order:
            cursor = 0
            for scene in job.storyboard.scenes:
                count = len(scene.photos)
                scene.photos = order[cursor:cursor + count]
                cursor += count
        assets.restore(job)
    assets.invalidate(job)
    job.message = '사진 순서를 변경했습니다. 기존 음성·자막을 유지합니다. 각 장면의 사진과 문구가 맞는지 미리보기에서 확인하세요.'
