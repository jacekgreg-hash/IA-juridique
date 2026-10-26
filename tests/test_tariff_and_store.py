"""Tests du moteur tarifaire (§9/§10/§11) et de la persistance (§20/§21/§24) — V3."""

from server.tariff.engine import propose_classement
from server.persistence import store


# --- moteur tarifaire ---

def test_tariff_commode_bois():
    r = propose_classement({'objet': 'commode', 'caracteristiques': ['gris', 'bois', 'tiroirs']},
                          'petit meuble ancien en bois foncé', [])
    assert r['statut'] == 'candidat_dominant'
    assert r['candidats'][0]['code'] == '9403 60 00'
    assert r['candidats'][0]['statut'] == 'propose'      # jamais « confirmé » (§29)


def test_tariff_montre_automatique():
    r = propose_classement({'objet': 'montre'}, "montre Automatic Diver's 200m", ['AUTOMATIC'])
    assert r['candidats'][0]['code'] == '9101 21 00'


def test_tariff_telephone_clavier_est_pas_smartphone():
    r = propose_classement({'objet': 'téléphone'},
                           'téléphone avec écran monochrome et clavier numérique', ['NOKIA', 'Menu'])
    assert r['candidats'][0]['code'] == '8517 14 00'


def test_tariff_chaussure_mesh_textile():
    r = propose_classement({'objet': 'chaussure de sport', 'caracteristiques': ['blanc', 'mesh']},
                           'chaussure en maille textile', [])
    assert r['candidats'][0]['code'] == '6404 11 00'


def test_tariff_question_ciblee_quand_info_manque():
    # §11/§31.3 : sans matière de tige, plusieurs candidats + la question qui départage.
    r = propose_classement({'objet': 'chaussure de sport', 'caracteristiques': ['blanc']}, 'une chaussure', [])
    assert r['statut'] == 'candidats_a_departager'
    assert len(r['candidats']) >= 2
    assert r['questions'] and r['questions'][0]['champ'] == 'tige'
    assert 'tige' in r['informations_manquantes']


def test_tariff_nature_inconnue_refuse_de_classer():
    r = propose_classement({'objet': None}, '', [])
    assert r['statut'] == 'impossible'
    assert r['candidats'] == []
    assert 'nature de la marchandise' in ' '.join(r['informations_manquantes'])


def test_tariff_base_separee_du_code():
    # §10 : les données vivent dans data/tariff/tariff_base.json, versionnées et sourcées.
    base = propose_classement({'objet': 'commode'}, 'bois', [])
    assert base['base_version'] and base['base_source'] and base['date_validite']


# --- persistance ---

def test_store_save_list_get(tmp_path):
    db = tmp_path / 'test.sqlite'
    payload = {'produit': {'marque': 'Nike', 'objet': 'chaussure de sport', 'modele_candidate': 'P-6000'},
               'decision_candidat': {'statut': 'candidat_fort'},
               'classement': {'candidats': [{'code': '6404 11 00'}]},
               'meta': {'version': 'RITA Vision V3'}}
    aid = store.save_analysis(payload, image_name='photo.jpg', db_path=db)
    assert aid
    rows = store.list_history(db_path=db)
    assert len(rows) == 1
    assert rows[0]['id'] == aid
    assert rows[0]['marque'] == 'Nike' and rows[0]['code_top'] == '6404 11 00'
    back = store.get_analysis(aid, db_path=db)
    assert back['produit']['modele_candidate'] == 'P-6000'
    assert store.get_analysis('inexistant', db_path=db) is None
