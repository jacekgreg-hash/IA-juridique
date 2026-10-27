import io
import os
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image

from ocr_utils import clean_text, keep, fallback_scale
from server.ocr.paddle_client import filter_by_score
from server.candidates import visual_web
from server.candidates.web_search import extract_product_models


def test_filter_by_score_splits_and_keeps_alignment():
    kept, rejected = filter_by_score(['P-6000', 'xq', 'NIKE'], [0.97, 0.31, 0.88], 0.5)
    assert kept == [('P-6000', 0.97), ('NIKE', 0.88)]
    assert rejected == [('xq', 0.31)]


def test_filter_by_score_without_scores_keeps_all():
    kept, rejected = filter_by_score(['A1', 'B2'], [], 0.5)
    assert [t for t, _ in kept] == ['A1', 'B2'] and rejected == []


def test_fallback_scale_is_capped():
    assert fallback_scale(600, 400) == 2.0            # petite photo : x2
    assert fallback_scale(4000, 3000) == 0.0          # pleine résolution : pas d'agrandissement
    assert 1.2 <= fallback_scale(2000, 1500, 3200) < 2.0
    # ne dépasse jamais le plafond
    for w, h in ((800, 600), (1600, 1200), (2500, 1800)):
        s = fallback_scale(w, h)
        assert s == 0.0 or max(w, h) * s <= 3200 + 1


def test_service_text_filters():
    assert clean_text('P-6000 ®') == 'P-6000'
    assert keep('P-6000') and not keep('---') and not keep('aaa')


def test_ssrf_guard_blocks_private_and_non_http():
    for url in ('http://127.0.0.1/x.jpg', 'http://localhost/x', 'http://192.168.0.5/a', 'http://10.1.2.3/a',
                'http://169.254.169.254/latest/meta-data', 'http://[::1]/a', 'file:///etc/passwd', 'ftp://example.com/a.jpg'):
        assert not visual_web.is_public_url(url), url


def test_ssrf_guard_allows_public_literal_ip():
    assert visual_web.is_public_url('https://93.184.216.34/img.jpg')


# --- V3.6 : épinglage DNS anti-rebinding (§ sécurité avant exposition) ---

def test_resolve_public_refuse_localhost():
    assert visual_web._resolve_public('localhost', 80) is None


def _serveur_local(handler_class):
    """Démarre un serveur HTTP local éphémère ; retourne (serveur, base_url)."""
    serveur = ThreadingHTTPServer(('127.0.0.1', 0), handler_class)
    thread = threading.Thread(target=serveur.serve_forever, daemon=True)
    thread.start()
    return serveur, f'http://127.0.0.1:{serveur.server_port}'


def test_fetch_refuse_localhost_meme_avec_serveur_local():
    # Un serveur tourne bien sur 127.0.0.1 — le téléchargement doit être REFUSÉ :
    # la résolution de « localhost » ne donne pas d'IP public.
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header('Content-Type', 'image/jpeg'); self.end_headers()
            self.wfile.write(b'x')
        def log_message(self, *a): pass

    serveur, base = _serveur_local(_H)
    try:
        url = base.replace('127.0.0.1', 'localhost')
        assert visual_web._fetch(url) is None
        assert visual_web.download_image(url) is None
    finally:
        serveur.shutdown()


def test_fetch_epingle_lip_et_transmet_le_bon_host(tmp_path, monkeypatch):
    # La résolution est contournée (IP « vérifié » simulé) : la connexion se
    # fait SUR CET IP avec le Host d'origine — comportement de l'épinglage.
    vus = {}

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            vus['host'] = self.headers.get('Host')
            vus['ua'] = self.headers.get('User-Agent')
            buf = io.BytesIO()
            Image.new('RGB', (120, 120), 'red').save(buf, 'JPEG')
            corps = buf.getvalue()
            self.send_response(200)
            self.send_header('Content-Type', 'image/jpeg')
            self.send_header('Content-Length', str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)
        def log_message(self, *a): pass

    serveur, base = _serveur_local(_H)
    monkeypatch.setattr(visual_web, 'CACHE_DIR', tmp_path)
    monkeypatch.setattr(visual_web, '_resolve_public', lambda h, p: '127.0.0.1')
    try:
        # L'URL nomme un hôte fictif ; l'IP épinglé est 127.0.0.1 (simulé).
        url = base.replace('127.0.0.1', 'hote-public.example') + '/img.jpg'
        chemin = visual_web.download_image(url)
        assert chemin is not None and chemin.exists()
        assert vus.get('host') == 'hote-public.example'   # Host d'origine transmis
        assert vus.get('ua', '').startswith('RITA-Vision')
    finally:
        serveur.shutdown()


def test_fetch_redirection_vers_ip_prive_refusee():
    # La cible initiale est « publique » (IP épinglé simulé) mais redirige vers
    # un IP privé : le saut suivant doit être refusé (résolution -> refus).
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header('Location', 'http://192.168.0.5/x.jpg')
            self.end_headers()
        def log_message(self, *a): pass

    serveur, base = _serveur_local(_H)
    monkeypatch_ip = '127.0.0.1'
    orig = visual_web._resolve_public
    try:
        import server.candidates.visual_web as vw
        # Premier saut : IP « public » simulé ; le suivant re-résout vraiment.
        appel = {'n': 0}
        def faux(hostname, port):
            appel['n'] += 1
            if appel['n'] == 1:
                return monkeypatch_ip
            return orig(hostname, port)
        vw._resolve_public = faux
        assert visual_web._fetch(base + '/img.jpg') is None
    finally:
        vw._resolve_public = orig
        serveur.shutdown()


def test_fetch_refuse_erreur_http():
    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404); self.end_headers()
        def log_message(self, *a): pass

    serveur, base = _serveur_local(_H)
    try:
        assert visual_web._fetch(base + '/x.jpg') is None
    finally:
        serveur.shutdown()


def test_purge_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_web, 'CACHE_DIR', tmp_path)
    old = tmp_path / 'old.jpg'; old.write_bytes(b'x')
    os.utime(old, (time.time() - 30 * 86400,) * 2)
    for i in range(5):
        f = tmp_path / f'new{i}.jpg'; f.write_bytes(b'x')
        os.utime(f, (time.time() - i,) * 2)
    removed = visual_web.purge_cache(max_files=3, max_age_days=7)
    left = sorted(p.name for p in tmp_path.glob('*.jpg'))
    assert removed == 3 and len(left) == 3 and 'old.jpg' not in left


def test_generic_category_words_are_not_models():
    assert extract_product_models('Nike Sportswear - Site officiel', 'Nike') == []
    assert extract_product_models('Nike Running Chaussures', 'Nike') == []
    assert 'P-6000' in extract_product_models('Nike P-6000 Metallic Silver homme', 'Nike')
    assert extract_product_models('Adidas Samba OG noir', 'Adidas') == ['Samba OG']


def test_build_queries_with_and_without_brand():
    from server.candidates.web_search import build_queries
    fast = {'marque': 'Nike', 'objet': 'chaussure de sport', 'caracteristiques': ['argenté', 'noir']}
    q = build_queries(fast, ['P-6000'])
    assert q[0] == 'Nike chaussure de sport argenté noir' and 'Nike P-6000' in q
    # Régression V2.13.6 : sans marque, aucune requête n'était émise.
    q2 = build_queries({**fast, 'marque': None}, ['P-6000'])
    assert q2 and 'chaussure de sport P-6000' in q2
    assert build_queries({'marque': None, 'objet': None, 'caracteristiques': []}, []) == []


def test_mistral_ocr_markdown_lines_filter_image_artifacts():
    # V2.14.1 : l'API laisse des placeholders « ![](img-0.jpeg) » quand
    # include_image_base64=False — ils ne sont pas du texte lu sur la photo.
    from server.ocr.mistral_ocr import _markdown_lines
    md = '![img-0.jpeg](img-0.jpeg)\nP. 6000\n|Modele|P-6000|\n![img-1.png](img-1.png) Air Max\n'
    lines = _markdown_lines(md)
    assert lines == ['P. 6000', 'Modele', 'P-6000', 'Air Max']
    assert _markdown_lines('![img-0.jpeg](img-0.jpeg)') == []


def test_french_prose_after_brand_is_not_a_model():
    # V2.14.2 : extraits français — « Seiko avec couleur de cadran » donnait
    # « avec couleur de », « Seiko 5 cadran orange » donnait « 5cadran ».
    assert extract_product_models('Seiko avec couleur de cadran orange', 'Seiko') == []
    assert extract_product_models('Seiko 5 cadran orange vif', 'Seiko') == []
    # les vraies formes de modèle passent toujours
    assert extract_product_models('Seiko 5 Sports GMT automatique', 'Seiko') == ['5 Sports GMT']
    assert extract_product_models('Adidas Samba OG noir', 'Adidas') == ['Samba OG']


def test_ocr_corroborates_web_model_codes():
    # V2.14.2 : l'OCR lit « 3310e », le web propose « 3310 Cellular Phone » —
    # égalité exacte impossible, la similarité des tokens à chiffres fait le pont.
    from server.candidates.external import ocr_corroborates, _digit_tokens
    toks = _digit_tokens(['NOKIA', '17:38', '3310e', 'orange™'])
    assert toks == {'3310E'}                        # marque et heure sans valeur
    assert ocr_corroborates('Nokia 3310 Cellular Phone', toks) is True
    assert ocr_corroborates('Nokia 2660 Flip', toks) is False
    assert ocr_corroborates('Nike P-1000', _digit_tokens(['P. 1111'])) is False
    assert ocr_corroborates('Seiko 5 Sports', set()) is False  # sans OCR : jamais
