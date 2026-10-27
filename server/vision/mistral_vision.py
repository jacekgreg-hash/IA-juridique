"""Moteur vision Mistral (API) — contrat identique à server/vision/florence.py.

Activable via VISION_ENGINE=mistral (voir server/vision/select.py).

Conformité au cahier des charges :
* §4 (IA interchangeable) : même contrat que Florence ; enrich.py, la fusion et
  les candidats restent inchangés ;
* §22 (coûts) : une analyse = exactement 1 appel vision ; le compteur de
  server/api/routes.py (meta.suivi_couts) suit les appels par analyse ;
* §9.1 du cahier général (protection des données) : vérifier les conditions de
  La Plateforme (rétention, réutilisation, localisation) avant d'y envoyer des
  photographies de clients.

Florence-2 reste le moteur local par défaut : ce module ne fait que proposer
une alternative de qualité, par analyse, sans toucher au reste de la chaîne.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps

from server.utils.brands import find_brand

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv('MISTRAL_VISION_MODEL', 'mistral-large-latest').strip()
API_URL = os.getenv('MISTRAL_VISION_URL', 'https://api.mistral.ai/v1/chat/completions').rstrip('/')
API_KEY = os.getenv('MISTRAL_API_KEY', '').strip()
TIMEOUT = float(os.getenv('MISTRAL_VISION_TIMEOUT', '60'))
MAX_SIDE = int(os.getenv('MISTRAL_VISION_MAX_SIDE', '1024'))
# Reproductibilité du banc d'essai (§26) : température 0 + graine fixe. L'API
# peut rester non déterministe côté serveur ; le banc mesure cette variance.
SEED = os.getenv('MISTRAL_VISION_SEED', '')

# La légende produite alimente le même enrichissement déterministe que Florence
# (server/vision/enrich.py). Aucun modèle ni référence n'est demandé ici :
# jamais d'invention pour compléter une fiche (§4.4 du cahier des charges RITA).
PROMPT = (
    "Décris précisément la marchandise visible sur cette photographie, pour aider à son "
    "identification douanière. Décris uniquement ce qui est visible : nature du produit, "
    "marque lisible, texte visible, couleurs, matières apparentes, caractéristiques "
    "distinctives, usage évident. N'invente aucune information absente de l'image. "
    "Réponds en une seule phrase complète, en français."
)


def prepare_image(path: Path) -> Image.Image:
    """Image redimensionnée, conservée localement pour le moteur de similarité."""
    image = ImageOps.exif_transpose(Image.open(path).convert('RGB'))
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    return image


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or 'image/jpeg'
    payload = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{payload}'


def analyze(path: Path) -> dict[str, Any]:
    if not API_KEY:
        raise RuntimeError('MISTRAL_API_KEY absente : nécessaire pour VISION_ENGINE=mistral')
    image = prepare_image(path)
    started = time.time()
    payload = {
        'model': MODEL_ID,
        'temperature': 0,
        'max_tokens': 220,
        'messages': [{
            'role': 'user',
            'content': [
                {'type': 'text', 'text': PROMPT},
                {'type': 'image_url', 'image_url': _data_url(path)},
            ],
        }],
    }
    if SEED:
        payload['random_seed'] = int(SEED)
    response = requests.post(
        API_URL,
        headers={'Authorization': f'Bearer {API_KEY}', 'Accept': 'application/json'},
        json=payload,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    caption = str(response.json()['choices'][0]['message']['content'] or '').strip()
    elapsed = time.time() - started
    logger.info('Mistral vision: %s en %.2fs', MODEL_ID, elapsed)
    return {
        'image': image,
        'fast': {
            'caption': caption,
            'objet': None,             # posé par server.vision.enrich.enrich_vision
            'marque': find_brand(caption),
            'texte_visible': [],
            'caracteristiques': [],
            'couleurs': [],
            'incertitudes': [],
            'modele': None,
            'reference': None,
            'modele_candidate': None,
            'reference_candidate': None,
        },
        'caption_raw': caption,
        'ocr_raw': '',
        'fast_time': elapsed,
        'model': MODEL_ID,
        'device': 'api',
    }
