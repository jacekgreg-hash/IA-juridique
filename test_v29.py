import json
from pathlib import Path
from server.candidates.engine import load_catalog
from server.candidates.web_search import extract_identifiers

products=load_catalog()
p6000=next(x for x in products if x['id']=='nike-p-6000')
assert 'multiples empiècements' in p6000['visual_profile']
assert 'Swoosh latéral' in p6000['visual_profile']
assert '1972' not in extract_identifiers('Nike 1972 collection')
print('OK V2.9 profils visuels discriminatifs + sécurité modèle')
