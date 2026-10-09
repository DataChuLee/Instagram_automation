"""Live candidate assessment/selection/draft evaluation without Fish calls."""
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'.tools/studio-python')]
from studio import codex, composition, recommendation
from studio.models import Job
from studio.paths import job_path


async def main():
    if not await codex.login_status():raise RuntimeError('Codex login required')
    job=Job(id=uuid.uuid4().hex,workflow_version=2,composition_mode='ai',target_count=5)
    folder=job_path(job.id)
    folder.mkdir(parents=True,exist_ok=True)
    for index,path in enumerate(sorted((ROOT/'Data/Test_Data').glob('*.jpg'))):
        shutil.copy2(path,folder/path.name)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        job.candidates.append({'id':digest,'sha256':digest,'file':path.name,'name':path.name,'source_index':index})
    print(f'Evaluating all {len(job.candidates)} candidates',flush=True)
    result=await recommendation.choose(job,lambda message:print(message,flush=True))
    composition.select(job,result['ids'])
    output={'selection':result,'selected_source_indices':[p['source_index'] for p in job.photos],
            'candidate_count':len(job.candidates),'human_score':None}
    target=ROOT/'.local/probes/recommendation-evaluation.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        job.storyboard=await codex.analyze(job)
        output['plan']=job.storyboard.model_dump()
    except Exception as error:
        output['draft_error']=str(error)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: full candidate assessment, global selection, reasons and ordered draft; no Fish calls.',flush=True)


if __name__=='__main__':asyncio.run(main())
