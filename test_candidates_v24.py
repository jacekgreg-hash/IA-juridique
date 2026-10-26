from pathlib import Path
from PIL import Image, ImageEnhance
from server.candidates.engine import search_candidates

BASE = Path(__file__).resolve().parent
IMG = BASE / 'data' / 'reference_images' / 'NIKE-P-6000.jpg'


def main():
    image = Image.open(IMG).convert('RGB')
    transformed = ImageEnhance.Contrast(image).enhance(0.93)
    transformed = ImageEnhance.Sharpness(transformed).enhance(1.1)
    vision = {
        'marque': 'Nike',
        'objet': 'chaussure de sport',
        'modele_candidate': 'P-1000',
        'caracteristiques': ['argenté brillant', 'soulier à lacets', 'semelle épaisse'],
    }
    candidates = search_candidates(transformed, vision, ['SD attr', 'aaa ag'], limit=5)
    assert candidates[0]['id'] == 'nike-p-6000', candidates
    assert candidates[0]['score'] > candidates[1]['score'], candidates
    print('OK: V2.4 local ranking regression')
    print(candidates[:2])


if __name__ == '__main__':
    main()
