"""Moteur de perception Florence-2 (légende uniquement ; l'OCR est fait par PaddleOCR).

V2.13.7 :
* torch / transformers sont importés à la demande (l'API et les tests unitaires
  démarrent sans eux) ;
* chargement du modèle protégé par un verrou et préchargeable au démarrage ;
* la génération est décodée SANS tokens spéciaux : avant, la légende commençait
  par « </s><s> » et polluait `objet` et les requêtes de recherche ;
* la marque est détectée avec limites de mot (voir server/utils/brands.py).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from server.utils.brands import find_brand

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv('FLORENCE_MODEL', 'microsoft/Florence-2-base')
DEVICE = os.getenv('FLORENCE_DEVICE', 'cpu')
DTYPE_NAME = os.getenv('FLORENCE_DTYPE', 'float32')
NUM_BEAMS = int(os.getenv('FLORENCE_NUM_BEAMS', '3'))

_processor = None
_model = None
_load_lock = threading.Lock()
_run_lock = threading.Lock()  # une seule génération à la fois (RAM/CPU limités)

_SPECIAL = re.compile(r'</?s>|<pad>|<unk>|<[A-Z_]{3,}>|<loc_\d+>')


def clean_generation(text: str) -> str:
    """Retire les tokens spéciaux résiduels et normalise les espaces."""
    text = _SPECIAL.sub(' ', str(text or ''))
    return re.sub(r'\s+', ' ', text).strip()


def _dtype():
    import torch
    if DTYPE_NAME == 'float16' and DEVICE != 'cpu':
        return torch.float16
    if DTYPE_NAME == 'bfloat16':
        return torch.bfloat16
    return torch.float32


def load_model():
    global _processor, _model
    if _processor is not None and _model is not None:
        return _processor, _model
    with _load_lock:
        if _processor is not None and _model is not None:
            return _processor, _model
        from transformers import AutoModelForCausalLM, AutoProcessor
        started = time.time()
        processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(MODEL_ID, trust_remote_code=True, torch_dtype=_dtype())
        model.to(DEVICE)
        model.eval()
        _processor, _model = processor, model
        logger.info('Florence chargé (%s, %s) en %.1fs', MODEL_ID, DEVICE, time.time() - started)
    return _processor, _model


def prepare_image(path: Path) -> Image.Image:
    image = ImageOps.exif_transpose(Image.open(path).convert('RGB'))
    image.thumbnail((768, 768), Image.Resampling.LANCZOS)
    return image


def run_task(image: Image.Image, task_prompt: str, max_new_tokens: int = 128) -> str:
    import torch
    processor, model = load_model()
    inputs = processor(text=task_prompt, images=image, return_tensors='pt')
    inputs = {k: v.to(DEVICE) if hasattr(v, 'to') else v for k, v in inputs.items()}
    with _run_lock, torch.inference_mode():
        generated_ids = model.generate(
            input_ids=inputs['input_ids'],
            pixel_values=inputs.get('pixel_values'),
            max_new_tokens=max_new_tokens,
            num_beams=NUM_BEAMS,
            do_sample=False,
        )
    return clean_generation(processor.batch_decode(generated_ids, skip_special_tokens=True)[0])


def _infer_brand(caption: str) -> str | None:
    """Marque explicitement présente (mot entier) dans la légende, sinon None."""
    return find_brand(caption)


def analyze(path: Path) -> dict[str, Any]:
    image = prepare_image(path)
    started = time.time()
    caption = run_task(image, '<MORE_DETAILED_CAPTION>', 128)
    elapsed = time.time() - started
    return {
        'image': image,
        'fast': {
            'caption': caption,
            'objet': None,             # posé par server.vision.enrich.enrich_vision
            'marque': _infer_brand(caption),
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
        'device': DEVICE,
    }
