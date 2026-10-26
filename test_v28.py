from pathlib import Path
from PIL import Image
from server.candidates.engine import image_similarity
from server.candidates.web_search import extract_identifiers

root = Path(__file__).resolve().parent
img = root / "data" / "reference_images" / "NIKE-P-6000.jpg"
assert "P-6000" in extract_identifiers("Chaussures Nike P-6000. Nike FR")
assert "1972" not in extract_identifiers("Né en 1972, Nike")
score, kind = image_similarity(Image.open(img), img)
assert score == 1.0 and kind == "doublon_exact"
print("OK V2.8 discriminatif: identifiants + visuel + tests de base")
