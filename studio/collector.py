"""Persistent, local collection jobs using the packaged browser and shared Yeogi parser."""
from __future__ import annotations

import asyncio
import io
import json
import re
import uuid

from PIL import Image, ImageOps
from playwright.async_api import async_playwright, TimeoutError as BrowserTimeout

from . import paths
from .yeogi import (cached_image, describe_image, extract_photos, image_url,
                    normalize_url, now, read_json, write_json)


def folder(collection_id):
    if not isinstance(collection_id, str) or not re.fullmatch(r'[a-f0-9]{32}', collection_id):
        raise ValueError('올바르지 않은 수집 번호입니다.')
    return paths.DATA / 'collections' / collection_id


def read(collection_id):
    manifest = read_json(folder(collection_id) / 'manifest.json')
    if not manifest:
        raise FileNotFoundError('수집 작업이 없습니다.')
    return manifest


def save(collection_id, manifest):
    write_json(folder(collection_id) / 'manifest.json', manifest)


def recover():
    for path in (paths.DATA / 'collections').glob('*/manifest.json'):
        manifest = read_json(path)
        if manifest.get('status') == 'in_progress':
            manifest.update(status='interrupted', message='수집이 중단되었습니다. 같은 링크로 다시 수집할 수 있습니다.')
            write_json(path, manifest)


def start(url):
    accommodation_id, url = normalize_url(url)
    collection_id = uuid.uuid4().hex
    old = {}
    for path in (paths.DATA / 'collections').glob('*/manifest.json'):
        candidate = read_json(path)
        if candidate.get('source_url') == url:
            collection_id, old = path.parent.name, candidate
            if old.get('status') == 'in_progress':
                return collection_id, False
            break
    manifest = dict(old, accommodation_id=accommodation_id, source_url=url,
                    status='in_progress', started_at=now(), processed=0, total=0,
                    message='수집용 브라우저에서 숙소 사진 목록을 확인하고 있습니다.', error=None)
    manifest.setdefault('images', [])
    manifest.setdefault('failures', [])
    save(collection_id, manifest)
    return collection_id, True


def unique_photos(manifest):
    photos = {}
    for entry in manifest.get('images', []):
        digest = entry.get('sha256', '')
        if not re.fullmatch(r'[a-f0-9]{64}', digest):
            continue
        if digest not in photos:
            photos[digest] = dict(entry, id=digest, labels=list(entry.get('labels', [])))
        else:
            for label in entry.get('labels', []):
                if label not in photos[digest]['labels']:
                    photos[digest]['labels'].append(label)
    return list(photos.values())


def gallery(collection_id):
    manifest = read(collection_id)
    photos = []
    for entry in unique_photos(manifest):
        usable = entry.get('bytes', 0) <= 20 * 1024 * 1024 and min(entry.get('width', 0), entry.get('height', 0)) >= 300
        photos.append({key: entry.get(key) for key in ('id', 'labels', 'width', 'height', 'bytes')} | {
            'usable': usable, 'reason': '' if usable else '사진당 20MB 이하, 짧은 변 300px 이상이어야 합니다.'})
    return {'id': collection_id, 'name': manifest.get('name', ''), 'source_url': manifest['source_url'],
            'status': manifest['status'], 'message': manifest.get('message', ''),
            'processed': manifest.get('processed', 0), 'total': manifest.get('total', 0),
            'photos': photos, 'failures': manifest.get('failures', []), 'error': manifest.get('error')}


def photo_entry(collection_id, photo_id):
    manifest = read(collection_id)
    entry = next((p for p in unique_photos(manifest) if p['id'] == photo_id), None)
    if not entry or not cached_image(folder(collection_id), entry):
        raise FileNotFoundError('수집한 사진을 찾지 못했습니다. 다시 수집해 주세요.')
    return entry


def thumbnail(collection_id, photo_id):
    entry = photo_entry(collection_id, photo_id)
    with Image.open(folder(collection_id) / entry['file']) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
        image.thumbnail((320, 320))
    output = io.BytesIO()
    image.save(output, format='JPEG', quality=85)
    return output.getvalue()


async def load_page(page, url):
    for attempt in range(3):
        try:
            response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            if response and response.status in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(2 ** (attempt + 1))
                continue
            if response and response.status >= 400:
                raise ValueError(f'숙소 페이지 HTTP {response.status}; 차단·인증 또는 서버 오류입니다.')
            if normalize_url(page.url)[0] != normalize_url(url)[0]:
                raise ValueError('다른 숙소 페이지로 이동했습니다.')
            text = await page.locator('script#__NEXT_DATA__').text_content(timeout=15000)
            return extract_photos(json.loads(text))
        except BrowserTimeout as error:
            if attempt == 2 or 'goto' not in str(error).lower():
                raise ValueError('페이지 시간 초과 또는 차단·추가 인증 화면입니다.') from error
            await asyncio.sleep(2 ** (attempt + 1))


async def fetch_image(context, url):
    image_url(url)
    for attempt in range(3):
        response = None
        try:
            response = await context.request.get(url, timeout=30000, max_redirects=0)
            if response.status in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(2 ** (attempt + 1))
                continue
            if response.status != 200:
                raise ValueError(f'이미지 HTTP {response.status}')
            if not response.headers.get('content-type', '').lower().startswith('image/'):
                raise ValueError('서버 응답이 이미지 형식이 아닙니다.')
            return await response.body()
        except BrowserTimeout:
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** (attempt + 1))
        finally:
            if response:
                await response.dispose()
            await asyncio.sleep(1)


async def collect(collection_id):
    manifest = read(collection_id)
    root = folder(collection_id)
    previous = {entry['url']: entry for entry in manifest.get('images', []) if 'url' in entry}
    browser = None
    try:
        async with async_playwright() as playwright:
            # The portable app bundles full Chromium, not the optional headless-shell package.
            browser = await playwright.chromium.launch(headless=False, executable_path=playwright.chromium.executable_path)
            try:
                context = await browser.new_context(locale='ko-KR', viewport={'width': 1440, 'height': 1000})
                page = await context.new_page()
                async def restrict_navigation(route):
                    if route.request.is_navigation_request() and route.request.frame == page.main_frame:
                        try:
                            normalize_url(route.request.url)
                        except ValueError:
                            await route.abort()
                            return
                    await route.continue_()
                await page.route('**/*', restrict_navigation)
                name, photos = await load_page(page, manifest['source_url'])
                manifest.update(name=name, images=[], failures=[], total=len(photos))
                (root / 'images').mkdir(parents=True, exist_ok=True)
                save(collection_id, manifest)
                for index, photo in enumerate(photos):
                    try:
                        entry = cached_image(root, previous.get(photo['url'], {}))
                        if entry:
                            entry = dict(entry, labels=photo['labels'], reused=True)
                        else:
                            content = await fetch_image(context, photo['url'])
                            details = describe_image(content)
                            extension = {'JPEG': 'jpg', 'TIFF': 'tif'}.get(details['format'], details['format'].lower())
                            relative = 'images/' + details['sha256'] + '.' + extension
                            target = root / relative
                            if not target.exists() or target.read_bytes() != content:
                                pending = target.with_suffix(target.suffix + '.part')
                                pending.write_bytes(content)
                                pending.replace(target)
                            entry = dict(details, url=photo['url'], labels=photo['labels'], file=relative,
                                         downloaded_at=now(), reused=False)
                        manifest['images'].append(entry)
                    except Exception as error:
                        manifest['failures'].append({'url': photo['url'], 'labels': photo['labels'], 'error': str(error)})
                    manifest.update(processed=index + 1, message=f'{index + 1}/{len(photos)}개 사진을 확인했습니다.')
                    save(collection_id, manifest)
                manifest['status'] = 'complete' if not manifest['failures'] else 'partial' if manifest['images'] else 'failed'
                manifest.update(unique_files=len(unique_photos(manifest)), completed_at=now(),
                                message=f"사진 {len(unique_photos(manifest))}장 수집 · 실패 {len(manifest['failures'])}개")
                save(collection_id, manifest)
            finally:
                await browser.close()
    except asyncio.CancelledError:
        manifest.update(status='interrupted', message='수집이 중단되었습니다. 같은 링크로 다시 수집해 주세요.')
        save(collection_id, manifest)
        raise
    except Exception as error:
        manifest.update(status='failed', error=str(error), message='이미지 수집에 실패했습니다.')
        save(collection_id, manifest)
