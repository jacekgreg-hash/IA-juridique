"""Service OCR local RITA (PaddleOCR PP-OCRv5), à lancer avec Python 3.12.

V2.13.7 :
* plus de module `cgi` (retiré de Python 3.13) : le corps de la requête est l'image brute ;
* une seule instance PaddleOCR partagée => les prédictions sont sérialisées par un verrou ;
* le repli « agrandissement x2 » est plafonné (photo pleine résolution = mémoire) ;
* taille maximale du corps configurable (PADDLE_OCR_MAX_MB).

API :  POST /ocr   (Content-Type: application/octet-stream, en-tête X-Filename optionnel)
       GET  /health
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from paddleocr import PaddleOCR
from ocr_utils import clean_text as _clean_text, keep as _keep, fallback_scale as _fallback_scale

HOST = os.getenv("PADDLE_OCR_HOST", "127.0.0.1")
PORT = int(os.getenv("PADDLE_OCR_PORT", "8010"))
MAX_BYTES = int(float(os.getenv("PADDLE_OCR_MAX_MB", "25")) * 1024 * 1024)
FALLBACK_MAX_SIDE = int(os.getenv("PADDLE_OCR_FALLBACK_MAX_SIDE", "3200"))
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

print("[RITA][PaddleOCR] Loading PP-OCRv5...", flush=True)
_STARTED = time.perf_counter()
OCR = PaddleOCR(
    lang="fr",
    ocr_version="PP-OCRv5",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)
print(f"[RITA][PaddleOCR] Ready in {time.perf_counter()-_STARTED:.2f}s (lang=fr, PP-OCRv5)", flush=True)
_PREDICT_LOCK = threading.Lock()


def _extract(result):
    texts, scores = [], []
    try:
        items = list(result)
    except TypeError:
        items = [result]
    for item in items:
        data = None
        try:
            data = item.json
            if callable(data):
                data = data()
            if isinstance(data, str):
                data = json.loads(data)
        except Exception:
            pass
        if isinstance(data, dict):
            res = data.get("res", data)
            texts.extend(str(x) for x in (res.get("rec_texts") or []))
            scores.extend(float(x) for x in (res.get("rec_scores") or []))
            continue
        for attr in ("rec_texts", "texts"):
            try:
                vals = getattr(item, attr)
                if vals:
                    texts.extend(str(x) for x in vals)
                    break
            except Exception:
                pass
        for attr in ("rec_scores", "scores"):
            try:
                vals = getattr(item, attr)
                if vals:
                    scores.extend(float(x) for x in vals)
                    break
            except Exception:
                pass
    return texts, scores


def _run(path: Path):
    started = time.perf_counter()
    with _PREDICT_LOCK:  # instance unique : pas de prédictions concurrentes
        result = OCR.predict(str(path))
        texts, scores = _extract(result)
    return texts, scores, time.perf_counter() - started


def _run_with_fallback(path: Path):
    texts_all, scores_all = [], []
    total = 0.0
    variants = ["original"]
    first_error = None
    try:
        texts, scores, elapsed = _run(path)
        total += elapsed
        for text, score in zip(texts, scores or [1.0] * len(texts)):
            clean = _clean_text(text)
            if _keep(clean):
                texts_all.append(clean)
                scores_all.append(float(score))
    except Exception as exc:
        first_error = f"{type(exc).__name__}: {exc}"

    # Une passe de repli contrôlée pour les marquages petits/flous (recall, pas de seuil agressif).
    if not any(re.search(r"\d", t) for t in texts_all) or len(texts_all) < 2:
        try:
            from PIL import Image, ImageEnhance
            with Image.open(path).convert("RGB") as img:
                scale = _fallback_scale(img.width, img.height, FALLBACK_MAX_SIDE)
                if scale:
                    up = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
                    up = ImageEnhance.Contrast(up).enhance(1.25)
                    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                        fallback = Path(tmp.name)
                    up.save(fallback, format="PNG")
                else:
                    fallback = None
            if fallback is not None:
                try:
                    t2, s2, e2 = _run(fallback)
                    total += e2
                    variants.append(f"up{scale:.1f}x_contrast")
                    for text, score in zip(t2, s2 or [1.0] * len(t2)):
                        clean = _clean_text(text)
                        if _keep(clean) and clean not in texts_all:
                            texts_all.append(clean)
                            scores_all.append(float(score))
                finally:
                    fallback.unlink(missing_ok=True)
        except Exception:
            pass

    return texts_all[:20], scores_all[:20], total, "+".join(variants), first_error


class Handler(BaseHTTPRequestHandler):
    server_version = "RITA-PaddleOCR/1.1"

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._json(HTTPStatus.OK, {"status": "ok", "service": "RITA PaddleOCR", "port": PORT,
                                       "lang": "fr", "ocr_version": "PP-OCRv5"})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/ocr":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "corps vide : envoyer l'image brute"})
            return
        if length > MAX_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": f"image > {MAX_BYTES // (1024 * 1024)} Mo"})
            return
        try:
            body = self.rfile.read(length)
            suffix = Path(self.headers.get("X-Filename", "") or ".img").suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                suffix = ".jpg"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(body)
                path = Path(tmp.name)
            try:
                texts, scores, elapsed, variant, warning = _run_with_fallback(path)
            finally:
                path.unlink(missing_ok=True)
            payload = {
                "text": texts,
                "scores": scores,
                "ocr_time": round(elapsed, 3),
                "variant": variant,
                "service": "paddleocr-pp-ocrv5",
            }
            if warning:
                payload["warning"] = warning
            self._json(HTTPStatus.OK, payload)
        except Exception as exc:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(exc).__name__}: {exc}"})

    def log_message(self, fmt, *args):
        print(f"[RITA][PaddleOCR] {self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"[RITA][PaddleOCR] Listening on http://{HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
