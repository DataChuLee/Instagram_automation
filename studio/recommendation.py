"""Evaluate every candidate in bounded image batches, then select globally."""
import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, Field
from PIL import Image, ImageOps

from . import codex, collector, domains
from .models import stable_hash
from .paths import job_path



def assessment_instructions(domain='stay'):
    return domains.load(domain).skill('SKILL_ASSESS.md').rstrip() + '\n'


def selection_instructions(domain, target_count):
    return domains.load(domain).skill('SKILL_SELECT.md').rstrip().replace('{target_count}', str(target_count))


class Assessment(BaseModel):
    id: str
    category: str
    subject: str  # What the photo shows by name: a room for stays, a product or part for shopping.
    facts: list[str]
    quality: int = Field(ge=1, le=5)
    reason: str


class Batch(BaseModel):
    photos: list[Assessment]


class SelectionReason(BaseModel):
    id: str
    reason: str


class Selection(BaseModel):
    ids: list[str]
    reasons: list[SelectionReason]


def candidate_path(job, candidate):
    if candidate.get('collection_id'):
        entry = collector.photo_entry(candidate['collection_id'], candidate['id'])
        return collector.folder(candidate['collection_id']) / entry['file']
    name = candidate.get('file', '')
    if Path(name).name != name or not name:
        raise ValueError('후보 사진 파일이 올바르지 않습니다.')
    return job_path(job.id) / name


def candidates(job, collection_id=None, photo_ids=()):
    """Only photos the user attached or picked from a collection become candidates."""
    by_id = {c['id']: dict(c) for c in job.candidates}
    for photo in job.photos:
        by_id.setdefault(photo['sha256'], dict(photo, id=photo['sha256'], file=photo.get('original_file', photo['file'])))
    if collection_id and photo_ids:
        gallery = collector.gallery(collection_id)
        if gallery['status'] == 'in_progress':
            raise ValueError('사진 수집이 끝난 뒤 추천해 주세요.')
        usable = {photo['id']: photo for photo in gallery['photos'] if photo['usable']}
        if any(i not in usable for i in photo_ids):
            raise ValueError('수집 목록에 없거나 사용할 수 없는 사진입니다.')
        for identifier in dict.fromkeys(photo_ids):
            by_id.setdefault(identifier, dict(usable[identifier], collection_id=collection_id,
                name=gallery['name'], source_url=gallery['source_url']))
    return list(by_id.values())


def runtime_identity():
    executable = Path(codex.executable())
    return {'exe': str(executable), 'size': executable.stat().st_size,
            'mtime': executable.stat().st_mtime_ns,
            'skill': stable_hash(codex.skill())}


async def choose(job, progress=lambda message: None):
    pool = job.candidates
    if len(pool) < job.target_count:
        raise ValueError(f'사용 가능한 후보는 {len(pool)}장입니다. 추천 장수를 줄여 주세요.')
    folder = job_path(job.id) / 'recommendation'
    folder.mkdir(parents=True, exist_ok=True)
    identity = runtime_identity()
    instructions = assessment_instructions(job.domain)
    all_assessments = []
    for offset in range(0, len(pool), 24):
        batch = pool[offset:offset+24]
        progress(f'후보 사진 {min(offset+24, len(pool))}/{len(pool)}장을 평가하고 있습니다.')
        signature = stable_hash({'ids': [p['id'] for p in batch], 'labels': [p.get('labels') for p in batch],
                                 'runtime': identity, 'prompt': instructions, 'domain': job.domain,
                                 'schema': stable_hash(Batch.model_json_schema())})
        cache = folder / f'cache-{signature}.json'
        if cache.is_file():
            result = Batch.model_validate_json(cache.read_text(encoding='utf-8'))
        else:
            photos = []
            for index, candidate in enumerate(batch):
                source = candidate_path(job, candidate)
                target = folder / f'batch-photo-{index:02}.jpg'
                def resize():
                    with Image.open(source) as original:
                        image = ImageOps.exif_transpose(original).convert('RGB')
                        image.thumbnail((1024, 1024))
                        image.save(target, quality=92)
                await asyncio.to_thread(resize)
                photos.append(target)
            prompt = instructions + json.dumps(batch, ensure_ascii=False)
            raw = await codex.run_structured(folder, prompt, photos, Batch.model_json_schema(), f'batch-{offset//24}')
            result = Batch.model_validate(raw)
            if [p.id for p in result.photos] != [p['id'] for p in batch]:
                raise ValueError('일부 후보 사진의 분석 결과가 누락되거나 순서가 변경되었습니다.')
            cache.write_text(result.model_dump_json(), encoding='utf-8')
        if [p.id for p in result.photos] != [p['id'] for p in batch]:
            raise ValueError('후보 사진의 분석 결과가 누락되거나 순서가 변경되었습니다.')
        all_assessments.extend(p.model_dump() for p in result.photos)
    prompt = selection_instructions(job.domain, job.target_count) + '\n' + json.dumps(all_assessments, ensure_ascii=False)
    result = Selection.model_validate(await codex.run_structured(folder, prompt, [], Selection.model_json_schema(), 'selection'))
    ids = result.ids
    if len(ids) != job.target_count or len(set(ids)) != len(ids) or not set(ids) <= {p['id'] for p in pool}:
        raise ValueError('AI 추천 사진 수 또는 사진 ID가 올바르지 않습니다.')
    if len(result.reasons) != len(ids) or {r.id for r in result.reasons} != set(ids) or any(not r.reason.strip() for r in result.reasons):
        raise ValueError('AI 추천 사진별 선정 이유가 누락되었습니다.')
    return result.model_dump()
