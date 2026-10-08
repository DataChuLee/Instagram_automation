"""Check local jobs or retry Fish workspace connection without printing credentials."""
import argparse
import json
import re
import time
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument('--check-idle', action='store_true')
args = parser.parse_args()
base = 'http://127.0.0.1:8766'
if args.check_idle:
    jobs = json.load(urllib.request.urlopen(base + '/api/jobs', timeout=10))
    active = [job for job in jobs if job['state'] in {'analyzing', 'quoting', 'generating', 'rendering'}]
    print('Active jobs:', len(active))
    assert not active, 'Do not restart during an active job'
else:
    html = urllib.request.urlopen(base, timeout=10).read().decode()
    token = re.search(r'name="studio-token" content="([^"]+)"', html).group(1)
    request = urllib.request.Request(base + '/api/connect/fish', b'{}',
        {'Content-Type': 'application/json', 'X-Studio-Token': token})
    assert json.load(urllib.request.urlopen(request, timeout=10))['ok']
    deadline = time.monotonic() + 330
    while time.monotonic() < deadline:
        time.sleep(2)
        state = json.load(urllib.request.urlopen(base + '/api/connections', timeout=30))
        if not state.get('fish_busy'):
            print(json.dumps({'fish_connected': state['fish'], 'workspace_count': len(state['workspaces']),
                'message': state['message']}, ensure_ascii=True), flush=True)
            assert state['fish'], 'Fish connection failed'
            break
    else:
        raise RuntimeError('Fish connection timeout')
