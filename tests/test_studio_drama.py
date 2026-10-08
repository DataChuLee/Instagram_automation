import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, Mock, patch

from studio.drama import Drama


class DramaLoginTests(unittest.IsolatedAsyncioTestCase):
    async def test_google_login_opens_regular_browser_without_automation(self):
        process = Mock()
        process.poll.return_value = None
        browser = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        drama = Drama()
        with patch('studio.drama.native_browser', return_value=browser), \
             patch('studio.drama.subprocess.Popen', return_value=process) as launch, \
             patch('studio.drama.async_playwright') as automate:
            await drama.open_login()
        automate.assert_not_called()
        args = launch.call_args.args[0]
        self.assertEqual(args[0], str(browser))
        self.assertTrue(any(arg.startswith('--user-data-dir=') and 'fish-manual' in arg for arg in args))
        self.assertFalse(any('automation' in arg or 'remote-debugging' in arg for arg in args))
        self.assertEqual(urlsplit(args[-1]).hostname, 'fish.audio')
        self.assertTrue(drama.login_open)

    async def test_generation_waits_until_manual_login_browser_closes(self):
        drama = Drama()
        drama.login_process = Mock()
        drama.login_process.poll.return_value = None
        with patch('studio.drama.async_playwright') as automate:
            with self.assertRaisesRegex(RuntimeError, '로그인 창을 닫'):
                await drama.open()
        automate.assert_not_called()

    async def test_login_editor_uses_working_google_origin_without_changing_drama_model(self):
        page = Mock()
        page.goto = AsyncMock()
        page.wait_for_timeout = AsyncMock()
        page.get_by_role.return_value.count = AsyncMock(return_value=0)
        context = SimpleNamespace(pages=[page])
        launch = AsyncMock(return_value=context)
        playwright = SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
        launcher = SimpleNamespace(start=AsyncMock(return_value=playwright))
        browser = Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
        with patch('studio.drama.async_playwright', return_value=launcher), \
             patch('studio.drama.native_browser', return_value=browser):
            opened = await Drama().open()
        self.assertIs(opened, page)
        target = urlsplit(page.goto.call_args.args[0])
        self.assertEqual(target.hostname, 'fish.audio')
        self.assertEqual(target.scheme, 'https')
        self.assertEqual(parse_qs(target.query)['version'], ['drama-3-preview'])
        self.assertEqual(launch.call_args.kwargs.get('locale'), 'en-US')
        self.assertEqual(launch.call_args.kwargs.get('executable_path'), str(browser))
        self.assertIn('fish-manual', launch.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
