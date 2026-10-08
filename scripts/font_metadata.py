from fontTools.ttLib import TTFont
from pathlib import Path
font = TTFont(Path(__file__).resolve().parents[1] / 'assets/fonts/Paperlogy-7Bold.ttf')
for identifier in (0, 13, 14):
    values = {name.toUnicode() for name in font['name'].names if name.nameID == identifier}
    print(identifier, '\n'.join(values))
