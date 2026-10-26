import json
import sys
from pathlib import Path

import requests

if len(sys.argv) != 2:
    print(r'Usage: python test_api.py "C:\chemin\image.jpg"')
    raise SystemExit(2)

path = Path(sys.argv[1])
if not path.is_file():
    print(f'Image introuvable : {path}')
    raise SystemExit(2)

with path.open('rb') as image:
    response = requests.post(
        'http://127.0.0.1:8000/api/v1/analysis',
        files={'image': (path.name, image, 'image/jpeg')},
        timeout=300,
    )

print('STATUS:', response.status_code)
try:
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))
except ValueError:
    print(response.text)
response.raise_for_status()
