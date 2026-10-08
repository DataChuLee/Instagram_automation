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

    async def test_legacy_sdk_tool_error_is_reported(self):
        response = SimpleNamespace(structuredContent={'error': 'Denied'}, content=[], isError=True)
        with self.assertRaisesRegex(RuntimeError, 'Denied'):
            await self.call_response(response)
