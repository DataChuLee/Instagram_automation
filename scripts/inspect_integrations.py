"""Inspect installed SDK interfaces; never print account credentials."""
import inspect
from pathlib import Path
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.shared.auth import OAuthClientMetadata, AuthorizationCodeResult
from mcp.client.streamable_http import streamable_http_client
from mcp import ClientSession
from playwright.sync_api import sync_playwright

for target in (OAuthClientProvider, TokenStorage, streamable_http_client, ClientSession):
    print(target.__name__, inspect.signature(target))
print(inspect.getsource(TokenStorage))
print(inspect.getsource(OAuthClientProvider.__init__))
print('AuthorizationCodeResult:', AuthorizationCodeResult)
print('OAuth metadata:', OAuthClientMetadata.model_fields)
with sync_playwright() as playwright:
    path = Path(playwright.chromium.executable_path)
    print('chromium:', path, 'exists:', path.exists())
