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
NOTES_PATH = Path(__file__).resolve().parents[2] / 'data' / 'tariff' / 'notes_cn_fr.json'

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

# Vocabulaire courant -> mots des NOTES EXPLICATIVES de la CN. Chaque entrée
# est ancrée dans un texte officiel, ex. : les bouilloires relèvent de
# « chaudières électriques qui produisent uniquement de l'eau chaude »
# (NENC, sous-positions 8516 10 11 et 8516 10 80).
SYNONYMES_NOTES = {
    'bouilloire': ('chaudiere',),
}

# Matières : elles sont utiles pour chercher dans les désignations mais NON
# pour départager des notes explicatives (les tubes « pour chaudières » en
# acier 7304 ne doivent pas devancer les chauffe-eau 8516 pour une bouilloire).
MATIERES = {
    'acier', 'inox', 'inoxydable', 'metal', 'metaux', 'plastique', 'bois', 'cuir', 'textile',
    'caoutchouc', 'verre', 'aluminium', 'cuivre', 'fonte', 'ceramique', 'porcelaine', 'carton',
    'papier', 'or', 'argent', 'bronze', 'laiton', 'zinc', 'titane', 'nylon', 'polyester', 'coton',
    'laine', 'soie', 'velours', 'daim', 'suede',
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
def _notes() -> tuple[list[dict], dict[str, list[int]]] | None:
    """Charge les notes explicatives de la CN (absentes = pas de second niveau)."""
    if not NOTES_PATH.exists():
        return None
    with open(NOTES_PATH, encoding='utf-8') as f:
        doc = json.load(f)
    segments = doc['segments']
    index: dict[str, list[int]] = {}
    for i, seg in enumerate(segments):
        vus = set()
        for mot in _vocabulaire(seg['texte']):
            if mot in vus:
                continue
            vus.add(mot)
            index.setdefault(mot, []).append(i)
    return segments, index


def _codes_segment(brut: str) -> tuple[list[str], list[tuple[str, str]]]:
    """« 8516 10 11 et 8516 10 80 » -> codes exacts ; « X à Y » -> plages.

    Les codes de niveau position tarifaire (4 chiffres, ex. « 8516 ») sont
    ignorés : trop larges pour proposer des candidats exploitables.
    """
    exacts: list[str] = []
    plages: list[tuple[str, str]] = []
    trouve = [(m.start(), m.end(), m.group(0).replace(' ', ''))
              for m in re.finditer(r'\b\d{4}(?: \d{2}){0,2}\b', brut)]
    k = 0
    while k < len(trouve):
        _debut, fin, code = trouve[k]
        pont = brut[fin:trouve[k + 1][0]] if k + 1 < len(trouve) else ''
        if 'à' in pont and k + 1 < len(trouve):
            if len(code) >= 6 and len(trouve[k + 1][2]) >= 6:
                plages.append((code.ljust(10, '0'), trouve[k + 1][2].ljust(10, '0')))
            k += 2
            continue
        if len(code) >= 6:
            exacts.append(code.ljust(10, '0'))
        k += 1
    return exacts, plages


def _rechercher_notes(textes: list[str], codes_nomenclature: list[dict],
                     carte: dict[str, dict], limite: int = 5) -> dict:
    """Second niveau de preuve : la nature absente des désignations officielles
    est cherchée dans les notes explicatives de la CN — textes officiels
    d'interprétation qui utilisent le vocabulaire courant.

    La granularité est la PHRASE : une note énumère souvent plusieurs exemples
    (« ... 1. les chauffe-eau...; 2. les chaudières électriques qui produisent
    uniquement de l'eau chaude ») et la phrase qui matche est la justification
    citée au candidat. Le mot de la nature (poids 2) domine ; la légende/OCR
    (poids 0,25, matières exclues) départage (« électrique » distingue la
    bouilloire 8516 des chaudières à vapeur 8402 ou des tubes 7304).
    """
    charge = _notes()
    if charge is None:
        return {'statut': 'aucun_resultat', 'candidats': []}
    segments, index = charge
    nature = _vocabulaire(textes[0]) if textes else []
    formes_nature: list[str] = []
    for mot in nature:
        formes_nature.extend(dict.fromkeys((mot,) + SYNONYMES_NOTES.get(mot, ())))
    if not formes_nature:
        return {'statut': 'aucun_resultat', 'candidats': []}
    secondaires = set()
    for t in textes[1:]:
        secondaires.update(_vocabulaire(t))
    secondaires -= MATIERES  # les matières ne départagent pas les notes

    seg_touches = set()
    for forme in formes_nature:
        seg_touches.update(index.get(forme, ()))
    phrases = []  # (score, index segment, phrase)
    for i in seg_touches:
        for phrase in re.split(r'(?<=[.;:!?])\s+', segments[i]['texte']):
            mots_phrase = set(_vocabulaire(phrase))
            if not any(f in mots_phrase for f in formes_nature):
                continue
            hits_sec = secondaires & mots_phrase
            # Proximité nature/secondaire : « chaudières électriques » (le
            # produit, 8516) doit battre « ...pour les centrales électriques »
            # (mention lointaine, 7304).
            tokens = [_normalise(m) for m in re.split(r'[^0-9a-zA-ZÀ-ÿ-]+', phrase)]
            pos_nature = [k for k, tk in enumerate(tokens) if tk in formes_nature]
            pos_sec = [k for k, tk in enumerate(tokens) if tk in secondaires]
            prox = 0.5 if pos_nature and pos_sec and \
                min(abs(a - b) for a in pos_nature for b in pos_sec) <= 2 else 0.0
            # Mention de contexte « pour/de/dans » devant la forme : le produit
            # n'est pas la chose nommée (tubes POUR chaudières, fours DE
            # cimenterie), le classement officiel la cite en passant.
            phrase_norm = ''.join(c for c in unicodedata.normalize('NFD', phrase.lower())
                                  if unicodedata.category(c) != 'Mn')
            contexte = -0.75 if re.search(
                r'\b(?:pour|dans|de)\s+(?:[a-z0-9-]+\s+)?(?:les\s+|la\s+|le\s+)?'
                r'(?:' + '|'.join(re.escape(f) for f in formes_nature) + r')\b',
                phrase_norm) else 0.0
            phrases.append((2.0 + 0.25 * len(hits_sec) + prox + contexte, i, phrase.strip()))
    if not phrases:
        return {'statut': 'aucun_resultat', 'candidats': []}
    phrases.sort(key=lambda p: (-p[0], p[1]))

    candidats = []
    vus_codes = set()
    for score, i, phrase in phrases:
        seg = segments[i]
        exacts, plages = _codes_segment(seg['codes'])
        entrees = []
        for c in exacts:
            if c in carte:
                entrees.append(carte[c])
            else:
                # Code CN8 subdivisé (ex. 8516 10 80) : proposer ses fils TARIC10.
                fils = sorted(k for k in carte if k.startswith(c[:8]) and k not in vus_codes)[:2]
                entrees.extend(carte[k] for k in fils)
        for c, fin in plages:
            entrees.extend(carte[code10] for code10 in sorted(carte)
                           if c <= code10 <= fin and code10 not in vus_codes)
        citation = phrase[:220] + ('…' if len(phrase) > 220 else '')
        for e in entrees[:3]:
            if e['code10'] in vus_codes:
                continue
            vus_codes.add(e['code10'])
            candidats.append({
                'code': e['code'],
                'code10': e['code10'],
                'designation': e['designation'],
                'confiance': round(min(0.45, 0.20 + 0.10 * score), 2),
                'raisons': [f'note explicative officielle de la CN (segment « {seg["codes"]} ») : '
                            f'« {citation} »'],
                'taux_indicatif_droits': f"{e['taux_pays_tiers']:.3f}" if e['taux_pays_tiers'] is not None else None,
                'statut': 'propose',
            })
        if len(candidats) >= limite:
            break
    if not candidats:
        return {'statut': 'aucun_resultat', 'candidats': []}
    return {'statut': 'candidats', 'source': 'notes_explicatives', 'candidats': candidats[:limite]}


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
    # n'utilise pas — on tente les NOTES EXPLICATIVES (textes officiels
    # d'interprétation, qui utilisent le vocabulaire courant) avant de refuser.
    if textes:
        nature = _vocabulaire(textes[0])
        if nature:
            trouve = any(any(index.get(forme, ()) for forme in
                             (mot,) + SYNONYMES.get(mot, ())) for mot in nature)
            if not trouve:
                carte = {c['code10']: c for c in codes}
                resultat_notes = _rechercher_notes(textes, codes, carte, limite)
                if resultat_notes['candidats']:
                    return resultat_notes
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
    return {'statut': 'candidats', 'source': 'designation', 'candidats': candidats}
