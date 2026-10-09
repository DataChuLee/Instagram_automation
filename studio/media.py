from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .models import CaptionStyle
from .paths import font_path

SIZE = (1080, 1920)


def crop_photo(path: Path, focus_x=0.5, focus_y=0.5) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert('RGB')
    width, height = image.size
    target_ratio = SIZE[0] / SIZE[1]
    if width / height > target_ratio:
        crop_width = height * target_ratio
        left = min(max(0, width * focus_x - crop_width / 2), width - crop_width)
        box = (left, 0, left + crop_width, height)
    else:
        crop_height = width / target_ratio
        top = min(max(0, height * focus_y - crop_height / 2), height - crop_height)
        box = (0, top, width, top + crop_height)
    return image.crop(box).resize(SIZE, Image.Resampling.LANCZOS)


def wrap_caption(text: str, font, width=940, outline=8) -> str:
    draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    lines, line = [], ''
    for char in text.strip():
        if char == '\n':
            lines.append(line)
            line = ''
        elif draw.textlength(line + char, font=font) + 2 * outline > width and line:
            split = line.rfind(' ')
            if split > len(line) / 2:
                lines.append(line[:split])
                line = line[split + 1:] + char
            else:
                lines.append(line)
                line = char.lstrip()
        else:
            line += char
    if line:
        lines.append(line)
    return '\n'.join(lines)


def caption_image(text: str, style: CaptionStyle | None = None) -> Image.Image:
    style = style or CaptionStyle()
    font = ImageFont.truetype(str(font_path()), style.font_size)
    text = wrap_caption(text, font, outline=style.outline)
    layer = Image.new('RGBA', SIZE)
    draw = ImageDraw.Draw(layer)
    center = style.center(*SIZE)
    kwargs = dict(font=font, anchor='mm', align='center', spacing=round(style.font_size * 0.12),
                  stroke_width=style.outline)
    bounds = draw.multiline_textbbox(center, text, **kwargs)
    if style.background_opacity:
        draw.rectangle(bounds, fill=(0, 0, 0, round(255 * style.background_opacity)))
    if style.shadow:
        shadow = Image.new('RGBA', SIZE)
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.multiline_text((center[0] + style.shadow, center[1] + style.shadow), text,
                                  fill='black', stroke_fill='black', **kwargs)
        layer.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(1)))
    ImageDraw.Draw(layer).multiline_text(center, text, fill=style.color, stroke_fill='black', **kwargs)
    return layer


def caption_segments(text: str, style: CaptionStyle) -> list[str]:
    font = ImageFont.truetype(str(font_path()), style.font_size)
    lines = wrap_caption(text, font, outline=style.outline).splitlines()
    return ['\n'.join(lines[i:i + 2]) for i in range(0, len(lines), 2)] or ['']


def preview_image(photo: Path, text: str, style: CaptionStyle, focus=(0.5, 0.5)):
    image = crop_photo(photo, *focus).convert('RGBA')
    image.alpha_composite(caption_image(text, style))
    return image.convert('RGB')


def allocate_frames(audio_seconds: float, motion_flags: list[bool], fps=30) -> list[int]:
    if not motion_flags:
        raise ValueError('사진이 없습니다.')
    total = max(math.ceil((audio_seconds + 0.25) * fps), len(motion_flags) * 9)
    # Motion gets more screen time while every uploaded photo remains visible.
    weights = [2 if moving else 1 for moving in motion_flags]
    remaining = total - len(weights) * 9
    weight_sum = sum(weights)
    raw = [remaining * weight / weight_sum for weight in weights]
    counts = [9 + math.floor(value) for value in raw]
    for index in sorted(range(len(raw)), key=lambda i: raw[i] % 1, reverse=True)[:total - sum(counts)]:
        counts[index] += 1
    return counts


def srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'
