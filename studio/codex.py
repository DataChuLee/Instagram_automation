from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path

from .models import Storyboard
from .paths import DATA, RESOURCES, initialize, job_path


def executable():
    runtime = RESOURCES / 'tools/codex-runtime/bin/codex.exe'
    if runtime.is_file():
        return str(runtime)
    bundled = RESOURCES / 'tools/codex.exe'
    if bundled.is_file():
        return str(bundled)
    root = Path(os.environ.get('APPDATA', '')) / 'npm/node_modules/@openai/codex/node_modules'
    matches = list(root.glob('@openai/codex-win32-*/vendor/*/bin/codex.exe'))
    matches += list(root.glob('@openai/codex-win32-*/vendor/*/codex/codex.exe'))
    if matches:
        return str(matches[0])
    found = shutil.which('codex.exe')
    if found:
        return found
    raise RuntimeError('Codex 실행 파일이 없습니다. 배포 폴더를 확인해 주세요.')


def environment():
    env = os.environ.copy()
    initialize()
    codex_home = DATA / 'auth/codex'
    codex_home.mkdir(parents=True, exist_ok=True)
    env['CODEX_HOME'] = str(codex_home)
    for key in list(env):
        if key.upper() in {'OPENAI_API_KEY', 'AZURE_OPENAI_API_KEY', 'FISH_AUDIO_API_KEY'}:
            env.pop(key)
    return env


async def login_status():
    process = await asyncio.create_subprocess_exec(executable(), 'login', 'status',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment())
    stdout, stderr = await process.communicate()
    message = (stdout + stderr).decode('utf-8', 'replace')
    return process.returncode == 0 and 'ChatGPT' in message


async def login():
    process = await asyncio.create_subprocess_exec(executable(), 'login',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=environment())
    return process


async def analyze(job):
    if not await login_status():
        raise RuntimeError('설정에서 ChatGPT 구독 계정으로 Codex에 로그인해 주세요.')
    folder = job_path(job.id)
    schema = folder / 'schema.json'
    schema.write_text(json.dumps(strict_schema(Storyboard.model_json_schema()), ensure_ascii=False), encoding='utf-8')
    output = folder / 'analysis.json'
    args = [executable(), 'exec', '--sandbox', 'read-only', '--skip-git-repo-check',
            '--ephemeral', '--ignore-user-config', '--ignore-rules', '-C', str(folder),
            '--output-schema', str(schema), '-o', str(output)]
    for photo in job.photos:
        args += ['-i', str(folder / photo['file'])]
    prompt = f'''첨부된 숙소 사진 {len(job.photos)}장을 순서대로 0부터 번호 매겨 분석하세요.
모든 사진을 정확히 한 번 사용하여 25~35초 한국어 숙소 소개 쇼츠 대본을 만드세요.
사진에서 확인되는 사실만 말하고 위치, 가격, 상호, 시설을 추측하지 마세요.
장면당 1~3장의 사진과 짧은 자연스러운 한국어 문장을 넣으세요.
움직임이 유용한 사진만 최대 {job.options.max_motion}장 고르세요. 적합한 사진이 없으면 motion은 빈 목록.
수영장 물결이나 사람의 작은 자연스러운 동작에 한정하고 건물, 얼굴, 가구를 바꾸지 마세요.
motion.prompt는 보존해야 할 원본 요소와 작고 자연스러운 동작을 명확히 영어로 적으세요.
각 사진의 중요한 피사체가 중앙 9:16 크롭에 남도록 crop_focus에 x,y 0~1 좌표를 주세요.
파일을 수정하거나 도구를 사용하지 말고 지정 JSON 스키마 결과만 반환하세요.'''
    args += ['-']
    process = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment())
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(prompt.encode('utf-8')), 600)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise RuntimeError('사진 분석 시간이 초과되었습니다. 다시 시도해 주세요.')
    if process.returncode or not output.is_file():
        raise RuntimeError('Codex 사진 분석에 실패했습니다. 계정 로그인과 구독 사용 한도를 확인해 주세요.')
    return Storyboard.validate_plan(json.loads(output.read_text(encoding='utf-8')),
                                   len(job.photos), job.options.max_motion)


def strict_schema(value):
    if isinstance(value, dict):
        result = {key: strict_schema(item) for key, item in value.items() if key != 'default'}
        if result.get('type') == 'object':
            result['additionalProperties'] = False
            result['required'] = list(result.get('properties', {}))
        return result
    if isinstance(value, list):
        return [strict_schema(item) for item in value]
    return value
