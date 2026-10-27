"""Renseignements tarifaires contraignants (RTC/EBTI) — niveau 3 de preuve.

Un RTC est une décision d'administration douanière, contraignante, sur le
classement d'un bien précis. RITA ne l'utilise que pour CONFORTER un candidat
déjà proposé (familles, désignations ou notes explicatives) : le code du
candidat doit être couvert par le RTC (jokers '*' respectés) ET la description
du RTC doit recouper l'analyse (au moins deux mots utiles en commun). Jamais
un RTC ne classe à la place de l'utilisateur (§29) — la photo d'un produit ne
prouve pas qu'il est identique à celui décrit dans la décision.

Base : data/tariff/ebti.sqlite (générée par tools/import_taric.py, ignorée par
git — 19 000+ RTC valides, langue FR).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from server.tariff.search import _vocabulaire

DB_EBTI = Path(__file__).resolve().parents[2] / 'data' / 'tariff' / 'ebti.sqlite'

# Nombre de mots utiles (hors mots-outils, cf. search._vocabulaire) communs
# entre la description du RTC et l'analyse, minimum pour considérer que le
# RTC décrit un bien similaire.
RECOUPEMENT_MIN = 2
# Majoration de confiance quand des RTC confortent le candidat — faible :
# un RTC est une forte preuve sur le code, mais la similarité du bien reste
# une appréciation (§29 : la décision reste à l'utilisateur).
BONUS_CONFIANCE = 0.04
CONFIANCE_PLAFOND = 0.75
# Exemples cités par candidat.
EXEMPLES_MAX = 3


def _correspond(mask10: str, code10: str) -> bool:
    """Le code candidat respecte toutes les positions spécifiées du RTC."""
    return all(p == c for p, c in zip(mask10, code10) if p != '*')


def conforter(candidats: list[dict], textes: list[str], db_path: Path | None = None) -> None:
    """Ajoute aux candidats couverts les RTC à la description similaire.

    Silencieux sans base (l'import EBTI est optionnel) ; ne lève jamais.
    Mutations : candidat['rtc'] = {nb, exemples:[...]}, confiance +bonus,
    raison « conforté par N renseignements tarifaires contraignants ».
    """
    if not candidats:
        return
    chemin = Path(db_path) if db_path else DB_EBTI
    if not chemin.exists():
        return
    vise: set[str] = set()
    for t in textes or []:
        vise.update(_vocabulaire(t))
    if not vise:
        return
    try:
        con = sqlite3.connect(f'file:{chemin}?mode=ro', uri=True)
        con.row_factory = sqlite3.Row
        try:
            for cand in candidats:
                code10 = cand.get('code10')
                if not code10 or len(code10) != 10:
                    continue
                rows = con.execute(
                    'SELECT ref, pays, fin, mask10, prefix, description FROM rti '
                    "WHERE ? LIKE prefix || '%'", (code10,)).fetchall()
                retenus = []
                for row in rows:
                    if not _correspond(row['mask10'], code10):
                        continue
                    mots_rtc = set(_vocabulaire(row['description']))
                    recoupement = vise & mots_rtc
                    if len(recoupement) < RECOUPEMENT_MIN:
                        continue  # même code mais bien non similaire : pas une preuve
                    retenus.append((len(recoupement), row))
                if not retenus:
                    continue
                retenus.sort(key=lambda x: -x[0])
                exemples = [{'ref': row['ref'], 'pays': row['pays'], 'valide_jusqua': row['fin'],
                             'extrait': row['description'][:180]}
                            for _, row in retenus[:EXEMPLES_MAX]]
                cand['rtc'] = {'nb': len(retenus), 'exemples': exemples}
                cand['raisons'] = list(cand.get('raisons') or []) + [
                    f'conforté par {len(retenus)} renseignement(s) tarifaire(s) contraignant(s) '
                    f'— ex. {retenus[0][1]["ref"]} ({retenus[0][1]["pays"]})']
                cand['confiance'] = round(min(cand.get('confiance', 0) + BONUS_CONFIANCE,
                                              CONFIANCE_PLAFOND), 2)
        finally:
            con.close()
    except Exception:
        return  # le confort RTC ne doit jamais casser le classement
