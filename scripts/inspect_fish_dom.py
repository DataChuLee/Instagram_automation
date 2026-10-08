from pathlib import Path
from html.parser import HTMLParser
import sys
import inspect
sys.stdout.reconfigure(encoding='utf-8')
from mcp.shared.auth import AuthorizationCodeResult
print(inspect.getsource(AuthorizationCodeResult))
class Parser(HTMLParser):
    def handle_starttag(self, tag, attrs):
        if tag in ('textarea', 'input') or dict(attrs).get('contenteditable'):
            print(tag, attrs)
Parser().feed(Path('.local/probes/fish-editor.html').read_text(encoding='utf-8'))
