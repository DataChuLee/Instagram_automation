import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class PerformanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_stages_and_thread_keep_run_identity(self):
        from studio import performance
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with performance.run(folder, 'generate'):
                async def branch(name):
                    with performance.span(name):
                        await asyncio.to_thread(lambda: self.thread_span(performance))
                        await asyncio.sleep(0.01)
                await asyncio.gather(branch('motion'), branch('voice'))
            rows = [json.loads(line) for line in (folder / 'performance.jsonl').read_text().splitlines()]
            self.assertEqual(len({row['run_id'] for row in rows}), 1)
            root = next(row for row in rows if row['stage'] == 'generate')
            children = [row for row in rows if row['stage'] in ('motion', 'voice')]
            self.assertTrue(all(row['parent_id'] == root['span_id'] for row in children))
            self.assertTrue(all(row['status'] == 'ok' and row['seconds'] >= 0 for row in rows))
            self.assertGreater(sum(row['seconds'] for row in children), root['seconds'])

    def thread_span(self, performance):
        with performance.span('thread.work'):
            pass

    async def test_failure_and_cancel_are_recorded_without_swallowing(self):
        from studio import performance
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with self.assertRaises(asyncio.CancelledError):
                with performance.run(folder, 'generate'):
                    await performance.wait('voice.generate', self.cancel())
            rows = [json.loads(line) for line in (folder / 'performance.jsonl').read_text().splitlines()]
            self.assertEqual([row['status'] for row in rows], ['cancelled', 'cancelled'])
            with self.assertRaisesRegex(ValueError, 'private'):
                with performance.run(folder, 'quote'):
                    raise ValueError('private token must not be logged')
            last = json.loads((folder / 'performance.jsonl').read_text().splitlines()[-1])
            self.assertEqual(last['status'], 'error')
            self.assertNotIn('private', json.dumps(last))

    async def cancel(self):
        raise asyncio.CancelledError()

    async def test_logging_failure_does_not_break_generation(self):
        from studio import performance
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, 'open', side_effect=OSError('disk full')):
                with performance.run(Path(directory), 'generate'):
                    result = await performance.wait('voice.generate', asyncio.sleep(0, result='finished'))
            self.assertEqual(result, 'finished')

    async def test_report_keeps_retries_separate_and_tolerates_partial_tail(self):
        from studio import performance
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.assertEqual(performance.report(folder)['runs'], [])
            for _ in range(2):
                with performance.run(folder, 'generate'):
                    await performance.wait('voice.generate', asyncio.sleep(0))
            with (folder / 'performance.jsonl').open('a', encoding='utf-8') as output:
                output.write('{"incomplete":')
            report = performance.report(folder)
            self.assertEqual(len(report['runs']), 2)
            self.assertNotEqual(report['runs'][0]['run_id'], report['runs'][1]['run_id'])
            self.assertTrue(all(run['wall_seconds'] is not None and run['status'] == 'ok' for run in report['runs']))
