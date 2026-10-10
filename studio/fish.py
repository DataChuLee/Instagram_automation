from __future__ import annotations

import asyncio
import ctypes
import json
import os
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
from mcp import ClientSession
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client import streamable_http as transport
from mcp.shared.auth import OAuthClientMetadata, AuthorizationCodeResult, OAuthToken, OAuthClientInformationFull

from .paths import DATA, initialize

URL = 'https://api.fish.audio/mcp'
IDLE = 60  # Seconds the shared MCP session stays open after its last call.
CONNECTION_CLOSED = -32000  # JSON-RPC code the SDK gives pending calls when the session drops.


class ToolError(RuntimeError):
    """Fish answered the call with an error, as opposed to the connection failing."""


class Blob(ctypes.Structure):
    _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(data: bytes, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('계정 토큰 저장은 Windows에서만 지원합니다.')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    function = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


class WindowsTokens(TokenStorage):
    def _get(self, name, model):
        path = DATA / 'auth' / (name + '.bin')
        return model.model_validate_json(protect(path.read_bytes(), True)) if path.exists() else None

    def _set(self, name, value):
        initialize()
        path = DATA / 'auth' / (name + '.bin')
        temporary = path.with_suffix('.tmp')
        temporary.write_bytes(protect(value.model_dump_json().encode()))
        temporary.replace(path)

    async def get_tokens(self):
        return self._get('fish-token', OAuthToken)

    async def set_tokens(self, value):
        self._set('fish-token', value)

    async def get_client_info(self):
        return self._get('fish-client', OAuthClientInformationFull)

    async def set_client_info(self, value):
        self._set('fish-client', value)


class Fish:
    def __init__(self, base_url='http://127.0.0.1:8765'):
        self.base_url = base_url
        self.callback = None
        self.authorization_url = None
        self.lock = asyncio.Lock()
        self.link = None

    async def redirect(self, url):
        self.authorization_url = url
        self.callback = asyncio.get_running_loop().create_future()
        webbrowser.open(url)

    async def wait_callback(self):
        if self.callback is None:
            raise RuntimeError('로그인 요청이 없습니다.')
        return await asyncio.wait_for(self.callback, 300)

    def receive_callback(self, code, state, issuer=None):
        if self.callback is None or self.callback.done():
            raise ValueError('만료된 로그인 요청입니다.')
        # SDK verifies PKCE and expected state before exchanging the code.
        self.callback.set_result(AuthorizationCodeResult(code=code, state=state, iss=issuer))

    @asynccontextmanager
    async def session(self, interactive=False):
        storage = WindowsTokens()
        if not interactive and not await storage.get_tokens():
            raise RuntimeError('Fish 계정을 먼저 연결해 주세요.')
        async def no_redirect(url):
            raise RuntimeError('Fish 로그인이 만료되었습니다. 계정을 다시 연결해 주세요.')
        provider = OAuthClientProvider(server_url=URL,
            client_metadata=OAuthClientMetadata(client_name='Stay Studio Local',
                redirect_uris=[self.base_url + '/oauth/callback'],
                grant_types=['authorization_code', 'refresh_token'], response_types=['code'],
                token_endpoint_auth_method='none'), storage=storage,
            redirect_handler=self.redirect if interactive else no_redirect,
            callback_handler=self.wait_callback)
        # MCP 1.x uses httpx; MCP 2.x ships its own httpx2 transport.
        http_module = getattr(transport, 'httpx2', httpx)
        async with http_module.AsyncClient(auth=provider, timeout=120) as client:
            async with transport.streamable_http_client(URL, http_client=client) as streams:
                read, write = tuple(streams)[:2]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session

    async def hold(self, link):
        """Keeps one MCP session open in its own task until it has been idle for IDLE seconds."""
        try:
            async with self.session() as session:
                link.session = session
                link.ready.set_result(session)
                while link.active or asyncio.get_running_loop().time() - link.used < IDLE:
                    await asyncio.sleep(1)
        except Exception as error:
            while isinstance(error, ExceptionGroup) and error.exceptions:
                error = error.exceptions[0]
            link.failure = error
            if not link.ready.done():
                link.ready.set_exception(error)
        finally:
            link.closed = True
            if not link.ready.done():
                link.ready.cancel()

    async def open(self):
        """Returns the shared session, reconnecting if the last one closed or failed."""
        async with self.lock:
            link = self.link
            if link is None or link.closed:
                loop = asyncio.get_running_loop()
                link = SimpleNamespace(session=None, ready=loop.create_future(), active=0,
                                       used=loop.time(), failure=None, closed=False)
                link.task = asyncio.create_task(self.hold(link))
                self.link = link
            link.active += 1
        try:
            await asyncio.shield(link.ready)
        except BaseException:
            link.active -= 1
            raise
        return link

    async def call(self, name, args, interactive=False):
        if interactive:
            # Login runs its own session; the shared one reconnects with the new tokens.
            if self.link:
                self.link.used, self.link = float('-inf'), None
            async with self.session(True) as session:
                response = await session.call_tool(name, args)
            return self.parse(response)
        link = await self.open()
        try:
            response = await link.session.call_tool(name, args)
        except Exception as error:
            # A dropped connection only reports "closed"; surface why it closed (e.g. expired login).
            if link.closed or getattr(getattr(error, 'error', None), 'code', None) == CONNECTION_CLOSED:
                await asyncio.wait({link.task}, timeout=5)
            if link.failure is not None:
                raise link.failure from error
            raise
        finally:
            link.active -= 1
            link.used = asyncio.get_running_loop().time()
        return self.parse(response)

    async def calls(self, requests):
        """Run read-only calls together on the shared session; each result is a value or the ToolError it raised."""
        async def one(name, args):
            try:
                return await self.call(name, args)
            except ToolError as error:
                return error
        return await asyncio.gather(*(one(name, args) for name, args in requests))

    @staticmethod
    def parse(response):
        # MCP 2.x uses snake_case attributes; 1.x used the wire field names.
        value = getattr(response, 'structured_content', getattr(response, 'structuredContent', None))
        if value is None:
            text = '\n'.join(block.text for block in response.content if block.type == 'text')
            try:
                value = json.loads(text)
            except ValueError:
                value = {'message': text}
        is_error = getattr(response, 'is_error', getattr(response, 'isError', False))
        if is_error or (isinstance(value, dict) and value.get('error')):
            detail = value.get('error', value) if isinstance(value, dict) else value
            raise ToolError('Fish 작업에 실패했습니다: ' + str(detail))
        return value

    async def connect(self):
        return await self.call('list_my_workspaces', {}, interactive=True)

    async def upload(self, path: Path, workspace: str):
        value = await self.call('create_media_upload', {'workspace_id': workspace,
            'file_name': path.name, 'content_type': 'image/jpeg', 'file_size': path.stat().st_size})
        upload = value.get('upload', value)
        url = upload.get('upload_url') or upload.get('url')
        key = upload.get('object_key') or value.get('object_key')
        if not url or not key:
            raise RuntimeError('Fish 업로드 응답 형식을 확인할 수 없습니다.')
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.put(url, content=path.read_bytes(),
                headers=upload.get('headers', {'Content-Type': 'image/jpeg'}))
            response.raise_for_status()
        return key

    async def download(self, url, path):
        if not url.startswith('https://'):
            raise RuntimeError('Fish 결과 다운로드 주소가 올바르지 않습니다.')
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            async with client.stream('GET', url) as response:
                response.raise_for_status()
                temporary = path.with_suffix('.part')
                with temporary.open('wb') as file:
                    async for chunk in response.aiter_bytes():
                        file.write(chunk)
                temporary.replace(path)
