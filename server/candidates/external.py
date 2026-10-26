from __future__ import annotations
import os, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from server.candidates.web_search import BraveSearchProvider,SearXNGSearchProvider,build_queries,domain_weight,extract_product_models
from server.candidates.visual_web import score_image
from server.candidates.engine import clean,tokens
from server.candidates.llm_extractor import extract as llm_extract, MAX_ITEMS as LLM_MAX_ITEMS

def _brand_ok(text,brand): return bool(brand and clean(brand) in clean(text))
def _model_key(model): return clean(model)
def _best_model_title(model,title): return clean(model) in clean(title)
def _independent_domains(urls): return len({urlparse(u).netloc.lower() for u in urls if u})

# V2.14 : la recherche externe (surtout les téléchargements d'images) respecte un
# budget de temps global. Avant : jusqu'à 24 images évaluées séquentiellement à
# 12 s de timeout chacune, pire cas ~5 min — incompatible avec l'objectif
# « analyse normale < 60 s » du cahier des charges (§22).
EXTERNAL_DEADLINE_S=float(os.getenv('EXTERNAL_DEADLINE_S','20'))
EXTERNAL_IMAGE_WORKERS=int(os.getenv('EXTERNAL_IMAGE_WORKERS','4'))
EXTERNAL_MAX_IMAGES=int(os.getenv('EXTERNAL_MAX_IMAGES','24'))

def search_external(vision,ocr_text,query_image=None,provider=None,fallback=None,limit=8):
    queries=build_queries(vision,ocr_text); primary=provider or SearXNGSearchProvider(); emergency=fallback or BraveSearchProvider(); used=[]; raw=[]; errors=[]; imgs=[]
    if primary.enabled:
        used.append(primary.name)
        for q in queries:
            try: raw.extend(primary.search(q))
            except Exception as e: errors.append(f"{primary.name}: {type(e).__name__}: {e}")
            if hasattr(primary,'image_search'):
                try: imgs.extend(primary.image_search(q))
                except Exception as e: errors.append(f"{primary.name}:images:{type(e).__name__}: {e}")
    if not raw and emergency.enabled and emergency is not primary:
        used.append(emergency.name)
        for q in queries:
            try: raw.extend(emergency.search(q))
            except Exception as e: errors.append(f"{emergency.name}: {type(e).__name__}: {e}")
    if not primary.enabled and not emergency.enabled:
        return {'statut':'desactive','provider_principal':primary.name,'providers_utilises':[],'queries':queries,'resultats':[],'images':[],'candidats':[],'erreurs':['SEARXNG_URL absent et BRAVE_SEARCH_API_KEY absent'],'brave_role':'secours_uniquement','llm_extraction':{'statut':'non_execute'},'meta':{'nb_requetes':0}}

    byurl={r.url:r for r in raw}; byimg={r.image_url:r for r in imgs}; brand=str(vision.get('marque') or '')
    images_pool=list(byimg.values())[:EXTERNAL_MAX_IMAGES]
    # First pass: build compact sources for the single local text-LLM call.
    llm_sources=[]
    for i,row in enumerate(byurl.values(),1):
        llm_sources.append({'source_id':f'w{i}','title':row.title,'snippet':row.snippet,'url':row.url,'source':row.source})
    for j,img in enumerate(images_pool,1):
        llm_sources.append({'source_id':f'i{j}','title':img.title,'snippet':img.page_url,'url':img.page_url,'source':img.source})
    # Deterministic extraction first. The text LLM is a fallback for ambiguous
    # product names, not a mandatory step. This avoids wasting ~30-60 s when
    # sources already contain explicit references such as P-6000 or GSR 18V-60.
    deterministic_by_id={}
    for i,row in enumerate(byurl.values(),1):
        models=extract_product_models(f"{row.title} {row.snippet}",brand)
        if models:
            deterministic_by_id[f'w{i}']=models
    for j,img in enumerate(images_pool,1):
        models=extract_product_models(f"{img.title} {img.page_url}",brand)
        if models:
            deterministic_by_id[f'i{j}']=models

    need_llm = not any(deterministic_by_id.values())
    # V2.14.1 : la tranche doit suivre MAX_ITEMS de llm_extractor — avant, 16
    # sources étaient envoyées alors que seules les 8 premières étaient traitées.
    llm_result = llm_extract(llm_sources[:LLM_MAX_ITEMS]) if need_llm else {'statut':'non_execute','raison':'references explicites deja detectees par Python','extractions':[]}
    llm_by_id={x['source_id']:x for x in llm_result.get('extractions',[])}

    cmap=defaultdict(lambda:{'rows':[],'images':[],'urls':set(),'titles':[],'snips':[],'domains':set(),'llm':[]})
    for i,row in enumerate(byurl.values(),1):
        sid=f'w{i}'; text=f"{row.title} {row.snippet}"; models=extract_product_models(text,brand)
        if sid in llm_by_id: models.append(llm_by_id[sid]['modele'])
        for model in dict.fromkeys(models):
            key=_model_key(model); b=cmap[key]; b['rows'].append(row); b['urls'].add(row.url); b['titles'].append(row.title); b['snips'].append(row.snippet); b['domains'].add(row.source or urlparse(row.url).netloc.lower())
            if sid in llm_by_id: b['llm'].append(llm_by_id[sid])

    # V2.14 : téléchargements/évaluations d'images concurrents sous budget de temps.
    # pool.map préserve l'ordre ; chaque tâche vérifie la deadline avant de commencer,
    # les suivantes sont simplement sautées (elles restent visibles dans meta).
    visual_rows=[]; scored=[]; images_unscored=0
    if query_image is not None and images_pool:
        deadline=time.monotonic()+EXTERNAL_DEADLINE_S
        def _score_one(j_img):
            j,img=j_img
            if time.monotonic()>deadline:
                return j,img,0.0,None,{}
            try:
                vs,path,det=score_image(query_image,img)
            except Exception:
                vs,path,det=0.0,None,{}
            return j,img,vs,path,det
        with ThreadPoolExecutor(max_workers=max(1,EXTERNAL_IMAGE_WORKERS)) as pool:
            for j,img,vs,path,det in pool.map(_score_one,enumerate(images_pool,1)):
                if vs: scored.append((j,img,vs,path,det))
                else: images_unscored+=1
        for j,img,vs,path,det in scored:
            sid=f'i{j}'
            visual_rows.append({'title':img.title,'image_url':img.image_url,'page_url':img.page_url,'source':img.source,'similarite':round(vs,3),'details_visuels':{k:round(v,3) for k,v in det.items() if k!='type'},'type_preuve_visuelle':det.get('type'),'cache':str(path) if path else None})
            text=f"{img.title} {img.page_url}"; models=extract_product_models(text,brand)
            if sid in llm_by_id: models.append(llm_by_id[sid]['modele'])
            for model in dict.fromkeys(models):
                key=_model_key(model); b=cmap[key]; b['images'].append({'score':vs,'brand_ok':_brand_ok(text,brand),'title_ok':_best_model_title(model,img.title),'page_url':img.page_url}); b['urls'].add(img.page_url); b['titles'].append(img.title); b['domains'].add(img.source or urlparse(img.page_url).netloc.lower())
                if sid in llm_by_id: b['llm'].append(llm_by_id[sid])

    candidates=[]
    for key,b in cmap.items():
        if not b['rows'] and not b['images']: continue
        model=next((x['modele'] for x in b['llm'] if x.get('modele')),None) or next((m for m in extract_product_models(' | '.join(b['titles']),brand) if _model_key(m)==key),key)
        text_rows=[r for r in b['rows'] if _brand_ok(f"{r.title} {r.snippet}",brand)]
        exact_title=sum(1 for r in text_rows if _best_model_title(model,r.title))
        llm_certain=sum(1 for x in b['llm'] if x.get('confiance')=='certain')
        domains=_independent_domains(list(b['urls']))
        ev=max(b['images'],key=lambda x:x['score']) if b['images'] else None; visual=ev['score'] if ev else 0
        brand_image=bool(ev and ev['brand_ok']); title_image=bool(ev and ev['title_ok'])
        score=0.0; reasons=[]; contradictions=[]
        # Text-only evidence is intentionally capped. A generic retailer page must not
        # outrank a product whose title and image agree across independent sources.
        if text_rows:
            score+=.07; reasons.append('preuve textuelle avec marque')
        if exact_title:
            score+=min(.20,.10*exact_title); reasons.append('modèle explicitement présent dans un titre produit')
        if llm_certain:
            score+=min(.10,.05*llm_certain); reasons.append('modèle extrait sémantiquement d’une source')
        if domains>=2:
            score+=min(.18,.09*(domains-1)); reasons.append(f"confirmé par {domains} domaines")
        elif domains==1: score+=.02
        if any(domain_weight(r.url,brand)>=.85 for r in text_rows): score+=.08; reasons.append('source fabricant ou distributeur réputé')
        if brand_image: score+=.07; reasons.append('image cohérente avec la marque')
        # Cross-modal agreement is the strongest web signal.
        if title_image and visual>=.78:
            score+=.34; reasons.append(f'image + titre modèle concordants ({visual:.2f})')
        elif title_image and visual>=.68:
            score+=.22; reasons.append(f'image + titre modèle compatibles ({visual:.2f})')
        elif brand_image and visual>=.88:
            score+=.08; reasons.append(f'image fortement similaire ({visual:.2f})')
        elif visual>=.75:
            score+=.02; reasons.append(f'image compatible ({visual:.2f})')
        if visual>=.88 and not brand_image:
            score-=.18; contradictions.append('forte similarité visuelle sans concordance de marque')
        # Multiple sources with the same exact model in product titles are meaningful,
        # but less than cross-modal evidence.
        if exact_title>=2: score+=.08; reasons.append('titre modèle répété')
        score=max(0,min(1,score))
        candidates.append({'id':f'web:{key.lower()}','modele':model,'score':round(score,3),'source':'web','similarite_image_web':round(visual,3),'urls':list(b['urls'])[:8],'titres':list(dict.fromkeys(b['titles']))[:8],'extraits':list(dict.fromkeys(b['snips']))[:4],'domaines':list(b['domains'])[:8],'raisons':reasons,'contradictions':contradictions,'nb_domaines_independants':domains,'preuves_titre_modele':exact_title,'preuves_llm':len(b['llm']),'preuves_llm_certaines':llm_certain})
    candidates.sort(key=lambda x:x['score'],reverse=True); visual_rows.sort(key=lambda x:x['similarite'],reverse=True)
    # V2.14 : compteur d'appels externes par analyse (§22 du cahier des charges :
    # mesurer le coût d'un dossier). Les montants se déduisent des tarifs en vigueur.
    meta={'nb_requetes':len(queries),'nb_resultats_texte':len(byurl),'nb_images_trouvees':len(images_pool),
          'nb_images_evaluees':len(scored),'nb_images_non_evaluees':images_unscored,
          'deadline_s':EXTERNAL_DEADLINE_S,'deadline_depassee':images_unscored>0,
          'extraction_llm':llm_result.get('statut')}
    return {'statut':'ok' if candidates or visual_rows else ('erreur' if errors else 'aucun_resultat'),'provider_principal':primary.name,'providers_utilises':used,'queries':queries,'resultats':[{'title':x.title,'url':x.url,'snippet':x.snippet,'source':x.source} for x in list(byurl.values())[:20]],'images':visual_rows[:20],'candidats':candidates[:limit],'erreurs':errors,'brave_role':'secours_uniquement','llm_extraction':llm_result,'meta':meta}
