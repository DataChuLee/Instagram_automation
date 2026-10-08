from pathlib import Path
import re
import sys
sys.stdout.reconfigure(encoding='utf-8')
text=Path('.local/probes/public-js/beta-uael_dMy.js').read_text(encoding='utf-8')
index=text.index('generate_speech_tooltip')
print(text[max(0,index-4300):index+600])
index=text.index('const{fetchPackage:')
print(text[index:index+3500])
print('Instant task SDK:')
text=Path('.local/probes/public-js/task-BPXO6JNl.js').read_text(encoding='utf-8')
index=text.index('class Y')
print(text[index:index+3800])
