"""Enrichissement déterministe de la sortie Florence, une fois l'OCR disponible.

Pourquoi ce module (V2.13.7) :
* Florence ne renvoie qu'une légende ; les champs `caracteristiques` et `couleurs`
  restaient vides, ce qui désactivait le bonus de caractéristiques, la 3e requête
  de recherche et l'indice structurel du moteur de candidats.
* La marque n'était cherchée que dans la légende ; sans marque, aucune requête
  externe n'était émise. On la cherche aussi dans le texte OCR.
* La légende brute (« The image shows a pair of ... on a white background »)
  faisait une très mauvaise requête de recherche.

Tout est déterministe et reste de l'evidence faible : rien ici ne propose de
modèle ni de référence, et rien n'est tarifaire.
"""
from __future__ import annotations

import re
from typing import Any

from server.utils.brands import find_brand

# Confiance de perception seule (Florence). Reste sous le plafond de 0.30 que
# `fuse()` applique aux preuves « vision ». Valeurs de départ à calibrer.
CONF_OBJET_SEUL = 0.15
CONF_OBJET_ET_MARQUE = 0.25

# Graine de vocabulaire (à étendre avec le catalogue / le banc d'essai).
_COLORS = (
    ('argenté', ('silver', 'argent', 'metallic silver')),
    ('noir', ('black', 'noir', 'noire')),
    ('blanc', ('white', 'blanc', 'blanche')),
    ('gris', ('gray', 'grey', 'gris', 'grise')),
    ('bleu', ('blue', 'navy', 'bleu', 'bleue')),
    ('rouge', ('red', 'rouge')),
    ('vert', ('green', 'vert', 'verte')),
    ('jaune', ('yellow', 'jaune')),
    ('orange', ('orange',)),
    ('rose', ('pink', 'rose')),
    ('marron', ('brown', 'marron')),
    ('beige', ('beige', 'tan', 'cream')),
    ('doré', ('gold', 'golden', 'doré', 'dore')),
)
_FEATURES = (
    ('mesh', ('mesh',)),
    ('cuir', ('leather', 'cuir')),
    ('daim', ('suede', 'daim')),
    ('toile', ('canvas', 'toile')),
    ('plastique', ('plastic', 'plastique')),
    ('métal', ('metal', 'metallic', 'métal', 'métallique')),
    ('caoutchouc', ('rubber', 'caoutchouc')),
    ('lacets', ('laces', 'lace', 'lacets', 'lacet')),
    ('semelle', ('sole', 'soles', 'semelle')),
    ('swoosh', ('swoosh',)),
    ('sangle', ('strap', 'straps', 'sangle')),
    ('fermeture éclair', ('zipper', 'zip', 'fermeture éclair')),
    ('capuche', ('hood', 'capuche')),
    ('écran', ('screen', 'display', 'écran')),
    ('bouton', ('button', 'buttons', 'bouton', 'boutons')),
    ('batterie', ('battery', 'batterie')),
    # V2.14.1 : matières fréquentes hors textile/chaussure
    ('bois', ('wood', 'wooden', 'bois')),
    ('verre', ('glass', 'verre')),
    ('rotin', ('rattan', 'rotin')),
    ('tissu', ('fabric', 'tissu', 'textile')),
    ('tiroirs', ('drawer', 'drawers', 'tiroir', 'tiroirs')),
)
# (motifs anglais/français dans la légende) -> catégorie française
# Ordre : du plus spécifique au plus générique (premier motif gagnant).
_OBJECTS = (
    (('sneaker', 'sneakers', 'trainer', 'trainers', 'running shoe', 'athletic shoe', 'basket', 'baskets'), 'chaussure de sport'),
    (('boot', 'boots', 'bottine', 'bottines'), 'botte'),
    (('shoe', 'shoes', 'chaussure', 'chaussures'), 'chaussure'),
    (('t-shirt', 'tshirt', 'shirt'), 'chemise ou t-shirt'),
    (('jacket', 'coat', 'veste', 'manteau'), 'veste'),
    (('pants', 'trousers', 'jean', 'jeans', 'pantalon'), 'pantalon'),
    (('dress', 'robe'), 'robe'),
    (('sweater', 'pullover', 'pull'), 'pull'),
    (('drill', 'perceuse'), 'perceuse'),
    (('smartphone', 'phone', 'téléphone', 'telephone'), 'téléphone'),
    (('headphone', 'headphones', 'earbuds', 'casque'), 'casque audio'),
    (('watch', 'montre'), 'montre'),
    (('bag', 'backpack', 'handbag', 'sac'), 'sac'),
    (('suitcase', 'luggage', 'valise'), 'valise'),
    # V2.14.1 : électroménager (micro-ondes avant four : « four micro-ondes »)
    (('microwave', 'micro-ondes', 'micro onde'), 'micro-ondes'),
    (('oven', 'cuisinière', 'cuisiniere'), 'four'),
    (('washing machine', 'machine à laver', 'machine a laver', 'lave-linge'), 'machine à laver'),
    (('fridge', 'refrigerator', 'réfrigérateur', 'refrigérateur', 'frigidaire'), 'réfrigérateur'),
    (('vacuum', 'aspirateur'), 'aspirateur'),
    (('coffee machine', 'espresso machine', 'machine à café', 'machine a cafe', 'cafetière'), 'machine à café'),
    (('kettle', 'bouilloire'), 'bouilloire'),
    (('mixer', 'blender', 'mixeur'), 'mixeur'),
    # V2.14.1 : informatique / image
    (('laptop', 'ordinateur portable', 'notebook', 'macbook'), 'ordinateur portable'),
    (('computer', 'ordinateur'), 'ordinateur'),
    (('tablet', 'tablette'), 'tablette'),
    (('television', 'télévision', 'televiseur'), 'télévision'),
    (('printer', 'imprimante'), 'imprimante'),
    (('keyboard', 'clavier'), 'clavier'),
    # V2.14.1 : meubles et décoration
    (('commode', 'dresser', 'chest of drawers'), 'commode'),
    (('armoire', 'wardrobe', 'closet'), 'armoire'),
    (('shelf', 'shelves', 'étagère', 'etagere', 'bookcase', 'bibliothèque'), 'étagère'),
    (('sofa', 'couch', 'canapé', 'canape'), 'canapé'),
    (('armchair', 'fauteuil'), 'fauteuil'),
    (('chair', 'chaise', 'chaises'), 'chaise'),
    (('table', 'tables'), 'table'),
    (('bed', 'lit'), 'lit'),
    (('mirror', 'miroir'), 'miroir'),
    (('lamp', 'lampe', 'luminaire'), 'lampe'),
    (('rug', 'carpet', 'tapis'), 'tapis'),
    (('furniture', 'meuble', 'meubles'), 'meuble'),
    # V2.14.1 : sport / jouets
    (('bicycle', 'bike', 'vélo', 'velo'), 'vélo'),
    (('racket', 'racquet', 'raquette'), 'raquette'),
    (('football', 'soccer ball', 'ballon'), 'ballon'),
    (('plush', 'teddy', 'peluche'), 'peluche'),
    (('toy', 'jouet', 'jouets'), 'jouet'),
)
_CLAUSE_CUT = re.compile(r"\s+(?:with|on|against|sitting|placed|in|that|which|featuring|has|having|showing|next to|beside)\s+", re.I)
_LEAD = re.compile(r"^(?:the\s+)?(?:image|picture|photo|photograph)\s+(?:shows|is|features|depicts|contains)\s+(?:(?:a|an)\s+(?:photograph|photo|picture)\s+of\s+)?", re.I)


def _has_word(text_low: str, word: str) -> bool:
    return re.search(r'(?<![a-zà-ÿ0-9])' + re.escape(word) + r'(?![a-zà-ÿ0-9])', text_low) is not None


def _collect(text_low: str, table) -> list[str]:
    out: list[str] = []
    for label, words in table:
        if any(_has_word(text_low, w) for w in words) and label not in out:
            out.append(label)
    return out


def short_object_phrase(caption: str, limit: int = 90) -> str | None:
    """Courte description de l'objet, coupée aux mots, sans le contexte (fond, support...)."""
    text = re.sub(r'\s+', ' ', str(caption or '')).strip()
    if not text:
        return None
    first = re.split(r'(?<=[.!?])\s+', text)[0].strip().rstrip('.!?')
    first = _LEAD.sub('', first)
    first = re.sub(r'^this\s+is\s+(?:a|an)\s+', '', first, flags=re.I)
    first = _CLAUSE_CUT.split(first, maxsplit=1)[0].strip() or first
    if len(first) > limit:
        first = first[:limit].rsplit(' ', 1)[0]
    return first or None


# V2.14.1 : « La photographie montre un téléphone » — le verbe « montre » ne doit
# pas être pris pour le nom « montre » (horlogerie). On neutralise la tournure de
# légende avant la catégorisation.
_SHOWS_VERB = re.compile(r"\b(?:la\s+(?:photographie|photo)|l'?image|cette\s+(?:photo|image)|la\s+figure)\s+montre\b", re.I)


def object_category(caption: str) -> str | None:
    low = _SHOWS_VERB.sub(' ', str(caption or '').lower())
    for words, label in _OBJECTS:
        if any(_has_word(low, w) for w in words):
            return label
    return None


def enrich_vision(fast: dict[str, Any], ocr_text: list[str]) -> dict[str, Any]:
    """Complète `fast` (sortie de `florence.analyze`) en place et le retourne.

    `fast['caption']` doit contenir la légende nettoyée (posé par `florence.analyze`)."""
    caption = str(fast.get('caption') or '')
    low = caption.lower()

    brand = fast.get('marque')
    source = 'legende' if brand else None
    if not brand:
        # 2e chance : le texte lu par l'OCR (« NIKE » sur la languette, etc.).
        brand = find_brand(' | '.join(ocr_text or []))
        source = 'ocr' if brand else None
    fast['marque'] = brand
    fast['marque_source'] = source

    phrase = short_object_phrase(caption)
    category = object_category(caption)
    fast['objet_legende'] = phrase
    fast['objet'] = category or phrase

    colors = _collect(low, _COLORS)
    fast['couleurs'] = colors
    features = _collect(low, _FEATURES)
    # Couleurs d'abord (les plus discriminantes dans le catalogue), puis matières/éléments.
    fast['caracteristiques'] = [*colors, *features][:8]

    # Texte visible = lignes OCR retenues (l'OCR reste une preuve, pas une décision).
    fast['texte_visible'] = list(ocr_text or [])[:5]

    if fast['objet']:
        fast['identification_confiance'] = CONF_OBJET_ET_MARQUE if (brand and source == 'legende') else CONF_OBJET_SEUL
    else:
        fast['identification_confiance'] = 0.0
    return fast
