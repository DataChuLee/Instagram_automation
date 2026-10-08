"""Normal Fish web editor actions. No developer API or hidden generation calls."""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from .models import DRAMA_MODEL, VOICE_ID
from .paths import DATA

# Beta's Google OAuth currently rejects its origin. Production serves the same Drama3 editor.
EDITOR = 'https://fish.audio/app/text-to-speech/?version=' + DRAMA_MODEL


def native_browser():
    """Use an installed supported browser for human Google authentication."""
    roots = [os.environ.get(name) for name in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
    for relative in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe'):
        for root in roots:
            if root and (path := Path(root) / relative).is_file():
                return path
    raise RuntimeError('Drama3 로그인에 사용할 Chrome 또는 Edge를 설치해 주세요.')


class Drama:
    def __init__(self):
        self.playwright = None
        self.context = None
        self.page = None
        self.lock = asyncio.Lock()
        self.open_lock = asyncio.Lock()
        self.login_process = None

    @property
    def login_open(self):
        return bool(self.login_process and self.login_process.poll() is None)

    async def open_login(self):
        """Authenticate manually first; automate Fish only after the window closes."""
        async with self.open_lock:
            if self.login_open:
                return
            browser = native_browser()
            await self.close()
            profile = DATA / 'browser/fish-manual'
            profile.mkdir(parents=True, exist_ok=True)
            self.login_process = subprocess.Popen([str(browser),
                '--user-data-dir=' + str(profile), '--no-first-run', '--no-default-browser-check',
                '--disable-background-mode', '--lang=en-US', '--new-window', EDITOR],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def open(self):
        async with self.open_lock:
            return await self._open()

    async def _open(self):
        if self.login_open:
            raise RuntimeError('Fish에서 로그인을 완료한 뒤 로그인 창을 닫고 다시 진행해 주세요.')
        if self.context and self.page and not self.page.is_closed():
            return self.page
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            str(DATA / 'browser/fish-manual'), headless=False, executable_path=str(native_browser()),
            locale='en-US', viewport={'width': 1400, 'height': 1000}, accept_downloads=True)
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        await self.page.goto(EDITOR, wait_until='domcontentloaded', timeout=60000)
        await self.page.wait_for_timeout(2000)
        button = self.page.get_by_role('button', name='Try it now', exact=True)
        if await button.count():
            await button.click()
        return self.page

    async def close(self):
        if self.context:
            await self.context.close()
        if self.playwright:
            await self.playwright.stop()
        self.context = self.page = self.playwright = None

    async def ensure_voice(self, page):
        body = await page.locator('body').inner_text()
        if 'Login / Sign up' in body:
            raise RuntimeError('열린 Fish 창에서 로그인한 뒤 견적을 다시 요청해 주세요.')
        model = page.get_by_role('button', name=re.compile(r'Fish Audio Drama 3'))
        if not await model.count():
            raise RuntimeError('Fish 화면에서 Drama 3 모델을 확인할 수 없습니다. 다른 모델로 생성하지 않습니다.')
        selected = page.locator(f'img[src*="{VOICE_ID}"]')
        if await selected.count() and not await page.get_by_placeholder('Search', exact=True).count():
            return
        choose = page.get_by_role('button', name='Choose a voice', exact=True)
        if not await choose.count():
            choose = page.get_by_role('button', name='Add another voice', exact=True)
        await choose.click()
        await page.get_by_placeholder('Search', exact=True).fill('일반여성2')
        await page.wait_for_timeout(2500)
        # Match the exact public voice ID in its card/link, never first search result.
        card = page.locator(f'img[src*="{VOICE_ID}"]').first
        if await card.count():
            parent = card.locator('xpath=ancestor::*[.//button[normalize-space()="Use"]][1]')
            await parent.get_by_role('button', name='Use', exact=True).evaluate('(element)=>element.click()')
        else:
            raise RuntimeError('일반여성2 음성 ID를 확인할 수 없습니다. 음성 검색 결과를 확인해 주세요.')
        await page.wait_for_timeout(500)
        if not await selected.count() or await page.get_by_placeholder('Search', exact=True).count():
            raise RuntimeError('일반여성2 선택을 확인하지 못했습니다.')

    async def enter(self, text):
        page = await self.open()
        await self.ensure_voice(page)
        editor = page.locator('[contenteditable="true"]').first
        if not await editor.count():
            editor = page.locator('textarea').first
        if not await editor.count():
            raise RuntimeError('Fish 텍스트 입력 화면이 변경되었습니다. 생성 없이 중단했습니다.')
        await editor.fill(text)
        await page.wait_for_timeout(600)
        return page

    async def quote(self, text):
        async with self.lock:
            page = await self.enter(text)
            button = page.get_by_role('button', name=re.compile('Generate Speech'))
            await button.hover()
            await page.wait_for_timeout(400)
            # Read an explicit cost, not the balance or character counter.
            sources = [await button.inner_text()]
            tips = page.get_by_role('tooltip')
            sources += await tips.all_inner_texts()
            sources += await page.locator('[data-testid*="cost"], [data-testid*="credit-estimate"]').all_inner_texts()
            for source in sources:
                match = re.search(r'(?:cost|consume|uses?|비용|사용)\s*:?\s*([\d,]+)\s*(?:credits?|크레딧)', source, re.I)
                if not match:
                    match = re.search(r'^\s*([\d,]+)\s*(?:credits?|크레딧)\s*$', source, re.I)
                if match:
                    return int(match.group(1).replace(',', ''))
            raise RuntimeError('Drama3의 사전 크레딧 견적이 화면에 표시되지 않습니다. 금액을 확인할 수 없어 유료 생성은 중단했습니다.')

    async def generate(self, text, expected_credits, path, submitted):
        async with self.lock:
            page = await self.enter(text)
            # Re-read UI cost immediately before the paid click.
        actual = await self.quote(text)
        if actual != expected_credits:
            raise RuntimeError('Drama3 크레딧 견적이 바뀌었습니다. 다시 승인해 주세요.')
        async with self.lock:
            page = await self.enter(text)
            old_urls = await page.locator('audio').evaluate_all('(els)=>els.map(e=>e.currentSrc||e.src)')
            old_urls += await page.locator('a[download]').evaluate_all('(els)=>els.map(e=>e.href)')
            await submitted({'state': 'submitted', 'model': DRAMA_MODEL, 'voice': VOICE_ID})
            await page.get_by_role('button', name=re.compile('Generate Speech')).click()
            # A failed/uncertain click is never retried automatically.
            for _ in range(180):
                await asyncio.sleep(2)
                urls = await page.locator('audio').evaluate_all('(els)=>els.map(e=>e.currentSrc||e.src)')
                urls += await page.locator('a[download]').evaluate_all('(els)=>els.map(e=>e.href)')
                for url in urls:
                    if not url or url in old_urls or not url.startswith('https://'):
                        continue
                    host = urlparse(url).hostname or ''
                    if not (host.endswith('.fish.audio') or host == 'fish.audio'):
                        continue
                    await submitted({'state': 'completed', 'model': DRAMA_MODEL,
                                     'voice': VOICE_ID, 'url': url})
                    response = await self.context.request.get(url)
                    if not response.ok:
                        raise RuntimeError('Drama3 음성 다운로드에 실패했습니다. 기록된 결과로 재개해 주세요.')
                    path.write_bytes(await response.body())
                    return
                body = await page.locator('body').inner_text()
                if 'insufficient credits' in body.lower():
                    raise RuntimeError('Fish 크레딧이 부족합니다.')
            raise RuntimeError('Drama3 음성 완료를 확인하지 못했습니다. Fish History에서 결과를 확인해 주세요. 자동 재생성하지 않습니다.')
