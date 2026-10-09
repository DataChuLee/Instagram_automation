from __future__ import annotations

import asyncio
import hashlib
import uuid

from . import assets, codex, composition, recommendation, store
from .media import crop_photo
from .models import MOTION_PARAMETERS, VIDEO_MODEL, motion_fingerprint, stable_hash
from .paths import job_path
from .render import publish_preview, render, video_size


class Pipeline:
    def __init__(self, fish, drama):
        self.fish, self.drama = fish, drama
        self.tasks = {}

    def launch(self, job_id, operation, *args):
        if job_id in self.tasks and not self.tasks[job_id].done():
            raise ValueError('이 작업은 이미 실행 중입니다.')
        self.tasks[job_id] = asyncio.create_task(self.guarded(job_id, operation, *args))

    def busy(self, job_id):
        return job_id in self.tasks and not self.tasks[job_id].done()

    async def guarded(self, job_id, operation, *args):
        try:
            await operation(job_id, *args)
        except Exception as error:
            job = store.read(job_id)
            job.state = 'error'
            job.error = str(error) or type(error).__name__
            job.message = '작업을 중단했습니다. 저장된 결과는 유지됩니다.'
            store.save(job)

    def update(self, job, state, message):
        job.state, job.message, job.error = state, message, None
        store.save(job)

    async def analyze(self, job_id):
        job = store.read(job_id)
        if assets.pending(job):
            raise ValueError('제출한 생성 작업을 먼저 완료하거나 복구해 주세요.')
        if job.workflow_version < 2 and (job.generated or assets.voice_started(job)):
            raise ValueError('생성 결과가 있는 작업은 대본을 다시 분석할 수 없습니다. 새 작업을 만들어 주세요.')
        self.update(job, 'analyzing', 'Codex가 사진을 보고 대본과 움직임 장면을 고르고 있습니다.')
        assets.capture(job)
        assets.checkpoint(job)
        job.storyboard = await codex.analyze(job)
        assets.restore(job)
        assets.invalidate(job)
        self.update(job, 'uploaded', '대본을 준비했습니다. 자막을 조절하고 크레딧 견적을 확인해 주세요.')

    async def recommend(self, job_id):
        job = store.read(job_id)
        self.update(job, 'recommending', '전체 후보 사진을 평가하고 숙소 소개 구성을 추천합니다.')
        working = job.model_copy(deep=True)
        def progress(message):
            job.message = message
            store.save(job)
        selection = await recommendation.choose(working, progress)
        composition.select(working, selection['ids'])
        working.composition_mode = 'ai'
        working.storyboard = await codex.analyze(working)
        reasons = {r['id']: r['reason'] for r in selection['reasons']}
        working.storyboard.selection_reasons = {str(i): reasons.get(p['id'], '') for i, p in enumerate(working.photos)}
        assets.restore(working)
        self.update(working, 'uploaded', 'AI 추천 구성을 준비했습니다. 선정 이유와 대본을 확인해 주세요.')

    async def quote(self, job_id, workspace):
        job = store.read(job_id)
        if not job.storyboard:
            raise ValueError('사진 분석을 먼저 실행해 주세요.')
        self.update(job, 'quoting', '움직임과 Drama3 음성의 실제 크레딧 견적을 확인하고 있습니다.')
        job.approval = None
        store.save(job)
        if job.workflow_version >= 2:
            assets.capture(job)
            assets.restore(job)
        if job.storyboard.motion:
            model = await self.fish.call('get_media_model', {'model_id': VIDEO_MODEL})
            schema = model['capabilities']['i2v']['parameter_schema']['properties']
            if '1080p' not in schema['resolution']['enum'] or '9:16' not in schema['aspect_ratio']['enum']:
                raise RuntimeError('현재 Fish 모델이 1080p / 9:16 생성을 지원하지 않습니다.')
        folder = job_path(job.id)
        focus = {item.photo: (item.x, item.y) for item in job.storyboard.crop_focus}
        videos, voices = [], []
        for motion in job.storyboard.motion:
            index = str(motion.photo)
            saved = job.generated.get(index, {})
            if saved.get('idempotency_key') and saved.get('workspace') != workspace:
                raise RuntimeError('이미 제출한 생성 요청의 작업 공간은 바꿀 수 없습니다. 기존 작업 공간에서 재개해 주세요.')
            if saved.get('file') and (folder / saved['file']).exists():
                continue
            if saved.get('generation_id'):
                continue  # Already submitted: resume polling without purchasing it again.
            image = folder / f'motion-source-{motion.photo:03}.jpg'
            crop_photo(folder / job.photos[motion.photo]['file'], *focus.get(motion.photo, (0.5, 0.5))).save(image, quality=96)
            fingerprint = motion_fingerprint(hashlib.sha256(image.read_bytes()).hexdigest(), motion.prompt)
            if saved.get('fingerprint') != fingerprint or saved.get('workspace') != workspace:
                saved = {'fingerprint': fingerprint, 'workspace': workspace,
                         'asset_key': assets.cache_key(job, assets.motion_key(job, motion)),
                         'photo_sha': job.photos[motion.photo]['sha256'], 'prompt': motion.prompt,
                         'object_key': await self.fish.upload(image, workspace)}
                job.generated[index] = saved
                store.save(job)
            request = {'workspace_id': workspace, 'model_id': VIDEO_MODEL, 'operation': 'i2v',
                       'parameters': MOTION_PARAMETERS, 'prompt': motion.prompt,
                       'input_object_key': saved['object_key']}
            value = await self.fish.call('estimate_video_generation', request)
            if not value.get('can_generate'):
                raise RuntimeError('Fish 움직임 생성에 필요한 크레딧이 부족합니다.')
            videos.append({'photo': motion.photo, 'request': request, 'credits': value['credits'],
                           'pricing_version': value['pricing_version'], 'balance': value.get('balance')})
        for scene_index, scene in enumerate(job.storyboard.scenes):
            saved = job.narration.get(str(scene_index), {})
            if saved.get('file') and (folder / saved['file']).exists():
                continue
            if saved.get('state') == 'submitted' and not saved.get('url'):
                if saved.get('project_id') and saved.get('block'):
                    continue  # Recover the submitted MCP block without another purchase.
                raise RuntimeError('응답을 확인하지 못한 기존 브라우저 음성이 있습니다. Fish History 음성을 복구해 주세요.')
            if saved.get('url'):
                continue
            asset_key = assets.cache_key(job, assets.voice_key(job, scene))
            saved = job.narration.setdefault(str(scene_index), {})
            saved.update(asset_key=asset_key, text=scene.text)
            async def persist(data):
                saved.update(data)
                assets.capture(job)
                store.save(job)
            name = 'Stay Studio ' + job.id + ' ' + stable_hash(asset_key)
            voice_quote = await self.drama.quote(scene.text, name, saved, persist)
            voices.append({**voice_quote, 'scene': scene_index, 'asset_key': asset_key})
        assets.capture(job)
        total = sum(item['credits'] for item in videos + voices)
        balances = [item['balance'] for item in videos + voices if item.get('balance') is not None]
        if balances and total > min(balances):
            raise RuntimeError('영상과 음성 전체 견적이 남은 Fish 크레딧보다 큽니다.')
        job.quote = {'id': uuid.uuid4().hex, 'total': total, 'videos': videos, 'voices': voices,
                     'workspace': workspace, 'plan_hash': store.plan_hash(job)}
        self.update(job, 'awaiting_approval', '견적을 확인했습니다. 승인하면 Fish 크레딧을 사용해 생성합니다.')

    async def generate(self, job_id):
        job = store.read(job_id)
        store.generation_allowed(job)
        self.update(job, 'generating', '승인한 크레딧으로 움직임과 Drama3 음성을 만들고 있습니다.')
        folder = job_path(job.id)
        for item in job.quote['videos']:
            key = str(item['photo'])
            saved = job.generated[key]
            if saved.get('generation_id') or saved.get('file'):
                continue
            idempotency = saved.setdefault('idempotency_key', stable_hash({'job': job.id, 'asset': saved.get('asset_key', saved['fingerprint'])}))
            saved['state'] = 'submitting'
            store.save(job)
            value = await self.fish.call('generate_video', {**item['request'],
                'expected_credits': item['credits'], 'pricing_version': item['pricing_version'],
                'idempotency_key': idempotency})
            generation_id = value.get('generation_id') or value.get('generation', {}).get('generation_id')
            if not generation_id:
                raise RuntimeError('Fish 생성 ID를 확인하지 못했습니다. 저장한 동일 요청 키로만 재개할 수 있습니다.')
            saved.update(generation_id=generation_id, state='submitted')
            store.save(job)
        for motion in job.storyboard.motion:
            key = str(motion.photo)
            saved = job.generated[key]
            if saved.get('file') and (folder / saved['file']).exists():
                continue
            generation_id = saved.get('generation_id')
            if not generation_id:
                raise RuntimeError('움직임 생성 ID가 없습니다. 견적 단계로 돌아가 주세요.')
            for _ in range(120):
                value = await self.fish.call('get_generation_status', {'generation_id': generation_id})
                status = value.get('status')
                if status in {'failed', 'cancelled'}:
                    saved['state'] = status
                    assets.capture(job)
                    store.save(job)
                    raise RuntimeError('Fish 움직임 생성이 실패했습니다. 저장된 ID: ' + generation_id)
                if status in {'completed', 'succeeded', 'finished'}:
                    result = await self.fish.call('get_generation_result', {'generation_id': generation_id})
                    results = result.get('results', [])
                    media = result.get('media') or (results[0].get('media', results[0]) if results else {})
                    url = media.get('url')
                    if not url:
                        raise RuntimeError('완료된 Fish 결과의 다운로드 주소를 찾지 못했습니다.')
                    saved.update(url=url, state='completed')
                    store.save(job)
                    output = folder / (f"motion-{stable_hash(saved['asset_key'])}.mp4" if job.workflow_version >= 2 else f'motion-{motion.photo:03}.mp4')
                    await self.fish.download(url, output)
                    if await asyncio.to_thread(video_size, output) != (1080, 1920):
                        raise RuntimeError('Fish 결과가 1080×1920이 아닙니다. 이 결과를 고화질로 표시하지 않습니다.')
                    saved['file'] = output.name
                    store.save(job)
                    break
                await asyncio.sleep(min(max(value.get('poll_after_seconds', 60), 5), 60))
            else:
                raise RuntimeError('움직임 생성 대기 시간이 초과되었습니다. 저장된 ID로 재개할 수 있습니다.')
        for scene_index, scene in enumerate(job.storyboard.scenes):
            key = str(scene_index)
            saved = job.narration.setdefault(key, {})
            if saved.get('file') and (folder / saved['file']).exists():
                continue
            asset_key = assets.cache_key(job, assets.voice_key(job, scene))
            if job.workflow_version >= 2 and job.assets.get(asset_key, {}).get('file'):
                job.narration[key] = dict(job.assets[asset_key])
                continue
            saved['asset_key'] = asset_key
            saved['text'] = scene.text
            output = folder / (f'voice-{stable_hash(asset_key)}.mp3' if job.workflow_version >= 2 else f'voice-{scene_index:03}.mp3')
            async def submitted(data):
                saved.update(data)
                assets.capture(job)
                store.save(job)
            if saved.get('url'):
                await self.fish.download(saved['url'], output)
            elif saved.get('state') == 'submitted':
                if not saved.get('project_id') or not saved.get('block'):
                    raise RuntimeError('중단된 음성 생성은 자동 재요청하지 않습니다. Fish History 음성을 복구해 주세요.')
                await self.drama.recover(saved, output, submitted)
            else:
                item = next(item for item in job.quote['voices'] if item['scene'] == scene_index)
                await self.drama.generate(scene.text, item['credits'], output, submitted, item)
            saved['file'] = output.name
            assets.capture(job)
            store.save(job)
        assets.capture(job)
        store.save(job)
        if job.workflow_version >= 2:
            await self.preview(job_id)
        else:
            await self.render(job_id)

    async def preview(self, job_id):
        job = store.read(job_id)
        if not assets.ready(job, job_path(job.id)):
            raise ValueError('미리보기에 필요한 음성·움직임을 먼저 생성해 주세요.')
        revision = assets.render_revision(job)
        self.update(job, 'previewing', '음성·움직임·자막을 1080p 미리보기로 합성하고 있습니다.')
        def progress(message):
            job.message = message
            store.save(job)
        if not job.preview or job.preview.get('revision') != revision or not (job_path(job.id) / job.preview['file']).is_file():
            job.preview = await asyncio.to_thread(render, job, progress, True)
            job.preview['revision'] = revision
        self.update(job, 'preview_ready', '1080p 미리보기를 확인한 뒤 최종 영상을 내보내세요.')

    async def render(self, job_id):
        job = store.read(job_id)
        if job.workflow_version >= 2:
            if not job.preview or job.preview.get('revision') != assets.render_revision(job):
                raise ValueError('변경 내용을 반영한 미리보기를 먼저 만들어 주세요.')
            self.update(job, 'rendering', '확인한 미리보기를 최종 파일로 내보내고 있습니다.')
            job.result = await asyncio.to_thread(publish_preview, job)
            self.update(job, 'complete', '확인한 1080×1920 미리보기를 최종 영상으로 내보냈습니다.')
            return
        self.update(job, 'rendering', '저장된 영상과 음성을 합성하고 있습니다. 추가 크레딧을 사용하지 않습니다.')
        def progress(message):
            job.message = message
            store.save(job)
        job.result = await asyncio.to_thread(render, job, progress)
        self.update(job, 'complete', '1080×1920 영상이 완성되었습니다.')
