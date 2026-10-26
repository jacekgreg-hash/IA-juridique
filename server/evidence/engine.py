import re
from difflib import SequenceMatcher


def clean_text(value: str) -> str:
    value = str(value or '').upper().strip()
    value = re.sub(r'[^A-Z0-9]+', '', value)
    return value


def similarity(a: str, b: str) -> float:
    a, b = clean_text(a), clean_text(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def looks_like_identifier(value: str) -> bool:
    v = clean_text(value)
    if len(v) < 3 or len(v) > 24:
        return False
    return bool(re.search(r'\d', v) and re.search(r'[A-Z]', v)) or bool(re.fullmatch(r'[A-Z]{1,5}[-.]?\d{2,8}', v))


def candidate_from_fields(vision: dict) -> list[tuple[str, str]]:
    out = []
    for field in ('reference', 'modele'):
        value = vision.get(field)
        if value and looks_like_identifier(value):
            out.append((field, str(value).strip()))
    return out


def score_candidate(field: str, value: str, vision: dict, ocr_text: list[str]) -> tuple[float, list[str], list[str]]:
    score = 0.0
    evidence = []
    contradictions = []
    vconf = float(vision.get('reference_confiance', 0) or 0)

    # The model's own statement is weak evidence. It can propose, never certify.
    if field == 'reference':
        score += min(vconf, 0.20)
    else:
        score += min(float(vision.get('identification_confiance', 0) or 0), 0.10)

    best = 0.0
    best_text = None
    for text in ocr_text:
        sim = similarity(value, text)
        if sim > best:
            best, best_text = sim, text
    if best >= 0.96:
        score += 0.65
        evidence.append(f'OCR confirme exactement {best_text!r}')
    elif best >= 0.82:
        score += 0.40
        evidence.append(f'OCR ressemble à {best_text!r}')
    elif best >= 0.65:
        score += 0.15
        evidence.append(f'OCR partiellement compatible avec {best_text!r}')

    # A visible identifier needs independent support. Vision alone is not enough.
    if not evidence:
        contradictions.append(f'Aucune preuve OCR indépendante pour {field}={value!r}')

    return max(0.0, min(1.0, score)), evidence, contradictions


def apply_evidence(vision: dict, ocr_text: list[str]) -> dict:
    result = dict(vision)
    result['informations_visuelles_certaines'] = []
    result['informations_a_verifier'] = []
    result['reference_candidate'] = None
    result['modele_candidate'] = None
    result['reference_statut'] = 'inconnu'
    result['modele_statut'] = 'inconnu'

    # Brand/category are deliberately conservative: model confidence is capped.
    if result.get('marque'):
        result['informations_visuelles_certaines'].append(f"Marque proposée par la vision : {result['marque']}")

    for field, value in candidate_from_fields(vision):
        score, evidence, contradictions = score_candidate(field, value, vision, ocr_text)
        result[f'{field}_candidate'] = value
        if score >= 0.80:
            result[field] = value
            result[f'{field}_statut'] = 'confirme'
            result[f'{field}_confiance_moteur'] = round(score, 3)
            result['informations_visuelles_certaines'].extend(evidence)
        elif score >= 0.45:
            result[field] = None
            result[f'{field}_statut'] = 'probable'
            result[f'{field}_confiance_moteur'] = round(score, 3)
            result['informations_a_verifier'].append(f'{field.capitalize()} candidat : {value}')
            result['informations_a_verifier'].extend(evidence)
        else:
            result[field] = None
            result[f'{field}_statut'] = 'a_verifier'
            result[f'{field}_confiance_moteur'] = round(score, 3)
            result['informations_a_verifier'].append(f'{field.capitalize()} rejeté provisoirement : {value}')
            result['informations_a_verifier'].extend(contradictions)

    # Filter obviously noisy OCR. Keep raw OCR elsewhere for traceability.
    clean_ocr = []
    for text in ocr_text:
        t = str(text).strip()
        compact = clean_text(t)
        if len(compact) >= 3 and not re.fullmatch(r'(.)\1{2,}', compact):
            clean_ocr.append(t)

    result['identification_confiance'] = round(min(0.85, float(vision.get('identification_confiance', 0) or 0)), 3)
    result['reference_confiance'] = round(float(result.get('reference_confiance', 0) or 0), 3)
    result['informations_a_verifier'] = list(dict.fromkeys(result['informations_a_verifier']))[:12]
    result['informations_visuelles_certaines'] = list(dict.fromkeys(result['informations_visuelles_certaines']))[:8]
    return result
