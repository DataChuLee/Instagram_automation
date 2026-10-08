"""Open the program's login windows; never invoke generation tools."""
import json
import re
import urllib.request

BASE = 'http://127.0.0.1:8766'
with urllib.request.urlopen(BASE) as response:
    html = response.read().decode()
token = re.search(r'name="studio-token" content="([^"]+)"', html).group(1)
for provider in ('fish', 'drama'):
    request = urllib.request.Request(BASE + '/api/connect/' + provider, b'{}',
        {'X-Studio-Token': token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request) as response:
        print(provider, response.status)
