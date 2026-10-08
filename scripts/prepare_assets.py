"""Fetch redistributable font resources into the application, not system fonts."""
from pathlib import Path
import hashlib
import urllib.request
import io
import zipfile

ROOT = Path(__file__).resolve().parents[1]
destination = ROOT / 'assets/fonts'
destination.mkdir(parents=True, exist_ok=True)
url = 'https://github.com/Freesentation/paperlogy/raw/refs/heads/main/Paperlogy-1.001.zip'
with urllib.request.urlopen(url, timeout=60) as response:
    archive = zipfile.ZipFile(io.BytesIO(response.read()))
names = archive.namelist()
print('Archive files:', names)
font = next(name for name in names if name.endswith('Paperlogy-7Bold.ttf') and not name.startswith('__MACOSX'))
data = archive.read(font)
if data[:4] not in (b'\x00\x01\x00\x00', b'OTTO'):
    raise RuntimeError('Invalid font download')
(destination / 'Paperlogy-7Bold.ttf').write_bytes(data)
licenses = [name for name in names if not name.startswith('__MACOSX') and
            ('license' in name.lower() or 'ofl' in name.lower()) and not name.endswith('/')]
if not licenses:
    license_url = 'https://www.designptn.com/wp-content/uploads/2024/08/OFL-license.txt'
    with urllib.request.urlopen(license_url, timeout=60) as response:
        license_data = response.read()
    if b'OPEN FONT LICENSE' not in license_data.upper():
        raise RuntimeError('Official license download is not OFL text')
    (destination / 'OFL.txt').write_bytes(license_data)
for index, name in enumerate(licenses):
    (destination / ('OFL' + (str(index) if index else '') + Path(name).suffix)).write_bytes(archive.read(name))
(destination / 'SOURCE.txt').write_text('Official source: ' + url + '\nAuthor: Lee Juim / Paperlogy\n'
    + 'Font SHA256: ' + hashlib.sha256(data).hexdigest() + '\n', encoding='utf-8')
print('Official font and licenses installed', len(data), hashlib.sha256(data).hexdigest())
