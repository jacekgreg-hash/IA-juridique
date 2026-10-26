from __future__ import annotations
import json, logging, re
from pathlib import Path
from difflib import SequenceMatcher
from PIL import Image, ImageOps, ImageStat, ImageFilter

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
CATALOG_PATH = BASE_DIR / 'data' / 'catalog' / 'products.json'
REFERENCE_DIR = BASE_DIR / 'data' / 'reference_images'


def clean(value: str | None) -> str:
    return re.sub(r'[^A-Z0-9]+', '', str(value or '').upper())

def tokens(value: str | None) -> set[str]:
    return {x for x in re.findall(r'[A-Z0-9À-ÿ]+', str(value or '').upper()) if len(x) >= 2}

def similarity(a: str | None, b: str | None) -> float:
    a, b = clean(a), clean(b)
    if not a or not b: return 0.0
    if a == b: return 1.0
    return SequenceMatcher(None, a, b).ratio()

def list_similarity(a: list[str], b: list[str]) -> float:
    aa, bb = tokens(' '.join(a or [])), tokens(' '.join(b or []))
    return len(aa & bb) / max(1, len(aa | bb)) if aa and bb else 0.0

def _ahash(im, size=16):
    g = ImageOps.grayscale(im).resize((size,size), Image.Resampling.BILINEAR)
    v=list(g.getdata()); m=sum(v)/len(v)
    return [x>=m for x in v]

def _phash(im, size=32):
    g=ImageOps.grayscale(im).resize((size,size), Image.Resampling.BILINEAR)
    m=ImageStat.Stat(g).mean[0]
    return [(x-m)/128.0 for x in g.getdata()]

def _cos(a,b):
    d=sum(x*y for x,y in zip(a,b)); na=sum(x*x for x in a)**.5; nb=sum(y*y for y in b)**.5
    return 0.0 if not na or not nb else max(0,min(1,(d/(na*nb)+1)/2))

def _edges(im,size=32):
    g=ImageOps.grayscale(im).resize((size,size), Image.Resampling.BILINEAR).filter(ImageFilter.FIND_EDGES)
    v=list(g.getdata()); m=sum(v)/len(v)
    return [x>=m*1.25 for x in v]

def _edge_sim(a,b): return 1-sum(x!=y for x,y in zip(_edges(a),_edges(b)))/1024

def _hist(im,bins=8):
    im=im.convert('RGB').resize((64,64),Image.Resampling.BILINEAR); h=[0.0]*(bins*3)
    for r,g,b in im.getdata():
        h[r*bins//256]+=1; h[bins+g*bins//256]+=1; h[2*bins+b*bins//256]+=1
    return [x/4096 for x in h]

def _hist_i(a,b): return max(0,min(1,sum(min(x,y) for x,y in zip(a,b))/3))

def _crop_set(im):
    w,h=im.size
    return {
        'centre': im.crop((int(.15*w),int(.18*h),int(.85*w),int(.82*h))),
        'bas': im.crop((int(.08*w),int(.55*h),int(.92*w),h)),
        'gauche': im.crop((0,int(.20*h),int(.62*w),int(.88*h))),
        'droite': im.crop((int(.38*w),int(.20*h),w,int(.88*h))),
    }

def visual_feature_scores(query, candidate):
    q=ImageOps.exif_transpose(query.convert('RGB')); c=ImageOps.exif_transpose(candidate.convert('RGB'))
    ah=1-sum(a!=b for a,b in zip(_ahash(q),_ahash(c)))/256
    ph=_cos(_phash(q),_phash(c)); structure=_edge_sim(q,c); colors=_hist_i(_hist(q),_hist(c))
    ql=ImageStat.Stat(ImageOps.grayscale(q).resize((32,32))).mean[0]; cl=ImageStat.Stat(ImageOps.grayscale(c).resize((32,32))).mean[0]
    lum=max(0,1-abs(ql-cl)/255)
    qc=_crop_set(q); cc=_crop_set(c); crop_scores=[]
    for name in qc:
        a,b=qc[name],cc[name]
        crop_scores.append(.55*_edge_sim(a,b)+.25*_cos(_phash(a),_phash(b))+.20*_hist_i(_hist(a),_hist(b)))
    local=max(crop_scores) if crop_scores else 0.0
    local_avg=sum(crop_scores)/len(crop_scores) if crop_scores else 0.0
    return {'ahash':ah,'structure':structure,'couleurs':colors,'luminance':lum,'phash_coarse':ph,'local_max':local,'local_moyenne':local_avg}

def image_similarity(query, candidate_path):
    try:
        ref=ImageOps.exif_transpose(Image.open(candidate_path).convert('RGB')); q=ImageOps.exif_transpose(query.convert('RGB'))
        if q.size==ref.size and list(q.getdata())==list(ref.getdata()): return 1.0,'doublon_exact'
        f=visual_feature_scores(q,ref)
        score=.12*f['ahash']+.28*f['structure']+.15*f['couleurs']+.15*f['phash_coarse']+.05*f['luminance']+.25*f['local_max']
        return max(0,min(1,score)),'visuel_multicritere_local'
    except Exception:
        logger.warning("Image similarity failed for reference %s", candidate_path, exc_info=True)
        return 0.0,'indisponible'


def load_catalog(): return json.loads(CATALOG_PATH.read_text(encoding='utf-8')).get('products',[])

def _feature_token_score(query_chars, profile):
    q=tokens(' '.join(query_chars or [])); p=tokens(' '.join(profile or []))
    if not q or not p: return 0.0, []
    hits=sorted(q & p)
    return len(hits)/max(1,len(q)), hits

def search_candidates(query_image, vision, ocr_text, limit=5):
    products=load_catalog(); results=[]
    qbrand=clean(vision.get('marque')); qobject=tokens(vision.get('objet')); qchars=vision.get('caracteristiques') or []
    for product in products:
        score=0.0; reasons=[]; contradictions=[]
        brand=clean(product.get('brand'))
        if qbrand and brand:
            if qbrand==brand: score+=.16; reasons.append('marque concordante')
            else: contradictions.append('marque différente'); score-=.10
        pobj=tokens(product.get('object'))
        if qobject and pobj:
            overlap=len(qobject&pobj)/max(1,len(qobject|pobj)); score+=.10*overlap
            if overlap>=.25: reasons.append('nature compatible')
        # Independent OCR is strong only when it actually resembles a catalog identifier.
        ident_best=0; ident_source=None; ident_seen=None
        for text in ocr_text or []:
            for val in (product.get('reference'), product.get('model')):
                if val:
                    s=similarity(text,val)
                    if s>ident_best: ident_best,ident_source,ident_seen=s,'ocr',text
        if ident_source:
            if ident_best>=.96: score+=.48; reasons.append('identifiant concordant (ocr)')
            elif ident_best>=.82: score+=.26; reasons.append('identifiant proche (ocr)')
        # Vision characteristics are descriptive evidence, never a model claim.
        profile=product.get('visual_profile') or product.get('characteristics') or []
        fs,hits=_feature_token_score(qchars,profile)
        if fs>=.45: score+=.22; reasons.append(f'caractéristiques distinctives concordantes ({fs:.2f})')
        elif fs>=.25: score+=.10; reasons.append(f'caractéristiques compatibles ({fs:.2f})')
        visual=0.0; vtype='indisponible'; features={}
        if product.get('image'):
            ref_path=REFERENCE_DIR/product['image']; visual,vtype=image_similarity(query_image,ref_path)
            try:
                with Image.open(ref_path) as ref: features=visual_feature_scores(query_image,ref)
            except Exception: pass
        if vtype=='doublon_exact': score+=.55; reasons.append('photo identique à une référence catalogue')
        elif visual>=.90: score+=.12; reasons.append(f'concordance visuelle forte et locale ({visual:.2f})')
        elif visual>=.82: score+=.10; reasons.append(f'concordance visuelle compatible ({visual:.2f})')
        elif visual>=.72: score+=.05; reasons.append(f'similarité visuelle modérée ({visual:.2f})')
        elif visual>=.62: score+=.03; reasons.append(f'similarité visuelle faible ({visual:.2f})')
        # Generic structural hint: any catalogue product whose own model code is
        # explicitly present, verbatim, among the characteristics/OCR tokens gets a
        # small boost. (Previously this was hardcoded to a single test SKU, "P-6000" —
        # that only ever helped one fixture and would silently do nothing for any other
        # product added to the catalogue.)
        model_code=str(product.get('model') or '').strip().lower()
        if model_code and any(model_code in str(x).lower() for x in qchars):
            score+=.08; reasons.append(f"indice structurel explicite {product.get('model')}")
        score=max(0,min(1,score))
        results.append({'id':product.get('id'),'marque':product.get('brand'),'objet':product.get('object'),'modele':product.get('model'),'reference':product.get('reference'),'source':product.get('source','catalogue_local'),'score':round(score,3),'raisons':reasons,'contradictions':contradictions,'preuve_identifiant':ident_seen,'preuve_identifiant_source':ident_source,'similarite_image':round(visual,3),'type_preuve_visuelle':vtype,'details_visuels':{k:round(v,3) for k,v in features.items()}})
    results.sort(key=lambda x:x['score'],reverse=True)
    return results[:limit]
