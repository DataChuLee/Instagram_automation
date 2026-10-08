"""Collect one real public listing with the app collector; never calls paid services."""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
sys.stdout.reconfigure(encoding='utf-8')
os.environ['STAY_STUDIO_DATA'] = str(ROOT / '.local/probes/link/data')
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.tools/ms-playwright')
from studio import collector


async def main():
    collector.recover()
    collection_id, _ = collector.start('https://www.yeogi.com/domestic-accommodations/9816')
    task = asyncio.create_task(collector.collect(collection_id))
    while not task.done():
        await asyncio.wait({task}, timeout=5)
        value = collector.gallery(collection_id)
        print(f"{value['status']}: {value['processed']}/{value['total']} · 사진 {len(value['photos'])}장", flush=True)
    await task
    value = collector.gallery(collection_id)
    print(value['name'], value['status'], value['error'], flush=True)
    if value['status'] not in {'complete', 'partial'} or not value['photos']:
        raise RuntimeError(value['error'] or 'No collected photos')
    assert len({p['id'] for p in value['photos']}) == len(value['photos'])
    for photo in value['photos']:
        collector.photo_entry(collection_id, photo['id'])
    print('Real public listing, original-image verification and unique gallery passed', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
