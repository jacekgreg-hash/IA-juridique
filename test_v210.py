from pathlib import Path
from server.candidates.engine import search_candidates
from server.candidates.web_search import WebResult, ImageResult, extract_product_models
from server.candidates.external import search_external
from PIL import Image

ROOT=Path(__file__).resolve().parent
IMG=ROOT/'data'/'reference_images'/'NIKE-P-6000.jpg'

assert extract_product_models('Nike 2026 - Air Force 1 - de 100 en 1978') == ['Air Force 1']
assert extract_product_models('Nike P-6000 argent (CN0149-001)') == ['P-6000']

im=Image.open(IMG).convert('RGB')
vision={'objet':'chaussure de sport','marque':'Nike','modele':None,'modele_candidate':None,'caracteristiques':['multiples empiècements','Swoosh latéral','semelle épaisse','aspect argenté']}
local=search_candidates(im,vision,['P-1000','bruit'],limit=5)
assert local and local[0]['id']=='nike-p-6000', local

class Fake:
    name='fake_searxng'
    enabled=True
    def search(self,q):
        return [WebResult('Nike P-6000 argent (CN0149-001)','https://www.snipes.com/fr-ch/p/nike-p-6000-argent-28309','Nike P-6000 argent','snipes.com'), WebResult('Nike P-6000','https://www.nike.com/fr/t/chaussure-nike-p-6000-Z6nJN4Ea','Nike P-6000','nike.com')]
    def image_search(self,q): return []

out=search_external(vision,[],query_image=im,provider=Fake(),fallback=Fake())
assert out['candidats'] and out['candidats'][0]['modele'].upper()=='P-6000', out
assert out['candidats'][0]['nb_domaines_independants']>=2
assert out['brave_role']=='secours_uniquement'
print('OK V2.10 hygiene + ranking + multi-domain aggregation')
