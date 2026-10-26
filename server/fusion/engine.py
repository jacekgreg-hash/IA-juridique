from server.evidence.engine import apply_evidence, clean_text, similarity
from server.models.schemas import AnalysisResponse, Evidence, ProductIdentification
from server.utils.normalize import normalize_model_output


def unique(values):
    result = []
    for value in values or []:
        value = str(value).strip()
        if value and value not in result:
            result.append(value)
    return result


def fuse(vision, ocr_text, timings, verification=None):
    data = apply_evidence(normalize_model_output(vision), ocr_text)
    data['texte_visible'] = unique(data.get('texte_visible'))[:5]
    data['caracteristiques'] = unique(data.get('caracteristiques'))[:5]

    contradictions = []
    evidence = []
    if data.get('marque'):
        evidence.append(Evidence(source='vision', field='marque', value=data['marque'], confidence=min(float(data.get('identification_confiance', 0)), .30), role='faible'))
    if data.get('objet'):
        evidence.append(Evidence(source='vision', field='objet', value=data['objet'], confidence=min(float(data.get('identification_confiance', 0)), .30), role='faible'))

    for field in ('modele', 'reference'):
        candidate = data.get(f'{field}_candidate')
        if candidate:
            status = data.get(f'{field}_statut', 'a_verifier')
            conf = float(data.get(f'{field}_confiance_moteur', 0))
            evidence.append(Evidence(source='vision', field=f'{field}_candidate', value=candidate, confidence=conf, role='candidate'))
            if status != 'confirme':
                contradictions.append(f'{field.capitalize()} non confirmé indépendamment : {candidate}')

    for text in ocr_text[:15]:
        role = 'support' if any(similarity(text, data.get(f'{f}_candidate') or '') >= .82 for f in ('modele', 'reference')) else 'brut'
        evidence.append(Evidence(source='ocr', field='texte_visible', value=text, confidence=.65 if role == 'support' else .10, role=role))

    if verification:
        for item in verification:
            if item.get('vu') is True and item.get('candidat'):
                evidence.append(Evidence(source='qwen_verification', field='candidat', value=str(item['candidat']), confidence=float(item.get('confiance', 0) or 0), role='support'))
            elif item.get('candidat'):
                contradictions.append(f"Vérification ciblée non concluante : {item['candidat']}")

    missing = []
    if not data.get('objet'):
        missing.append('nature de la marchandise')
    if not data.get('modele'):
        missing.append('modèle confirmé')
    if not data.get('reference'):
        missing.append('référence confirmée')
    if not data.get('matiere_composition'):
        missing.append('matière/composition')

    return AnalysisResponse(
        produit=ProductIdentification(**data),
        ocr_text=ocr_text,
        preuves=evidence,
        contradictions=unique(contradictions),
        informations_manquantes=unique(missing),
        meta=timings,
    )
