from pathlib import Path
import os

from server.vision.florence import analyze

image = Path(os.getenv('RITA_IMAGE', 'data/reference_images/NIKE-P-6000.jpg'))
print('FLORENCE_MODEL=', os.getenv('FLORENCE_MODEL', 'microsoft/Florence-2-base'))
print('IMAGE=', image.resolve())

result = analyze(image)
print('\n=== CAPTION ===')
print(result['caption_raw'])
print('\n=== OCR ===')
print(result['ocr_raw'])
print(f"\nTIME={result['fast_time']:.2f}s")
