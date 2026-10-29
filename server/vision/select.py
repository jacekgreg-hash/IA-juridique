"""Sélecteur de moteur vision (§4 du cahier des charges : interchangeabilité).

VISION_ENGINE :
  * ``mistral`` (défaut) : modèle vision hébergé via API (nécessite MISTRAL_API_KEY) ;
  * ``florence``       : Florence-2-base en local — sans coût API, hors ligne.

Fallback automatique : si VISION_ENGINE=mistral mais que l'API Mistral est
inutilisable (clé absente, erreur réseau, timeout), le système bascule
automatiquement sur Florence avec un avertissement dans les logs et la
réponse API (meta.fallback_warning).

Le contrat (dict retourné par ``analyze``) est identique d'un moteur à l'autre :
voir ``server.vision.florence.analyze`` et ``server.vision.mistral_vision.analyze``.
``enrich.py``, la fusion et les candidats n'ont pas à savoir quel moteur a
produit la légende. C'est la validation concrète de l'exigence d'interchangeabilité.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Importation lazy pour permettre le fallback
_mistral_module = None
_florence_module = None

def _get_mistral():
    global _mistral_module
    if _mistral_module is None:
        try:
            from server.vision import mistral_vision
            _mistral_module = mistral_vision
        except Exception:
            _mistral_module = None
    return _mistral_module

def _get_florence():
    global _florence_module
    if _florence_module is None:
        try:
            from server.vision import florence
            _florence_module = florence
        except Exception:
            _florence_module = None
    return _florence_module

def analyze(path: Path) -> dict[str, Any]:
    """Analyse une image avec le moteur configuré, avec fallback sur florence.
    
    Si VISION_ENGINE=mistral mais que Mistral API est inutilisable,
    bascule automatiquement sur Florence et log un avertissement.
    La réponse inclut meta.vision_engine_used et meta.fallback_warning.
    """
    engine = os.getenv('VISION_ENGINE', 'mistral').strip().lower()
    fallback_warning = None
    engine_used = engine
    
    try:
        if engine == 'mistral':
            mistral = _get_mistral()
            if mistral is None:
                raise RuntimeError('Module mistral_vision non chargeable')
            result = mistral.analyze(path)
            engine_used = 'mistral'
        else:
            florence = _get_florence()
            if florence is None:
                raise RuntimeError('Module florence non chargeable')
            result = florence.analyze(path)
            engine_used = 'florence'
    except Exception as e:
        # Mistral a échoué, on bascule sur Florence
        if engine == 'mistral':
            logger.warning(
                f"Moteur vision Mistral API inutilisable "
                f"({type(e).__name__}: {str(e)}). "
                f"Basculé sur le moteur local Florence-2. "
                f"Vérifiez MISTRAL_API_KEY et votre connexion réseau."
            )
            fallback_warning = (
                "Attention : le moteur Mistral Vision API n'a pas pu être utilisé "
                f"({type(e).__name__}: {str(e)}). "
                "Analyse effectuée avec le moteur local Florence-2 (gratuit, hors ligne). "
                "Vérifiez votre clé API Mistral et votre connexion réseau."
            )
            # Essayer Florence
            try:
                florence = _get_florence()
                if florence is not None:
                    result = florence.analyze(path)
                    engine_used = 'florence (fallback)'
                else:
                    raise RuntimeError('Aucun moteur vision disponible (mistral échoué, florence non chargeable)')
            except Exception as e2:
                logger.error(
                    f"TOUS les moteurs vision sont inutilisables! "
                    f"Mistral: {type(e).__name__}, Florence: {type(e2).__name__}"
                )
                raise RuntimeError(
                    f"Aucun moteur vision disponible: Mistral ({type(e).__name__}), "
                    f"Florence ({type(e2).__name__})"
                ) from e
        else:
            # Engine = florence mais ça a échoué
            raise
    
    # Ajouter les métadonnées du moteur
    if 'meta' not in result:
        result['meta'] = {}
    result['meta']['vision_engine_used'] = engine_used
    result['meta']['vision_fallback_warning'] = fallback_warning
    
    return result
