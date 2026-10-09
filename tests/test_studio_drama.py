import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from studio.drama import Drama
from studio.models import DRAMA_MODEL, VOICE_ID


class DramaMCPTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fish = AsyncMock()
        self.drama = Drama(self.fish)
        self.record = {'project_id': 'project', 'block': 'block', 'rev': 'rev',
                       'model': DRAMA_MODEL, 'voice': VOICE_ID, 'text': '숙소'}
        self.block = {'anchor': 'block', 'rev': 'rev', 'text': '숙소',
                      'voice': '일반여성2', 'dirty': True}
        self.calls = []

    async def respond(self, name, args):
        self.calls.append((name, args))
        if name == 'studio_project':
            return {'default_backend': DRAMA_MODEL, 'roster': [
                {'name': '일반여성2', 'voice_id': VOICE_ID}],
                'chapters': [{'anchor': 'chapter'}]}
        if name == 'studio_read_blocks':
            return {'blocks': [dict(self.block)]}
        if name == 'studio_generate':
            if args.get('dry_run'):
                return {'estimated_credits': 6, 'balance': 100}
            self.block.update(dirty=False, audio_url='https://fish.audio/audio.mp3')
            return {}
        return {}

    async def test_quote_configures_drama_before_creating_spoken_block(self):
        inserted = False
        async def call(name, args):
            nonlocal inserted
            if name == 'studio_list_projects':
                return {'projects': [], 'has_next': False}
            if name == 'studio_create_project':
                return {'project_id': 'project'}
            if name == 'studio_read_blocks' and 'chapter' in args and not inserted:
                return {'blocks': [{'anchor': 'empty', 'text': ''}]}
            if name == 'studio_write_blocks':
                inserted = True
            return await self.respond(name, args)
        self.fish.call.side_effect = call
        saved = AsyncMock()
        quote = await self.drama.quote('숙소', 'unique-name', {}, saved)
        self.assertEqual(quote['credits'], 6)
        self.assertEqual(quote['block'], 'block')
        update = next(args for name, args in self.calls if name == 'studio_update_project')
        self.assertEqual(update['default_backend'], DRAMA_MODEL)
        self.assertEqual(update['scene_preset'], 'off')
        names = [name for name, _ in self.calls]
        self.assertLess(names.index('studio_update_project'), names.index('studio_write_blocks'))
        self.assertTrue(all(args.get('dry_run') for name, args in self.calls if name == 'studio_generate'))
        self.assertTrue(saved.await_count)

    async def test_generation_rechecks_quote_and_downloads_after_recording_url(self):
        self.fish.call.side_effect = self.respond
        events = []
        async def save(data):
            events.append(data['state'])
        async def download(url, path):
            self.assertEqual(events[-1], 'completed')
        self.fish.download.side_effect = download
        await self.drama.generate('숙소', 6, Path('voice.mp3'), save, self.record)
        self.assertEqual(events, ['submitted', 'completed'])
        paid = [args for name, args in self.calls if name == 'studio_generate' and not args.get('dry_run')]
        self.assertEqual(len(paid), 1)
        self.assertEqual(paid[0]['blocks'], ['block'])
        self.fish.download.assert_awaited_once()

    async def test_changed_price_blocks_paid_generation(self):
        self.fish.call.side_effect = self.respond
        with self.assertRaisesRegex(RuntimeError, '견적'):
            await self.drama.generate('숙소', 5, Path('voice.mp3'), AsyncMock(), self.record)
        self.assertFalse(any(name == 'studio_generate' and not args.get('dry_run') for name, args in self.calls))

    async def test_content_change_blocks_generation(self):
        self.fish.call.side_effect = self.respond
        self.block['rev'] = 'changed'
        with self.assertRaisesRegex(RuntimeError, '변경'):
            await self.drama.generate('숙소', 6, Path('voice.mp3'), AsyncMock(), self.record)
        self.assertFalse(any(name == 'studio_generate' for name, _ in self.calls))

    async def test_resume_reads_existing_audio_without_generation(self):
        self.fish.call.side_effect = self.respond
        self.block.update(dirty=False, audio_url='https://fish.audio/audio.mp3')
        await self.drama.recover(self.record, Path('voice.mp3'), AsyncMock())
        self.assertFalse(any(name == 'studio_generate' for name, _ in self.calls))
        self.fish.download.assert_awaited_once()

    async def test_quote_reuses_saved_block(self):
        self.fish.call.side_effect = self.respond
        quote = await self.drama.quote('숙소', 'unique-name', self.record, AsyncMock())
        self.assertEqual(quote['credits'], 6)
        self.assertFalse(any(name in {'studio_create_project', 'studio_write_blocks'} for name, _ in self.calls))

    async def test_wrong_model_blocks_generation(self):
        async def call(name, args):
            result = await self.respond(name, args)
            if name == 'studio_project':
                result['default_backend'] = 's2-pro'
            return result
        self.fish.call.side_effect = call
        with self.assertRaisesRegex(RuntimeError, '모델 설정'):
            await self.drama.generate('숙소', 6, Path('voice.mp3'), AsyncMock(), self.record)
        self.assertFalse(any(name == 'studio_generate' for name, _ in self.calls))

    async def test_timeout_recovery_never_repeats_paid_call(self):
        self.fish.call.side_effect = self.respond
        async def save(data):
            self.record.update(data)
        async def fail(name, args):
            if name == 'studio_generate' and not args.get('dry_run'):
                raise TimeoutError('lost response')
            return await self.respond(name, args)
        self.fish.call.side_effect = fail
        with self.assertRaises(TimeoutError):
            await self.drama.generate('숙소', 6, Path('voice.mp3'), save, self.record)
        self.assertEqual(self.record['state'], 'submitted')
        self.calls.clear()
        self.block.update(dirty=False, audio_url='https://fish.audio/audio.mp3')
        await self.drama.recover(self.record, Path('voice.mp3'), save)
        self.assertFalse(any(name == 'studio_generate' for name, _ in self.calls))
