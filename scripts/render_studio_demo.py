"""Render existing, already paid narration. This is not a Drama3/motion generation test."""
import json
import shutil
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
from studio.models import Job, Storyboard
from studio.paths import job_path, initialize
from studio import store
from studio.render import render

initialize()
job = Job(id='d'*32)
folder = job_path(job.id)
folder.mkdir(parents=True,exist_ok=True)
photos = sorted((ROOT / 'Data/Test_Data').glob('*.jpg'))
import hashlib
for index,photo in enumerate(photos):
    name=f'photo-{index:03}.jpg'
    shutil.copy2(photo,folder/name)
    job.photos.append({'file':name,'name':photo.name,'sha256':hashlib.sha256(photo.read_bytes()).hexdigest()})
previous=json.loads((ROOT / 'output/storyboard.json').read_text(encoding='utf-8'))
job.storyboard=Storyboard(scenes=[{'photos':s['images'],'text':s['text']} for s in previous['scenes']])
for index,scene in enumerate(previous['scenes']):
    name=f'voice-{index:03}.mp3'
    shutil.copy2(ROOT / scene['audio'],folder/name)
    job.narration[str(index)]={'file':name,'source':'previously-generated-not-Drama3'}
job.state='rendering'
store.save(job)
job.result=render(job,lambda message:print(message,flush=True))
job.state='complete'
job.message='합성 검증용 영상 · 기존 음성 재사용 (Drama3 생성 아님)'
store.save(job)
print(folder / job.result['file'])
