"""Tests du moteur fiscal (§16) — estimation des droits par origine (V3.2).

La base data/tariff/fiscal.sqlite est générée par tools/import_taric.py depuis
l'extraction TARIC officielle et versionnée ; les taux ci-dessous sont ceux de
la référence 2026-10 (à ajuster si la base est réimportée après un accord).
"""

from pathlib import Path

import pytest

from server.tariff.fiscal import DB_PATH, taux_estime

pytestmark = pytest.mark.skipif(
    not Path(DB_PATH).exists(),
    reason='base fiscale absente — lancer python tools/import_taric.py')


def test_fiscal_preference_vietnam():
    # Accord UE-Viêt Nam : 0 % au lieu du droit de pays tiers (8 %).
    r = taux_estime('6403 19 00', 'VN')
    assert r['statut'] == 'estime'
    assert r['droit_pays_tiers']['taux'] == 0.08
    assert r['preference']['taux'] == 0.0
    assert r['taux_estime'] == 0.0
    assert r['preference']['groupe'] == 'Viet Nam'


def test_fiscal_mercosur():
    # Brésil = membre du groupe Mercosur (préférence 7 % sur ce code).
    r = taux_estime('6403 19 00', 'BR')
    assert r['preference']['groupe'] == 'Mercosur'
    assert r['preference']['taux'] == 0.07
    assert r['taux_estime'] == 0.07


def test_fiscal_erga_omnes_sans_preference():
    r = taux_estime('6403 19 00', 'US')
    assert r['preference'] is None
    assert r['taux_estime'] == 0.08


def test_fiscal_nom_francais_resolu():
    # « Chine » -> CN (la base TARIC nomme les pays en anglais).
    assert taux_estime('6403 19 00', 'Chine')['origine_iso'] == 'CN'


def test_fiscal_antidumping_sajoute():
    # Éléments de bicyclette, Chine : droit de pays tiers 4,7 % + antidumping
    # maximal 48,5 % -> estimation prudente 53,2 % ; taux par entreprise listés.
    r = taux_estime('8714911031', 'CN')
    assert r['droit_pays_tiers']['taux'] == 0.047
    assert r['antidumping'] is not None
    assert r['antidumping']['taux_max'] == 0.485
    assert len(r['antidumping']['lignes']) > 1   # taux par entreprise (codes additionnels)
    assert r['taux_estime'] == pytest.approx(0.532)


def test_fiscal_normalisation_code():
    # « 6403 19 00 » (CN8) et « 6403190000 » donnent le même résultat.
    assert taux_estime('6403 19 00', 'CN')['taux_estime'] == \
           taux_estime('6403190000', 'CN')['taux_estime']


def test_fiscal_ne_confirme_jamais():
    # §29 : une estimation documentée avec avertissement, jamais une certitude.
    r = taux_estime('6403 19 00', 'VN')
    assert r['statut'] == 'estime'
    assert r['avertissement']
    assert r['preference']['base_legale']


def test_fiscal_refus_origine_inconnue():
    r = taux_estime('6403190000', 'Atlantide')
    assert r['statut'] == 'impossible'
    assert 'origine inconnue' in r['raison']


def test_fiscal_refus_code_invalide():
    r = taux_estime('12', 'CN')
    assert r['statut'] == 'impossible'
    assert 'code' in r['raison']


# --- route API ---

def test_duty_route():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server.api.routes import router
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    r = client.get('/api/v1/duty', params={'code': '6403 19 00', 'origine': 'Chine'})
    assert r.status_code == 200
    body = r.json()
    assert body['statut'] == 'estime'
    assert body['origine_iso'] == 'CN'
    assert body['taux_estime'] == 0.08
    assert body['avertissement']
