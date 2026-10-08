from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / '.tools/studio-python'))
sys.stdout.reconfigure(encoding='utf-8')
from playwright.sync_api import sync_playwright
paths=[ROOT / '.tools/ms-playwright/chromium-1243/chrome-win64/chrome.exe',Path.home() / 'AppData/Local/ms-playwright/chromium-1208/chrome-win64/chrome.exe']
with sync_playwright() as playwright:
    for index,path in enumerate(paths):
        try:
            context=playwright.chromium.launch_persistent_context(str(ROOT / f'.local/probes/browser-runtime-{index}'),headless=False,executable_path=str(path))
            page=context.pages[0]
            page.goto('about:blank')
            print(path.name,path.parent.parent.name,'headed launch passed',flush=True)
            context.close()
        except Exception as error:
            print(path.parent.parent.name,'ERROR',str(error)[-3000:],flush=True)
