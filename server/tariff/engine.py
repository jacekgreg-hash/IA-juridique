"""Moteur de classification tarifaire (§9, §10, §11, §31.3 du cahier des charges).

Principes :
* le moteur est SÉPARÉ de l'IA (§9) : il reçoit les faits identifiés (nature,
  matière, fonction...) et applique des règles déterministes sur une base
  tarifaire elle aussi séparée du code (§10, data/tariff/tariff_base.json) ;
* il peut retourner PLUSIEURS candidats quand une information manque (§9) ;
* il indique quelles informations permettraient de départager les candidats
  (§11) — le moteur d'orchestration en fait des questions ciblées (§31.3) ;
* jamais de code « confirmé » : le résultat est une PROPOSITION, la décision
  finale reste à l'utilisateur (§29) ;
* les taux affichés sont INDICATIFS et dépendent de l'origine (préférences UE,
  accords) — ils ne constituent pas un calcul fiscal (§16, moteur séparé).

L'« IA propose, les données officielles vérifient, le moteur tarifaire décide
et l'utilisateur conserve le contrôle. » (§29)
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from server.tariff.search import rechercher

_BASE_PATH = Path(__file__).resolve().parents[2] / 'data' / 'tariff' / 'tariff_base.json'

# Attribution des valeurs de discriminant : mots observés dans les preuves
# (caractéristiques enrichies, légende, OCR) -> valeur de la base tarifaire.
_DISCRIMINATORS = {
    'tige': (
        ('cuir', (r'\bcuir\b', r'\bleather\b')),
        ('textile', (r'\bmesh\b', r'\btoile\b', r'\btissu\b', r'\btextile\b', r'\bcanvas\b', r'\bmaill\w*\b')),
        ('plastique/caoutchouc', (r'\bplastique\b', r'\bplastic\b', r'\bcaoutchouc\b', r'\brubber\b')),
    ),
    'type_appareil': (
        ('smartphone', (r'\btactile\b', r'\btouchscreen\b', r'\btouch screen\b', r'\bsmartphone\b')),
        ('classique', (r'\bclavier\b', r'\bkeyboard\b', r'\bTouches\b', r'\bfeature phone\b')),
    ),
    'mouvement': (
        ('automatique', (r'\bautomatic\b', r'\bautomatique\b', r'\bremontage automatique\b', r'\bmécanique\b')),
        ('numerique', (r'\bnumérique\b', r'\bnumerique\b', r'\bdigital\b', r'\bLCD\b')),
        ('quartz', (r'\bquartz\b', r'\bpile\b', r'\bélectrique\b')),
    ),
    'matiere_principale': (
        ('bois', (r'\bbois\b', r'\bwood\b', r'\bchêne\b', r'\bhêtre\b', r'\bpin\b', r'\bmahogany\b', r'\bverni\b')),
        ('plastique', (r'\bplastique\b', r'\bplastic\b', r'\bPVC\b')),
        ('métal', (r'\bmétal\b', r'\bmetal\b', r'\bmétallique\b', r'\bacier\b', r'\bacier\b', r'\baluminium\b')),
    ),
}


@lru_cache(maxsize=1)
def load_base() -> dict:
    """Charge la base tarifaire (§10 : données séparées du code)."""
    with open(_BASE_PATH, encoding='utf-8') as f:
        return json.load(f)


def _family_for(nature: str) -> tuple[str, dict] | tuple[None, None]:
    nature = str(nature or '').strip().lower()
    base = load_base()
    for key, fam in base['familles'].items():
        if nature in [str(n).lower() for n in fam['natures']]:
            return key, fam
    return None, None


def _detect_discriminator(family_key: str, texts: list[str]) -> str | None:
    """Valeur du critère de départage, déterministe, à partir des preuves texte."""
    haystack = ' | '.join(str(t or '') for t in texts if t)
    for value, patterns in _DISCRIMINATORS.get(family_key, ()):
        for p in patterns:
            if re.search(p, haystack, flags=re.IGNORECASE):
                return value
    return None


def propose_classement(produit: dict, caption: str = '', ocr_text: list | None = None) -> dict:
    """Propose des positions tarifaires candidates (jamais une certitude).

    Entrée : le dict `produit` de la réponse d'analyse (objet, marque,
    caracteristiques...) + les preuves texte (légende, OCR)."""
    base = load_base()
    nature = str((produit or {}).get('objet') or '').strip().lower()
    family_key, family = _family_for(nature)
    result = {
        'statut': 'impossible',
        'principe': "Le moteur tarifaire classe à partir des faits identifiés; "
                    "le résultat est une proposition, la décision reste à l'utilisateur (§29).",
        'base_version': base.get('version'),
        'base_source': base.get('source'),
        'date_validite': base.get('date_validite'),
        'famille': None,
        'candidats': [],
        'questions': [],
        'informations_manquantes': [],
    }
    if not family:
        # Aucune famille codée ne correspond : essai par désignation dans la
        # nomenclature officielle (§9 : proposer des candidats plutôt que
        # d'abandonner) — preuve faible, à départager par l'utilisateur (§29).
        result['raison'] = 'nature de la marchandise inconnue ou hors familles couvertes par la base'
        texts = [nature,
                 str(produit.get('caracteristiques') or []),
                 str(produit.get('matiere_composition') or ''),
                 str(produit.get('usage_fonction') or ''),
                 caption] + list(ocr_text or [])
        recherche = rechercher(texts)
        if recherche['candidats']:
            result['statut'] = 'candidats_a_departager'
            result['candidats'] = recherche['candidats']
            result['recherche'] = recherche.get('source', 'designation')
            result['questions'] = [{'champ': 'nature',
                                   'question': 'Quelle est la nature précise de la marchandise ?',
                                   'impact': "confirme ou écarte les positions trouvées par recherche "
                                             'de désignation dans la nomenclature officielle'}]
            result['informations_manquantes'] = ['nature précise de la marchandise '
                                                 '(candidats issus d\'une recherche par désignation)']
        else:
            result['informations_manquantes'] = ['nature de la marchandise (aucune famille tarifaire ne peut être proposée sans elle)']
            if recherche.get('raison'):
                result['raison'] += ' ; ' + recherche['raison']
        return result

    result['famille'] = family_key
    discriminant = family['discriminant']
    texts = [caption] + list(ocr_text or []) + [str(produit.get('caracteristiques') or [])] \
        + [str(produit.get('matiere_composition') or '')] + [str(produit.get('usage_fonction') or '')]
    value = _detect_discriminator(discriminant, texts)

    cands = []
    for entry in family['codes']:
        score, raison = 0.30, 'nature de la marchandise cohérente avec cette position'
        if value and entry.get(discriminant) == value:
            score += 0.45
            raison = f'{discriminant} = « {value} », détecté dans les preuves'
        elif value and entry.get(discriminant):
            score -= 0.05
        cands.append({
            'code': entry['code'],
            'designation': entry['designation'],
            'confiance': round(max(0.0, min(0.9, score)), 2),
            'raisons': [raison],
            'taux_indicatif_droits': entry.get('taux_indicatif_droits'),
            'notes': entry.get('notes'),
            'statut': 'propose',
        })
    cands.sort(key=lambda c: (-c['confiance'], c['code']))

    result['candidats'] = cands
    if not value:
        # §11 + §31.3 : on n'invente pas, on demande le critère qui départage.
        question_text = family.get(f'question_{discriminant}') or f"Quelle est la valeur de « {discriminant} » ?"
        result['questions'] = [{'champ': discriminant, 'question': question_text,
                               'impact': 'permet de choisir entre les positions ' + ', '.join(c['code'] for c in cands)}]
        result['informations_manquantes'] = [discriminant]
        result['statut'] = 'candidats_a_departager'
    elif len(cands) >= 2 and cands[0]['confiance'] == cands[1]['confiance']:
        # Égalité parfaite : le discriminant identifié ne suffit pas à départager
        # les positions (ex. remontage automatique avec boîte précieuse => 9101
        # vs non précieuse => 9102). On demande le critère supplémentaire plutôt
        # que de trancher (§9 : candidats multiples, §29 : décision à l'utilisateur).
        codes = ', '.join(c['code'] for c in cands if c['confiance'] == cands[0]['confiance'])
        result['questions'] = [{'champ': 'criteres_complementaires',
                               'question': f"Plusieurs positions correspondent aux faits identifiés ({codes}) ; "
                                           "quel critère supplémentaire permet de les départager (examinez leurs désignations officielles) ?",
                               'impact': 'choix entre les positions ' + codes}]
        result['informations_manquantes'] = ['critère de départage entre les positions ' + codes]
        result['statut'] = 'candidats_a_departager'
    else:
        result['statut'] = 'candidat_dominant'
        result['informations_manquantes'] = []
    return result
