from __future__ import annotations
import json, os, re, time
from typing import Any
import requests
from dotenv import load_dotenv

load_dotenv()
OLLAMA_URL = os.getenv('OLLAMA_TEXT_URL', 'http://127.0.0.1:11434/api/generate').rstrip('/')
TEXT_MODEL = os.getenv('TEXT_MODEL', 'qwen3:0.6b').strip()
TIMEOUT = int(os.getenv('TEXT_LLM_TIMEOUT', '35'))
MAX_ITEMS = int(os.getenv('TEXT_LLM_MAX_ITEMS', '16'))

PROMPT = r'''Tu es un extracteur de références produit. Tu ne dois PAS identifier le produit à partir du monde réel et tu ne dois rien inventer.
Pour chaque source ci-dessous, extrais uniquement un nom/code de modèle réellement présent dans le titre ou l'extrait.
Le modèle doit être distinct de la catégorie, de la couleur, de la taille, de l'année, du prix et du texte marketing.
Conserve exactement la forme visible dans la source (tu peux seulement normaliser les espaces).
Si aucun modèle clair n'est présent, mets modele à null.
La confiance est "certain" seulement si le modèle est explicitement présenté comme produit/modèle; sinon "probable" ou "inconnu".
Réponds UNIQUEMENT avec ce JSON :
{"extractions":[{"source_id":"w1","modele":null,"confiance":"inconnu"}]}

SOURCES:
'''

def _balanced_json(text: str) -> dict:
    start=text.find('{')
    if start<0: raise ValueError('JSON absent')
    depth=0; ins=False; esc=False
    for i,ch in enumerate(text[start:], start):
        if ins:
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': ins=False
        else:
            if ch=='"': ins=True
            elif ch=='{': depth+=1
            elif ch=='}':
                depth-=1
                if depth==0: return json.loads(text[start:i+1])
    raise ValueError('JSON tronqué')

def _norm(s: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'[^\wÀ-ÿ0-9\-./+ ]+', ' ', s or '')).strip().casefold()

def _exact_in_source(model: str, title: str, snippet: str) -> bool:
    if not model: return False
    m=_norm(model); return bool(m) and (m in _norm(title) or m in _norm(snippet))

def extract(sources: list[dict[str, Any]]) -> dict[str, Any]:
    sources=sources[:MAX_ITEMS]
    if not sources:
        return {'statut':'aucune_source','modele':TEXT_MODEL,'extractions':[],'temps':0.0}
    lines=[]
    for s in sources:
        sid=str(s.get('source_id',''))
        title=str(s.get('title','')).strip()[:260]
        snippet=str(s.get('snippet','')).strip()[:420]
        lines.append(f'[{sid}] TITRE: {title}\nEXTRAIT: {snippet}')
    payload={'model':TEXT_MODEL,'prompt':PROMPT+'\n\n'.join(lines),'stream':False,'format':'json','keep_alive':'0s','options':{'temperature':0,'top_k':8,'top_p':0.8,'num_ctx':2048,'num_predict':180}}
    started=time.time()
    try:
        r=requests.post(OLLAMA_URL,json=payload,timeout=TIMEOUT)
        r.raise_for_status(); data=r.json(); content=str(data.get('response') or '')
        obj=_balanced_json(content)
        accepted=[]
        byid={str(s.get('source_id')):s for s in sources}
        for row in obj.get('extractions') or []:
            sid=str(row.get('source_id') or '')
            model=row.get('modele')
            conf=str(row.get('confiance') or 'inconnu').lower()
            src=byid.get(sid)
            if not src or not isinstance(model,str) or not model.strip():
                continue
            model=re.sub(r'\s+',' ',model).strip()
            if conf not in {'certain','probable','inconnu'}: conf='inconnu'
            # Hard anti-hallucination barrier: the extracted model must literally
            # occur in the source title or snippet after conservative normalization.
            if conf=='inconnu' or not _exact_in_source(model,src.get('title',''),src.get('snippet','')):
                continue
            accepted.append({'source_id':sid,'modele':model,'confiance':conf})
        return {'statut':'ok','modele':TEXT_MODEL,'extractions':accepted,'temps':round(time.time()-started,2)}
    except Exception as exc:
        return {'statut':'indisponible','modele':TEXT_MODEL,'extractions':[],'temps':round(time.time()-started,2),'erreur':f'{type(exc).__name__}: {exc}'}
