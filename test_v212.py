import json
from pathlib import Path
from server.vision.ollama import analyze, MODEL
from server.ocr.tesseract import ocr

IMAGE = Path(__file__).resolve().parent / "data" / "reference_images" / "NIKE-P-6000.jpg"

if __name__ == "__main__":
    print(f"VISION_MODEL={MODEL}")
    print(f"IMAGE={IMAGE}")
    result = analyze(IMAGE)
    print("\
========== VISION LEGERE ==========")
    print(json.dumps(result["fast"], ensure_ascii=False, indent=2))
    print(f"Temps vision : {result['fast_time']:.2f} s")
    print("\
========== OCR ==========")
    print(json.dumps(ocr(IMAGE), ensure_ascii=False, indent=2))
