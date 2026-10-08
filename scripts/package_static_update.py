"""Refresh only web assets in an existing portable build, then recreate its ZIP."""
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
folder = ROOT / 'dist/StayStudio'
assert (folder / 'StayStudio.exe').is_file(), 'Build the portable executable first'
shutil.copytree(ROOT / 'studio/web', folder / '_internal/studio/web', dirs_exist_ok=True)
destination = ROOT / 'dist/StayStudio-Windows.zip'
temporary = destination.with_suffix('.pending.zip')
with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
    for path in folder.rglob('*'):
        if path.is_file():
            bundle.write(path, path.relative_to(ROOT / 'dist').as_posix())
temporary.replace(destination)
with zipfile.ZipFile(destination) as bundle:
    assert bundle.testzip() is None
    for name in ('app.js', 'index.html', 'style.css'):
        assert bundle.read('StayStudio/_internal/studio/web/' + name) == (ROOT / 'studio/web' / name).read_bytes()
print('Portable web assets and ZIP integrity verified', flush=True)
