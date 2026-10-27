"""Tests du niveau 3 de preuve : renseignements tarifaires contraignants (V3.7).

Les tests utilisent une base factice — la vraie base (data/tariff/ebti.sqlite,
19 000+ RTC FR valides) est générée par tools/import_taric.py et ignorée par
git : elle n'est pas requise pour exécuter la suite.
"""

import sqlite3
from pathlib import Path

from server.tariff.rti import conforter

SCHEMA = """
CREATE TABLE rti (ref TEXT, pays TEXT, debut TEXT, fin TEXT,
    mask10 TEXT, prefix TEXT, description TEXT);
CREATE INDEX idx_rti_prefix ON rti(prefix);
"""


def _base(tmp_path, lignes):
    chemin = tmp_path / 'ebti.sqlite'
    con = sqlite3.connect(chemin)
    con.executescript(SCHEMA)
    con.executemany('INSERT INTO rti VALUES (?,?,?,?,?,?,?)', lignes)
    con.commit()
    con.close()
    return chemin


def _candidat(code10='6404110000', confiance=0.6):
    return {'code': '6404 11 00', 'code10': code10, 'confiance': confiance,
            'raisons': ['raisons initiale'], 'statut': 'propose'}


def test_rtc_confort_candidat_couvert(tmp_path):
    chemin = _base(tmp_path, [
        ('FRBTIFR-BTI-2025-00001', 'FR', '01/01/2025', '31/12/2027',
         '64041100**', '64041100', 'Chaussure de sport à dessus textile, semelle en caoutchouc'),
    ])
    cand = _candidat()
    conforter([cand], ['chaussure de sport', 'baskets textile'], db_path=chemin)
    assert cand['rtc']['nb'] == 1
    assert cand['rtc']['exemples'][0]['ref'] == 'FRBTIFR-BTI-2025-00001'
    assert any('contraignant' in r for r in cand['raisons'])
    assert cand['confiance'] == 0.64          # +0.04, confort — pas une confirmation
    assert cand['statut'] == 'propose'         # §29 : jamais « confirmé »


def test_rtc_description_non_similaire_non_comptee(tmp_path):
    # Même code, mais bien sans rapport : le recoupement (< 2 mots) l'écarte.
    chemin = _base(tmp_path, [
        ('DEBTI-2025-00002', 'DE', '01/01/2025', '31/12/2027',
         '6404110000', '6404110000', 'Pièce de rechange pour machine à café automatique'),
    ])
    cand = _candidat()
    conforter([cand], ['chaussure de sport', 'baskets textile'], db_path=chemin)
    assert 'rtc' not in cand
    assert cand['confiance'] == 0.6


def test_rtc_masque_avec_jokers(tmp_path):
    # « 9403****00 » : positions 4-7 non spécifiées (jokers '*').
    chemin = _base(tmp_path, [
        ('FRBTIFR-BTI-2025-00003', 'FR', '01/01/2025', '31/12/2027',
         '9403****00', '9403', 'Meuble en bois, bibliothèque six étagères'),
    ])
    ok = {'code10': '9403609000', 'confiance': 0.6, 'raisons': []}
    ko = {'code10': '8712003000', 'confiance': 0.6, 'raisons': []}
    conforter([ok, ko], ['bibliothèque bois étagères meuble'], db_path=chemin)
    assert ok.get('rtc', {}).get('nb') == 1    # 9403 60 90 : jokers respectés
    assert 'rtc' not in ko


def test_rtc_sans_base_silencieux(tmp_path):
    cand = _candidat()
    conforter([cand], ['chaussure de sport'], db_path=tmp_path / 'inexistant.sqlite')
    assert 'rtc' not in cand and cand['confiance'] == 0.6


def test_rtc_candidat_sans_code10_ignore(tmp_path):
    chemin = _base(tmp_path, [
        ('FRBTIFR-BTI-2025-00004', 'FR', '01/01/2025', '31/12/2027',
         '6404110000', '6404110000', 'Chaussure de sport textile blanche'),
    ])
    cand = {'code': '6404 11 00', 'confiance': 0.5, 'raisons': []}   # pas de code10
    conforter([cand], ['chaussure de sport textile'], db_path=chemin)
    assert 'rtc' not in cand


def test_rtc_plafond_de_confiance(tmp_path):
    chemin = _base(tmp_path, [
        ('FRBTIFR-BTI-2025-00005', 'FR', '01/01/2025', '31/12/2027',
         '6404110000', '6404110000', 'Chaussure de sport textile blanche pour la course'),
    ])
    cand = _candidat(confiance=0.74)
    conforter([cand], ['chaussure de sport textile course'], db_path=chemin)
    assert cand['confiance'] == 0.75           # +0.04 mais plafonné à 0.75
