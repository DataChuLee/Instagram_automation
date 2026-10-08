"""Compare official login origins without credentials or generation."""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.tools/ms-playwright')
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=False, executable_path=playwright.chromium.executable_path)
    try:
        for host in ('fish.audio', 'beta.fish.audio'):
            context = browser.new_context(locale='en-US')
            page = context.new_page()
            try:
                page.goto(f'https://{host}/app/text-to-speech/?version=drama-3-preview', wait_until='domcontentloaded', timeout=60000)
                page.get_by_role('button', name=re.compile(r'^(Try it now|Login \/ Sign up|Log in|Login|Sign in)$', re.I)).first.wait_for(timeout=30000)
                page.wait_for_timeout(1000)
                trial = page.get_by_role('button', name='Try it now', exact=True)
                if trial.count():
                    trial.click()
                page.wait_for_timeout(1000)
                result = {'requested_host': host, 'editor_host': urlsplit(page.url).hostname,
                          'drama_button': bool(page.get_by_role('button', name=re.compile('Fish Audio Drama 3')).count())}
                result['title'] = page.title()
                result['buttons'] = page.locator('button').all_text_contents()
                result['public_text'] = page.locator('body').inner_text()[:1400]
                destination = ROOT / '.local/probes' / (host + '-login.png')
                destination.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(destination))
                login = page.get_by_role('button', name=re.compile(r'^(Login \/ Sign up|Log in|Login|Sign in)$', re.I))
                if login.count():
                    login.first.click()
                    page.wait_for_timeout(3000)
                google = page.get_by_role('button', name=re.compile('Google', re.I))
                if not google.count():
                    google = page.get_by_text(re.compile(r'^(Continue with Google|Sign in with Google|Google)$', re.I))
                result['google_button'] = bool(google.count())
                if google.count():
                    google.first.click()
                    page.wait_for_timeout(6000)
                    google_pages = [p for p in context.pages if urlsplit(p.url).hostname == 'accounts.google.com']
                    auth_page = google_pages[-1] if google_pages else page
                    body = auth_page.locator('body').inner_text()
                    result.update(auth_host=urlsplit(auth_page.url).hostname,
                                  origin_mismatch='origin_mismatch' in body,
                                  account_prompt=bool(re.search(r'Email or phone|이메일 또는 전화|Sign in|로그인', body, re.I)))
                print(json.dumps(result, ensure_ascii=False), flush=True)
            finally:
                context.close()
    finally:
        browser.close()
