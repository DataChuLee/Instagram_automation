"""Verify the packaged Drama editor origin and portable ZIP integrity."""
from pathlib import Path
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/studio-python'))
from PyInstaller.archive.readers import CArchiveReader

archive = CArchiveReader(str(ROOT / 'dist/StayStudio/StayStudio.exe'))
pyz = archive.open_embedded_archive('PYZ.pyz')
code = pyz.extract('studio.drama')
assert 'https://fish.audio/app/text-to-speech/?version=' in code.co_consts
assert not any(isinstance(value, str) and 'beta.fish.audio' in value for value in code.co_consts)
print('Packaged Drama editor: fish.audio verified')
def strings(code):
    for value in code.co_consts:
        if isinstance(value, str):
            yield value
        elif isinstance(value, types.CodeType):
            yield from strings(value)

drama_constants = set(strings(code))
assert 'browser/fish-manual' in drama_constants
assert '--new-window' in drama_constants
def code_objects(code):
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from code_objects(value)

assert any('open_login' in nested.co_names for nested in code_objects(pyz.extract('studio.app')))
fish_constants = set(strings(pyz.extract('studio.fish')))
assert {'structured_content', 'is_error', 'structuredContent', 'isError'} <= fish_constants
print('Packaged Fish MCP response compatibility verified')
with zipfile.ZipFile(ROOT / 'dist/StayStudio-Windows.zip') as bundle:
    assert bundle.testzip() is None
    assert bundle.read('StayStudio/StayStudio.exe') == (ROOT / 'dist/StayStudio/StayStudio.exe').read_bytes()
    for name in ('app.js', 'index.html', 'style.css'):
        assert bundle.read('StayStudio/_internal/studio/web/' + name) == (ROOT / 'studio/web' / name).read_bytes()
print('ZIP integrity and updated executable verified')
