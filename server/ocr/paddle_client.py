from __future__ import annotations

import os
import time
from pathlib import Path

import requests

PADDLE_OCR_URL = os.getenv("PADDLE_OCR_URL", "http://127.0.0.1:8010").rstrip("/")
TIMEOUT = float(os.getenv("PADDLE_OCR_TIMEOUT", "30"))
# Les lignes dont le score de reconnaissance est inférieur sont écartées des preuves
# (elles restent visibles dans `ocr_details.rejetes` pour la traçabilité).
MIN_SCORE = float(os.getenv("PADDLE_OCR_MIN_SCORE", "0.50"))


def filter_by_score(texts: list[str], scores: list[float], min_score: float = MIN_SCORE):
    """Sépare (retenus, rejetés) selon le score. Sans score fourni, tout est retenu."""
    kept, rejected = [], []
    for i, text in enumerate(texts):
        text = str(text).strip()
        if not text:
            continue
        score = scores[i] if i < len(scores) else None
        if score is None or score >= min_score:
            kept.append((text, score))
        else:
            rejected.append((text, score))
    return kept, rejected


def ocr_detailed(path: Path) -> dict:
    started = time.perf_counter()
    try:
        # Corps binaire brut (le service n'utilise plus `cgi`, retiré de Python 3.13).
        response = requests.post(
            f"{PADDLE_OCR_URL}/ocr",
            data=path.read_bytes(),
            headers={"Content-Type": "application/octet-stream", "X-Filename": path.name},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        elapsed = time.perf_counter() - started
        texts = [str(x) for x in (payload.get("text") or [])]
        scores = [float(x) for x in (payload.get("scores") or [])]
        kept, rejected = filter_by_score(texts, scores)
        return {
            "text": [t for t, _ in kept],
            "scores": [s for _, s in kept if s is not None],
            "rejetes": [{"text": t, "score": s} for t, s in rejected],
            "seuil_score": MIN_SCORE,
            "time": float(payload.get("ocr_time", elapsed)),
            "service": payload.get("service", "paddleocr"),
            "variant": payload.get("variant", "original+fallback"),
            "error": None,
        }
    except Exception as exc:
        return {
            "text": [],
            "scores": [],
            "rejetes": [],
            "seuil_score": MIN_SCORE,
            "time": round(time.perf_counter() - started, 3),
            "service": "paddleocr",
            "variant": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def ocr(path: Path) -> list[str]:
    return ocr_detailed(path)["text"]
