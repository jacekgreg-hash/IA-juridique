from __future__ import annotations
import hashlib, io, ipaddress, logging, os, socket, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from PIL import Image, ImageOps, ImageStat, ImageFilter
from server.candidates.web_search import ImageResult
from server.candidates.engine import visual_feature_scores

logger = logging.getLogger(__name__)

CACHE_DIR=Path(__file__).resolve().parents[2]/'data'/'web_image_cache'; CACHE_DIR.mkdir(parents=True,exist_ok=True)
MAX_BYTES=2_000_000; TIMEOUT=12; MAX_REDIRECTS=3
# Cache : les images web sont des copies temporaires de travail, pas une base d'images.
CACHE_MAX_FILES=int(os.getenv('WEB_IMAGE_CACHE_MAX_FILES','300'))
CACHE_MAX_AGE_DAYS=float(os.getenv('WEB_IMAGE_CACHE_MAX_AGE_DAYS','7'))
_purged=False

def _key(url): return CACHE_DIR/(hashlib.sha256(url.encode('utf-8')).hexdigest()+'.jpg')

def is_public_url(url):
    """Garde anti-SSRF : http(s) uniquement, et tous les IP résolus doivent être publics.

    Limite connue : un rebinding DNS entre cette vérification et la requête reste possible ;
    à durcir (résolveur/egress dédié) avant toute exposition hors poste local."""
    try:
        parsed=urlparse(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname: return False
        for info in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),proto=socket.IPPROTO_TCP):
            ip=ipaddress.ip_address(info[4][0])
            if not ip.is_global: return False
        return True
    except Exception:
        return False

def purge_cache(max_files=None,max_age_days=None):
    """Supprime les fichiers trop anciens puis les plus anciens au-delà de `max_files`."""
    max_files=CACHE_MAX_FILES if max_files is None else max_files
    max_age_days=CACHE_MAX_AGE_DAYS if max_age_days is None else max_age_days
    removed=0
    try:
        files=sorted((f for f in CACHE_DIR.glob('*.jpg') if f.is_file()),key=lambda f:f.stat().st_mtime)
        limit=time.time()-max_age_days*86400
        keep=[]
        for f in files:
            if f.stat().st_mtime<limit: f.unlink(missing_ok=True); removed+=1
            else: keep.append(f)
        for f in keep[:max(0,len(keep)-max_files)]:
            f.unlink(missing_ok=True); removed+=1
    except Exception:
        logger.warning("Web image cache purge failed",exc_info=True)
    return removed

def _fetch(url):
    """GET en suivant les redirections à la main, chacune revalidée par is_public_url."""
    for _ in range(MAX_REDIRECTS+1):
        if not is_public_url(url): return None
        r=requests.get(url,timeout=TIMEOUT,headers={'User-Agent':'RITA-Vision/2.13'},stream=True,allow_redirects=False)
        if r.is_redirect or r.status_code in (301,302,303,307,308):
            loc=r.headers.get('location'); r.close()
            if not loc: return None
            url=urljoin(url,loc); continue
        r.raise_for_status(); return r
    return None

def download_image(url):
    global _purged
    if not url.startswith(('http://','https://')): return None
    if not _purged: _purged=True; purge_cache()
    path=_key(url)
    if path.exists() and path.stat().st_size>0: return path
    try:
        r=_fetch(url)
        if r is None: return None
        ctype=(r.headers.get('content-type') or '').lower()
        if ctype and not ctype.startswith('image/'): return None
        data=bytearray()
        for chunk in r.iter_content(65536):
            data.extend(chunk)
            if len(data)>MAX_BYTES: return None
        im=Image.open(io.BytesIO(data)).convert('RGB')
        if min(im.size)<80: return None
        im.thumbnail((1000,1000),Image.Resampling.LANCZOS); im.save(path,'JPEG',quality=85,optimize=True); return path
    except Exception:
        logger.warning("Web image download failed for %s", url, exc_info=True)
        return None

def _ahash(im,size=16):
    g=ImageOps.grayscale(im).resize((size,size),Image.Resampling.BILINEAR); v=list(g.getdata()); m=sum(v)/len(v); return [1 if x>=m else 0 for x in v]
def _phash(im,size=32):
    g=ImageOps.grayscale(im).resize((size,size),Image.Resampling.BILINEAR); m=ImageStat.Stat(g).mean[0]; return [(x-m)/128.0 for x in g.getdata()]
def _cos(a,b):
    d=sum(x*y for x,y in zip(a,b)); na=sum(x*x for x in a)**.5; nb=sum(y*y for y in b)**.5
    return 0.0 if not na or not nb else max(0.0,min(1.0,(d/(na*nb)+1)/2))
def _edges(im,size=32):
    g=ImageOps.grayscale(im).resize((size,size),Image.Resampling.BILINEAR).filter(ImageFilter.FIND_EDGES); v=list(g.getdata()); m=sum(v)/len(v); return [1 if x>=m*1.25 else 0 for x in v]
def _edge_sim(a,b): return 1.0-sum(x!=y for x,y in zip(_edges(a),_edges(b)))/1024
def _hist(im,bins=8):
    im=im.convert('RGB').resize((64,64),Image.Resampling.BILINEAR); h=[0.0]*(bins*3)
    for r,g,b in im.getdata(): h[r*bins//256]+=1; h[bins+g*bins//256]+=1; h[2*bins+b*bins//256]+=1
    return [x/4096 for x in h]
def _hist_i(a,b): return max(0.0,min(1.0,sum(min(x,y) for x,y in zip(a,b))/3.0))
def compare(query,candidate):
    q=ImageOps.exif_transpose(query.convert('RGB')); c=ImageOps.exif_transpose(candidate.convert('RGB'))
    if q.size==c.size and list(q.getdata())==list(c.getdata()): return 1.0
    ah=1-sum(a!=b for a,b in zip(_ahash(q),_ahash(c)))/256
    structure=_edge_sim(q,c); colors=_hist_i(_hist(q),_hist(c)); ph=_cos(_phash(q),_phash(c))
    lq=ImageStat.Stat(ImageOps.grayscale(q).resize((32,32))).mean[0]; lc=ImageStat.Stat(ImageOps.grayscale(c).resize((32,32))).mean[0]; lum=max(0,1-abs(lq-lc)/255)
    f=visual_feature_scores(q,c)
    return max(0,min(1,.12*f['ahash']+.28*f['structure']+.15*f['couleurs']+.15*f['phash_coarse']+.05*f['luminance']+.25*f['local_max']))
def compare_details(query,candidate):
    q=ImageOps.exif_transpose(query.convert('RGB')); c=ImageOps.exif_transpose(candidate.convert('RGB'))
    if q.size==c.size and list(q.getdata())==list(c.getdata()): return {'type':'doublon_exact','ahash':1,'structure':1,'couleurs':1,'phash_coarse':1,'luminance':1}
    f=visual_feature_scores(q,c); return {'type':'visuel_multicritere_local',**f}
def score_image(query,result):
    path=download_image(result.image_url)
    if not path: return 0.0,None,{}
    try:
        with Image.open(path) as im: return compare(query,im),path,compare_details(query,im)
    except Exception:
        logger.warning("Web image comparison failed for cached file %s", path, exc_info=True)
        return 0.0,None,{}
