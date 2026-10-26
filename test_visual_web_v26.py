from PIL import Image
from server.candidates.visual_web import compare

img = Image.new('RGB', (200, 200), (120, 120, 120))
assert compare(img, img) > 0.99
other = Image.new('RGB', (200, 200), (20, 20, 20))
assert compare(img, other) < compare(img, img)
print('OK V2.6 visual comparison')
