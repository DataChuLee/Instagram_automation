from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT / '.tools/studio-python'))
from studio import store
from studio.render import render,run
from studio.paths import job_path
job=store.read('e'*32)
folder=job_path(job.id)
run('-f','lavfi','-i','color=black:s=720x1280:r=30','-t','0.2','-c:v','libx264',folder / 'lowres.mp4')
job.generated['0']['file']='lowres.mp4'
try:
    render(job)
except RuntimeError as error:
    assert '네이티브' in str(error)
else:
    raise AssertionError('Low-resolution motion accepted')
print('720p motion rejected; existing complete result preserved')
