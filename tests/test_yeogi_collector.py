import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image


MODULE_PATH = Path(__file__).resolve().parents[1] / 'scripts/collect_yeogi_images.py'


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE_PATH.exists(), 'the standalone collector must exist')
        spec = importlib.util.spec_from_file_location('yeogi_collector', MODULE_PATH)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def png(self):
        buffer = io.BytesIO()
        Image.new('RGB', (12, 8), 'blue').save(buffer, format='PNG')
        return buffer.getvalue()

    def test_accepts_only_domestic_detail_links(self):
        self.assertEqual(self.m.normalize_url('https://www.yeogi.com/domestic-accommodations/9816?x=1#photos')[0], '9816')
        for url in ['https://evil.test/domestic-accommodations/9816',
                    'https://www.yeogi.com/overseas-accommodations/9816',
                    'https://www.yeogi.com/domestic-accommodations/../9816',
                    'https://www.yeogi.com@evil.test/domestic-accommodations/9816']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.m.normalize_url(url)

    def test_extracts_all_rooms_keeps_labels_and_excludes_reviews(self):
        shared = 'https://image.withstatic.com/shared.png'
        info = {'meta': {'name': '테스트 숙소', 'newImages': [{'title': '수영장', 'image': shared}],
                         'images': [{'image': 'outdated.jpg'}]},
                'rooms': [{'name': '오션뷰', 'newImages': [{'image': shared}, {'image': 'https://image.withstatic.com/room.jpg'}]},
                          {'name': '트윈', 'images': [{'image': 'https://image.withstatic.com/twin.jpg'}]}],
                'reviews': [{'image': 'https://image.withstatic.com/review.jpg'}]}
        name, photos = self.m.extract_photos({'props': {'pageProps': {'accommodationInfo': info}}})
        self.assertEqual(name, '테스트 숙소')
        self.assertEqual(len(photos), 3)
        self.assertEqual(photos[0]['labels'], [{'category': 'property', 'title': '수영장', 'room_name': None},
                                              {'category': 'room', 'title': None, 'room_name': '오션뷰'}])

    def test_structure_change_is_reported_instead_of_empty_success(self):
        for data in [{}, {'props': {'pageProps': {'accommodationInfo': {'meta': {}, 'rooms': []}}}}]:
            with self.assertRaises(ValueError):
                self.m.extract_photos(data)

    def test_page_failure_preserves_previous_records_and_continues_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / '9816'
            first.mkdir()
            self.m.write_json(first / 'manifest.json', {'images': [{'url': 'old', 'file': 'images/old.png'}]})
            context = Mock()
            photos = [{'url': 'https://image.withstatic.com/a.png', 'labels': []}]
            with patch.object(self.m, 'load_page', side_effect=[ValueError('HTTP 403'), ('다음 숙소', photos)]), \
                    patch.object(self.m, 'downloader', return_value=lambda url: self.png()):
                report = self.m.collect_batch(context, [('9816', 'https://www.yeogi.com/domestic-accommodations/9816'),
                                                         ('9817', 'https://www.yeogi.com/domestic-accommodations/9817')], root, 0)
            self.assertEqual([row['status'] for row in report['results']], ['failed', 'complete'])
            self.assertEqual(self.m.read_json(first / 'manifest.json')['images'][0]['url'], 'old')
            context.new_page.return_value.close.assert_called_once()

    def test_blocked_image_is_not_retried_and_transient_server_failure_is(self):
        context = Mock()
        blocked = Mock(status=403)
        context.request.get.return_value = blocked
        with patch.object(self.m.time, 'sleep'):
            with self.assertRaisesRegex(ValueError, '403'):
                self.m.downloader(context, 0)('https://image.withstatic.com/a.png')
        self.assertEqual(context.request.get.call_count, 1)
        context.request.get.reset_mock()
        server_error = Mock(status=503)
        success = Mock(status=200, headers={'content-type': 'image/png'})
        success.body.return_value = self.png()
        context.request.get.side_effect = [server_error, success]
        with patch.object(self.m.time, 'sleep'):
            content = self.m.downloader(context, 0)('https://image.withstatic.com/a.png')
        self.assertEqual(self.m.describe_image(content)['format'], 'PNG')
        self.assertEqual(context.request.get.call_count, 2)
        server_error.dispose.assert_called_once()
        success.dispose.assert_called_once()

    def test_manifest_recovers_from_temporary_windows_file_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'manifest.json'
            target.write_text('{"old": true}', encoding='utf-8')
            original_replace = Path.replace
            attempts = []
            def temporarily_locked(source, destination):
                attempts.append(source)
                if len(attempts) == 1:
                    raise PermissionError(13, 'file temporarily locked')
                return original_replace(source, destination)
            with patch.object(Path, 'replace', new=temporarily_locked), patch.object(self.m.time, 'sleep'):
                try:
                    self.m.write_json(target, {'new': True})
                except PermissionError:
                    self.fail('temporary Windows locks should be retried without losing the manifest')
            self.assertEqual(self.m.read_json(target), {'new': True})
            self.assertEqual(len(attempts), 2)

    def test_content_dedup_resume_corruption_and_partial_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            photos = [{'url': 'https://image.withstatic.com/a.jpg', 'labels': []},
                      {'url': 'https://image.withstatic.com/b.jpg', 'labels': []},
                      {'url': 'https://image.withstatic.com/bad.jpg', 'labels': []}]
            calls = []
            def fetch(url):
                calls.append(url)
                return b'not an image' if url.endswith('bad.jpg') else self.png()
            result = self.m.save_collection(root, 'https://www.yeogi.com/domestic-accommodations/9816', '숙소', photos, fetch)
            self.assertEqual(result['status'], 'partial')
            self.assertEqual(len(list((root / 'images').iterdir())), 1)
            self.assertEqual(len(result['images']), 2)
            self.assertTrue(result['images'][0]['file'].endswith('.png'))
            self.assertEqual(result['images'][0]['width'], 12)
            self.assertEqual(len(result['failures']), 1)
            calls.clear()
            self.m.save_collection(root, result['source_url'], '숙소', photos, fetch)
            self.assertEqual(calls, ['https://image.withstatic.com/bad.jpg'])
            (root / result['images'][0]['file']).write_bytes(b'corrupted')
            calls.clear()
            self.m.save_collection(root, result['source_url'], '숙소', photos, fetch)
            self.assertIn('https://image.withstatic.com/a.jpg', calls)
            self.assertEqual(len(list((root / 'images').iterdir())), 1)
            self.assertEqual(json.loads((root / 'manifest.json').read_text(encoding='utf-8'))['status'], 'partial')

    def test_no_urls_argument_prompts_and_passes_valid_links_to_collector(self):
        with tempfile.TemporaryDirectory() as folder:
            url = 'https://www.yeogi.com/domestic-accommodations/9816'
            with patch('builtins.input', side_effect=['bad link', url, url + '#photos', '']), \
                    patch('playwright.sync_api.sync_playwright'), \
                    patch.object(self.m, 'collect_batch', return_value={'results': [{'status': 'complete'}]}) as collect, \
                    patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
                try:
                    status = self.m.main(['--output', folder])
                except SystemExit:
                    self.fail('running without --urls must allow terminal input')
            self.assertEqual(status, 0)
            self.assertEqual(collect.call_args.args[1], [('9816', url)])
            self.assertEqual(self.m.read_json(Path(folder) / 'collection_report.json')['results'][0]['status'], 'complete')

    def test_empty_interactive_input_exits_without_starting_browser_or_writing_files(self):
        for response in ['', EOFError(), KeyboardInterrupt()]:
            with self.subTest(response=type(response).__name__), tempfile.TemporaryDirectory() as folder:
                with patch('builtins.input', side_effect=[response]), \
                        patch('playwright.sync_api.sync_playwright') as browser, \
                        patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO):
                    try:
                        status = self.m.main(['--output', folder])
                    except SystemExit:
                        self.fail('empty terminal input should exit cleanly')
                self.assertEqual(status, 130 if isinstance(response, KeyboardInterrupt) else 0)
                browser.assert_not_called()
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_file_input_still_runs_without_prompting(self):
        with tempfile.TemporaryDirectory() as folder:
            url = 'https://www.yeogi.com/domestic-accommodations/9816'
            input_file = Path(folder) / 'urls.txt'
            input_file.write_text(url + '\n', encoding='utf-8')
            with patch('builtins.input') as prompt, patch('playwright.sync_api.sync_playwright'), \
                    patch.object(self.m, 'collect_batch', return_value={'results': [{'status': 'complete'}]}) as collect, \
                    patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(self.m.main(['--urls', str(input_file), '--output', folder]), 0)
            prompt.assert_not_called()
            self.assertEqual(collect.call_args.args[1], [('9816', url)])


if __name__ == '__main__':
    unittest.main()
