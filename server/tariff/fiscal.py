"""Moteur fiscal (§16 du cahier des charges) — séparé du moteur de classement.

Rôle : estimer les droits d'importation UE pour un code marchandise et une
origine donnée, en appliquant les mesures du TARIC officiel (base générée par
tools/import_taric.py dans data/tariff/fiscal.sqlite) :

* 103 — droit de pays tiers (ERGA OMNES, sans préférence) ;
* 142 — préférence tarifaire (accord bilatéral, GSP...) : applicable si le pays
  d'origine est membre du groupe géographique de la mesure ;
* 552 — droit antidumping définitif : s'ajoute au droit de base ;
* 117 — suspension tarifaire : information complémentaire.

Principes (même esprit que le moteur tarifaire, §29) :
* le résultat est une ESTIMATION documentée, jamais une certitude fiscale —
  la préférence suppose des preuves d'origine et le respect des règles
  d'origine de l'accord, ce que l'outil ne vérifie pas ;
* aucune donnée n'est codée en dur : tout vient de la base SQLite, régénérée
  depuis l'extraction TARIC officielle.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from functools import lru_cache
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / 'data' / 'tariff' / 'fiscal.sqlite'

# Quelques noms français usuels d'origines (la base TARIC nomme les pays en
# anglais) — complément d'ergonomie, jamais une source de vérité fiscale.
PAYS_FR = {
    'CHINE': 'CN', 'VIETNAM': 'VN', 'VIÊT NAM': 'VN', 'VIET NAM': 'VN',
    'TURQUIE': 'TR', 'INDE': 'IN', 'BANGLADESH': 'BD', 'MAROC': 'MA',
    'TUNISIE': 'TN', 'ALGERIE': 'DZ', 'ALGÉRIE': 'DZ', 'ETATS-UNIS': 'US',
    'ÉTATS-UNIS': 'US', 'JAPON': 'JP', 'COREE DU SUD': 'KR', 'CORÉE DU SUD': 'KR',
    'BRESIL': 'BR', 'BRÉSIL': 'BR', 'ARGENTINE': 'AR', 'SUISSE': 'CH',
    'NORVEGE': 'NO', 'NORVÈGE': 'NO', 'ROYAUME-UNI': 'GB', 'UK': 'GB',
    'UKRAINE': 'UA', 'INDONESIE': 'ID', 'INDONÉSIE': 'ID', 'THAILANDE': 'TH',
    'THAÏLANDE': 'TH', 'PAKISTAN': 'PK', 'CAMBODGE': 'KH', 'MYANMAR': 'MM',
    'BIRMANIE': 'MM', 'TAIWAN': 'TW', 'PHILIPPINES': 'PH', 'MALAISIE': 'MY',
    'MEXIQUE': 'MX', 'CANADA': 'CA', 'EGYPTE': 'EG', 'AFRIQUE DU SUD': 'ZA',
}


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError('Base fiscale absente — lancer tools/import_taric.py')
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    return con


def normalise_code(code: str) -> str | None:
    """« 6403 19 00 » ou « 6403190000 » -> « 6403190000 » ; CN8 complété par 00."""
    digits = ''.join(c for c in str(code or '') if c.isdigit())
    if len(digits) == 8:
        digits += '00'
    return digits if len(digits) == 10 else None


def normalise_origine(origine: str, con: sqlite3.Connection) -> str | None:
    """« Chine », « china », « CN » -> « CN » (ISO2, via la base + noms FR usuels)."""
    o = str(origine or '').strip().upper()
    if not o:
        return None
    if len(o) == 2 and o.isalpha():
        return o
    iso = PAYS_FR.get(o)
    if iso:
        return iso
    row = con.execute("SELECT pays_iso FROM aires_geo WHERE upper(nom)=? LIMIT 1", (o,)).fetchone()
    if row:
        return row['pays_iso']
    row = con.execute("SELECT pays_iso FROM aires_geo WHERE upper(nom) LIKE ? LIMIT 1", (f'%{o}%',)).fetchone()
    return row['pays_iso'] if row else None


@lru_cache(maxsize=256)
def _groupes_du_pays(iso: str) -> tuple[tuple[str, str], ...]:
    """Groupes d'origine contenant le pays (geo, nom du groupe)."""
    with _connect() as con:
        rows = con.execute(
            'SELECT g.geo, COALESCE(gr.nom, g.geo) AS nom FROM aires_geo g '
            'LEFT JOIN groupes gr ON gr.geo = g.geo WHERE g.pays_iso = ?', (iso,)).fetchall()
        return tuple((r['geo'], r['nom']) for r in rows)


def _code_cascade(code10: str) -> list[str]:
    """Le code puis ses parents TARIC par mise à zéro des paires finales.

    Principe de cascade TARIC : une mesure définie à un niveau s'applique aux
    niveaux subordonnés (ex. une préférence au niveau CN8 couvre ses TARIC10).
    """
    codes = [code10]
    for fin in (8, 6, 4):
        codes.append(code10[:fin] + '00' * (5 - fin // 2))
    return codes


def _mesures(con: sqlite3.Connection, codes: list[str], types: set[str]) -> list[sqlite3.Row]:
    marqueurs = ','.join('?' * len(codes))
    rows = con.execute(
        f'SELECT * FROM mesures WHERE code10 IN ({marqueurs}) AND type IN ({",".join("?" * len(types))})',
        (*codes, *types)).fetchall()
    # Les mesures les plus spécifiques (code le plus long) l'emportent.
    rows.sort(key=lambda r: -len(r['code10']))
    return rows


def taux_estime(code: str, origine: str) -> dict:
    """Estime les droits d'importation UE pour un code et une origine.

    Retourne une estimation documentée — jamais une décision fiscale (§29) :
    les préférences supposent des preuves et des règles d'origine respectées.
    """
    result = {
        'principe': "Le moteur fiscal applique les mesures du TARIC officiel ; le résultat est "
                    "une estimation documentée, la décision reste au déclarant (§29).",
        'statut': 'estime',
        'code': str(code or '').strip(),
        'code10': None,
        'origine': str(origine or '').strip(),
        'origine_iso': None,
        'droit_pays_tiers': None,
        'taux_sans_preference': None,
        'preference': None,
        'suspension': None,
        'antidumping': None,
        'taux_estime': None,
        'justificatifs_requis': [],
        'explication': [],
        'avertissement': 'Vérification officielle requise (TARIC/Access2Markets) : les préférences '
                         'supposent des preuves d\'origine et des règles d\'origine respectées ; '
                         'd\'autres mesures (contingents, contrôles) peuvent s\'appliquer.',
    }
    con = _connect()
    try:
        code10 = normalise_code(code)
        if not code10:
            result['statut'] = 'impossible'
            result['raison'] = 'code marchandise invalide (10 chiffres ou CN8 attendus)'
            return result
        result['code10'] = code10
        iso = normalise_origine(origine, con)
        if not iso:
            result['statut'] = 'impossible'
            result['raison'] = f"origine inconnue : « {origine} »"
            return result
        result['origine_iso'] = iso
        codes = _code_cascade(code10)
        toutes = _mesures(con, codes, {'103', '142', '552', '117'})
        if not toutes:
            result['statut'] = 'impossible'
            result['raison'] = 'aucune mesure fiscale dans la base pour ce code'
            return result

        # Droit de pays tiers (ERGA OMNES, le plus spécifique gagne).
        tiers = next((m for m in toutes if m['type'] == '103'), None)
        if tiers:
            result['droit_pays_tiers'] = _detail(tiers)
            result['taux_sans_preference'] = tiers['taux']
            result['explication'].append(
                f"Droit de pays tiers ({tiers['brut']}) : s'applique sans préférence.")

        # Préférence : mesure 142 dont l'origine couvre le pays (ISO direct ou
        # groupe). On retient le taux le plus bas parmi les préférences
        # applicables ; l'ambiguïté éventuelle est signalée.
        groupes = dict(_groupes_du_pays(iso))
        prefs = [m for m in toutes if m['type'] == '142'
                 and (m['geo'] == iso or m['geo'] in groupes)]
        prefs_valides = [m for m in prefs if m['taux'] is not None]
        if prefs_valides:
            prefs_valides.sort(key=lambda m: (m['taux'], -len(m['code10'])))
            meilleure = prefs_valides[0]
            nom_geo = groupes.get(meilleure['geo'], meilleure['geo_nom'])
            result['preference'] = _detail(meilleure) | {'groupe': nom_geo}
            autres = [m for m in prefs_valides[1:]]
            if autres:
                result['explication'].append(
                    'Autres préférences applicables : ' + ', '.join(
                        f"{m['brut']} ({m['geo_nom']})" for m in autres) + '.')
            # L'origine préférentielle N'est PAS automatique (§16) : elle exige
            # un justificatif d'origine et le respect des règles de l'accord.
            result['explication'].append(
                f"Préférence possible ({nom_geo} : {meilleure['brut']}) — UNIQUEMENT sur "
                'justificatif d\'origine et si les règles d\'origine de l\'accord sont '
                f"respectées ; sans justificatif, le droit applicable est "
                f"{result['droit_pays_tiers']['brut'] if result['droit_pays_tiers'] else 'le droit de pays tiers'}.")
            result['justificatifs_requis'] = _justificatifs(nom_geo)

        # Suspension (information, cas d'application restreints).
        susp = next((m for m in toutes if m['type'] == '117'), None)
        if susp:
            result['suspension'] = _detail(susp)
            result['explication'].append(
                f"Suspension enregistrée ({susp['type_nom']}, {susp['brut']}) : "
                "vérifier si le cas précis entre dans le champ de la suspension.")

        # Antidumping : s'ajoute au droit de base ; les taux par entreprise
        # (codes additionnels) sont listés, l'estimation retient le maximum.
        ads = [m for m in toutes if m['type'] == '552'
               and (m['geo'] == iso or m['geo'] in groupes)]
        if ads:
            detail = [_detail(m) | {'add_code': m['add_code'] or None} for m in ads]
            taux_ads = sorted(m['taux'] for m in ads if m['taux'] is not None)
            result['antidumping'] = {'lignes': detail,
                                     'taux_min': taux_ads[0] if taux_ads else None,
                                     'taux_max': taux_ads[-1] if taux_ads else None,
                                     'brut': ads[-1]['brut']}
            result['explication'].append(
                f"Droit antidumping définitif pour {iso} ({ads[-1]['brut']}) : s'ajoute au droit "
                'de base ; taux variable selon les entreprises (codes additionnels).')

        # Estimation : préférence (si justifiée) sinon pays tiers ; l'antidumping s'ajoute.
        base = result['preference'] or result['droit_pays_tiers']
        ad_max = result['antidumping']['taux_max'] if result['antidumping'] else None
        if base and base['taux'] is not None:
            total = base['taux'] + (ad_max or 0)
            if result['preference'] and result['taux_sans_preference'] is not None:
                sans_justif = result['taux_sans_preference'] + (ad_max or 0)
                result['taux_sans_justificatif'] = round(sans_justif, 4)
                result['explication'].append(
                    f"Estimation AVEC justificatif d'origine ({base['brut']}"
                    + (f" + antidumping {result['antidumping']['brut']}" if result['antidumping'] else '')
                    + f") = {_pct(total)} ; SANS justificatif = {_pct(sans_justif)}.")
            else:
                result['explication'].append(
                    f"Taux estimé ({base['brut']}"
                    + (f" + antidumping {result['antidumping']['brut']}" if result['antidumping'] else '')
                    + f") = {_pct(total)} ad valorem.")
            if ad_max is not None:
                result['explication'].append(
                    "Estimation prudente : antidumping maximal retenu (le taux par "
                    'entreprise sera révisé à la déclaration).')
            result['taux_estime'] = round(total, 4)
        elif base:
            result['explication'].append(
                f"Droit non ad valorem ({base['brut']}) : le taux ne peut pas être sommé "
                'en pourcentage ; montants à la pièce/kg selon la base officielle.')
        return result
    finally:
        con.close()


def _pct(taux: float) -> str:
    return f"{taux * 100:.3f} %".rstrip('0').rstrip('.')


def _justificatifs(groupe: str) -> list[str]:
    """Justificatifs exigés pour l'origine préférentielle (jamais automatique, §16).

    La forme exacte dépend de l'accord : le moteur la précise pour les cas
    connus (GSP => REX) et renvoie sinon à la documentation de l'accord.
    """
    docs = ["Preuve d'origine conforme à l'accord (certificat EUR.1 ou déclaration "
           "d'origine sur la facture/autre document commercial) ;",
           'respect des règles d\'origine de l\'accord (transformation suffisante, '
           'non-altération, transport direct selon les termes de l\'accord).']
    if 'GSP' in str(groupe or '').upper():
        docs.insert(0, "Inscription de l'exportateur au registre REX (numéro REX "
                       "mentionné sur la déclaration d'origine) — système du SPG ;")
    return docs


def question_origine() -> dict:
    """Question ciblée (§31.3) : l'origine permet d'estimer les droits (§16)."""
    return {
        'champ': 'origine',
        'question': "Quel est le pays d'origine de la marchandise (lieu de production, "
                    'et non simplement le pays d\'expédition) ?',
        'impact': "permet d'estimer les droits d'importation (droit de pays tiers, "
                  'préférence éventuelle SUR JUSTIFICATIF d\'origine, antidumping) ; '
                  "sans origine, seul le droit de pays tiers indicatif est affiché",
    }


def _detail(m: sqlite3.Row) -> dict:
    return {'type': m['type_nom'], 'taux': m['taux'], 'brut': m['brut'],
            'base_legale': m['legal'], 'geo': m['geo'], 'code10': m['code10']}
