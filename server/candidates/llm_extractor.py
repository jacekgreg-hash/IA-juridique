from __future__ import annotations
import json, os, re, time
from typing import Any
import requests
from dotenv import load_dotenv

load_dotenv()

# V2.14 : le fournisseur du LLM texte est interchangeable (§4 du cahier des charges).
#   ollama  : moteur local (défaut — gratuit, hors ligne, confidentiel) ;
#   mistral : API Mistral (nécessite MISTRAL_API_KEY ; vérifier les conditions de
#             La Plateforme avant d'y envoyer des données clients, §9.1 cahier général).
PROVIDER=os.getenv('TEXT_LLM_PROVIDER','ollama').strip().lower()
OLLAMA_URL = os.getenv('OLLAMA_TEXT_URL', 'http://127.0.0.1:11434/api/generate').rstrip('/')
TEXT_MODEL = os.getenv('TEXT_MODEL', 'qwen3:0.6b').strip()
MISTRAL_URL = os.getenv('MISTRAL_TEXT_URL', 'https://api.mistral.ai/v1/chat/completions')
MISTRAL_TEXT_MODEL = os.getenv('MISTRAL_TEXT_MODEL', 'mistral-small-latest').strip()
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY', '').strip()
TIMEOUT = int(os.getenv('TEXT_LLM_TIMEOUT', '35'))
# V2.14 : 16 sources × ~50 tokens de JSON dépassaient num_predict=180 : la réponse
# était tronquée et _balanced_json levait « JSON tronqué » => extraction
# « indisponible » silencieuse. 8 sources et 768 tokens de sortie.
MAX_ITEMS = int(os.getenv('TEXT_LLM_MAX_ITEMS', '8'))

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

def _current_model() -> str:
    return MISTRAL_TEXT_MODEL if PROVIDER=='mistral' else TEXT_MODEL

def _call_ollama(prompt: str) -> tuple[str, str]:
    payload={'model':TEXT_MODEL,'prompt':prompt,'stream':False,'format':'json','keep_alive':'0s',
             'options':{'temperature':0,'top_k':8,'top_p':0.8,'num_ctx':2048,'num_predict':768}}
    r=requests.post(OLLAMA_URL,json=payload,timeout=TIMEOUT)
    r.raise_for_status()
    return str(r.json().get('response') or ''), TEXT_MODEL

def _call_mistral(prompt: str) -> tuple[str, str]:
    if not MISTRAL_API_KEY:
        raise RuntimeError('MISTRAL_API_KEY absente (TEXT_LLM_PROVIDER=mistral)')
    payload={'model':MISTRAL_TEXT_MODEL,'temperature':0,'max_tokens':768,
             'response_format':{'type':'json_object'},
             'messages':[{'role':'user','content':prompt}]}
    r=requests.post(MISTRAL_URL,json=payload,timeout=TIMEOUT,
                    headers={'Authorization':f'Bearer {MISTRAL_API_KEY}','Accept':'application/json'})
    r.raise_for_status()
    content=r.json()['choices'][0]['message']['content']
    return str(content or ''), MISTRAL_TEXT_MODEL

def extract(sources: list[dict[str, Any]]) -> dict[str, Any]:
    sources=sources[:MAX_ITEMS]
    if not sources:
        return {'statut':'aucune_source','modele':_current_model(),'extractions':[],'temps':0.0}
    lines=[]
    for s in sources:
        sid=str(s.get('source_id',''))
        title=str(s.get('title','')).strip()[:260]
        snippet=str(s.get('snippet','')).strip()[:420]
        lines.append(f'[{sid}] TITRE: {title}\nEXTRAIT: {snippet}')
    prompt=PROMPT+'\n\n'.join(lines)
    started=time.time()
    try:
        content, model = (_call_mistral(prompt) if PROVIDER=='mistral' else _call_ollama(prompt))
        obj=_balanced_json(content)
        accepted=[]
        byid={str(s.get('source_id')):s for s in sources}
        for row in obj.get('extractions') or []:
            sid=str(row.get('source_id') or '')
            model_name=row.get('modele')
            conf=str(row.get('confiance') or 'inconnu').lower()
            src=byid.get(sid)
            if not src or not isinstance(model_name,str) or not model_name.strip():
                continue
            model_name=re.sub(r'\s+',' ',model_name).strip()
            if conf not in {'certain','probable','inconnu'}: conf='inconnu'
            # Hard anti-hallucination barrier: the extracted model must literally
            # occur in the source title or snippet after conservative normalization.
            # (Garde conservée quel que soit le fournisseur — c'est elle, pas le
            # modèle, qui garantit la fiabilité.)
            if conf=='inconnu' or not _exact_in_source(model_name,src.get('title',''),src.get('snippet','')):
                continue
            accepted.append({'source_id':sid,'modele':model_name,'confiance':conf})
        return {'statut':'ok','modele':model,'extractions':accepted,'temps':round(time.time()-started,2)}
    except Exception as exc:
        return {'statut':'indisponible','modele':_current_model(),'extractions':[],'temps':round(time.time()-started,2),'erreur':f'{type(exc).__name__}: {exc}'}
