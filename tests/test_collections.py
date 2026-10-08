import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from studio import collector


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch('studio.paths.DATA', self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_recovery_and_restart_keep_saved_records_and_prevent_duplicate_workers(self):
        url = 'https://www.yeogi.com/domestic-accommodations/9816'
        collection_id, launch = collector.start(url)
        self.assertTrue(launch)
        manifest = collector.read(collection_id)
        manifest['images'] = [{'file': 'saved-photo.jpg'}]
        collector.save(collection_id, manifest)
        same_id, launch = collector.start(url)
        self.assertEqual(same_id, collection_id)
        self.assertFalse(launch)
        collector.recover()
        self.assertEqual(collector.read(collection_id)['status'], 'interrupted')
        same_id, launch = collector.start(url)
        self.assertEqual(same_id, collection_id)
        self.assertTrue(launch)
        self.assertEqual(collector.read(collection_id)['images'], [{'file': 'saved-photo.jpg'}])

    async def test_blocked_image_fails_without_retry_and_server_error_retries(self):
        response = AsyncMock()
        response.status = 403
        context = AsyncMock()
        context.request.get.return_value = response
        with patch('studio.collector.asyncio.sleep', new=AsyncMock()):
            with self.assertRaisesRegex(ValueError, '403'):
                await collector.fetch_image(context, 'https://image.withstatic.com/a.jpg')
        self.assertEqual(context.request.get.await_count, 1)
        failed = AsyncMock()
        failed.status = 503
        success = AsyncMock()
        success.status = 200
        success.headers = {'content-type': 'image/jpeg'}
        success.body.return_value = b'image bytes'
        context.request.get.side_effect = [failed, success]
        with patch('studio.collector.asyncio.sleep', new=AsyncMock()):
            result = await collector.fetch_image(context, 'https://image.withstatic.com/a.jpg')
        self.assertEqual(result, b'image bytes')

    async def test_cancelled_collection_is_persisted_as_interrupted(self):
        collection_id, _ = collector.start('https://www.yeogi.com/domestic-accommodations/9816')
        browser = AsyncMock()
        playwright = AsyncMock()
        playwright.chromium.executable_path = 'browser.exe'
        playwright.chromium.launch.return_value = browser
        context_manager = AsyncMock()
        context_manager.__aenter__.return_value = playwright
        with patch('studio.collector.async_playwright', return_value=context_manager), \
                patch('studio.collector.load_page', side_effect=asyncio.CancelledError):
            with self.assertRaises(asyncio.CancelledError):
                await collector.collect(collection_id)
        self.assertEqual(collector.read(collection_id)['status'], 'interrupted')
        browser.close.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
