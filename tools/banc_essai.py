"""Banc d'essai (§26 du cahier des charges) : calibrage des seuils.

Exécute des analyses RÉELLES (moteurs configurés par .env — vision, OCR) sur
des cas documentés (photo + résultats attendus), puis mesure la chaîne
complète : vision -> enrichissement -> fusion des preuves -> classement
tarifaire -> moteur fiscal.

Chaque cas vit dans data/banc_essai/cases.json :
    { "id": "nike-p-6000",
      "image": "data/banc_essai/images/NIKE-P-6000.jpg",
      "attendus": {
        "nature": "chaussure de sport",
        "marque": "Nike",
        "modele": "P-6000",
        "codes_acceptables": ["6404 11 00", "6403 19 00"],
        "origine": "VN",
        "note": "tige textile ou cuir selon la paire photographiée" } }

Ajouter un cas = déposer une photo dans data/banc_essai/images/ + une entrée.
Le rapport mesure nature/marque/modèle/code et les délais — le calibrage des
seuils (fusion OCR 0.96/0.82/0.65, statuts 0.80/0.45, classement) se fait sur
ces mesures, pas sur des hypothèses.

Usage : python tools/banc_essai.py [id_cas ...]   (sans argument : tous)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # paquet `server`

from dotenv import load_dotenv  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BANC = ROOT / 'data' / 'banc_essai'
CASES_FILE = BANC / 'cases.json'


def _verdict_code(classement: dict, acceptables: list[str]) -> str:
    codes = [c['code'] for c in classement.get('candidats') or []]
    if not codes:
        return 'impossible'
    if codes[0] in acceptables:
        return 'exact'
    if any(c in acceptables for c in codes):
        return 'present'
    return 'faux_positif'


def _verdict_text(obtenu: str | None, attendu: str | None) -> str | None:
    if not attendu:
        return None
    o = str(obtenu or '').strip().lower()
    if o == attendu.lower():
        return 'exact'
    if attendu.lower() in o:
        return 'exact_partiel'
    return 'manque'


def executer_cas(case: dict) -> dict:
    from server.vision.select import analyze
    from server.ocr.select import ocr_detailed
    from server.vision.enrich import enrich_vision
    from server.fusion.engine import fuse
    from server.tariff.engine import propose_classement
    from server.tariff.fiscal import taux_estime

    image = ROOT / case['image']
    if not image.exists():
        return {'id': case['id'], 'erreur': f'image absente : {case["image"]}'}
    attendus = case.get('attendus') or {}
    repetitions = int(case.get('repetitions') or 1)
    executions = []
    for rang in range(repetitions):
        t0 = time.time()
        vision = analyze(image)
        t_vision = time.time() - t0
        t1 = time.time()
        ocr_detail = ocr_detailed(image)
        ocr_text = ocr_detail.get('text') or []
        t_ocr = time.time() - t1
        enrich_vision(vision['fast'], ocr_text)
        timings = {'version': 'banc_essai', 'temps_ocr': round(t_ocr, 2),
                   'temps_vision': round(t_vision, 2)}
        reponse = fuse(vision['fast'], ocr_text, timings, []).model_dump(mode='json')
        t2 = time.time()
        classement = propose_classement(reponse['produit'], vision['fast'].get('caption') or '', ocr_text)
        t_classement = time.time() - t2
        candidats = [{'code': c['code'], 'confiance': c['confiance'],
                      'rtc': (c.get('rtc') or {}).get('nb', 0)}
                     for c in (classement.get('candidats') or [])[:3]]
        executions.append({
            'legende': (vision['fast'].get('caption') or '')[:300],
            'produit': {'objet': reponse['produit'].get('objet'),
                        'marque': reponse['produit'].get('marque'),
                        'modele': reponse['produit'].get('modele'),
                        'modele_candidate': reponse['produit'].get('modele_candidate')},
            'verdicts': {
                'nature': _verdict_text(reponse['produit'].get('objet'), attendus.get('nature')),
                'marque': _verdict_text(reponse['produit'].get('marque'), attendus.get('marque')),
                'modele': _verdict_text(reponse['produit'].get('modele') or
                                        reponse['produit'].get('modele_candidate'),
                                        attendus.get('modele')),
                'code': _verdict_code(classement, attendus.get('codes_acceptables') or []),
            },
            'classement': {'statut': classement.get('statut'),
                           'recherche': classement.get('recherche'),
                           'candidats': candidats,
                           'questions': len(classement.get('questions') or [])},
            'delais_s': {'vision': round(t_vision, 2), 'ocr': round(t_ocr, 2),
                         'classement': round(t_classement, 3)},
        })
    resultat = dict(executions[-1])          # la dernière exécution en détail
    resultat['id'] = case['id']
    resultat['executions'] = executions      # trace complète des répétitions
    # Stabilité (§26 : la variance du moteur vision se mesure) — légendes
    # distinctes et verdicts divergents entre les exécutions.
    legendes = {e['legende'] for e in executions}
    codes_top1 = {e['classement']['candidats'][0]['code']
                  for e in executions if e['classement']['candidats']}
    resultat['stabilite'] = {'executions': len(executions),
                             'legendes_distinctes': len(legendes),
                             'codes_top1_distincts': len(codes_top1)}
    # Moteur fiscal si une origine est documentée pour le cas.
    origine = attendus.get('origine')
    if origine and classement.get('candidats'):
        fiscal = taux_estime(classement['candidats'][0]['code'], origine) \
            if classement['candidats'][0].get('code') else None
        if isinstance(fiscal, dict):
            resultat['fiscal'] = {k: fiscal[k] for k in
                                  ('origine_iso', 'taux_estime', 'taux_sans_justificatif')}
    return resultat


def main() -> None:
    load_dotenv(ROOT / '.env')
    cases = json.loads(CASES_FILE.read_text(encoding='utf-8'))['cases']
    if len(sys.argv) > 1:
        cases = [c for c in cases if c['id'] in sys.argv[1:]]
    print(f"Banc d'essai (§26) : {len(cases)} cas — moteurs configurés par .env")
    resultats = []
    for case in cases:
        print(f"  … {case['id']}")
        resultat = executer_cas(case)
        resultats.append(resultat)
        if 'erreur' in resultat:
            print(f"     ERREUR : {resultat['erreur']}")
        else:
            v = resultat['verdicts']
            stab = resultat.get('stabilite') or {}
            print(f"     nature={v['nature']} marque={v['marque']} modele={v['modele']} "
                  f"code={v['code']} | classement={resultat['classement']['statut']}"
                  + (f" | stabilité : {stab['legendes_distinctes']} légende(s), "
                     f"{stab['codes_top1_distincts']} code(s) top-1 en {stab['executions']} exécution(s)"
                     if stab.get('executions', 1) > 1 else ''))
    # Synthèse.
    verdicts = [r['verdicts'] for r in resultats if 'verdicts' in r]
    synthese = {}
    for champ in ('nature', 'marque', 'modele', 'code'):
        valeurs = [v[champ] for v in verdicts if v.get(champ)]
        synthese[champ] = {'exact': valeurs.count('exact') + valeurs.count('exact_partiel'),
                           'total': len(valeurs)}
    rapport = {'date': date.today().isoformat(), 'cas': resultats, 'synthese': synthese}
    chemin = BANC / f'rapport_{date.today().isoformat()}.json'
    chemin.write_text(json.dumps(rapport, ensure_ascii=False, indent=1), encoding='utf-8')
    print('\nSynthèse :')
    for champ, s in synthese.items():
        print(f"  {champ:<8} : {s['exact']}/{s['total']} exact")
    print(f"\nRapport complet : {chemin}")


if __name__ == '__main__':
    main()
