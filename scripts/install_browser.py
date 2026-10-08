import os
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
environment['PYTHONPATH'] = str(ROOT / '.tools/studio-python')
environment['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.tools/ms-playwright')
subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'],env=environment,check=True)
