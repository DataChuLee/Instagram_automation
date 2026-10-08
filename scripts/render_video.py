"""Render the saved storyboard and Fish audio; does not call paid services."""
import argparse
import json
import math
import subprocess
import sys
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.tools/python'))
SIZE = (1080, 1920)
FPS = 30


def scene_frames(audio_seconds, photo_count):
    return max(math.ceil((audio_seconds + 0.25) * FPS), photo_count * 27)


def split_frames(total, count):
    return [total // count + (i < total % count) for i in range(count)]


def srt_time(seconds):
    millis = round(seconds * 1000)
    hours, millis = divmod(millis, 3600000)
    minutes, millis = divmod(millis, 60000)
    secs, millis = divmod(millis, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{millis:03}'


def run(ffmpeg, *args):
    result = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)],
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))


def photo_canvas(path):
    with Image.open(path) as source:
        photo = ImageOps.exif_transpose(source).convert('RGB')
    ratio = photo.width / photo.height
    if ratio < 1.05:
        return ImageOps.fit(photo, SIZE, method=Image.Resampling.LANCZOS)
    background = ImageOps.fit(photo, SIZE, method=Image.Resampling.LANCZOS)
    background = ImageEnhance.Brightness(background.filter(ImageFilter.GaussianBlur(45))).enhance(0.55)
    foreground = ImageOps.contain(photo, (1080, 1500), method=Image.Resampling.LANCZOS)
    # Leave generous margins for the original landscape composition.
    background.paste(foreground, ((1080 - foreground.width) // 2, (1920 - foreground.height) // 2))
    return background


def caption_image(text):
    layer = Image.new('RGBA', SIZE)
    draw = ImageDraw.Draw(layer)
    size = 64
    font_path = 'C:/Windows/Fonts/malgunbd.ttf'
    while True:
        font = ImageFont.truetype(font_path, size)
        if draw.textbbox((0, 0), text, font=font, stroke_width=5)[2] <= 940 or size <= 42:
            break
        size -= 2
    draw.text((540, 930), text, font=font, fill='white', anchor='mm',
              stroke_width=5, stroke_fill='black')
    return layer


def main():
    import imageio_ffmpeg
    parser = argparse.ArgumentParser()
    parser.add_argument('--storyboard', default='output/storyboard.json')
    args = parser.parse_args()
    story_path = ROOT / args.storyboard
    story = json.loads(story_path.read_text(encoding='utf-8'))
    photos = sorted((ROOT / 'Data/Test_Data').glob('*.jpg'))
    for scene in story['scenes']:
        if not (ROOT / scene['audio']).is_file():
            raise FileNotFoundError(scene['audio'])
        for i in scene['images']:
            if i < 0 or i >= len(photos):
                raise ValueError(f'Invalid photo index: {i}')
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    output = ROOT / 'output'
    work = output / 'render'
    work.mkdir(exist_ok=True)
    clips, subtitles, previews = [], [], []
    timeline_samples = bytearray()
    total_frames = 0
    clip_index = 0
    for scene_index, scene in enumerate(story['scenes']):
        wav_path = work / f'audio_{scene_index:02}.wav'
        run(ffmpeg, '-i', ROOT / scene['audio'], '-af', 'atempo=0.75',
            '-ar', 48000, '-ac', 1, '-c:a', 'pcm_s16le', wav_path)
        with wave.open(str(wav_path)) as audio:
            pcm = audio.readframes(audio.getnframes())
            audio_duration = audio.getnframes() / audio.getframerate()
        frames = scene_frames(audio_duration, len(scene['images']))
        duration = frames / FPS
        start = total_frames / FPS
        scene.update(start=start, duration=duration, audio_duration=audio_duration)
        subtitles.append(f'{scene_index + 1}\n{srt_time(start)} --> {srt_time(start + audio_duration)}\n{scene["text"]}\n')
        padded_samples = int(frames * 48000 / FPS)
        timeline_samples.extend(pcm)
        timeline_samples.extend(b'\x00' * max(0, padded_samples * 2 - len(pcm)))
        caption = caption_image(scene['text'])
        cap_path = work / f'caption_{scene_index:02}.png'
        caption.save(cap_path)
        photo_frames = split_frames(frames, len(scene['images']))
        elapsed_scene_frames = 0
        for photo_index, count in zip(scene['images'], photo_frames):
            base = photo_canvas(photos[photo_index])
            base_path = work / f'photo_{clip_index:02}.png'
            base.save(base_path)
            if len(previews) < 10:
                preview = base.convert('RGBA')
                preview.alpha_composite(caption)
                previews.append(preview.convert('RGB'))
            clip_path = work / f'clip_{clip_index:02}.mp4'
            # Caption remains stationary while the photo slowly zooms.
            step = 0.035 / max(1, count - 1)
            visible = max(0, audio_duration - elapsed_scene_frames / FPS)
            filters = (
                f'[0:v]scale=2160:3840,zoompan=z=1+on*{step:.9f}:'
                f'x=iw/2-iw/zoom/2:y=ih/2-ih/zoom/2:d={count}:s=1080x1920:fps=30[v];'
                f"[v][1:v]overlay=0:0:enable='lt(t,{visible:.6f})',format=yuv420p[out]"
            )
            run(ffmpeg, '-i', base_path, '-loop', 1, '-i', cap_path,
                '-filter_complex', filters, '-map', '[out]', '-frames:v', count,
                '-c:v', 'libx264', '-preset', 'fast', '-crf', 19, '-threads', 2,
                '-an', clip_path)
            clips.append(clip_path)
            elapsed_scene_frames += count
            clip_index += 1
            print(f'Photo {clip_index}/{len(photos)} rendered ({count / FPS:.2f}s)', flush=True)
        total_frames += frames
    full_wav = output / 'narration.wav'
    with wave.open(str(full_wav), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(timeline_samples)
    concat_path = work / 'clips.txt'
    concat_path.write_text('\n'.join(f"file '{p.name}'" for p in clips), encoding='utf-8')
    run(ffmpeg, '-f', 'concat', '-safe', 0, '-i', concat_path, '-i', full_wav,
        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
        '-b:a', '192k', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-movflags', '+faststart',
        output / 'stay_reel.mp4')
    (output / 'stay_reel.srt').write_text('\n'.join(subtitles), encoding='utf-8')
    story.update(width=1080, height=1920, fps=30, duration=total_frames / FPS, audio_speed=0.75,
                 photos=[str(p.relative_to(ROOT)).replace('\\', '/') for p in photos])
    story_path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding='utf-8')
    sheet = Image.new('RGB', (1080, 1920), '#202020')
    for i, preview in enumerate(previews[:10]):
        thumb = preview.resize((216, 384), Image.Resampling.LANCZOS)
        sheet.paste(thumb, ((i % 5) * 216, (i // 5) * 960 + 250))
    sheet.save(output / 'preview.jpg', quality=92)
    print(f'Complete: {total_frames / FPS:.3f}s, {clip_index} photos', flush=True)


if __name__ == '__main__':
    main()
