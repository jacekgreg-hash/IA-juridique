"""Sélecteur de moteur OCR (§6 du cahier des charges : OCR indépendant et interchangeable).

OCR_ENGINE :
  * ``mistral`` (défaut) : API Mistral OCR (nécessite MISTRAL_API_KEY) ;
  * ``paddle``         : service local PaddleOCR (tools/paddle_ocr_service.py).

Fallback automatique : si OCR_ENGINE=mistral mais que l'API Mistral est
inutilisable (clé absente, erreur réseau, timeout), le système bascule
automatiquement sur PaddleOCR avec un avertissement dans les logs et la
réponse API (meta.ocr_engine_used, meta.ocr_fallback_warning).

Même contrat : ``ocr_detailed(path) -> dict`` avec les clés text, scores, rejetes,
seuil_score, time, service, variant, error. Différence documentée : Mistral OCR ne
fournit pas de score de confiance par ligne — ``scores`` est alors vide et
``seuil_score`` vaut None (toutes les lignes sont retournées ; le filtrage par
score reste une capacité du service local Paddle).
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Importation lazy pour permettre le fallback
_mistral_module = None
_paddle_module = None

def _get_mistral():
    global _mistral_module
    if _mistral_module is None:
        try:
            from server.ocr import mistral_ocr
            _mistral_module = mistral_ocr
        except Exception:
            _mistral_module = None
    return _mistral_module

def _get_paddle():
    global _paddle_module
    if _paddle_module is None:
        try:
            from server.ocr import paddle_client
            _paddle_module = paddle_client
        except Exception:
            _paddle_module = None
    return _paddle_module

def ocr_detailed(path: Path) -> dict[str, Any]:
    """OCR détaillé avec le moteur configuré, avec fallback sur paddle.
    
    Si OCR_ENGINE=mistral mais que Mistral API est inutilisable,
    bascule automatiquement sur PaddleOCR et log un avertissement.
    La réponse inclut meta.ocr_engine_used et meta.ocr_fallback_warning.
    """
    engine = os.getenv('OCR_ENGINE', 'mistral').strip().lower()
    fallback_warning = None
    engine_used = engine
    
    try:
        if engine == 'mistral':
            mistral = _get_mistral()
            if mistral is None:
                raise RuntimeError('Module mistral_ocr non chargeable')
            result = mistral.ocr_detailed(path)
            # Mistral OCR retourne 'error' dans le dict si échec
            if result.get('error'):
                raise RuntimeError(result['error'])
            engine_used = 'mistral'
        else:
            paddle = _get_paddle()
            if paddle is None:
                raise RuntimeError('Module paddle_client non chargeable')
            result = paddle.ocr_detailed(path)
            engine_used = 'paddle'
    except Exception as e:
        # Mistral a échoué, on bascule sur Paddle
        if engine == 'mistral':
            logger.warning(
                f"Moteur OCR Mistral API inutilisable "
                f"({type(e).__name__}: {str(e)}). "
                f"Basculé sur le moteur local PaddleOCR. "
                f"Vérifiez MISTRAL_API_KEY et votre connexion réseau."
            )
            fallback_warning = (
                "Attention : le moteur Mistral OCR API n'a pas pu être utilisé "
                f"({type(e).__name__}: {str(e)}). "
                "OCR effectuée avec le moteur local PaddleOCR (gratuit, hors ligne). "
                "Vérifiez votre clé API Mistral et votre connexion réseau."
            )
            # Essayer Paddle
            try:
                paddle = _get_paddle()
                if paddle is not None:
                    result = paddle.ocr_detailed(path)
                    engine_used = 'paddle (fallback)'
                else:
                    raise RuntimeError('Aucun moteur OCR disponible (mistral échoué, paddle non chargeable)')
            except Exception as e2:
                logger.error(
                    f"TOUS les moteurs OCR sont inutilisables! "
                    f"Mistral: {type(e).__name__}, Paddle: {type(e2).__name__}"
                )
                raise RuntimeError(
                    f"Aucun moteur OCR disponible: Mistral ({type(e).__name__}), "
                    f"Paddle ({type(e2).__name__})"
                ) from e
        else:
            # Engine = paddle mais ça a échoué
            raise
    
    # Ajouter les métadonnées du moteur
    if 'meta' not in result:
        result['meta'] = {}
    result['meta']['ocr_engine_used'] = engine_used
    result['meta']['ocr_fallback_warning'] = fallback_warning
    
    return result

def ocr(path: Path) -> list[str]:
    """OCR simple (texte seulement) avec fallback."""
    return ocr_detailed(path)['text']
