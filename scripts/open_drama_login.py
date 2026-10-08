"""Open the local studio's Drama login window without handling credentials."""
import json
import re
import time
import urllib.request

base = 'http://127.0.0.1:8766'
html = urllib.request.urlopen(base, timeout=10).read().decode()
token = re.search(r'name="studio-token" content="([^"]+)"', html).group(1)
request = urllib.request.Request(base + '/api/connect/drama', b'{}',
    {'Content-Type': 'application/json', 'X-Studio-Token': token})
assert json.load(urllib.request.urlopen(request, timeout=10))['ok']
for _ in range(45):
    time.sleep(1)
    state = json.load(urllib.request.urlopen(base + '/api/connections', timeout=10))
    if not state.get('drama_busy'):
        print(json.dumps({'drama_open': state['drama_open'], 'message': state['message']}, ensure_ascii=True))
        assert state['drama_open'], 'Drama browser did not open'
        break
else:
    raise RuntimeError('Drama browser startup timeout')
