"""Inspect only the public editor. Does not log in, enter text, or generate."""
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / '.local/probes'
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={'width': 1400, 'height': 1000})
    page.goto('https://beta.fish.audio/app/text-to-speech/?version=drama-3-preview',
              wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(6000)
    if page.get_by_role('button', name='Try it now', exact=True).count():
        page.get_by_role('button', name='Try it now', exact=True).click()
    if page.get_by_role('button', name='Choose a voice', exact=True).count():
        page.get_by_role('button', name='Choose a voice', exact=True).click()
        page.wait_for_timeout(2000)
        page.get_by_placeholder('Search', exact=True).fill('일반여성2')
        page.wait_for_timeout(4000)
        use = page.get_by_role('button', name='Use', exact=True)
        if use.count() == 1:
            use.evaluate('(element)=>element.click()')
            page.wait_for_timeout(1000)
    print('URL:', page.url)
    print(page.locator('body').inner_text()[:12000])
    print('INPUTS:', page.locator('input, textarea, [contenteditable]').evaluate_all('(els)=>els.map(e=>e.outerHTML)'))
    page.screenshot(path=str(out / 'fish-editor.png'))
    (out / 'fish-editor.html').write_text(page.content(), encoding='utf-8')
    browser.close()
