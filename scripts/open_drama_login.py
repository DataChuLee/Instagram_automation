"""Compatibility helper: Drama3 now uses the shared Fish MCP login."""
import json
import re
import time
import urllib.request

base = 'http://127.0.0.1:8766'
html = urllib.request.urlopen(base, timeout=10).read().decode()
token = re.search(r'name="studio-token" content="([^"]+)"', html).group(1)
request = urllib.request.Request(base + '/api/connect/fish', b'{}',
    {'Content-Type': 'application/json', 'X-Studio-Token': token})
assert json.load(urllib.request.urlopen(request, timeout=10))['ok']
for _ in range(45):
    time.sleep(1)
    state = json.load(urllib.request.urlopen(base + '/api/connections', timeout=10))
    if not state.get('fish_busy'):
        print(json.dumps({'fish': state['fish'], 'message': state['message']}, ensure_ascii=True))
        assert state['fish'], 'Fish MCP connection did not complete'
        break
else:
    raise RuntimeError('Fish MCP login timeout')
