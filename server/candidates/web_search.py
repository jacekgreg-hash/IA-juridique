from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

load_dotenv()
TIMEOUT = 15

@dataclass
class WebResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""

@dataclass
class ImageResult:
    title: str
    image_url: str
    page_url: str = ""
    thumbnail_url: str = ""
    source: str = ""
    width: int | None = None
    height: int | None = None

class SearXNGSearchProvider:
    name = "searxng_web"
    def __init__(self, base_url: str | None = None, count: int = 8, language: str = "fr-FR"):
        self.base_url = (base_url or os.getenv("SEARXNG_URL", "")).strip().rstrip("/")
        self.count = max(1, min(int(count), 20)); self.language = language
    @property
    def enabled(self) -> bool: return bool(self.base_url)
    def _request(self, query: str, categories: str):
        r=requests.get(f"{self.base_url}/search",params={"q":query[:600],"format":"json","language":self.language,"categories":categories,"safesearch":0},timeout=TIMEOUT)
        r.raise_for_status(); return r.json()
    def search(self, query: str) -> list[WebResult]:
        if not self.enabled or not query.strip(): return []
        data=self._request(query,"general"); out=[]
        for row in (data.get("results") or [])[:self.count]:
            url=str(row.get("url") or "").strip(); title=str(row.get("title") or "").strip()
            if url and title: out.append(WebResult(title,url,str(row.get("content") or "").strip(),str(row.get("engine") or urlparse(url).netloc.lower())))
        return out
    def image_search(self, query: str) -> list[ImageResult]:
        if not self.enabled or not query.strip(): return []
        data=self._request(query,"images"); out=[]
        for row in (data.get("results") or [])[:self.count]:
            iu=str(row.get("img_src") or "").strip()
            if not iu: continue
            res=row.get("resolution")
            out.append(ImageResult(str(row.get("title") or "").strip(),iu,str(row.get("url") or "").strip(),str(row.get("thumbnail_src") or row.get("thumbnail") or "").strip(),str(row.get("engine") or urlparse(str(row.get("url") or "")).netloc.lower()),res[0] if isinstance(res,list) and len(res)>0 else None,res[1] if isinstance(res,list) and len(res)>1 else None))
        return out

class BraveSearchProvider:
    name="brave_web_fallback"; BRAVE_URL="https://api.search.brave.com/res/v1/web/search"
    def __init__(self,api_key=None,country="fr",language="fr",count=8):
        self.api_key=api_key or os.getenv("BRAVE_SEARCH_API_KEY","").strip(); self.country=country; self.language=language; self.count=max(1,min(int(count),20))
    @property
    def enabled(self): return bool(self.api_key)
    def search(self,query):
        if not self.enabled or not query.strip(): return []
        r=requests.get(self.BRAVE_URL,headers={"Accept":"application/json","X-Subscription-Token":self.api_key},params={"q":query[:600],"count":self.count,"country":self.country,"search_lang":self.language},timeout=TIMEOUT); r.raise_for_status()
        rows=((r.json().get("web") or {}).get("results") or [])
        return [WebResult(str(x.get("title") or ""),str(x.get("url") or ""),str(x.get("description") or ""),urlparse(str(x.get("url") or "")).netloc.lower()) for x in rows if x.get("url") and x.get("title")]

def build_queries(vision: dict, ocr_text: list[str]) -> list[str]:
    brand=str(vision.get("marque") or "").strip()
    obj=str(vision.get("objet") or "").strip()
    chars=[str(x).strip() for x in (vision.get("caracteristiques") or []) if str(x).strip()]
    queries=[]
    if brand and obj:
        queries.append(" ".join([brand,obj,*chars[:2]]))
    if brand and ocr_text:
        for text in ocr_text:
            candidate=str(text).strip()
            if re.search(r"[A-Za-z]\s*[- ]\s*\d{2,}", candidate) or re.search(r"[A-Za-z]{1,6}\s+\d{2,}[A-Za-z0-9-]*", candidate):
                queries.append(f"{brand} {candidate}")
    if brand and chars:
        queries.append(" ".join([brand,*chars[:3]]))
    if not brand and obj:
        # V2.13.7 : sans marque (ni légende ni OCR), on tente quand même objet + caractéristiques,
        # puis objet + identifiant lu par l'OCR. Preuves faibles : `external.py` exige toujours la
        # marque pour créditer une preuve textuelle, donc ces résultats restent peu scorés.
        queries.append(" ".join([obj,*chars[:2]]))
        for text in ocr_text or []:
            candidate=str(text).strip()
            if re.search(r"[A-Za-z]\s*[- ]\s*\d{2,}", candidate) or re.search(r"[A-Za-z]{1,6}\s+\d{2,}[A-Za-z0-9-]*", candidate):
                queries.append(f"{obj} {candidate}")
    out=[]; seen=set()
    for q in queries:
        q=re.sub(r"\s+"," ",q).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower()); out.append(q[:300])
    return out[:3]

# Product-name hygiene: only coherent model forms are accepted. Bare years, numbers,
# snippets such as "de 100" and generic category text never become candidates.
#
# NOTE (generalisation V2.11): the patterns below were originally sneaker/Nike-specific
# (they only recognised Nike model-line names). RITA Vision must eventually cover shoes,
# clothing, electronics, toys, tools, auto parts, household items, etc. (see banc de test,
# section 26 du cahier des charges), so a brand-specific whitelist cannot be the only
# mechanism. Two brand-agnostic mechanisms were added below:
#   1. _CODE_PATTERNS: a generic "letters + separator + digits" identifier shape
#      (e.g. "GT-2000", "RS 750", "XR-450"), which covers reference-style model codes
#      across any product category, not just Nike's "P-xxxx" line.
#   2. _extract_named_candidate(): when a brand is known (passed in from the vision
#      output), extract the words immediately following the brand name in a title/snippet,
#      stopping at colour words, sizes, marketing noise or another digit-year. This works
#      for "Bosch GSR 18V-60", "Lego Technic 42115", "Adidas Samba OG", etc. without any
#      brand-specific list.
# The original Nike-line patterns are kept as a legacy boost (extra recall for the
# existing sneaker fixtures/tests) but are no longer the only path to a candidate model.
_MODEL_PATTERNS=(
    r"\bP[- ]?\d{3,4}\b",
    r"\bAir\s+(?:Max|Force|Zoom|Pegasus|Jordan)\s+[A-Za-z0-9][A-Za-z0-9 .-]{1,35}",
    r"\b(?:Dunk|Cortez|Blazer|Vomero|Invincible|Structure|Infinity)\s+[A-Za-z0-9][A-Za-z0-9 .-]{1,30}",
)

# Generic reference/model-code shape, brand- and category-agnostic. A separator between
# the letters and the digits is required so that plain SKU-looking blobs like "CN0149"
# or "CN0149-001" (no letter/digit separator) are not mistaken for a model name.
# Matched case-sensitively (no re.I) and restricted to UPPERCASE letters: real product
# codes ("GT-2000", "XR-450") are written in caps, which also keeps this from matching
# ordinary capitalised words or brand names followed by a year/number, e.g. "Nike 2026"
# or the French preposition in "de 100".
_CODE_PATTERNS=(
    r"\b[A-Z]{1,4}[- ]\d{3,6}\b",
)

# Words that end a "brand + model" phrase across product categories (colours, sizes,
# marketing/e-commerce noise, in French and English since listings mix languages).
_STOPWORDS_AFTER_MODEL={
    "noir","noire","blanc","blanche","bleu","bleue","rouge","vert","verte","gris","grise",
    "jaune","orange","rose","marron","beige","argent","argenté","argente","or","doré","dore",
    "black","white","blue","red","green","grey","gray","silver","gold","metallic","navy",
    "homme","femme","enfant","unisexe","junior","adulte","men","women","kids","unisex",
    "taille","tailles","pointure","size","sizes",
    "pas","cher","chere","soldes","promo","promotion","destockage","neuf","occasion",
    "original","originale","authentique","new","sale","deal",
    "avis","test","prix","price","livraison","gratuite","garantie","warranty",
    "edition","édition","edition.","chaussure","chaussures","vetement","vêtement","article",
    # V2.13.7 : termes de catégorie/marketing qui, juste après la marque, produisaient de faux
    # « modèles » (ex. « Nike Sportswear » -> « Sportswear »).
    "sportswear","running","lifestyle","sneaker","sneakers","baskets","basket","trainers","training",
    "collection","officiel","officielle","official","boutique","shop","store","site","france",
    "nouveautes","nouveautés","nouveau","nouvelle","catalogue","magasin","accueil","home",
}

def _norm_model(value: str) -> str:
    v=re.sub(r"\s+"," ",str(value or "")).strip(" -–—,.;:()[]")
    v=re.sub(r"\b(202\d|19\d\d|20\d\d)\b","",v)
    v=re.sub(r"\s+"," ",v).strip()
    v=re.split(r"\s[-–—]\s", v, maxsplit=1)[0].strip()
    return v

def _extract_named_candidate(text: str, brand: str) -> str | None:
    """Brand-agnostic fallback: capture the words right after the brand name in a
    title/snippet, stopping at the first colour/size/marketing stopword, another
    occurrence of the brand itself, a bare year, or after 3 words — whichever comes
    first. Works for any brand/category, unlike the Nike-specific regex list above."""
    brand=str(brand or "").strip()
    if not brand:
        return None
    m=re.search(rf"\b{re.escape(brand)}\b\s+([A-Za-z0-9][\w .\-]{{1,60}})", text, flags=re.I|re.UNICODE)
    if not m:
        return None
    brand_clean=re.sub(r"[^\w]","",brand).lower()
    kept=[]
    for word in re.split(r"\s+", m.group(1).strip()):
        w=re.sub(r"[^\wÀ-ÖØ-öø-ÿ]","",word).lower()
        if not w:
            break
        if w in _STOPWORDS_AFTER_MODEL or w == brand_clean:
            break
        if re.fullmatch(r"(19|20)\d{2}", w):
            break
        if w.isdigit() and len(w) > 6:  # looks like a price/barcode, not a model number
            break
        kept.append(word)
        if len(kept) >= 3:
            break
    if not kept:
        return None
    candidate=_norm_model(" ".join(kept))
    if len(candidate) < 3 or re.fullmatch(r"\d+", candidate):
        return None
    return candidate

def extract_product_models(text: str, brand: str = "") -> list[str]:
    text=str(text or ""); found=[]
    for p in _MODEL_PATTERNS:
        for m in re.findall(p,text,flags=re.I):
            v=_norm_model(m)
            if len(v)<3 or re.fullmatch(r"\d+",v): continue
            # Reject fragments ending in obvious prose/numbers.
            if re.search(r"\b(?:de|en|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s*$",v,re.I): continue
            if v.lower() not in {x.lower() for x in found}: found.append(v)
    for p in _CODE_PATTERNS:
        for m in re.findall(p,text):  # case-sensitive on purpose, see comment above
            v=_norm_model(m)
            if len(v)<3 or re.fullmatch(r"\d+",v): continue
            if v.lower() not in {x.lower() for x in found}: found.append(v)
    named=_extract_named_candidate(text, brand)
    if named and named.lower() not in {x.lower() for x in found}:
        found.append(named)
    return found[:8]

def extract_identifiers(text: str, brand: str = "") -> list[str]:
    # Backward-compatible alias; V2.10 now returns product-model candidates only.
    return extract_product_models(text, brand)

# Category-agnostic reputable-retailer signal. Sneaker-specific domains are kept as a
# legacy boost, but the function no longer treats "not a sneaker site" as automatically
# low-trust — see domain_weight(url, brand) for the brand-aware, category-agnostic path.
_KNOWN_SNEAKER_DOMAINS=("nike.","adidas.","puma.","newbalance.","asics.","snipes.","courir.","footlocker.","zalando.")

def domain_weight(url: str, brand: str = "") -> float:
    host=urlparse(url).netloc.lower()
    brand_clean=re.sub(r"[^a-z0-9]","",str(brand or "").lower())
    # Brand-agnostic: the manufacturer's own domain (any brand) is the strongest signal.
    if brand_clean and (host==f"{brand_clean}.com" or host.endswith(f".{brand_clean}.com") or host==f"{brand_clean}.fr" or host.endswith(f".{brand_clean}.fr")):
        return 1.0
    if any(x in host for x in _KNOWN_SNEAKER_DOMAINS): return .85
    # Generic large/known e-commerce marketplaces are a moderate signal regardless of category.
    if any(x in host for x in ("amazon.","fnac.","cdiscount.","darty.","boulanger.","manomano.","leroymerlin.")): return .7
    if host.endswith(".fr"): return .55
    return .45
