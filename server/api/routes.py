import os, tempfile, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image
from server.candidates.engine import search_candidates
from server.candidates.external import search_external
from server.candidates.merge import merge_candidate_sources, candidate_decision, apply_candidate_decision_to_produit
from server.fusion.engine import fuse
from server.ocr.select import ocr_detailed
from server.persistence import store
from server.tariff.engine import propose_classement
from server.tariff.fiscal import question_origine, taux_estime
from server.vision.enrich import enrich_vision
from server.vision.select import MODEL, analyze

router=APIRouter()
APP_VERSION='3.5.0'
VERSION=(f'RITA Vision V{APP_VERSION} — moteurs interchangeables '
         f'(vision: {os.getenv("VISION_ENGINE","florence")}, ocr: {os.getenv("OCR_ENGINE","paddle")}, '
         f'llm: {os.getenv("TEXT_LLM_PROVIDER","ollama")}) + SearXNG + fusion de preuves')
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

# `def` (et non `async def`) : tout le traitement est bloquant (vision, requests, LLM).
# FastAPI l'exécute dans son pool de threads au lieu de figer la boucle d'événements.
# `origine` est facultatif : sans elle, l'analyse ajoute une question ciblée (§31.3)
# et n'affiche que le droit de pays tiers indicatif ; avec elle, le moteur fiscal
# estime les droits par candidat (§16) — la préférence reste SUR JUSTIFICATIF.
@router.post('/api/v1/analysis')
def analysis(image: UploadFile=File(...), origine: str=Form(None)):
    path=_read_upload(image)
    started=time.time()
    try:
        # L'OCR et la vision tournent en parallèle ; les preuves OCR restent
        # indépendantes de la vision. Les moteurs réels derrière `ocr_detailed` et
        # `analyze` sont choisis par OCR_ENGINE / VISION_ENGINE (voir server/ocr/select.py
        # et server/vision/select.py) : ce route ne connaît que leurs contrats.
        def timed_ocr(p):
            detail=ocr_detailed(p)
            return detail['text'], detail['time'], detail
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_ocr=pool.submit(timed_ocr,path)
            f_vis=pool.submit(analyze,path)
            ocr_text,ocr_time,ocr_detail=f_ocr.result(); vision=f_vis.result()
        # La vision ne fournit qu'une légende : marque (2e chance via OCR), catégorie,
        # couleurs, caractéristiques et texte visible sont dérivés de façon déterministe.
        enrich_vision(vision['fast'],ocr_text)
        candidate_search=search_candidates(vision['image'],vision['fast'],ocr_text,limit=5)
        ext_started=time.time()
        external_search=search_external(vision['fast'],ocr_text,query_image=vision['image'])
        ext_time=time.time()-ext_started
        candidate_search=merge_candidate_sources(candidate_search,external_search.get('candidats') or [],vision['fast'])
        total=time.time()-started
        # Suivi des coûts (§22 du cahier des charges : mesurer le coût d'un dossier).
        # Comptage des appels externes par analyse ; le montant se déduit des tarifs
        # en vigueur des fournisseurs (à brancher quand le service sera commercialisé).
        ext_meta=external_search.get('meta') or {}
        llm_statut=(external_search.get('llm_extraction') or {}).get('statut')
        suivi_couts={'appels_vision':1,'appels_ocr':1,
                     'requetes_web':len(external_search.get('queries') or []),
                     'images_web_evaluees':ext_meta.get('nb_images_evaluees',0),
                     'appels_llm_texte':1 if llm_statut=='ok' else 0,
                     'cout_estime': None}  # montant rempli quand les tarifs seront validés
        timings={'version':VERSION,'vision_model':MODEL,'image_resolution':[vision['image'].width,vision['image'].height],
                 'temps_ocr':round(ocr_time,2),'temps_vision':round(vision['fast_time'],2),
                 'temps_recherche_externe':round(ext_time,2),'temps_verification':0.0,
                 'temps_total':round(total,2),'verification_effectuee':False,
                 'suivi_couts':suivi_couts,
                 'principe':'La vision décrit; l\'OCR lit; la recherche externe apporte des preuves; Python fusionne et classe les hypothèses'}
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
        # V3 : classification tarifaire (§9/§10/§11) — moteur séparé de l'IA, base
        # de données séparée du code, candidats multiples et questions ciblées.
        response['classement']=propose_classement(response['produit'],vision['fast'].get('caption') or '',ocr_text)
        _enrichir_droits(response,origine)
        # V3 : persistance (§20/§21/§24) — l'analyse est conservée et devient
        # consultable via GET /api/v1/history et GET /api/v1/analysis/{id}.
        try:
            response['id_analyse']=store.save_analysis(response,image.filename or '')
        except Exception:
            response['id_analyse']=None  # la persistance ne doit jamais casser l'analyse
        return response
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500,detail=f'{type(exc).__name__}: {exc}') from exc
    finally:
        try:path.unlink()
        except OSError:pass

def _enrichir_droits(response: dict, origine: str | None) -> None:
    """Branche le moteur fiscal (§16) sur les candidats du classement.

    Sans origine : question ciblée (§31.3) — les droits dépendent de l'origine
    et la préférence n'est jamais automatique (justificatifs requis).
    Avec origine : estimation par candidat (3 premiers) ; une erreur du moteur
    fiscal ne doit jamais casser l'analyse (même politique que la persistance).
    """
    classement=response.get('classement') or {}
    codes=[c['code'] for c in (classement.get('candidats') or [])[:3]]
    if not codes:
        return
    if not origine:
        classement.setdefault('questions',[]).append(question_origine())
        classement.setdefault('informations_manquantes',[]).append("origine de la marchandise (pour l'estimation des droits)")
        return
    try:
        response['droits']={code:taux_estime(code,origine) for code in codes}
    except FileNotFoundError:
        response['droits']={'statut':'indisponible','raison':'base fiscale absente — lancer tools/import_taric.py'}
    except Exception as exc:
        response['droits']={'statut':'erreur','raison':f'{type(exc).__name__}: {exc}'}

# --- V3 : historique et consultation (§20 GET /history, GET /analysis/{id}) ---

@router.get('/api/v1/history')
def history(limit: int=20):
    """Historique des analyses (§24) : lignes résumées, plus récentes d'abord."""
    return {'analyses':store.list_history(limit=limit)}

@router.get('/api/v1/analysis/{aid}')
def analysis_detail(aid: str):
    """Résultat complet d'une analyse conservée (photos non stockées, §25)."""
    payload=store.get_analysis(aid)
    if payload is None:
        raise HTTPException(status_code=404,detail='Analyse inconnue')
    return payload

# --- V3.1 : moteur fiscal (§16) — estimation des droits par origine ---

@router.get('/api/v1/duty')
def duty(code: str, origine: str):
    """Droits d'importation UE estimés pour un code marchandise et une origine.

    Exemple : GET /api/v1/duty?code=6403190000&origine=CN
    Le résultat est une estimation documentée (jamais une décision fiscale) :
    préférence éventuelle de l'accord couvrant l'origine, droit antidumping
    éventuel, base légale et avertissement de vérification officielle.
    """
    try:
        return taux_estime(code,origine)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc
