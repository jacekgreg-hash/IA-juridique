import base64
import sys
import requests

if len(sys.argv) != 2:
    print(r'Usage: python test_ollama.py "C:\chemin\image.jpg"')
    raise SystemExit(2)

with open(sys.argv[1], 'rb') as f:
    image = base64.b64encode(f.read()).decode('ascii')

payload = {
    'model': 'qwen3-vl:2b-instruct',
    'messages': [{'role': 'user', 'content': 'Décris cette image en une seule phrase.', 'images': [image]}],
    'stream': False,
    'keep_alive': '2m',
    'options': {'temperature': 0.0, 'num_ctx': 512, 'num_predict': 60},
}

r = requests.post('http://127.0.0.1:11434/api/chat', json=payload, timeout=180)
print('STATUS:', r.status_code)
print(r.text)
r.raise_for_status()
