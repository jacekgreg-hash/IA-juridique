from server.candidates.merge import merge_candidate_sources, candidate_decision, apply_candidate_decision_to_produit

LOCAL = [{'id': 'nike-p-6000', 'marque': 'Nike', 'objet': 'chaussure de sport', 'modele': 'P-6000',
          'source': 'catalogue_local', 'score': 0.38, 'similarite_image': 0.999, 'raisons': ['forte concordance visuelle']}]
WEB = [{'id': 'web:p6000', 'marque': 'Nike', 'objet': 'chaussure de sport', 'modele': 'P-6000', 'source': 'web',
        'score': 0.86, 'similarite_image_web': 0.833, 'raisons': ['image + titre modèle concordants'],
        'urls': ['https://www.nike.com/fr/t/x', 'https://www.snipes.com/fr/x'],
        'titres': ['Nike P-6000 argent', 'Nike P-6000'], 'domaines': ['nike.com', 'snipes.com'],
        'preuves_titre_modele': 2, 'preuves_llm': 2, 'preuves_llm_certaines': 2}]
OTHER = [{'id': 'web:airmax270', 'marque': 'Nike', 'objet': 'chaussure de sport', 'modele': 'Air Max 270',
          'source': 'web', 'score': 0.25, 'raisons': ['preuve textuelle avec marque'],
          'urls': ['https://www.kaufland.fr/x'], 'titres': ['Nike Air Max 270'], 'domaines': ['kaufland.fr']}]


def test_v211_regression_same_model_single_candidate():
    merged = merge_candidate_sources(LOCAL, WEB, {'marque': 'Nike', 'objet': 'chaussure de sport'})
    assert merged[0]['modele'] == 'P-6000'
    assert sum(1 for x in merged if x['modele'] == 'P-6000') == 1
    assert merged[0]['score'] >= 0.9
    merged2 = merge_candidate_sources(LOCAL, OTHER, {'marque': 'Nike'})
    assert merged2[0]['modele'] == 'P-6000'


def test_brandless_web_candidate_still_merges_with_catalog():
    # Régression V2.13.6 : la vision ne trouve pas la marque, le candidat web n'en a pas.
    web = [{**WEB[0], 'marque': None}]
    merged = merge_candidate_sources(LOCAL, web, {'marque': None})
    p6000 = [x for x in merged if x['modele'] == 'P-6000']
    assert len(p6000) == 1
    assert p6000[0]['marque'] == 'Nike'
    assert 'convergence entre preuves locales et web' in p6000[0]['raisons']
    assert p6000[0]['sources'] == ['catalogue_local', 'web']


def test_same_model_different_explicit_brands_stay_apart():
    a = [{'id': 'a', 'marque': 'Asics', 'modele': 'GT-2000', 'source': 'web', 'score': 0.5}]
    b = [{'id': 'b', 'marque': 'Brooks', 'modele': 'GT-2000', 'source': 'web', 'score': 0.4}]
    merged = merge_candidate_sources(a, b, {})
    assert len(merged) == 2


def test_candidates_without_model_are_ignored():
    assert merge_candidate_sources([{'id': 'x', 'marque': 'Nike', 'modele': None, 'score': 0.9}], [], {}) == []


def test_decision_thresholds():
    assert candidate_decision([])['statut'] == 'aucun_candidat'
    strong = [{'id': 'a', 'score': 0.9}, {'id': 'b', 'score': 0.5}]
    assert candidate_decision(strong)['statut'] == 'candidat_fort'
    tie = [{'id': 'a', 'score': 0.9}, {'id': 'b', 'score': 0.85}]
    assert candidate_decision(tie)['statut'] == 'faible'
    mid = [{'id': 'a', 'score': 0.70}, {'id': 'b', 'score': 0.5}]
    assert candidate_decision(mid)['statut'] == 'candidats_a_verifier'


def test_decision_never_confirms():
    cands = [{'id': 'a', 'score': 0.95, 'modele': 'P-6000'}]
    produit = {}
    apply_candidate_decision_to_produit(produit, candidate_decision(cands), cands)
    assert produit['modele_candidate'] == 'P-6000'
    assert produit['modele_statut'] == 'probable'      # jamais 'confirme'
