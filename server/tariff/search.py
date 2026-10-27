"""Recherche par désignation dans la nomenclature TARIC officielle (§9, §10).

But : au-delà des familles codées dans le moteur tarifaire (chaussures,
téléphonie, horlogerie, meubles), proposer des positions tarifaires pour toute
marchandise en cherchant les mots de l'analyse (nature, caractéristiques,
légende, OCR) dans les désignations officielles FR des 16 725 codes
déclarables de data/tariff/nomenclature_fr.json.

Principes (§29) :
* la recherche est une PREUVE FAIBLE : elle propose des candidats à vérifier,
  jamais un classement confirmé — le statut reste « propose » et la confiance
  plafonne bas ;
* tout vient de la base officielle générée par tools/import_taric.py, rien
  n'est codé en dur ; la normalisation (accents, pluriels) est purement
  linguistique, les synonymes sont explicites et limités.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

NOMENCLATURE_PATH = Path(__file__).resolve().parents[2] / 'data' / 'tariff' / 'nomenclature_fr.json'

# Mots-outils exclus de la recherche (aucune valeur discriminante).
STOPWORDS = {
    # français
    'avec', 'sans', 'pour', 'dans', 'des', 'les', 'une', 'son', 'sa', 'ses', 'aux', 'au', 'ce', 'cette', 'ces',
    'autre', 'autres', 'plus', 'tres', 'tres', 'faits', 'fait', 'main', 'mains', 'pair', 'paires', 'set',
    'piece', 'pieces', 'partie', 'parties', 'types', 'type', 'sorte', 'sortes', 'meme', 'memes', 'specialement',
    'specifie', 'specifiees', 'utilisés', 'utilises', 'utilise', 'notamment', 'comporte', 'comportant',
    'peut', 'etre', 'sous', 'leur', 'leurs', 'dont', 'dont', 'et', 'est', 'que', 'qui', 'quo',
    # anglais (la légende/OCR peuvent être en anglais)
    'with', 'without', 'for', 'the', 'and', 'from', 'other', 'others', 'new', 'used', 'made',
}

# Synonymes explicites anglais/abréviations -> mot des désignations FR TARIC.
# Liste volontairement courte : chaque entrée est une décision, pas du bruit.
SYNONYMES = {
    'velo': ('bicyclette',), 'bike': ('bicyclette',), 'bicycle': ('bicyclette',),
    'bikes': ('bicyclette',), 'bicycles': ('bicyclette',),
    'drill': ('perceuse',), 'perceuses': ('perceuse',),
    'computer': ('informatique',), 'laptop': ('informatique',), 'ordinateur': ('informatique',),
    'handbag': ('sacs',), 'purse': ('sacs',), 'bag': ('sacs',), 'bags': ('sacs',),
    'chair': ('chaise',), 'chaises': ('chaise',), 'table': ('table',), 'tables': ('table',),
    'lamp': ('lampes',), 'lampe': ('lampes',), 'lampes': ('lampes',),
    'toy': ('jouets',), 'jouet': ('jouets',), 'jouets': ('jouets',),
}

# Longueur minimale d'un mot indexé/recherché (évite le bruit OCR).
LONGUEUR_MIN = 3
# Confiance maximale d'un candidat issu de la recherche (preuve faible, §29).
CONFIANCE_MAX = 0.60
# Bonus quand le mot apparaît dans la position tarifaire (fragment HS4, le
# « nom » du produit) : distingue le produit lui-même de ses mentions
# accessoires (ex. « casques » position 8518 vs viande « en casque », ou
# bicyclette position 8712 vs pneus « pour bicyclettes » 4011).
BONUS_POSITION = 1.5


def _normalise(mot: str) -> str:
    """Minuscules sans accents ; pluriel français simplifié (chaussures->chaussure)."""
    m = unicodedata.normalize('NFD', mot.strip().lower())
    m = ''.join(c for c in m if unicodedata.category(c) != 'Mn')
    m = re.sub(r'[^a-z0-9-]', '', m)
    if len(m) > LONGUEUR_MIN and (m.endswith('s') or m.endswith('x')):
        m = m[:-1]
    return m


def _vocabulaire(texte: str) -> list[str]:
    """Mots normalisés et dédupliqués d'un texte, hors mots-outils."""
    mots = []
    vus = set()
    for mot in re.split(r'[^0-9a-zA-ZÀ-ÿ-]+', str(texte or '')):
        n = _normalise(mot)
        if len(n) < LONGUEUR_MIN or n in STOPWORDS or n in vus:
            continue
        vus.add(n)
        mots.append(n)
    return mots


@lru_cache(maxsize=1)
def _index() -> tuple[list[dict], dict[str, list[int]], dict[str, set[int]]]:
    """Charge la nomenclature, l'index inversé mot -> indices de codes, et
    l'index des mots de la position tarifaire (fragments HS4)."""
    with open(NOMENCLATURE_PATH, encoding='utf-8') as f:
        doc = json.load(f)
    codes = doc['codes']
    index: dict[str, list[int]] = {}
    index_position: dict[str, set[int]] = {}
    for i, c in enumerate(codes):
        vus = set()
        for mot in _vocabulaire(c['designation']):
            if mot in vus:
                continue
            vus.add(mot)
            index.setdefault(mot, []).append(i)
        for mot in _vocabulaire(c.get('position') or ''):
            index_position.setdefault(mot, set()).add(i)
    return codes, index, index_position


def rechercher(textes: list[str], limite: int = 5) -> dict:
    """Cherche les positions tarifaires dont la désignation correspond aux textes.

    Pondération : les premiers textes (nature, caractéristiques) comptent plus
    que la légende/OCR (preuves faibles). Retourne des candidats au statut
    « propose », jamais une confirmation (§29).
    """
    codes, index, index_position = _index()
    # Garde (§11 : ne pas inventer) : si la nature (premier texte) est connue
    # mais absente de la nomenclature — ex. « bouilloire », mot que la CN
    # n'utilise pas — les mots restants (matière, couleur, marque) ne suffisent
    # pas à identifier un produit : on ne propose rien plutôt que du bruit
    # (ex. « acier inoxydable » pour une bouilloire).
    if textes:
        nature = _vocabulaire(textes[0])
        if nature:
            trouve = any(any(index.get(forme, ()) for forme in
                             (mot,) + SYNONYMES.get(mot, ())) for mot in nature)
            if not trouve:
                return {'statut': 'aucun_resultat', 'candidats': [],
                        'raison': "nature non trouvée dans la nomenclature officielle ; les autres "
                                  'mots (matière, couleur, marque) ne suffisent pas à proposer une '
                                  'position tarifaire'}
    poids_texte = (3.0, 2.0, 1.0, 1.0, 1.0)  # nature/caractéristiques > légende/OCR
    scores: dict[int, dict] = {}
    for rang, texte in enumerate(textes):
        poids = poids_texte[min(rang, len(poids_texte) - 1)]
        for mot in _vocabulaire(texte):
            # Le mot et ses synonymes dédoublonnés (ex. « vélo » -> bicyclette).
            formes = list(dict.fromkeys((mot,) + SYNONYMES.get(mot, ())))
            for forme in formes:
                for i in index.get(forme, ()):  # O(1) par forme
                    s = scores.setdefault(i, {'score': 0.0, 'raisons': set()})
                    s['score'] += poids
                    if i in index_position.get(forme, set()):
                        s['score'] += poids * BONUS_POSITION
                        s['raisons'].add(f'position tarifaire contenant « {mot} »')
                    else:
                        s['raisons'].add(f'désignation contenant « {mot} »')
    if not scores:
        return {'statut': 'aucun_resultat', 'candidats': []}

    # Les codes CN8 (terminés par 00) sont des points d'entrée plus pertinents
    # que leurs subdivisions TARIC10 — léger bonus pour garder le code le plus
    # général en tête.
    def bonus(c: dict) -> float:
        return 0.5 if c['code10'].endswith('00') else 0.0

    tries = sorted(scores.items(),
                   key=lambda kv: (-(kv[1]['score'] + bonus(codes[kv[0]])), codes[kv[0]]['code10']))
    meilleur = tries[0][1]['score'] + bonus(codes[tries[0][0]])
    candidats = []
    for i, s in tries[:limite]:
        c = codes[i]
        relative = (s['score'] + bonus(c)) / meilleur if meilleur else 0.0
        candidats.append({
            'code': c['code'],
            'code10': c['code10'],
            'designation': c['designation'],
            'confiance': round(min(CONFIANCE_MAX, 0.15 + 0.45 * relative), 2),
            'raisons': sorted(s['raisons'])[:4],
            'taux_indicatif_droits': f"{c['taux_pays_tiers']:.3f}" if c['taux_pays_tiers'] is not None else None,
            'statut': 'propose',
        })
    return {'statut': 'candidats', 'candidats': candidats}
