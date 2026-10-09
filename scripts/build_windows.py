"""Bundle public executables and app resources; never include user data or auth."""
from pathlib import Path
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
from studio.codex import executable
from studio.render import ffmpeg
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.tools/ms-playwright')
from playwright.sync_api import sync_playwright

tools = ROOT / 'build-resources/tools'
tools.mkdir(parents=True, exist_ok=True)
old_codex = tools / 'codex.exe'
if old_codex.is_file() and old_codex.resolve().is_relative_to(ROOT.resolve()):
    old_codex.unlink()
codex_path = Path(executable())
shutil.copytree(codex_path.parent.parent, tools / 'codex-runtime', dirs_exist_ok=True)
shutil.copy2(ffmpeg(), tools / 'ffmpeg.exe')
with sync_playwright() as playwright:
    browser = Path(playwright.chromium.executable_path)
if not browser.is_file():
    raise RuntimeError('Run scripts/install_browser.py first.')
browser_root = browser.parents[1]
shutil.copytree(browser_root, tools / 'ms-playwright' / browser_root.name, dirs_exist_ok=True)
versions = {name: importlib.metadata.version(name) for name in ('fastapi','starlette','mcp','pydantic','playwright','Pillow','uvicorn','pyinstaller','httpx','python-multipart','imageio-ffmpeg')}
(ROOT / 'requirements-studio.lock.txt').write_text(''.join(f'{name}=={value}\n' for name,value in versions.items()),encoding='utf-8')
(ROOT / 'build-resources/versions.json').write_text(json.dumps(versions,indent=2),encoding='utf-8')
environment = os.environ.copy()
environment['PYTHONPATH'] = str(ROOT / '.tools/studio-python')
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--name', 'StayStudio',
        '--paths', str(ROOT / '.tools/studio-python'), '--add-data', f'{ROOT / "studio/web"};studio/web',
        '--add-data', f'{ROOT / "assets/fonts"};assets/fonts',
        '--add-data', f'{ROOT / "studio/skills"};studio/skills',
        '--add-data', f'{ROOT / "build-resources/tools"};tools',
        '--add-data', f'{ROOT / "build-resources/versions.json"};.',
        '--collect-all', 'playwright', '--collect-all', 'mcp', '--collect-all', 'httpx2',
        '--collect-all', 'pkg_resources',
        '--collect-all', 'truststore', '--hidden-import', 'uvicorn.logging',
        '--hidden-import', 'uvicorn.loops.asyncio', '--hidden-import', 'uvicorn.protocols.http.h11_impl',
        '--hidden-import', 'uvicorn.lifespan.on', '--exclude-module', 'torch',
        '--exclude-module', 'tensorflow', '--exclude-module', 'matplotlib', '--exclude-module', 'pandas',
        '--exclude-module', 'IPython', '--exclude-module', 'numpy', '--exclude-module', 'scipy',
        '--exclude-module', 'pytest', '--exclude-module', 'notebook', '--exclude-module', 'openai',
        str(ROOT / 'launch.py')]
subprocess.run(args,cwd=ROOT,env=environment,check=True)
folder = ROOT / 'dist/StayStudio'
shutil.copy2(ROOT / 'docs/친구-PC-사용법.md', folder / '사용법.md')
print('Portable folder ready:', folder)
shutil.make_archive(str(ROOT / 'dist/StayStudio-Windows'), 'zip', root_dir=ROOT / 'dist', base_dir='StayStudio')
print('ZIP ready:', ROOT / 'dist/StayStudio-Windows.zip')
