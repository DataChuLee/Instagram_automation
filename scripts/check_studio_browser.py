"""End-to-end local UI check. Never presses paid generation."""
from pathlib import Path
import sys
import os
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / '.tools/studio-python'))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    # Public installed browser is usable for this local UI check; distribution uses dedicated bundle.
    browser=playwright.chromium.launch(headless=True,executable_path=str(Path.home() / 'AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe'))
    page=browser.new_page(viewport={'width':1500,'height':1100})
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(os.environ.get('STUDIO_TEST_URL','http://127.0.0.1:8765'),wait_until='networkidle')
    if page.locator('#settings').evaluate('(el)=>el.open'):
        page.locator('#closeSettings').click()
    photos=sorted((ROOT / 'Data/Test_Data').glob('*.jpg'))
    page.locator('#files').set_input_files([str(p) for p in photos])
    page.wait_for_function("document.querySelectorAll('#photoGrid button').length===17")
    page.wait_for_function("document.querySelector('#preview').naturalWidth===1080")
    page.locator('#posY').fill('20')
    page.locator('#posY').dispatch_event('input')
    page.wait_for_timeout(1000)
    assert page.locator('#posYValue').inner_text()=='20'
    page.locator('#saveStyle').click()
    page.wait_for_timeout(500)
    out=ROOT / '.local/probes'
    out.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(out / 'studio-ui.png'),full_page=True)
    print('17 photo upload, native portrait preview, caption position edit/save passed')
    assert not errors,errors
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(out / 'studio-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    print('Mobile layout and no JavaScript errors passed')
    browser.close()
