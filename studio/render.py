from __future__ import annotations

import json
import re
import subprocess
import wave
from pathlib import Path

from .media import allocate_frames, caption_image, crop_photo, srt_time
from .paths import RESOURCES, job_path


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


def verify(path, decode=True):
    if video_size(path) != (1080, 1920):
        raise RuntimeError('출력 영상이 1080×1920이 아닙니다.')
    if decode:
        run('-i', path, '-f', 'null', '-')


def render(job, progress=lambda message: None):
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
    for scene_index, scene in enumerate(job.storyboard.scenes):
        record = job.narration.get(str(scene_index), {})
        audio = folder / record.get('file', '__missing__')
        if not audio.is_file():
            raise RuntimeError(f'{scene_index + 1}번 장면의 음성이 필요합니다.')
        adjusted = export / f'audio-{scene_index:03}.wav'
        run('-i', audio, '-af', f'atempo={job.options.speed},loudnorm=I=-16:TP=-1.5:LRA=11',
            '-ar', '48000', '-ac', '2', adjusted)
        with wave.open(str(adjusted)) as source:
            seconds = source.getnframes() / source.getframerate()
        moving = [job.generated.get(str(index), {}).get('file') is not None for index in scene.photos]
        counts = allocate_frames(seconds, moving)
        caption = export / f'caption-{scene_index:03}.png'
        caption_image(scene.text, job.options.caption).save(caption)
        scene_duration = sum(counts) / 30
        padded = export / f'padded-{scene_index:03}.wav'
        run('-i', adjusted, '-af', 'apad', '-t', scene_duration, padded)
        audio_clips.append(padded)
        subtitles.append(f'{scene_index+1}\n{srt_time(offset)} --> {srt_time(offset+scene_duration)}\n{scene.text}\n')
        for photo_index, count, is_moving in zip(scene.photos, counts, moving):
            progress(f'{photo_index + 1}/{len(job.photos)} 사진을 1080p로 합성 중입니다.')
            clip = export / f'clip-{len(clips):03}.mp4'
            clean_clip = export / f'clean-{len(clips):03}.mp4'
            if is_moving:
                source = folder / job.generated[str(photo_index)]['file']
                if video_size(source) != (1080, 1920):
                    raise RuntimeError('생성 영상이 네이티브 1080×1920이 아닙니다. 저해상도 결과를 확대하지 않습니다.')
                inputs = ['-stream_loop', '-1', '-i', source]
                base = 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=1'
            else:
                source = export / f'photo-{photo_index:03}.jpg'
                crop_photo(folder / job.photos[photo_index]['file'], *focus.get(photo_index, (0.5, 0.5))).save(source, quality=96)
                inputs = ['-loop', '1', '-framerate', '30', '-i', source]
                # Render at 2x before zoom to avoid fractional-pixel jitter.
                base = f"scale=2160:3840,zoompan=z='1+0.035*on/{max(count-1,1)}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30,setsar=1"
            encoding = ['-an', '-frames:v', count, '-r', '30', '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-crf', '18', '-preset', 'fast',
                        '-threads', '2', '-movflags', '+faststart']
            run(*inputs, '-loop', '1', '-i', caption, '-filter_complex',
                f'[0:v]{base},split=2[clean][base];[base][1:v]overlay=0:0:format=auto,format=yuv420p[v]',
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
    for name in ('stay-reel.mp4', 'stay-video.mp4', 'stay-voice.mp3', 'stay-reel.srt',
                 'stay-script.txt', 'preview.jpg', 'verification.json'):
        (publish / name).replace(folder / name)
    return {'file': result.name, 'video': 'stay-video.mp4', 'audio': 'stay-voice.mp3',
            'script': 'stay-script.txt', 'srt': 'stay-reel.srt', 'verification': 'verification.json',
            'duration': offset, 'frames': report['frames']}
