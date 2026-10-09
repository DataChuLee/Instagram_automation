"""Verify the local Fish OAuth connection and Drama3 quote without spending credits."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
sys.stdout.reconfigure(encoding='utf-8')

from studio.drama import Drama
from studio.fish import Fish


async def main():
    drama = Drama(Fish())
    path = ROOT / '.local/probes/drama-mcp.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    record = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    async def save(data):
        record.update(data)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    result = await drama.quote('안녕하세요. 드라마 쓰리 모델 설정 확인입니다.',
                               'Stay Studio MCP 연결 검증 20261009', record, save)
    print(json.dumps({k: result[k] for k in ('model', 'voice', 'credits', 'project_id', 'block')}, ensure_ascii=False))
    print('Local Fish MCP: Drama3 / 일반여성2 quote verified; no paid generation')


asyncio.run(main())
