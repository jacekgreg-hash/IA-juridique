from typing import Any

LIST_FIELDS = {
    'texte_visible', 'caracteristiques', 'matiere_composition',
    'informations_visuelles_certaines', 'informations_a_verifier',
    'preuves_certaines', 'a_verifier', 'zones_interessantes'
}


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if x is not None and str(x).strip()]
    if isinstance(value, (tuple, set)):
        return [str(x).strip() for x in value if x is not None and str(x).strip()]
    if isinstance(value, str):
        value = value.strip()
        return [value] if value else []
    return [str(value).strip()]


def normalize_model_output(data: Any) -> dict:
    if not isinstance(data, dict):
        return {}
    out = dict(data)
    for key in LIST_FIELDS:
        if key in out:
            out[key] = as_list(out[key])
    for key in ('objet', 'designation_commerciale', 'marque', 'modele', 'reference', 'usage_fonction', 'origine_visible'):
        if out.get(key) is not None and not isinstance(out[key], str):
            out[key] = str(out[key])
    for key in ('identification_confiance', 'reference_confiance'):
        try:
            value = float(out.get(key, 0) or 0)
            if value > 1:
                value /= 100
            out[key] = max(0.0, min(1.0, value))
        except (TypeError, ValueError):
            out[key] = 0.0
    return out
