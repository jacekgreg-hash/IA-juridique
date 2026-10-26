from pathlib import Path
from PIL import Image
from server.candidates.engine import search_candidates

image = Path('data/reference_images/NIKE-P-6000.jpg')
vision = {
    'marque': 'Nike',
    'objet': 'chaussure de sport',
    'modele': None,
    'reference': None,
    'modele_candidate': 'P-1000',
    'reference_candidate': None,
    'caracteristiques': ['argenté brillant', 'soulier à lacets', 'logo Nike'],
}
ocr = ['P-6000']
results = search_candidates(Image.open(image).convert('RGB'), vision, ocr)
for item in results:
    print(item)
assert results[0]['id'] == 'nike-p-6000'
print('\nOK: le moteur local place Nike P-6000 en tête malgré le faux candidat P-1000 de la vision.')
