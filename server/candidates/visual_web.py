from __future__ import annotations
import hashlib, http.client, io, ipaddress, logging, os, socket, ssl, threading, time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from PIL import Image, ImageOps
from server.candidates.web_search import ImageResult
from server.candidates.engine import visual_feature_scores

logger = logging.getLogger(__name__)

CACHE_DIR=Path(__file__).resolve().parents[2]/'data'/'web_image_cache'; CACHE_DIR.mkdir(parents=True,exist_ok=True)
MAX_BYTES=2_000_000; TIMEOUT=12; MAX_REDIRECTS=3
# Cache : les images web sont des copies temporaires de travail, pas une base d'images.
CACHE_MAX_FILES=int(os.getenv('WEB_IMAGE_CACHE_MAX_FILES','300'))
CACHE_MAX_AGE_DAYS=float(os.getenv('WEB_IMAGE_CACHE_MAX_AGE_DAYS','7'))
# V2.14 : purge périodique. L'ancien drapeau « une seule purge par vie du process »
# laissait le cache grossir sans limite sur un serveur longue durée.
PURGE_EVERY=int(os.getenv('WEB_IMAGE_CACHE_PURGE_EVERY','50'))
_purge_lock=threading.Lock()
_download_count=0

def _key(url): return CACHE_DIR/(hashlib.sha256(url.encode('utf-8')).hexdigest()+'.jpg')

def _resolve_public(hostname: str, port: int) -> str | None:
    """Résout le nom d'hôte UNE fois et retourne un IP public vérifié.

    Tous les IP résolus doivent être publics : si un seul est privé/réservé
    (réseau local, lien-local, loopback), la résolution est refusée.
    """
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except Exception:
        return None
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            ips.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            return None
    if not ips or any(not ip.is_global for ip in ips):
        return None
    return str(ips[0])


def is_public_url(url):
    """Garde anti-SSRF : http(s) uniquement, et tous les IP résolus doivent être publics.

    V3.6 : la vérification n'est plus qu'un indicateur — le téléchargement
    (_fetch) épingle l'IP résolu : la connexion se fait SUR l'IP vérifié, une
    nouvelle résolution DNS (rebinding) est impossible."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return False
        return _resolve_public(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)) is not None
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

def _maybe_purge():
    """Purge au premier téléchargement puis tous les PURGE_EVERY téléchargements."""
    global _download_count
    with _purge_lock:
        _download_count+=1
        n=_download_count
    if n==1 or n % PURGE_EVERY==0:
        purge_cache()

class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS vers un IP ÉPINGLÉ, avec SNI et vérification de certificat sur le
    vrai nom d'hôte (pas l'IP) : le rebinding DNS est impossible — on se
    connecte à l'IP vérifié, jamais à une nouvelle résolution."""

    def __init__(self, ip, port, timeout, context, sni_hostname):
        super().__init__(ip, port, timeout=timeout, context=context)
        self._sni_hostname = sni_hostname

    def connect(self):
        sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self._sni_hostname)


def _fetch(url):
    """GET en suivant les redirections à la main, chaque saut résolu UNE fois
    vers un IP public vérifié puis ÉPINGLÉ (V3.6 : ferme la fenêtre de
    rebinding DNS qui existait entre la vérification et la requête).

    Retourne (connexion, réponse http.client, en-têtes minuscules) ou None.
    """
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return None
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        ip = _resolve_public(parsed.hostname, port)
        if not ip:
            return None
        cible = parsed.path or '/'
        if parsed.query:
            cible += '?' + parsed.query
        conn = resp = None
        try:
            if parsed.scheme == 'https':
                conn = _PinnedHTTPS(ip, port, TIMEOUT, ssl.create_default_context(), parsed.hostname)
            else:
                conn = http.client.HTTPConnection(ip, port, timeout=TIMEOUT)
            # Host : le nom d'hôte d'origine (le routage virtuel des serveurs
            # mutualisés en dépend), la connexion reste épinglée sur l'IP.
            conn.request('GET', cible, headers={'User-Agent': 'RITA-Vision/3.6',
                                               'Host': parsed.hostname})
            resp = conn.getresponse()
            status = resp.status
            headers = {k.lower(): v for k, v in resp.getheaders()}
            if status in (301, 302, 303, 307, 308):
                loc = headers.get('location')
                resp.close(); conn.close()
                if not loc:
                    return None
                url = urljoin(url, loc)
                continue
            if status >= 400:
                resp.close(); conn.close()
                return None
            return conn, resp, headers
        except Exception:
            if resp is not None:
                try: resp.close()
                except Exception: pass
            if conn is not None:
                try: conn.close()
                except Exception: pass
            return None
    return None

def download_image(url):
    if not url.startswith(('http://','https://')): return None
    _maybe_purge()
    path=_key(url)
    if path.exists() and path.stat().st_size>0: return path
    try:
        fetch=_fetch(url)
        if fetch is None: return None
        conn,resp,headers=fetch
        try:
            ctype=(headers.get('content-type') or '').lower()
            if ctype and not ctype.startswith('image/'): return None
            data=bytearray()
            while len(data)<=MAX_BYTES:
                chunk=resp.read(65536)
                if not chunk: break
                data.extend(chunk)
            if not data or len(data)>MAX_BYTES: return None
            im=Image.open(io.BytesIO(data)).convert('RGB')
            if min(im.size)<80: return None
            im.thumbnail((1000,1000),Image.Resampling.LANCZOS); im.save(path,'JPEG',quality=85,optimize=True); return path
        finally:
            resp.close(); conn.close()
    except Exception:
        logger.warning("Web image download failed for %s", url, exc_info=True)
        return None

def _analyze(query,candidate):
    """Une seule passe de caractéristiques visuelles -> (score, détails).

    V2.14 : score_image() appelait compare() puis compare_details(), et chacun
    recalculait visual_feature_scores() : la comparaison complète était doublée
    pour chaque image web évaluée. Tout passe désormais par cette fonction.
    Les fonctions _ahash/_phash/_cos/_edges/_hist locales (code dupliqué de
    engine.py, jamais utilisé dans le score final) ont été supprimées.
    """
    q=ImageOps.exif_transpose(query.convert('RGB')); c=ImageOps.exif_transpose(candidate.convert('RGB'))
    if q.size==c.size and list(q.getdata())==list(c.getdata()):
        perfect={'type':'doublon_exact','ahash':1.0,'structure':1.0,'couleurs':1.0,'phash_coarse':1.0,'luminance':1.0,'local_max':1.0,'local_moyenne':1.0}
        return 1.0,perfect
    f=visual_feature_scores(q,c)
    score=max(0,min(1,.12*f['ahash']+.28*f['structure']+.15*f['couleurs']+.15*f['phash_coarse']+.05*f['luminance']+.25*f['local_max']))
    details={'type':'visuel_multicritere_local',**{k:round(float(v),3) for k,v in f.items()}}
    return score,details

def compare(query,candidate):
    """Compatibilité : retourne uniquement le score (voir _analyze)."""
    return _analyze(query,candidate)[0]

def compare_details(query,candidate):
    """Compatibilité : retourne uniquement les détails (voir _analyze)."""
    return _analyze(query,candidate)[1]

def score_image(query,result):
    path=download_image(result.image_url)
    if not path: return 0.0,None,{}
    try:
        with Image.open(path) as im:
            score,details=_analyze(query,im)
            return score,path,details
    except Exception:
        logger.warning("Web image comparison failed for cached file %s", path, exc_info=True)
        return 0.0,None,{}
