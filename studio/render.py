from __future__ import annotations

import json
import re
import subprocess
import wave
import shutil
from pathlib import Path

from .media import allocate_frames, caption_image, caption_segments, crop_photo, cut_zoom, srt_time
from .assets import render_revision
from .models import MIN_MOTION_SIDE
from .paths import RESOURCES, job_path

# Drop leading silence and shrink every pause (mid-sentence and trailing) to 0.05s so speech runs back to back.
TIGHTEN = ('silenceremove=start_periods=1:start_threshold=-40dB:start_silence=0'
           ':stop_periods=-1:stop_duration=0.1:stop_threshold=-40dB:stop_silence=0.05')


def ffmpeg():
    path = RESOURCES / 'tools/ffmpeg.exe'
    if path.exists():
        return str(path)
    installed = list((RESOURCES / '.tools/python/imageio_ffmpeg/binaries').glob('ffmpeg*.exe'))
    if installed:
        return str(installed[0])
    import sys
    if str(RESOURCES / '.tools/python') not in sys.path:
        sys.path.insert(0, str(RESOURCES / '.tools/python'))
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(*args):
    process = subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)],
        capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if process.returncode:
        raise RuntimeError(process.stderr.decode('utf-8', 'replace')[-2000:])


def video_size(path):
    process = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path)], capture_output=True,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    text = process.stderr.decode('utf-8', 'replace')
    match = re.search(r'Video:.*?\b(\d{2,5})x(\d{2,5})\b', text)
    if not match:
        raise RuntimeError('영상 해상도를 읽을 수 없습니다.')
    return tuple(map(int, match.groups()))


def shot_bounds(path, shots):
    """(start, end) seconds of each hard-cut shot in a clip, placing cuts at the strongest scene changes."""
    process = subprocess.run([ffmpeg(), '-hide_banner', '-i', str(path), '-an', '-vf',
        "select='gte(scene,0)',metadata=print:key=lavfi.scene_score", '-f', 'null', '-'],
        capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    text = process.stderr.decode('utf-8', 'replace')
    match = re.search(r'Duration: (\d+):(\d+):([\d.]+)', text)
    duration = int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3]) if match else 4.0
    times = [float(t) for t in re.findall(r'pts_time:([\d.]+)', text)]
    scores = [float(s) for s in re.findall(r'lavfi\.scene_score=([\d.]+)', text)]
    cuts = []
    for time, score in sorted(zip(times, scores), key=lambda pair: pair[1], reverse=True):
        if len(cuts) == shots - 1 or score < 0.2:
            break
        if 0.3 < time < duration - 0.3 and all(abs(time - cut) > 0.35 for cut in cuts):
            cuts.append(time)
    if len(cuts) != shots - 1:  # The model merged or skipped a shot: fall back to equal parts.
        cuts = [duration * index / shots for index in range(1, shots)]
    edges = [0.0, *sorted(cuts), duration]
    return list(zip(edges, edges[1:]))


def verify(path, decode=True):
    if video_size(path) != (1080, 1920):
        raise RuntimeError('출력 영상이 1080×1920이 아닙니다.')
    if decode:
        run('-i', path, '-f', 'null', '-')


def render(job, progress=lambda message: None, preview=False):
    if not job.storyboard:
        raise ValueError('대본이 없습니다.')
    folder = job_path(job.id)
    for motion in job.storyboard.motion:
        asset = job.generated.get(str(motion.photo), {}).get('file')
        if not asset or not (folder / asset).is_file():
            raise RuntimeError('선택한 움직임 영상이 아직 없습니다. 생성 작업을 먼저 완료해 주세요.')
    export = folder / 'render'
    export.mkdir(exist_ok=True)
    clips, clean_clips, audio_clips, subtitles, timeline = [], [], [], [], []
    offset = 0
    focus = {item.photo: (item.x, item.y) for item in job.storyboard.crop_focus}
    shots = {}  # photo -> (clip file, start, end): each photo plays its own shot of a multi-photo clip.
    for motion in job.storyboard.motion:
        source = folder / job.generated[str(motion.photo)]['file']
        if min(video_size(source)) < MIN_MOTION_SIDE:
            raise RuntimeError(f'생성 영상이 {MIN_MOTION_SIDE}p보다 작아 1080×1920 영상에 사용할 수 없습니다.')
        for photo, (start, end) in zip(motion.photos, shot_bounds(source, len(motion.photos))):
            shots[photo] = (source, start, end)
    for scene_index, scene in enumerate(job.storyboard.scenes):
        record = job.narration.get(str(scene_index), {})
        audio = folder / record.get('file', '__missing__')
        if not audio.is_file():
            raise RuntimeError(f'{scene_index + 1}번 장면의 음성이 필요합니다.')
        adjusted = export / f'audio-{scene_index:03}.wav'
        run('-i', audio, '-af', f'{TIGHTEN},atempo={job.options.speed},loudnorm=I=-16:TP=-1.5:LRA=11',
            '-ar', '48000', '-ac', '2', adjusted)
        with wave.open(str(adjusted)) as source:
            seconds = source.getnframes() / source.getframerate()
        moving = [index in shots for index in scene.photos]
        counts = allocate_frames(seconds, moving)
        scene_duration = sum(counts) / 30
        segments = caption_segments(scene.text, job.options.caption)
        scene_start = offset
        caption_paths = []
        weights = [max(len(text), 1) for text in segments]
        boundary = 0
        for part, text in enumerate(segments):
            caption = export / f'caption-{scene_index:03}-{part:03}.png'
            caption_image(text, job.options.caption).save(caption)
            start = scene_duration * boundary / sum(weights)
            boundary += weights[part]
            end = scene_duration * boundary / sum(weights)
            caption_paths.append((caption, start, end))
            subtitles.append(f'{len(subtitles)+1}\n{srt_time(offset+start)} --> {srt_time(offset+end)}\n{text}\n')
        padded = export / f'padded-{scene_index:03}.wav'
        run('-i', adjusted, '-af', 'apad', '-t', scene_duration, padded)
        audio_clips.append(padded)
        for photo_index, count, is_moving in zip(scene.photos, counts, moving):
            progress(f'{photo_index + 1}/{len(job.photos)} 사진을 1080p로 합성 중입니다.')
            clip = export / f'clip-{len(clips):03}.mp4'
            clean_clip = export / f'clean-{len(clips):03}.mp4'
            if is_moving:
                source, start, end = shots[photo_index]
                inputs = ['-i', source]
                # Stretch or trim the photo's shot to its slot (at most 2x slow motion, then hold the last frame),
                # upscale 720p-class clips to 1080×1920 and split long shots into punch-in cuts.
                speed = min(max(count / 30 / max(end - start, 0.1), 0.5), 2.0)
                base = (f'trim=start={start:.3f}:end={end:.3f},setpts=(PTS-STARTPTS)*{speed:.4f},'
                        f'scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,crop=1080:1920,fps=30,'
                        f'tpad=stop_mode=clone:stop_duration={count/30+1},'
                        f"zoompan=z='{cut_zoom(count)}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,setsar=1")
            else:
                source = export / f'photo-{photo_index:03}.jpg'
                crop_photo(folder / job.photos[photo_index]['file'], *focus.get(photo_index, (0.5, 0.5))).save(source, quality=96)
                inputs = ['-loop', '1', '-framerate', '30', '-i', source]
                # Render at 2x before zoom to avoid fractional-pixel jitter.
                base = f"scale=2160:3840,zoompan=z='1+0.035*on/{max(count-1,1)}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,setsar=1"
            encoding = ['-an', '-frames:v', count, '-r', '30', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'fast',
                        '-threads', '2', '-movflags', '+faststart']
            filters = [f'[0:v]{base},split=2[clean][base]']
            current = 'base'
            for part, (caption, start, end) in enumerate(caption_paths):
                inputs += ['-loop', '1', '-i', caption]
                local_start, local_end = start - (offset - scene_start), end - (offset - scene_start)
                output = f'cap{part}'
                filters.append(f"[{current}][{part+1}:v]overlay=0:0:format=auto:enable='gte(t,{local_start})*lt(t,{local_end})'[{output}]")
                current = output
            filters.append(f'[{current}]format=yuv420p[v]')
            run(*inputs, '-filter_complex', ';'.join(filters),
                '-map', '[clean]', *encoding, clean_clip, '-map', '[v]', *encoding, clip)
            clips.append(clip)
            clean_clips.append(clean_clip)
            timeline.append({'photo': photo_index, 'start': offset, 'frames': count, 'motion': is_moving})
            offset += count / 30
    video_list = export / 'video-list.txt'
    audio_list = export / 'audio-list.txt'
    clean_list = export / 'clean-list.txt'
    video_list.write_text(''.join(f"file '{p.name}'\n" for p in clips), encoding='utf-8')
    audio_list.write_text(''.join(f"file '{p.name}'\n" for p in audio_clips), encoding='utf-8')
    clean_list.write_text(''.join(f"file '{p.name}'\n" for p in clean_clips), encoding='utf-8')
    narration = export / 'narration.wav'
    run('-f', 'concat', '-safe', '0', '-i', audio_list, '-c:a', 'pcm_s16le', narration)
    publish = export / 'publish'
    publish.mkdir(exist_ok=True)
    result = folder / 'stay-reel.mp4'
    pending = publish / 'stay-reel.mp4'
    clean_pending = publish / 'stay-video.mp4'
    voice_pending = publish / 'stay-voice.mp3'
    run('-f', 'concat', '-safe', '0', '-i', clean_list, '-an', '-c:v', 'copy',
        '-movflags', '+faststart', '-t', offset, clean_pending)
    run('-i', narration, '-c:a', 'libmp3lame', '-q:a', '2', '-t', offset, voice_pending)
    run('-f', 'concat', '-safe', '0', '-i', video_list, '-i', narration, '-c:v', 'copy',
        '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-t', offset, pending)
    progress('최종 영상 전체를 디코딩하여 검사하고 있습니다.')
    verify(pending)
    verify(clean_pending)
    run('-i', voice_pending, '-f', 'null', '-')
    (publish / 'stay-reel.srt').write_text('\n'.join(subtitles), encoding='utf-8')
    (publish / 'stay-script.txt').write_text('\n\n'.join(scene.text for scene in job.storyboard.scenes) + '\n', encoding='utf-8-sig')
    run('-i', pending, '-frames:v', '1', publish / 'preview.jpg')
    report = {'width': 1080, 'height': 1920, 'fps': 30, 'duration': offset,
              'frames': sum(item['frames'] for item in timeline), 'photos': len(timeline),
              'timeline': timeline, 'caption': job.options.caption.model_dump(), 'fully_decoded': True,
              'exports': {'final': 'stay-reel.mp4', 'video': 'stay-video.mp4', 'audio': 'stay-voice.mp3',
                          'script': 'stay-script.txt', 'srt': 'stay-reel.srt'}}
    (publish / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    # All deliverables are prepared before making the new set available.
    prefix = f'preview-{render_revision(job)}-' if preview else ''
    for name in ('stay-reel.mp4', 'stay-video.mp4', 'stay-voice.mp3', 'stay-reel.srt',
                 'stay-script.txt', 'preview.jpg', 'verification.json'):
        (publish / name).replace(folder / (prefix + name))
    warnings = []
    if not 25 <= offset <= 35:
        warnings.append(f'실제 길이가 {offset:.1f}초입니다. 권장 길이는 25~35초입니다.')
    if offset / len(timeline) < 1.5:
        warnings.append('사진당 평균 노출이 1.5초보다 짧습니다. 사진 수를 줄여 보세요.')
    if timeline[-1]['frames'] < 30:
        warnings.append('마지막 사진의 노출이 1초보다 짧습니다.')
    return {'file': prefix + result.name, 'video': prefix + 'stay-video.mp4', 'audio': prefix + 'stay-voice.mp3',
            'script': prefix + 'stay-script.txt', 'srt': prefix + 'stay-reel.srt', 'verification': prefix + 'verification.json',
            'duration': offset, 'frames': report['frames'], 'warnings': warnings}


def publish_preview(job):
    folder = job_path(job.id)
    names = {'file': 'stay-reel.mp4', 'video': 'stay-video.mp4', 'audio': 'stay-voice.mp3',
             'script': 'stay-script.txt', 'srt': 'stay-reel.srt', 'verification': 'verification.json'}
    for key in names:
        if not (folder / job.preview[key]).is_file():
            raise ValueError('미리보기 파일이 없습니다. 미리보기를 다시 만들어 주세요.')
    for key, name in names.items():
        pending = folder / (name + '.pending')
        shutil.copyfile(folder / job.preview[key], pending)
        pending.replace(folder / name)
    return {**job.preview, **names}
