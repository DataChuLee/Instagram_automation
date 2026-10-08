"""Exercise 25-photo/mixed video paths using saved media, without paid generation."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT / '.tools/studio-python'))
sys.stdout.reconfigure(encoding='utf-8')
from studio import store
from studio.models import Job, Storyboard
from studio.paths import job_path
from studio.render import render, run

job=Job(id='e'*32)
folder=job_path(job.id)
folder.mkdir(parents=True,exist_ok=True)
photos=sorted((ROOT / 'Data/Test_Data').glob('*.jpg'))
for index in range(25):
    photo=photos[index % len(photos)]
    name=f'photo-{index:03}.jpg'
    shutil.copy2(photo,folder/name)
    job.photos.append({'file':name,'name':photo.name,'sha256':hashlib.sha256(photo.read_bytes()).hexdigest()})
job.storyboard=Storyboard(scenes=[{'photos':list(range(25)),'text':'스물다섯 장의 사진으로 만드는 우리 숙소 이야기'}],
    motion=[{'photo':0,'prompt':'Fixture clip; no AI generation performed.'}])
shutil.copy2(ROOT / 'output/audio/00.mp3',folder / 'voice-000.mp3')
job.narration={'0':{'file':'voice-000.mp3','source':'existing test fixture'}}
run('-i',ROOT / 'Data/영상_1.mp4','-t','1','-an','-c:v','libx264','-crf','18',folder / 'motion-000.mp4')
job.generated={'0':{'file':'motion-000.mp4','source':'reference fixture, not AI generation'}}
job.result=render(job,lambda message:print(message,flush=True))
job.state='complete'
job.message='합성 검증용 · 25장 및 기존 영상 혼합 (새 유료 생성 아님)'
store.save(job)
report=json.loads((folder / 'verification.json').read_text(encoding='utf-8'))
assert report['photos']==25
assert sorted(p['photo'] for p in report['timeline'])==list(range(25))
assert report['timeline'][0]['motion']
run('-f','lavfi','-i','color=black:s=720x1280:r=30','-t','0.2','-c:v','libx264',folder / 'lowres.mp4')
job.generated['0']['file']='lowres.mp4'
try:
    render(job)
except RuntimeError as error:
    assert '네이티브' in str(error)
else:
    raise AssertionError('Low-resolution motion accepted')
print('25 photos, mixed video, full decode and native1080 rejection passed')
