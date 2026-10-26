"""Sélecteur de moteur vision (§4 du cahier des charges : interchangeabilité).

VISION_ENGINE :
  * ``florence`` (défaut) : Florence-2-base en local — sans coût API, hors ligne ;
  * ``mistral``           : modèle vision hébergé via API (nécessite MISTRAL_API_KEY).

Le contrat (dict retourné par ``analyze``) est identique d'un moteur à l'autre :
voir ``server.vision.florence.analyze`` et ``server.vision.mistral_vision.analyze``.
``enrich.py``, la fusion et les candidats n'ont pas à savoir quel moteur a
produit la légende. C'est la validation concrète de l'exigence d'interchangeabilité.
"""
from __future__ import annotations
import os

ENGINE = os.getenv('VISION_ENGINE', 'florence').strip().lower()

if ENGINE == 'mistral':
    from server.vision.mistral_vision import analyze, MODEL_ID as MODEL
else:
    from server.vision.florence import analyze, MODEL_ID as MODEL
