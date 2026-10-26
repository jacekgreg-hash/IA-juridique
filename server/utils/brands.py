"""Détection déterministe de marque, avec limites de mot.

Correctif V2.13.7 : l'ancienne version cherchait la marque par simple
sous-chaîne (« vans » dans « advanced », « lego » dans « elegant »).
Ici la marque doit être un mot entier (ou une suite de mots entiers).

La liste est un point de départ : elle est complétée à l'exécution par les
marques du catalogue local (voir `known_brands`).
"""
from __future__ import annotations

import re
from functools import lru_cache

SEED_BRANDS: tuple[str, ...] = (
    'Nike', 'Adidas', 'Puma', 'New Balance', 'ASICS', 'Reebok', 'Converse',
    'Vans', 'Under Armour', 'Apple', 'Samsung', 'Sony', 'Bosch', 'Makita',
    'DeWalt', 'Canon', 'Nikon', 'Lego', 'Dyson', 'Philips', 'Xiaomi',
    # V2.14.1 : horlogerie
    'Seiko', 'Casio', 'Citizen', 'Swatch', 'Tissot', 'Timex', 'Fossil',
    'Festina', 'Rolex',
    # V2.14.1 : téléphonie / électronique
    'Nokia', 'Motorola', 'OnePlus', 'Oppo', 'Alcatel', 'Wiko', 'HTC',
    'Fairphone', 'LG', 'Panasonic', 'Toshiba',
    # V2.14.1 : électroménager / cuisine
    'Siemens', 'Miele', 'Electrolux', 'Whirlpool', 'Indesit', 'Brandt',
    'Moulinex', 'Tefal', 'SEB', 'Rowenta', 'KitchenAid', 'Kenwood',
    'Nespresso', 'Krups', 'Russell Hobbs',
    # V2.14.1 : outillage
    'Hilti', 'Facom', 'Stanley', 'Milwaukee', 'Ryobi', 'Einhell', 'Metabo',
    'Black & Decker',
    # V2.14.1 : audio
    'JBL', 'Bose', 'Sennheiser', 'Beats', 'Marshall',
    # V2.14.1 : informatique
    'Lenovo', 'Asus', 'Acer', 'Dell', 'Logitech', 'Epson', 'TP-Link',
    # V2.14.1 : sport / mode
    'Salomon', 'Decathlon', 'Quechua', 'Wilson', 'Babolat', 'Mizuno',
    'Fila', 'Kappa', 'Umbro', 'Skechers', 'Lacoste', 'Ralph Lauren',
    "Levi's", 'Zara', 'Uniqlo', 'Timberland', 'Dr. Martens', 'Crocs',
    'Birkenstock', 'Columbia', 'Patagonia', 'Clarks',
    # V2.14.1 : meuble / déco / jouets
    'IKEA', 'Conforama', 'Maisons du Monde', 'Playmobil', 'Fisher-Price',
    'Hot Wheels', 'Ravensburger', 'Hasbro',
)


@lru_cache(maxsize=1)
def _catalog_brands() -> tuple[str, ...]:
    try:
        # Import tardif : évite toute dépendance circulaire au chargement.
        from server.candidates.engine import load_catalog
        return tuple(sorted({str(p.get('brand')).strip() for p in load_catalog() if p.get('brand')}))
    except Exception:
        return ()


def known_brands(extra: tuple[str, ...] | list[str] = ()) -> list[str]:
    seen: dict[str, str] = {}
    for b in (*SEED_BRANDS, *_catalog_brands(), *extra):
        b = str(b or '').strip()
        if b:
            seen.setdefault(b.lower(), b)
    return sorted(seen.values(), key=len, reverse=True)


def find_brand(text: str | None, extra: tuple[str, ...] | list[str] = ()) -> str | None:
    """Retourne la marque connue présente comme mot entier dans `text`, sinon None.

    Les marques les plus longues sont testées d'abord (« New Balance » avant « New »)."""
    text = str(text or '')
    if not text.strip():
        return None
    for brand in known_brands(extra):
        pattern = r'(?<![0-9A-Za-zÀ-ÿ])' + re.escape(brand).replace(r'\ ', r'\s+') + r'(?![0-9A-Za-zÀ-ÿ])'
        if re.search(pattern, text, flags=re.IGNORECASE):
            return brand
    return None
