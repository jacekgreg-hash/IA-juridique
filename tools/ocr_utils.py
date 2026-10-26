"""Fonctions pures du service OCR (testables sans PaddleOCR)."""
from __future__ import annotations

import re


def clean_text(value: str) -> str:
    value = re.sub(r"[^\wÀ-ÿ%+./\- ]", " ", str(value), flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def keep(text: str) -> bool:
    text = clean_text(text)
    compact = re.sub(r"\W", "", text, flags=re.UNICODE)
    if len(compact) < 2 or len(text) > 100:
        return False
    if re.fullmatch(r"(.)\1{2,}", compact):
        return False
    return sum(ch.isalpha() for ch in text) + sum(ch.isdigit() for ch in text) >= 2


def fallback_scale(width: int, height: int, max_side: int = 3200) -> float:
    """Facteur d'agrandissement du repli : 2x au plus, sans dépasser `max_side` sur le grand côté.

    Retourne 0.0 si l'agrandissement n'apporterait rien (image déjà grande)."""
    longest = max(int(width), int(height), 1)
    scale = min(2.0, max_side / longest)
    return scale if scale >= 1.2 else 0.0
