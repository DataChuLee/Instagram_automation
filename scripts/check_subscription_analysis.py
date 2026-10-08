"""Analyze existing demo photos using the signed-in Codex subscription, no Fish calls."""
from pathlib import Path
import sys
import asyncio
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT / '.tools/studio-python'))
sys.stdout.reconfigure(encoding='utf-8')
from studio import store
from studio.codex import analyze
job=store.read('d'*32)
plan=asyncio.run(analyze(job))
path=ROOT / '.local/probes/codex-storyboard.json'
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(plan.model_dump_json(indent=2),encoding='utf-8')
print('Subscription analysis validated:',len(job.photos),'photos,',len(plan.scenes),'scenes,',len(plan.motion),'motion selections')
