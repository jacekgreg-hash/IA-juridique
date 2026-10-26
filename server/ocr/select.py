"""Sélecteur de moteur OCR (§6 du cahier des charges : OCR indépendant et interchangeable).

OCR_ENGINE :
  * ``paddle`` (défaut) : service local PaddleOCR (tools/paddle_ocr_service.py) ;
  * ``mistral``         : API Mistral OCR (nécessite MISTRAL_API_KEY).

Même contrat : ``ocr_detailed(path) -> dict`` avec les clés text, scores, rejetes,
seuil_score, time, service, variant, error. Différence documentée : Mistral OCR ne
fournit pas de score de confiance par ligne — ``scores`` est alors vide et
``seuil_score`` vaut None (toutes les lignes sont retournées ; le filtrage par
score reste une capacité du service local Paddle).
"""
from __future__ import annotations
import os

ENGINE = os.getenv('OCR_ENGINE', 'paddle').strip().lower()

if ENGINE == 'mistral':
    from server.ocr.mistral_ocr import ocr_detailed, ocr
else:
    from server.ocr.paddle_client import ocr_detailed, ocr
