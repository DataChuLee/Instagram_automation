import asyncio
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from mcp.types import CallToolResult, TextContent
from studio.fish import Fish


class FishTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_two_stream_transport_initializes_session(self):
        read, write = object(), object()
        initialized = AsyncMock()

        @asynccontextmanager
        async def client(**kwargs):
            yield object()

        @asynccontextmanager
        async def transport(*args, **kwargs):
            yield read, write

        @asynccontextmanager
        async def session(actual_read, actual_write):
            self.assertIs(actual_read, read)
            self.assertIs(actual_write, write)
            yield SimpleNamespace(initialize=initialized)

        with patch('studio.fish.OAuthClientProvider'), \
             patch('studio.fish.transport.httpx2.AsyncClient', client), \
             patch('studio.fish.transport.streamable_http_client', transport), \
             patch('studio.fish.ClientSession', session):
            async with Fish().session(interactive=True):
                initialized.assert_awaited_once()

    async def test_login_timeout_has_bounded_wait(self):
        fish = Fish()
        with self.assertRaisesRegex(RuntimeError, '로그인 요청'):
            await fish.wait_callback()


class FishResponseTests(unittest.IsolatedAsyncioTestCase):
    async def call_response(self, response):
        tool = AsyncMock(return_value=response)

        @asynccontextmanager
        async def session(interactive=False):
            yield SimpleNamespace(call_tool=tool)

        fish = Fish()
        fish.session = session
        return await fish.connect()

    async def test_installed_sdk_structured_workspaces_response(self):
        value = {'workspaces': [{'workspace_id': 'test', 'workspace_name': 'Test'}]}
        response = CallToolResult(content=[], structured_content=value)
        self.assertEqual(await self.call_response(response), value)

    async def test_installed_sdk_text_json_workspaces_response(self):
        response = CallToolResult(content=[TextContent(text='{"workspaces": []}')])
        self.assertEqual(await self.call_response(response), {'workspaces': []})

    async def test_legacy_sdk_structured_response(self):
        response = SimpleNamespace(structuredContent={'workspaces': []}, content=[], isError=False)
        self.assertEqual(await self.call_response(response), {'workspaces': []})

    async def test_installed_sdk_tool_error_text_is_reported(self):
        response = CallToolResult(content=[TextContent(text='Permission denied')], is_error=True)
        with self.assertRaisesRegex(RuntimeError, 'Permission denied'):
            await self.call_response(response)

    async def test_non_object_tool_error_is_reported(self):
        response = CallToolResult(content=[], structured_content=['Permission denied'], is_error=True)
        with self.assertRaisesRegex(RuntimeError, 'Permission denied'):
            await self.call_response(response)

    def shared(self, tool):
        opened = []

        @asynccontextmanager
        async def session(interactive=False):
            opened.append(interactive)
            yield SimpleNamespace(call_tool=tool)

        fish = Fish()
        fish.session = session
        return fish, opened

    async def test_calls_reuse_one_session(self):
        fish, opened = self.shared(AsyncMock(return_value=CallToolResult(content=[], structured_content={'ok': 1})))
        for _ in range(3):
            self.assertEqual(await fish.call('get_generation_status', {}), {'ok': 1})
        self.assertEqual(await fish.calls([('a', {}), ('b', {})]), [{'ok': 1}, {'ok': 1}])
        self.assertEqual(opened, [False])

    async def test_calls_returns_tool_errors_per_request(self):
        fish, _ = self.shared(AsyncMock(return_value=CallToolResult(content=[TextContent(text='Denied')], is_error=True)))
        results = await fish.calls([('a', {})])
        self.assertIsInstance(results[0], RuntimeError)

    async def test_dropped_session_reports_why_it_closed(self):
        from mcp.shared.exceptions import MCPError
        closed = asyncio.Event()

        async def tool(name, args):
            await closed.wait()
            raise MCPError(code=-32000, message='Connection closed')

        @asynccontextmanager
        async def session(interactive=False):
            yield SimpleNamespace(call_tool=tool)
            closed.set()
            raise ExceptionGroup('unhandled errors in a TaskGroup', [RuntimeError('Fish 로그인이 만료되었습니다.')])

        fish = Fish()
        fish.session = session
        call = asyncio.create_task(fish.call('get_generation_status', {}))
        await asyncio.sleep(0.01)
        fish.link.active, fish.link.used = 0, float('-inf')  # Let the holder close as if the server dropped it.
        with self.assertRaisesRegex(RuntimeError, '로그인이 만료'):
            await call

    async def test_legacy_sdk_tool_error_is_reported(self):
        response = SimpleNamespace(structuredContent={'error': 'Denied'}, content=[], isError=True)
        with self.assertRaisesRegex(RuntimeError, 'Denied'):
            await self.call_response(response)
