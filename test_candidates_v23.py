from pathlib import Path
from PIL import Image, ImageEnhance
from server.candidates.engine import search_candidates

image = Path('data/reference_images/NIKE-P-6000.jpg')
base = Image.open(image).convert('RGB')

# Simulate a different capture of the same product: brightness + contrast,
# crop/pad. This is deliberately not the exact reference image.
query = ImageEnhance.Brightness(base).enhance(0.92)
query = ImageEnhance.Contrast(query).enhance(1.08)
query = query.resize((base.width - 20, base.height - 20))
canvas = Image.new('RGB', base.size, 'white')
canvas.paste(query, (10, 10))

vision = {
    'marque': 'Nike',
    'objet': 'chaussure de sport',
    'modele': None,
    'reference': None,
    'modele_candidate': 'P-1000',
    'reference_candidate': None,
    'caracteristiques': ['argenté brillant', 'soulier à lacets', 'logo Nike'],
}

# OCR intentionally remains noisy, reproducing the real V2.2 failure case.
ocr = ['SD attr', 'aaa ag', 'ee', 'sk', 'S S', 're', 'ss _ _ 4 _']

results = search_candidates(canvas, vision, ocr)
for item in results:
    print(item)

assert results[0]['id'] == 'nike-p-6000', results
assert results[0]['score'] > results[1]['score'], results
assert results[0]['id'] != 'nike-p-1000-decoy'
assert results[0]['type_preuve_visuelle'] in ('doublon_exact', 'visuel_multicritere_local')
print('\nOK: P-6000 reste en tête malgré la fausse hypothèse P-1000 et un OCR bruité.')
