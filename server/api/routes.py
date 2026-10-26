import os, tempfile, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, File, HTTPException, UploadFile
from PIL import Image
from server.candidates.engine import search_candidates
from server.candidates.external import search_external
from server.candidates.merge import merge_candidate_sources, candidate_decision, apply_candidate_decision_to_produit
from server.fusion.engine import fuse
from server.ocr.paddle_client import ocr_detailed
from server.vision.enrich import enrich_vision
from server.vision.ollama import MODEL, analyze

router=APIRouter()
APP_VERSION='2.13.7'
VERSION=f'RITA Vision V{APP_VERSION} Florence-2-base + PaddleOCR PP-OCRv5 + SearXNG + evidence fusion'
MAX_UPLOAD_BYTES=int(float(os.getenv('MAX_UPLOAD_MB','15'))*1024*1024)
ALLOWED_SUFFIXES={'.jpg','.jpeg','.png','.webp','.bmp'}

# Alias conservés : test_v211.py et d'éventuels scripts importent encore ces noms depuis routes.
_merge_candidate_sources=merge_candidate_sources
_candidate_decision=candidate_decision
_apply_candidate_decision_to_produit=apply_candidate_decision_to_produit

@router.get('/health')
def health():
    return {'status':'ok','service':VERSION,'vision_model':MODEL}

def _read_upload(image: UploadFile) -> Path:
    """Copie l'upload dans un fichier temporaire après contrôle de taille et de contenu."""
    data=image.file.read(MAX_UPLOAD_BYTES+1)
    if not data:
        raise HTTPException(status_code=400,detail='Fichier image vide')
    if len(data)>MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413,detail=f'Image trop volumineuse (maximum {MAX_UPLOAD_BYTES//(1024*1024)} Mo)')
    suffix=Path(image.filename or '').suffix.lower()
    if suffix not in ALLOWED_SUFFIXES: suffix='.jpg'
    with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as temp:
        temp.write(data); path=Path(temp.name)
    try:
        with Image.open(path) as im: im.verify()
    except Exception:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=415,detail="Le fichier n'est pas une image lisible (JPEG, PNG, WebP ou BMP)")
    return path

# `def` (et non `async def`) : tout le traitement est bloquant (Florence, requests, LLM).
# FastAPI l'exécute dans son pool de threads au lieu de figer la boucle d'événements.
@router.post('/api/v1/analysis')
def analysis(image: UploadFile=File(...)):
    path=_read_upload(image)
    started=time.time()
    try:
        # L'OCR (service séparé) et Florence tournent en parallèle ; les preuves OCR restent
        # indépendantes de la vision.
        def timed_ocr(p):
            detail=ocr_detailed(p)
            return detail['text'], detail['time'], detail
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_ocr=pool.submit(timed_ocr,path)
            f_vis=pool.submit(analyze,path)
            ocr_text,ocr_time,ocr_detail=f_ocr.result(); vision=f_vis.result()
        # Florence ne fournit qu'une légende : marque (2e chance via OCR), catégorie, couleurs,
        # caractéristiques et texte visible sont dérivés de façon déterministe (voir enrich.py).
        enrich_vision(vision['fast'],ocr_text)
        candidate_search=search_candidates(vision['image'],vision['fast'],ocr_text,limit=5)
        external_search=search_external(vision['fast'],ocr_text,query_image=vision['image'])
        candidate_search=merge_candidate_sources(candidate_search,external_search.get('candidats') or [],vision['fast'])
        total=time.time()-started
        timings={'version':VERSION,'vision_model':MODEL,'image_resolution':[vision['image'].width,vision['image'].height],
                 'temps_ocr':round(ocr_time,2),'temps_vision':round(vision['fast_time'],2),'temps_verification':0.0,
                 'temps_total':round(total,2),'verification_effectuee':False,
                 'principe':'Florence décrit; PaddleOCR lit; recherche externe apporte des preuves; Python fusionne et classe les hypothèses'}
        response=fuse(vision['fast'],ocr_text,timings,[]).model_dump(mode='json')
        response['candidats']=candidate_search
        decision=candidate_decision(candidate_search)
        response['decision_candidat']=decision
        response['recherche_externe']=external_search
        response['ocr_details']=ocr_detail
        response['perception']={'legende':vision['fast'].get('caption'),'objet_legende':vision['fast'].get('objet_legende'),
                                'marque_source':vision['fast'].get('marque_source'),'couleurs':vision['fast'].get('couleurs')}
        # Une seule identification unifiée (cahier des charges, section 17) : la décision
        # fondée sur les preuves est reflétée dans `produit`, sans jamais écrire « confirme ».
        apply_candidate_decision_to_produit(response['produit'],decision,candidate_search)
        return response
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500,detail=f'{type(exc).__name__}: {exc}') from exc
    finally:
        try:path.unlink()
        except OSError:pass
