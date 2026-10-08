"""Collect photos published on Yeogi domestic accommodation detail pages."""

import argparse
import hashlib
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from PIL import Image


IMAGE_HOSTS = {'image.withstatic.com', 'image.goodchoice.kr'}
MAX_IMAGE_BYTES = 50 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def normalize_url(url):
    parsed = urlsplit(url.strip())
    match = re.fullmatch(r'/domestic-accommodations/([1-9][0-9]*)/?', parsed.path)
    if (parsed.scheme != 'https' or parsed.hostname not in {'www.yeogi.com', 'yeogi.com'}
            or parsed.username or parsed.password or parsed.port not in {None, 443} or not match):
        raise ValueError('국내 숙소 상세 HTTPS 링크가 필요합니다.')
    return match[1], urlunsplit(('https', 'www.yeogi.com', parsed.path.rstrip('/'), parsed.query, ''))


def image_url(value):
    if not isinstance(value, str):
        raise ValueError('사진 주소가 없거나 형식이 변경됐습니다.')
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in IMAGE_HOSTS
            or parsed.username or parsed.password or parsed.port not in {None, 80, 443}
            or parsed.path in {'', '/'}):
        raise ValueError('지원하지 않는 사진 주소입니다: ' + value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ''))


def extract_photos(data):
    try:
        info = data['props']['pageProps']['accommodationInfo']
        meta = info['meta']
        name = meta['name']
        rooms = info['rooms']
        if not isinstance(name, str) or not name.strip() or not isinstance(rooms, list):
            raise ValueError('숙소 이름 또는 객실 목록이 유효하지 않습니다.')
        by_url = {}
        def add(entries, category, room_name=None):
            if not isinstance(entries, list):
                raise ValueError('사진 목록 형식이 변경됐습니다.')
            for entry in entries:
                url = image_url(entry['image'])
                label = {'category': category, 'title': entry.get('title'), 'room_name': room_name}
                photo = by_url.setdefault(url, {'url': url, 'labels': []})
                if label not in photo['labels']:
                    photo['labels'].append(label)
        add(meta.get('newImages') or meta.get('images') or [], 'property')
        for room in rooms:
            add(room.get('newImages') or room.get('images') or [], 'room', room.get('name'))
        if not by_url:
            raise ValueError('숙소·객실 사진 목록이 비어 있습니다.')
        return name, list(by_url.values())
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('숙소 페이지 데이터 구조가 변경됐거나 누락됐습니다.') from exc


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    replace_file(temporary, path)


def replace_file(temporary, target):
    # Windows readers/scanners can momentarily deny atomic replacement.
    # Persistent permissions errors remain errors after the bounded retry.
    for attempt in range(6):
        try:
            temporary.replace(target)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.1 * 2 ** attempt)


def describe_image(content):
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError('이미지 파일이 50 MiB 제한을 초과합니다.')
    with Image.open(io.BytesIO(content)) as img:
        width, height = img.size
        fmt = img.format
        if fmt not in {'JPEG', 'PNG', 'WEBP', 'GIF', 'TIFF', 'BMP', 'AVIF'}:
            raise ValueError('지원하지 않는 이미지 형식입니다: ' + str(fmt))
        img.verify()
    # verify checks structure; decoding also catches truncated pixel data.
    with Image.open(io.BytesIO(content)) as img:
        img.load()
    return {'sha256': hashlib.sha256(content).hexdigest(), 'width': width,
            'height': height, 'format': fmt, 'bytes': len(content)}


def cached_image(root, entry):
    try:
        digest = entry['sha256']
        if not re.fullmatch(r'[a-f0-9]{64}', digest):
            return None
        relative = Path(entry['file'])
        if relative.parent != Path('images') or relative.stem != digest:
            return None
        path = root / relative
        if path.stat().st_size > MAX_IMAGE_BYTES:
            return None
        details = describe_image(path.read_bytes())
        return entry if details['sha256'] == digest else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_collection(root, source_url, name, photos, fetch):
    root = Path(root)
    (root / 'images').mkdir(parents=True, exist_ok=True)
    manifest_path = root / 'manifest.json'
    old = read_json(manifest_path)
    previous = {entry['url']: entry for entry in old.get('images', [])
                if isinstance(entry, dict) and 'url' in entry}
    manifest = {'schema_version': 1, 'accommodation_id': normalize_url(source_url)[0],
                'name': name, 'source_url': source_url, 'collected_at': now(),
                'status': 'in_progress', 'images': [], 'failures': []}
    write_json(manifest_path, manifest)
    for photo in photos:
        try:
            entry = cached_image(root, previous.get(photo['url'], {}))
            if entry:
                entry = dict(entry, labels=photo['labels'], reused=True)
            else:
                content = fetch(photo['url'])
                details = describe_image(content)
                extension = {'JPEG': 'jpg', 'TIFF': 'tif'}.get(details['format'], details['format'].lower())
                relative = 'images/' + details['sha256'] + '.' + extension
                target = root / relative
                # Identical photos at different URLs resolve to one file.
                if not target.exists() or target.read_bytes() != content:
                    temporary = target.with_suffix(target.suffix + '.part')
                    temporary.write_bytes(content)
                    replace_file(temporary, target)
                entry = dict(details, url=photo['url'], labels=photo['labels'],
                             file=relative, downloaded_at=now(), reused=False)
            manifest['images'].append(entry)
        except Exception as exc:
            manifest['failures'].append({'url': photo['url'], 'labels': photo['labels'], 'error': str(exc)})
        write_json(manifest_path, manifest)
    manifest['status'] = ('complete' if not manifest['failures'] else
                          'partial' if manifest['images'] else 'failed')
    manifest['completed_at'] = now()
    manifest['unique_files'] = len({entry['file'] for entry in manifest['images']})
    write_json(manifest_path, manifest)
    return manifest


