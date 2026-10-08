import os
import sys
from pathlib import Path

RESOURCES = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
if os.environ.get('STAY_STUDIO_DATA'):
    DATA = Path(os.environ['STAY_STUDIO_DATA']).resolve()
elif getattr(sys, 'frozen', False):
    DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'StayStudio'
else:
    DATA = RESOURCES / '.local'


def initialize():
    for name in ('jobs', 'auth', 'browser', 'logs'):
        (DATA / name).mkdir(parents=True, exist_ok=True)


def job_path(job_id: str) -> Path:
    import re
    if not re.fullmatch(r'[a-f0-9]{32}', job_id):
        raise ValueError('올바르지 않은 작업 번호입니다.')
    return DATA / 'jobs' / job_id


def font_path() -> Path:
    path = RESOURCES / 'assets/fonts/Paperlogy-7Bold.ttf'
    if not path.is_file():
        raise RuntimeError('페이퍼로지 폰트가 없습니다. 배포 파일을 다시 확인해 주세요.')
    return path
