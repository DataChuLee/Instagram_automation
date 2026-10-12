from pathlib import Path
from PIL import Image, ImageOps, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
files = sorted((ROOT / 'Data/Test_Data').glob('*.jpg'))
canvas = Image.new('RGB', (1250, 1440), '#eeeeee')
draw = ImageDraw.Draw(canvas)
for index, path in enumerate(files):
    x, y = index % 5 * 250, index // 5 * 360
    canvas.paste(ImageOps.contain(Image.open(path), (240, 310)), (x, y + 28))
    draw.text((x + 10, y + 8), f'{index}: {path.stem[-3:]}', fill='black')
canvas.save(ROOT / 'output/test_contact_sheet.jpg')

import json
import shutil
OUT = ROOT / 'output/test5_20261009'
OUT.mkdir(parents=True, exist_ok=True)
entries = [
    (3, '강을 바라보며, 물 위에서 쉬어가요.', 'Slow gentle cinematic push forward over the outdoor pools toward the river. Subtle natural ripples on water and slight leaf movement. Preserve the exact architecture, pool shapes and landscape. No added people, objects, text or logos.'),
    (7, '나무 지붕 아래, 여유롭게 물놀이해요.', 'Slow subtle forward camera movement under the wooden pavilion over the pool. Gentle water ripples and minimal natural movement of existing swimmers. Preserve the wooden beams, proportions and all existing people without facial closeups. Do not add people or alter structures. No text or logos.'),
    (15, '물놀이 뒤에는, 포근한 침대에서 쉬어요.', 'Slow smooth camera slide slightly right across the hotel bedroom toward the balcony river view. Preserve the bed, linens, furniture and window geometry. Soft realistic daylight, very subtle curtain movement. No new furniture, people, text or logos.'),
    (11, '아침에는, 먹음직한 빵으로 시작해요.', 'Slow gentle cinematic camera slide right across the bakery buffet display. Preserve all existing pastries, trays and furniture exactly. Realistic warm indoor light. Food stays still. No invented food, people, steam, text or logos.'),
    (8, '밤에는, 조명이 물 위를 수놓아요.', 'Slow smooth forward camera movement above the outdoor pools at night. Gentle water ripples reflect the existing purple and warm lights. Preserve exact pool shapes, buildings and landscaping. No new lights or people, no text or logos.'),
]
scenes = []
for number, (index, text, prompt) in enumerate(entries, 1):
    source = files[index]
    shutil.copy2(source, OUT / f'{number:02}_original.jpg')
    photo = ImageOps.exif_transpose(Image.open(source)).convert('RGB')
    ImageOps.fit(photo, (1080, 1920), method=Image.Resampling.LANCZOS).save(OUT / f'{number:02}_input.jpg', quality=96)
    scenes.append(dict(number=number, source=str(source.relative_to(ROOT)), text=text,
                       prompt=prompt, input=f'{number:02}_input.jpg',
                       model_id='seedance-2.0', voice_id='4a81bbbb5cd44f22922bf934cb93b369',
                       voice_model='drama-3-preview',
                       parameters=dict(aspect_ratio='9:16', resolution='1080p', duration='5s')))
(OUT / 'storyboard.json').write_text(json.dumps(dict(scenes=scenes), ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(dict(folder=str(OUT), files=[dict(name=s['input'], size=(OUT/s['input']).stat().st_size) for s in scenes]), ensure_ascii=False))
