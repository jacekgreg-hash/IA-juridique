"""Tests de la recherche par désignation (nomenclature TARIC officielle) — V3.4.

La nomenclature data/tariff/nomenclature_fr.json est générée par
tools/import_taric.py et versionnée ; les positions ci-dessous sont celles de
la référence 2026-10.
"""

import pytest

from pathlib import Path

from server.tariff.search import CONFIANCE_MAX, NOMENCLATURE_PATH, rechercher

pytestmark = pytest.mark.skipif(
    not Path(NOMENCLATURE_PATH).exists(),
    reason='nomenclature absente — lancer python tools/import_taric.py')


def test_recherche_perceuse():
    r = rechercher(['perceuse électrique', 'perceuse noire avec mandrin', '', 'BLACK+DECKER'])
    assert r['statut'] == 'candidats'
    assert r['candidats'][0]['code'].startswith('8467')   # outils à main, perceuses
    assert any('perceuse' in raison for c in r['candidats'] for raison in c['raisons'])


def test_recherche_velo_synonyme():
    # « vélo » (et « bike ») -> « bicyclettes » ; la position 8712 doit
    # domancer les pièces qui la mentionnent (pneus 4011, chambres à air 4013).
    r = rechercher(['vélo', 'vélo de course bleu', '', 'RACING BIKE'])
    codes = [c['code'] for c in r['candidats']]
    assert codes[0].startswith('8712')                    # bicyclettes elles-mêmes
    assert not codes[0].startswith('4011')                # pas des pneumatiques en tête


def test_recherche_casque_audio_pas_viande():
    # La viande ovine « en casque ou demi-casque » (0204) doit céder devant la
    # position 8518 (casques) grâce au bonus de position tarifaire.
    r = rechercher(['casque audio', 'casque circum-aural noir', '', 'SONY WH-1000'])
    assert r['candidats'][0]['code'].startswith('8518')


def test_recherche_aspirateur():
    r = rechercher(['aspirateur', 'aspirateur traîneau rouge', '', 'PHILIPS'])
    assert r['candidats'][0]['code'].startswith('8508')


def test_recherche_sac():
    r = rechercher(['sac à dos', 'sac tissu noir', '', 'BACKPACK'])
    assert r['candidats'][0]['code'].startswith('4202')


def test_recherche_nature_absente_de_la_nomenclature_refuse():
    # « bouilloire » n'existe pas dans la CN (le classement officiel de la
    # bouilloire électrique est un débat douanier) : la matière seule (« inox »,
    # « acier ») ne doit PAS produire du bruit (lingots d'acier 7218).
    r = rechercher(['bouilloire', 'bouilloire en acier inoxydable', '', 'PHILIPS'])
    assert r['statut'] == 'aucun_resultat'
    assert r['candidats'] == []
    assert 'nature non trouvée' in r['raison']


def test_recherche_sans_texte():
    r = rechercher(['', '', ''])
    assert r['statut'] == 'aucun_resultat'
    assert r['candidats'] == []


def test_recherche_preuve_faible_ne_confirme_jamais():
    r = rechercher(['aspirateur', 'aspirateur', '', ''])
    for c in r['candidats']:
        assert c['statut'] == 'propose'
        assert c['confiance'] <= CONFIANCE_MAX


# --- intégration au moteur tarifaire (repli hors familles codées) ---

def test_moteur_hors_familles_propose_via_designation():
    from server.tariff.engine import propose_classement
    r = propose_classement({'objet': 'perceuse', 'caracteristiques': ['noir', 'électrique']},
                           'perceuse électrique sur un établi', [])
    assert r['statut'] == 'candidats_a_departager'
    assert r['recherche'] == 'designation'
    assert r['candidats'] and r['candidats'][0]['code'].startswith('8467')
    assert r['questions'] and r['questions'][0]['champ'] == 'nature'


def test_moteur_nature_inconnue_sans_texte_reste_impossible():
    from server.tariff.engine import propose_classement
    r = propose_classement({'objet': None}, '', [])
    assert r['statut'] == 'impossible'
    assert r['candidats'] == []
