"""Drama3 narration through the app's existing Fish OAuth/MCP connection."""
from __future__ import annotations

import asyncio

from .models import DRAMA_MODEL, VOICE_ID


class Drama:
    def __init__(self, fish):
        self.fish = fish
        self.lock = asyncio.Lock()
        self.help_loaded = False

    async def help(self):
        if not self.help_loaded:
            await self.fish.call('studio_help', {'topic': 'quickstart'})
            self.help_loaded = True

    async def project_for(self, name):
        # Recover a free create whose response was lost instead of duplicating it.
        page = 1
        while True:
            value = await self.fish.call('studio_list_projects', {'page': page, 'page_size': 100})
            matches = [p for p in value['projects'] if p['name'] == name]
            if len(matches) > 1:
                raise RuntimeError('동일한 음성 프로젝트가 여러 개 있습니다. Story Studio에서 확인해 주세요.')
            if matches:
                return matches[0]['project_id']
            if not value.get('has_next'):
                break
            page += 1
        value = await self.fish.call('studio_create_project', {
            'name': name, 'default_voice_id': VOICE_ID,
            'roster': [{'name': '일반여성2', 'voice_id': VOICE_ID}]})
        return value['project_id']

    async def read(self, request):
        project = await self.fish.call('studio_project', {'project_id': request['project_id']})
        if project.get('default_backend') != DRAMA_MODEL:
            raise RuntimeError('Story Studio의 Drama3 모델 설정이 변경되었습니다. 견적을 다시 확인해 주세요.')
        value = await self.fish.call('studio_read_blocks', {
            'project_id': request['project_id'], 'blocks': [request['block']], 'include_audio': True})
        blocks = value.get('blocks', [])
        if len(blocks) != 1:
            raise RuntimeError('Story Studio 음성 블록을 찾지 못했습니다.')
        block = blocks[0]
        roster = {p['name']: p['voice_id'] for p in project.get('roster', [])}
        voice = roster.get(block.get('voice'), block.get('voice'))
        if (block.get('text') != request['text'] or block.get('rev') != request['rev']
                or voice != VOICE_ID):
            raise RuntimeError('Story Studio 대본 또는 목소리가 변경되었습니다. 견적을 다시 확인해 주세요.')
        return block

    async def quote(self, text, name, record, saved):
        async with self.lock:
            await self.help()
            request = dict(record)
            if not request.get('project_id'):
                request['project_id'] = await self.project_for(name)
                await saved({'project_id': request['project_id'], 'provider': 'fish_mcp'})
            if not request.get('block'):
                # Defaults apply only to NEW blocks; configure before appending text.
                await self.fish.call('studio_update_project', {
                    'project_id': request['project_id'], 'default_backend': DRAMA_MODEL,
                    'default_voice_id': VOICE_ID, 'scene_preset': 'off'})
                project = await self.fish.call('studio_project', {'project_id': request['project_id']})
                if project.get('default_backend') != DRAMA_MODEL:
                    raise RuntimeError('Fish MCP에서 Drama3 설정을 확인하지 못했습니다.')
                chapter = project['chapters'][0]['anchor']
                value = await self.fish.call('studio_read_blocks', {
                    'project_id': request['project_id'], 'chapter': chapter})
                blocks = [b for b in value['blocks'] if b.get('text')]
                if not blocks:
                    await self.fish.call('studio_write_blocks', {
                        'project_id': request['project_id'],
                        'ops': [{'append_to': chapter, 'text': text, 'voice': VOICE_ID}]})
                    value = await self.fish.call('studio_read_blocks', {
                        'project_id': request['project_id'], 'chapter': chapter})
                    blocks = [b for b in value['blocks'] if b.get('text')]
                if len(blocks) != 1 or blocks[0]['text'] != text:
                    raise RuntimeError('Story Studio 대본이 변경되었습니다. 새 견적을 확인해 주세요.')
                request.update(block=blocks[0]['anchor'], rev=blocks[0]['rev'],
                               model=DRAMA_MODEL, voice=VOICE_ID, text=text, provider='fish_mcp')
                await saved(request)
            await self.read(request)
            value = await self.fish.call('studio_generate', {
                'project_id': request['project_id'], 'blocks': [request['block']], 'dry_run': True})
            credits = value.get('estimated_credits')
            if type(credits) is not int or credits < 0:
                raise RuntimeError('Drama3 크레딧 견적을 확인하지 못했습니다.')
            return {**request, 'credits': credits, 'balance': value.get('balance')}

    async def collect(self, request, path, saved):
        # Poll read-only verbs; an uncertain paid submission is never repeated.
        for attempt in range(120):
            block = await self.read(request)
            url = block.get('audio_url')
            if url and not block.get('dirty', True):
                await saved({**request, 'state': 'completed', 'url': url})
                await self.fish.download(url, path)
                return
            if attempt < 119:
                await asyncio.sleep(3)
        raise RuntimeError('Drama3 결과 대기 시간이 초과되었습니다. 이어서 진행하면 같은 MCP 블록을 조회합니다. 자동 재생성하지 않습니다.')

    async def recover(self, request, path, saved):
        async with self.lock:
            await self.help()
            await self.collect(request, path, saved)

    async def generate(self, text, expected_credits, path, saved, request):
        async with self.lock:
            await self.help()
            if request.get('text') != text or request.get('model') != DRAMA_MODEL or request.get('voice') != VOICE_ID:
                raise RuntimeError('Drama3 MCP 견적을 다시 받아 주세요.')
            block = await self.read(request)
            if not (block.get('audio_url') and not block.get('dirty', True)):
                value = await self.fish.call('studio_generate', {
                    'project_id': request['project_id'], 'blocks': [request['block']], 'dry_run': True})
                if value.get('estimated_credits') != expected_credits:
                    raise RuntimeError('Drama3 크레딧 견적이 바뀌었습니다. 다시 승인해 주세요.')
                await saved({**request, 'state': 'submitted'})
                await self.fish.call('studio_generate', {
                    'project_id': request['project_id'], 'blocks': [request['block']], 'only_dirty': True})
            await self.collect(request, path, saved)
