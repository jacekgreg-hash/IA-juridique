"""Fusion des candidats locaux (catalogue) et web, et décision finale.

Extrait de server/api/routes.py en V2.13.7 pour être testable sans FastAPI.

Correctif : avant, la clé de regroupement était (marque, modèle) et les candidats
web héritaient de la marque de la vision. Si la vision ne trouvait pas la marque,
le candidat web (marque vide) et le candidat catalogue (« Nike ») n'étaient jamais
regroupés : pas de bonus de convergence, et ils se faisaient concurrence.
Désormais un même modèle n'est séparé en deux groupes que si les deux marques sont
connues ET différentes.
"""
from __future__ import annotations

from server.candidates.engine import clean

_LIST_FIELDS = ('raisons', 'contradictions', 'urls', 'titres', 'extraits', 'domaines')


def _new_group(item: dict, brand: str | None) -> dict:
    model = item.get('modele')
    return {
        'id': f"candidate:{clean(brand) or 'inconnue'}:{clean(model)}".lower(),
        'marque': brand,
        'objet': item.get('objet'),
        'modele': model,
        'reference': item.get('reference'),
        'score': 0.0,
        'raisons': [], 'contradictions': [],
        'preuve_identifiant': None, 'preuve_identifiant_source': None,
        'similarite_image': None, 'type_preuve_visuelle': 'indisponible', 'details_visuels': {},
        'urls': [], 'titres': [], 'extraits': [], 'domaines': [],
        'sources': set(), 'preuves_llm': 0, 'preuves_llm_certaines': 0,
    }


def _find_group(groups: list[dict], model_key: str, brand: str | None) -> dict | None:
    for g in groups:
        if clean(g['modele']) != model_key:
            continue
        gb, ib = clean(g['marque']), clean(brand)
        if not gb or not ib or gb == ib:
            return g
    return None


def merge_candidate_sources(local_candidates, web_candidates, vision) -> list[dict]:
    vision_brand = vision.get('marque')
    groups: list[dict] = []
    # Les candidats locaux (marque connue du catalogue) d'abord, les candidats web ensuite.
    for item in list(local_candidates or []) + list(web_candidates or []):
        model = item.get('modele')
        if not model:
            continue
        brand = item.get('marque') or None
        g = _find_group(groups, clean(model), brand)
        if g is None:
            g = _new_group(item, brand or vision_brand)
            groups.append(g)
        elif not g.get('marque') and brand:
            g['marque'] = brand
            g['id'] = f"candidate:{clean(brand)}:{clean(g['modele'])}".lower()
        g['sources'].add(item.get('source', ''))
        g['score'] = max(g['score'], float(item.get('score') or 0))
        for field in _LIST_FIELDS:
            for v in item.get(field) or []:
                if v not in g[field]:
                    g[field].append(v)
        for field in ('preuve_identifiant', 'preuve_identifiant_source', 'reference'):
            if not g.get(field) and item.get(field):
                g[field] = item.get(field)
        sim = item.get('similarite_image')
        if sim is None:
            sim = item.get('similarite_image_web')
        if sim is not None and (g['similarite_image'] is None or sim > g['similarite_image']):
            g['similarite_image'] = sim
            g['type_preuve_visuelle'] = item.get('type_preuve_visuelle') or g['type_preuve_visuelle']
            g['details_visuels'] = item.get('details_visuels') or g['details_visuels']
        g['preuves_llm'] += int(item.get('preuves_llm') or 0)
        g['preuves_llm_certaines'] += int(item.get('preuves_llm_certaines') or 0)
    merged = []
    for g in groups:
        # La concordance entre sources est une couche de preuve distincte.
        if len(g['sources']) >= 2:
            g['score'] = min(1.0, g['score'] + 0.12)
            g['raisons'].append('convergence entre preuves locales et web')
        if len(g['domaines']) >= 2 and 'confirmé par' not in ' '.join(g['raisons']):
            g['score'] = min(1.0, g['score'] + 0.06)
        g['score'] = round(g['score'], 3)
        g['urls'] = g['urls'][:8]; g['titres'] = g['titres'][:8]
        g['extraits'] = g['extraits'][:4]; g['domaines'] = g['domaines'][:8]
        g['sources'] = sorted(s for s in g['sources'] if s)
        merged.append(g)
    merged.sort(key=lambda x: x['score'], reverse=True)
    return merged[:8]


def candidate_decision(candidates: list[dict]) -> dict:
    if not candidates:
        return {'statut': 'aucun_candidat', 'candidat': None, 'confiance': 0.0}
    top = candidates[0]
    second = candidates[1]['score'] if len(candidates) > 1 else 0.0
    margin = round(top['score'] - second, 3)
    if top['score'] >= .82 and margin >= .15:
        status = 'candidat_fort'
    elif top['score'] >= .62 and margin >= .08:
        status = 'candidats_a_verifier'
    else:
        status = 'faible'
    return {'statut': status, 'candidat': top['id'], 'confiance': top['score'], 'marge_sur_second': margin,
            'regle': 'aucune confirmation réglementaire sur la seule identification visuelle'}


def apply_candidate_decision_to_produit(produit: dict, decision: dict, candidates: list[dict]) -> None:
    """Reflète la décision dans produit.modele_candidate / statut (section 17 du cahier des charges).

    Un candidat n'est jamais écrit comme « confirme » : ce statut est réservé à une
    vérification contre des données officielles (section 8, hiérarchie des preuves)."""
    if decision.get('statut') not in ('candidat_fort', 'candidats_a_verifier') or not decision.get('candidat'):
        return
    top = next((c for c in candidates if c.get('id') == decision['candidat']), None)
    if not top or not top.get('modele'):
        return
    produit['modele_candidate'] = top['modele']
    produit['modele_statut'] = 'probable' if decision['statut'] == 'candidat_fort' else 'a_verifier'
    produit['modele_confiance_moteur'] = decision.get('confiance', 0.0)
