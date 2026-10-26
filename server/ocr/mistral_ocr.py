"""OCR via l'API Mistral OCR — contrat identique à server/ocr/paddle_client.py.

Activable via OCR_ENGINE=mistral (voir server/ocr/select.py).

Différence documentée avec PaddleOCR : Mistral OCR ne fournit pas de score de
confiance par ligne. ``scores`` est donc vide et ``seuil_score`` vaut None : le
client garde toutes les lignes (la traçabilité reste complète dans
``ocr_details.text``). Le filtrage par score reste une capacité du service
local Paddle uniquement.

Note coûts (§22) : environ 4 $ pour 1000 pages au tarif courant — à confirmer
sur La Plateforme. Une analyse = 1 page.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
import re
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

API_URL = os.getenv('MISTRAL_OCR_URL', 'https://api.mistral.ai/v1/ocr').rstrip('/')
MODEL_ID = os.getenv('MISTRAL_OCR_MODEL', 'mistral-ocr-latest').strip()
API_KEY = os.getenv('MISTRAL_API_KEY', '').strip()
TIMEOUT = float(os.getenv('MISTRAL_OCR_TIMEOUT', '30'))


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or 'image/jpeg'
    payload = base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{payload}'


# Artefacts d'images renvoyés par l'API (placeholders « ![](img-0.jpeg) » laissés
# quand include_image_base64=False) : jamais du texte lu sur la photo.
_IMAGE_RE = re.compile(r'!\[[^\]]*\]\([^)]*\)')


def _markdown_lines(markdown: str) -> list[str]:
    """Découpe le markdown retourné en lignes comparables aux lignes OCR.

    Les tableaux markdown sont séparés cellule par cellule pour retrouver des
    « lignes » exploitables par les extracteurs d'identifiants.
    """
    lines: list[str] = []
    for line in str(markdown or '').splitlines():
        line = _IMAGE_RE.sub(' ', line).strip()
        if line.startswith('|'):
            cells = [c.strip() for c in line.strip('|').split('|')]
        elif ' | ' in line:
            # cellules séparées hors tableau markdown : "P-6000 | NIKE" -> 2 lignes
            cells = [c.strip() for c in line.split(' | ')]
        else:
            cells = [line]
        for cell in cells:
            if len(cell) >= 2 and cell not in lines:
                lines.append(cell)
    return lines[:20]


def ocr_detailed(path: Path) -> dict:
    started = time.perf_counter()
    try:
        if not API_KEY:
            raise RuntimeError('MISTRAL_API_KEY absente : nécessaire pour OCR_ENGINE=mistral')
        response = requests.post(
            API_URL,
            headers={'Authorization': f'Bearer {API_KEY}', 'Accept': 'application/json'},
            json={
                'model': MODEL_ID,
                'document': {'type': 'image_url', 'image_url': _data_url(path)},
                'include_image_base64': False,
            },
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        pages = payload.get('pages') or []
        markdown = pages[0].get('markdown', '') if pages else ''
        text = _markdown_lines(markdown)
        elapsed = time.perf_counter() - started
        return {
            'text': text,
            'scores': [],          # pas de score par ligne côté Mistral OCR
            'rejetes': [],
            'seuil_score': None,
            'time': round(elapsed, 3),
            'service': 'mistral-ocr',
            'variant': 'markdown',
            'error': None,
        }
    except Exception as exc:
        logger.warning('Mistral OCR failed for %s', path, exc_info=True)
        return {
            'text': [],
            'scores': [],
            'rejetes': [],
            'seuil_score': None,
            'time': round(time.perf_counter() - started, 3),
            'service': 'mistral-ocr',
            'variant': None,
            'error': f'{type(exc).__name__}: {exc}',
        }


def ocr(path: Path) -> list[str]:
    return ocr_detailed(path)['text']
