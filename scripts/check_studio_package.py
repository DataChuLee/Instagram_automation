"""Verify source parity of the portable EXE/resources and absence of user data."""
from pathlib import Path, PurePosixPath
import sys
import types
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.tools/studio-python'))
from PyInstaller.archive.readers import CArchiveReader


def signature(code):
    if isinstance(code,types.CodeType):
        return (code.co_code,code.co_names,code.co_varnames,code.co_freevars,code.co_cellvars,
                tuple(signature(c) for c in code.co_consts))
    return code


folder=ROOT/'dist/StayStudio'
archive=CArchiveReader(str(folder/'StayStudio.exe'))
name=next(n for n in archive.toc if n.endswith('.pyz'))
modules=archive.open_embedded_archive(name)
for path in (ROOT/'studio').glob('*.py'):
    module='studio' if path.name=='__init__.py' else 'studio.'+path.stem
    bundled=modules.extract(module)
    current=compile(path.read_text(encoding='utf-8'),bundled.co_filename,'exec')
    assert signature(bundled)==signature(current),f'Outdated packaged module: {module}'
for subtree in ('studio/web','studio/skills'):
    for path in (ROOT/subtree).rglob('*'):
        if path.is_file():
            assert path.read_bytes()==(folder/'_internal'/path.relative_to(ROOT)).read_bytes(),path
assert (folder/'사용법.md').read_bytes()==(ROOT/'docs/친구-PC-사용법.md').read_bytes()
with zipfile.ZipFile(ROOT/'dist/StayStudio-Windows.zip') as package:
    names=package.namelist()
    for name in names:
        parts={p.lower() for p in PurePosixPath(name).parts}
        assert not parts.intersection({'.local','.env','auth.json','cookies.json','jobs','test_data','browser-profile'}),name
    assert any(n.endswith('studio/skills/stay-shortform/SKILL_TEXT.md') for n in names)
    assert any(n.endswith('studio/skills/stay-shortform/SKILL_MOTION.md') for n in names)
    assert any(n.endswith('studio/skills/stay-shortform/SKILL_ENHANCE.md') for n in names)
    assert any(n.endswith('studio/skills/stay-shortform/LICENSE') for n in names)
print('PASS: packaged Python modules/resources match current source; skill/license included; no stored jobs, photos, cookies or credentials in ZIP.')
