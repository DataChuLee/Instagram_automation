"""Fish image-to-video models that can deliver 720p-1080p vertical motion clips, with free estimates."""
import re
import time

QUALITIES = {'720p': '720p', '768p': '768p', '1080p': '1080p'}
MIN_SECONDS = 4
_catalog = {'time': 0, 'models': None}


def options(model_id, detail):
    """Selectable parameter sets for one model, or [] when it cannot make an explicit 9:16 720p-1080p clip."""
    props = detail.get('capabilities', {}).get('i2v', {}).get('parameter_schema', {}).get('properties', {})
    resolutions = [r for r in props.get('resolution', {}).get('enum', []) if r.lower() in QUALITIES]
    if not resolutions:
        return []
    # Only models that can be told to output 9:16 are offered; others may return another ratio.
    if '9:16' not in props.get('aspect_ratio', {}).get('enum', []):
        return []
    base = {'aspect_ratio': '9:16'}
    if 'duration' in props:
        lengths = sorted((int(m.group(1)), d) for d in props['duration'].get('enum', [])
                         if (m := re.fullmatch(r'(\d+)s', d)) and int(m.group(1)) >= MIN_SECONDS)
        if not lengths:
            return []
        base['duration'] = lengths[0][1]
    return [{'model': model_id, 'parameters': dict(base, resolution=r), 'quality': QUALITIES[r.lower()],
             'native': r.lower() == '1080p'} for r in resolutions]


async def catalog(fish):
    if _catalog['models'] is not None and time.monotonic() - _catalog['time'] < 1800:
        return _catalog['models']
    listing = await fish.call('list_media_models', {'media_type': 'video', 'capability': 'i2v'})
    entries = [m for m in listing.get('models', []) if 'i2v' in m.get('capabilities', [])]
    details = await fish.calls([('get_media_model', {'model_id': m['model_id']}) for m in entries])
    models = []
    for entry, detail in zip(entries, details):
        if isinstance(detail, Exception):
            continue
        for option in options(entry['model_id'], detail):
            models.append(dict(option, description=detail.get('description', ''), traits=entry.get('traits', [])))
    _catalog.update(time=time.monotonic(), models=models)
    return models


def find(models, model_id, parameters):
    return next((m for m in models if m['model'] == model_id and m['parameters'] == parameters), None)


async def estimates(fish, workspace, object_key, prompt):
    models = await catalog(fish)
    requests = [('estimate_video_generation', {'workspace_id': workspace, 'model_id': m['model'], 'operation': 'i2v',
                 'parameters': m['parameters'], 'prompt': prompt, 'input_object_key': object_key}) for m in models]
    results = await fish.calls(requests)
    rows = []
    for model, value in zip(models, results):
        if isinstance(value, Exception):
            rows.append(dict(model, credits=None, can_generate=False, error=str(value)))
        else:
            rows.append(dict(model, credits=value.get('credits'), can_generate=bool(value.get('can_generate')),
                             balance=value.get('balance'), error=None))
    return rows
