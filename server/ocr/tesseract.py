import logging
import os
import re
from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance

logger = logging.getLogger(__name__)


def configure() -> str | None:
    try:
        import pytesseract
        candidates = [os.getenv('TESSERACT_CMD', ''), r'C:\Program Files\Tesseract-OCR\tesseract.exe']
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                pytesseract.pytesseract.tesseract_cmd = candidate
                return candidate
        return pytesseract.pytesseract.tesseract_cmd
    except Exception:
        return None


def _clean(line: str) -> str:
    line = re.sub(r'[^\wÀ-ÿ%+./\- ]', ' ', line, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', line).strip()


def _add(result, text):
    line = _clean(text)
    compact = re.sub(r'\W', '', line, flags=re.UNICODE)
    if len(compact) < 3 or len(line) > 80:
        return
    # Keep plausible product/reference codes, reject obvious OCR noise.
    if re.fullmatch(r'(.)\1{2,}', compact):
        return
    alpha = sum(c.isalpha() for c in line)
    digits = sum(c.isdigit() for c in line)
    if alpha + digits < 3:
        return
    if len(line.split()) > 8 and digits == 0:
        return
    if line not in result:
        result.append(line)


def ocr(path: Path) -> list[str]:
    """V2.9: one cheap full-image pass, then one targeted pass only for
    plausible product-code text. This avoids the 8-12 Tesseract passes of V2.8.
    """
    try:
        import pytesseract
        configure()
        img = ImageOps.exif_transpose(Image.open(path).convert('RGB'))
        if max(img.size) < 1400:
            img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
        result = []
        gray = ImageOps.grayscale(img)
        # Fast general pass.
        text = pytesseract.image_to_string(gray, lang='fra+eng', config='--psm 11')
        for line in text.splitlines():
            _add(result, line)
        # Targeted pass is only one additional OCR, on the central/heel area
        # where shoe labels and model codes commonly appear.
        w, h = gray.size
        crop = gray.crop((0, int(h * 0.18), w, int(h * 0.78)))
        crop = ImageEnhance.Contrast(crop).enhance(1.6)
        text = pytesseract.image_to_string(crop, lang='fra+eng', config='--psm 11')
        for line in text.splitlines():
            _add(result, line)
        return result[:20]
    except Exception:
        logger.warning("OCR failed for %s", path, exc_info=True)
        return []
