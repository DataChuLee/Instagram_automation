"""Content-addressed media reuse, independent from scene and photo ordering."""
from .models import DRAMA_MODEL, VOICE_ID, VIDEO_MODEL, MOTION_PARAMETERS, stable_hash


def voice_key(job, scene):
    return 'voice:' + stable_hash({'text': scene.text, 'voice': VOICE_ID, 'model': DRAMA_MODEL})


def motion_key(job, motion):
    focus = next(((f.x, f.y) for f in job.storyboard.crop_focus if f.photo == motion.photo), (.5, .5))
    photo = job.photos[motion.photo]
    return 'motion:' + stable_hash({'photo': photo.get('sha256', photo.get('file')), 'crop': focus,
        'prompt': motion.prompt, 'model': VIDEO_MODEL, 'parameters': MOTION_PARAMETERS})


def cache_key(job, key):
    return f'{key}:{job.attempts.get(key, 0)}'


def capture(job):
    if not job.storyboard:
        return
    for index, scene in enumerate(job.storyboard.scenes):
        record = job.narration.get(str(index))
        if record:
            key = record.get('asset_key') or cache_key(job, voice_key(job, scene))
            job.assets[key] = dict(record, asset_key=key)
    for motion in job.storyboard.motion:
        record = job.generated.get(str(motion.photo))
        if record:
            key = record.get('asset_key') or cache_key(job, motion_key(job, motion))
            job.assets[key] = dict(record, asset_key=key)


def restore(job):
    job.narration, job.generated = {}, {}
    if not job.storyboard:
        return
    for index, scene in enumerate(job.storyboard.scenes):
        key = cache_key(job, voice_key(job, scene))
        if key in job.assets:
            job.narration[str(index)] = dict(job.assets[key])
    for motion in job.storyboard.motion:
        key = cache_key(job, motion_key(job, motion))
        if key in job.assets:
            job.generated[str(motion.photo)] = dict(job.assets[key])


def pending(job):
    records = list(job.generated.values()) + list(job.narration.values()) + list(job.assets.values())
    return any(r.get('state') in {'submitting', 'submitted'} and not r.get('file') for r in records)


def render_revision(job):
    return stable_hash({'photos': [p.get('sha256', p.get('file')) for p in job.photos],
        'storyboard': job.storyboard.model_dump() if job.storyboard else None,
        'caption': job.options.caption.model_dump(), 'speed': job.options.speed,
        'voices': job.narration, 'motions': job.generated})


def ready(job, folder):
    if not job.storyboard:
        return False
    voices = [job.narration.get(str(i), {}) for i in range(len(job.storyboard.scenes))]
    motions = [job.generated.get(str(m.photo), {}) for m in job.storyboard.motion]
    return all(r.get('file') and (folder / r['file']).is_file() for r in voices + motions)


def checkpoint(job):
    if job.storyboard:
        value = {'photos': job.photos, 'photo_order': job.photo_order,
                 'storyboard': job.storyboard.model_dump(), 'attempts': dict(job.attempts),
                 'mode': job.composition_mode}
        if not job.versions or stable_hash(job.versions[-1]) != stable_hash(value):
            job.versions.append(value)
            job.versions = job.versions[-30:]


def invalidate(job):
    job.quote = job.approval = job.result = None
    job.state, job.error = 'uploaded', None
    job.message = '구성이 변경되었습니다. 미리보기를 업데이트하거나 변경분 견적을 확인해 주세요.'
