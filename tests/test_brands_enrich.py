from server.utils.brands import find_brand
from server.vision.enrich import enrich_vision, short_object_phrase, object_category
from server.vision.florence import clean_generation, _infer_brand

CAPTION = 'The image shows a pair of silver and black Nike sneakers with a white sole on a white background.'


def test_brand_needs_whole_word():
    # Régressions V2.13.6 : la marque était cherchée par simple sous-chaîne.
    assert find_brand('pineapple on a plate') is None      # « Apple » (reproduit sur l'ancien code)
    assert find_brand('a canonical example') is None       # « Canon »
    assert find_brand('Evans Street sign') is None         # « Vans »
    assert find_brand('Legoland park') is None             # « Lego »
    assert find_brand('a sonya camera') is None            # « Sony »


def test_brand_found_and_longest_first():
    assert find_brand('a pair of nike sneakers') == 'Nike'
    assert find_brand('New Balance 574 shoe') == 'New Balance'
    assert find_brand('logo NIKE sur la languette') == 'Nike'


def test_catalog_brand_is_known():
    # « Nike » vient aussi du catalogue local
    assert _infer_brand('Nike P-6000') == 'Nike'


def test_clean_generation_strips_special_tokens():
    assert clean_generation('</s><s>The image shows a shoe.</s>') == 'The image shows a shoe.'
    assert clean_generation('<pad><pad>A shoe') == 'A shoe'


def test_short_object_phrase_drops_context():
    assert short_object_phrase(CAPTION) == 'a pair of silver and black Nike sneakers'
    assert len(short_object_phrase('x ' * 200)) <= 90
    assert short_object_phrase('') is None


def test_object_category_fr():
    assert object_category(CAPTION) == 'chaussure de sport'
    assert object_category('a red apple') is None


def test_enrich_from_caption():
    fast = {'caption': CAPTION, 'marque': 'Nike'}
    out = enrich_vision(fast, ['P-6000', 'NIKE'])
    assert out['objet'] == 'chaussure de sport'
    assert 'argenté' in out['caracteristiques'] and 'noir' in out['caracteristiques']
    assert 'semelle' in out['caracteristiques']
    assert out['marque_source'] == 'legende'
    assert out['texte_visible'] == ['P-6000', 'NIKE']
    assert 0 < out['identification_confiance'] < 0.30      # reste sous le plafond « vision »
    assert out['modele'] is None if 'modele' in out else True   # jamais de modèle proposé


def test_enrich_brand_from_ocr_when_caption_silent():
    fast = {'caption': 'A pair of sneakers on a table.', 'marque': None}
    out = enrich_vision(fast, ['NIKE', 'P-6000'])
    assert out['marque'] == 'Nike' and out['marque_source'] == 'ocr'


def test_enrich_no_brand_anywhere():
    out = enrich_vision({'caption': 'A pair of sneakers.', 'marque': None}, [])
    assert out['marque'] is None and out['marque_source'] is None
    assert out['objet'] == 'chaussure de sport'
