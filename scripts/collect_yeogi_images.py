"""Collect photos published on Yeogi domestic accommodation detail pages."""
import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from studio.yeogi import (normalize_url, image_url, extract_photos, now, read_json,
                         write_json, replace_file, describe_image, cached_image, save_collection)


def load_page(page, url):
    from playwright.sync_api import TimeoutError as BrowserTimeout
    for attempt in range(3):
        try:
            response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
            if response and response.status in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            if response and response.status >= 400:
                raise ValueError(f'숙소 페이지 HTTP {response.status}; 차단·인증 또는 서버 오류입니다.')
            if normalize_url(page.url)[0] != normalize_url(url)[0]:
                raise ValueError('다른 숙소 페이지로 이동했습니다.')
            # Missing data after navigation is a schema/challenge failure, not a retry trigger.
            text = page.locator('script#__NEXT_DATA__').text_content(timeout=15000)
            return extract_photos(json.loads(text))
        except BrowserTimeout as exc:
            if attempt == 2:
                raise ValueError('페이지 시간 초과 또는 차단·추가 인증 화면입니다.') from exc
            # Retry navigation timeouts only, never a missing data/challenge page.
            if 'goto' not in str(exc).lower():
                raise ValueError('페이지 데이터가 없거나 차단·추가 인증 화면입니다.') from exc
            time.sleep(2 ** (attempt + 1))


def downloader(context, interval):
    from playwright.sync_api import TimeoutError as BrowserTimeout
    def fetch(url):
        image_url(url)
        for attempt in range(3):
            response = None
            try:
                response = context.request.get(url, timeout=30000, max_redirects=0)
                if response.status in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 ** (attempt + 1))
                    continue
                if response.status != 200:
                    raise ValueError(f'이미지 HTTP {response.status}')
                if not response.headers.get('content-type', '').lower().startswith('image/'):
                    raise ValueError('서버 응답이 이미지 형식이 아닙니다.')
                return response.body()
            except BrowserTimeout:
                if attempt == 2:
                    raise
                time.sleep(2 ** (attempt + 1))
            finally:
                if response is not None:
                    response.dispose()
                time.sleep(interval)
    return fetch


def collect_batch(context, inputs, output_root, interval):
    report = {'started_at': now(), 'results': []}
    page = context.new_page()
    fetch = downloader(context, interval)
    try:
        for accommodation_id, url in inputs:
            folder = output_root / accommodation_id
            print(f'[{accommodation_id}] 페이지 확인: {url}', flush=True)
            try:
                name, photos = load_page(page, url)
                manifest = save_collection(folder, url, name, photos, fetch)
                result = {'accommodation_id': accommodation_id, 'source_url': url,
                          'status': manifest['status'], 'photo_urls': len(photos),
                          'unique_files': manifest['unique_files'], 'failures': len(manifest['failures']),
                          'reused_urls': sum(entry['reused'] for entry in manifest['images']),
                          'manifest': str(folder / 'manifest.json')}
                print(f"[{accommodation_id}] {result['status']}: 파일 {result['unique_files']}개, 실패 {result['failures']}개", flush=True)
            except Exception as exc:
                result = {'accommodation_id': accommodation_id, 'source_url': url,
                          'status': 'failed', 'error': str(exc)}
                # Preserve existing photo records even if a later page fetch fails.
                manifest = read_json(folder / 'manifest.json')
                manifest.update(accommodation_id=accommodation_id, source_url=url,
                                status='failed', last_attempt_at=now(), page_error=str(exc))
                write_json(folder / 'manifest.json', manifest)
                print(f'[{accommodation_id}] 실패: {exc}', file=sys.stderr, flush=True)
            report['results'].append(result)
            write_json(output_root / 'collection_report.json', report)
            time.sleep(interval)
    finally:
        page.close()
    report['completed_at'] = now()
    return report


def prompt_urls():
    print('여기어때 국내 숙소 링크를 한 줄씩 입력하세요.')
    print('입력이 끝나면 링크 없이 Enter를 누르세요. 그러면 수집을 시작합니다.')
    lines, seen = [], set()
    while True:
        try:
            line = input(f'숙소 링크 {len(lines) + 1}> ').strip()
        except EOFError:
            print()
            break
        if not line:
            break
        try:
            accommodation_id, url = normalize_url(line)
        except ValueError as exc:
            print(f'잘못된 링크: {exc} 다시 입력하세요.')
            continue
        if accommodation_id in seen:
            print('이미 입력한 숙소입니다. 다른 링크를 입력하세요.')
            continue
        lines.append(url)
        seen.add(accommodation_id)
    return lines


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--urls', type=Path, help='Optional UTF-8 URL file; omit to enter links in the terminal')
    parser.add_argument('--output', type=Path, default=PROJECT_ROOT / 'Data/accommodations')
    parser.add_argument('--headless', action='store_true', help='Optional; some sites block headless browsers')
    parser.add_argument('--interval', type=float, default=1.0, help='Seconds between requests (minimum 0.5)')
    args = parser.parse_args(argv)
    if args.interval < 0.5 or not args.interval < float('inf'):
        parser.error('--interval must be finite and at least 0.5')
    if args.urls is None:
        try:
            lines = prompt_urls()
        except KeyboardInterrupt:
            print('\n입력을 취소했습니다.')
            return 130
        if not lines:
            print('입력한 숙소 링크가 없어 종료합니다.')
            return 0
    else:
        try:
            lines = args.urls.read_text(encoding='utf-8-sig').splitlines()
        except (OSError, UnicodeError) as exc:
            parser.error(str(exc))
    inputs, invalid, seen = [], [], set()
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        try:
            accommodation_id, url = normalize_url(line)
            if accommodation_id not in seen:
                inputs.append((accommodation_id, url))
                seen.add(accommodation_id)
        except ValueError as exc:
            invalid.append({'source_url': line.strip(), 'status': 'invalid', 'error': str(exc)})
    if not inputs and not invalid:
        parser.error('입력 파일에 숙소 링크가 없습니다.')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        if inputs:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                # Prefer installed Chrome; bundled Chromium is used only when Chrome is absent.
                chrome = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
                options = {'headless': args.headless}
                if chrome.exists():
                    options['channel'] = 'chrome'
                browser = p.chromium.launch(**options)
                try:
                    context = browser.new_context(locale='ko-KR', viewport={'width': 1440, 'height': 1000})
                    report = collect_batch(context, inputs, output, args.interval)
                finally:
                    browser.close()
        else:
            report = {'started_at': now(), 'completed_at': now(), 'results': []}
    except Exception as exc:
        report = {'started_at': now(), 'completed_at': now(), 'results': [], 'error': str(exc)}
        report['results'].extend({'accommodation_id': aid, 'source_url': url,
                                  'status': 'failed', 'error': str(exc)} for aid, url in inputs)
        print('브라우저 실행 실패: ' + str(exc), file=sys.stderr)
    report['results'].extend(invalid)
    write_json(output / 'collection_report.json', report)
    print('수집 보고서: ' + str(output / 'collection_report.json'), flush=True)
    return 1 if any(row['status'] != 'complete' for row in report['results']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
