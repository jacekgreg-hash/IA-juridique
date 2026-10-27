"""Import de la base tarifaire officielle TARIC -> données RITA (§10 du cahier des charges).

Source : extraction mensuelle officielle de la base TARIC (Commission européenne,
groupe CIRCABC « TARIC & Quota Data and Information »), fichier eu-taric-*.zip.
La structure des fichiers est documentée dans le PDF CIRCABC « Explanation for
the Taric database extractions » :

* « Nomenclature FR » : hiérarchie des codes marchandises avec désignations FR.
  Le code est « 10 chiffres + suffixe de ligne » ; le suffixe 80 marque les lignes
  de biens réelles, les autres suffixes des lignes intermédiaires structurelles.
  La hiérarchie est donnée par l'indentation (colonne de tirets), en ordre de
  fichier — PAS par préfixe de code (les branches « autres » changent de
  chiffres par rapport à leur parent).
* « Declarable codes » : drapeau IS_LEAF (code déclarable en douane).
* « Duties Import 01-99 » : mesures par code ; le droit de pays tiers est la
  mesure de type 103 (« Third country duty ») à l'origine ERGA OMNES.

Sorties (régénérées, jamais éditées à la main) :
* data/tariff/nomenclature_fr.json — nomenclature FR des codes déclarables
  (CN8 et TARIC10) avec désignations assemblées depuis la hiérarchie et
  droits de pays tiers.
* data/tariff/tariff_base.json — base du moteur tarifaire : les familles et
  discriminants restent définis ci-dessous (logique RITA), mais codes,
  désignations, taux et bases légales proviennent du TARIC officiel.
* data/tariff/fiscal.sqlite — base du moteur fiscal (§16) : mesures par code
  et par origine (droit de pays tiers 103, préférences 142, antidumping 552,
  suspensions 117) + appartenance des pays aux groupes d'origine.

Usage : python tools/import_taric.py [chemin/vers/eu-taric-YYYY-MM.zip]
Sans argument, prend le eu-taric-*.zip le plus récent dans data/tariff/raw/.
"""
from __future__ import annotations

import csv
import gc
import json
import re
import sqlite3
import sys
import zipfile
import html
import io
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / 'data' / 'tariff' / 'raw'
OUT_NOMENCLATURE = ROOT / 'data' / 'tariff' / 'nomenclature_fr.json'
OUT_BASE = ROOT / 'data' / 'tariff' / 'tariff_base.json'
OUT_FISCAL = ROOT / 'data' / 'tariff' / 'fiscal.sqlite'
OUT_NOTES = ROOT / 'data' / 'tariff' / 'notes_cn_fr.json'
OUT_EBTI = ROOT / 'data' / 'tariff' / 'ebti.sqlite'

# Types de mesures conservés pour le moteur fiscal (§16) — codes TARIC
# officiels : 103 droit de pays tiers, 142 préférence tarifaire,
# 552 droit antidumping définitif, 117 suspension.
TYPES_FISCAL = {'103', '142', '552', '117'}

# Droit de pays tiers : type de mesure 103, origine ERGA OMNES (toutes origines
# sans préférence) — taux INDICATIF, le calcul fiscal (§16) dépend de l'origine.
THIRD_COUNTRY_DUTY_TYPE = '103'
ERGA_OMNES = 'ERGA OMNES'

# --- Familles du moteur tarifaire (logique RITA, §9/§11) ----------------------
# Les codes sont les codes TARIC 10 chiffres ; l'importeur refuse de produire la
# base si un code manque dans le TARIC officiel (aucune invention).
FAMILLES = [
    {
        'cle': 'chaussures',
        'natures': ['chaussure de sport', 'chaussure', 'botte'],
        'discriminant': 'tige',
        'question': 'Quelle est la matière de la tige (la partie supérieure) de la chaussure ?',
        'codes': [
            ('6403190000', 'cuir', "tige cuir => 6403 (chaussures de sport, autres que ski)"),
            ('6404110000', 'textile', "dessus textile => 6404 ; l'une des familles les plus taxées du chapitre 64"),
            ('6402190000', 'plastique/caoutchouc', "semelle et dessus en caoutchouc/plastique => 6402"),
        ],
    },
    {
        'cle': 'telephonie',
        'natures': ['téléphone'],
        'discriminant': 'type_appareil',
        'question': "S'agit-il d'un smartphone (écran tactile) ou d'un téléphone classique à clavier ?",
        'codes': [
            ('8517130000', 'smartphone', "smartphone = écran tactile, système d'exploitation complet"),
            ('8517140000', 'classique', 'téléphone classique/feature phone avec clavier physique'),
        ],
    },
    {
        'cle': 'horlogerie',
        'natures': ['montre'],
        'discriminant': 'mouvement',
        'question': "Quel est le mouvement de la montre : automatique/mécanique, à quartz analogique, ou à affichage numérique ?",
        'codes': [
            ('9101210000', 'automatique', "« Automatic » sur le cadran => remontage automatique ; "
                                          'boîte en métaux précieux ou plaqués => 9101'),
            ('9102210000', 'automatique', 'remontage automatique, boîte autre que métaux précieux => 9102'),
            ('9102110000', 'quartz', 'montre fonctionnant électriquement à affichage mécanique '
                                     'seulement (quartz analogique)'),
            ('9102190000', 'numerique', "montre électrique « autres » : comprend l'affichage "
                                        'numérique (LCD) et les autres affichages'),
        ],
    },
    {
        'cle': 'meubles',
        'natures': ['commode', 'armoire', 'étagère', 'canapé', 'fauteuil', 'chaise', 'table', 'lit', 'meuble'],
        'discriminant': 'matiere_principale',
        'question': 'Quelle est la matière principale du meuble : bois, plastique ou métal ?',
        'codes': [
            ('9403609000', 'bois', 'meuble en bois => 9403.6 ; chambres à coucher => 9403 50, '
                                   'salles à manger => 9403 60 10, magasins => 9403 60 30'),
            ('9403700000', 'plastique', 'meuble dont la structure est en plastique'),
            ('9403208080', 'métal', 'meuble à structure métallique => 9403.2 (bureau => 9403.10, '
                                    'lits => 9403 20 20)'),
        ],
    },
]


# --- Utilitaires ----------------------------------------------------------------

def _parse_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    for fmt in ('%d-%m-%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _aujourdhui(d: date | None) -> bool:
    return d is None or d >= date.today()


def _nettoie_texte(text: str) -> str:
    # '|' marque un retour à la ligne dans la désignation TARIC ; 'n$o' est la
    # graphie d'export de « n° » dans les renvois (ex. « autres que celles du
    # n° 9101 »).
    t = str(text or '').replace('|', ' ').replace('$o', '°')
    return re.sub(r'\s+', ' ', t).strip()


def _profondeur(indent) -> int:
    if not indent:
        return 0
    return len(re.findall(r'-', str(indent)))


def _formate_code(code10: str) -> str:
    """6403190000 -> « 6403 19 00 » (style CN) ; 9403609000 -> « 9403 60 90 ».

    Le TARIC stocke des codes 10 chiffres complétés par des paires de zéros :
    quand les chiffres 9-10 valent 00, le code signifiant est le CN8.
    """
    morceaux = [code10[:4], code10[4:6], code10[6:8]]
    if code10[8:10] != '00':
        morceaux.append(code10[8:10])
    return ' '.join(morceaux)


def _parse_taux(duty: str) -> tuple[float | None, str]:
    """« 16.900 % » -> (0.169, brut) ; « Free » -> (0.0, brut) ; spécifique -> (None, brut)."""
    brut = str(duty or '').strip()
    m = re.search(r'([\d.]+)\s*%', brut)
    if m:
        return round(float(m.group(1)) / 100.0, 4), brut
    if brut.lower() == 'free':
        return 0.0, brut
    return None, brut


def _lire_zip() -> tuple[zipfile.ZipFile, Path]:
    if len(sys.argv) > 1:
        chemin = Path(sys.argv[1])
    else:
        candidats = sorted(RAW_DIR.glob('eu-taric-*.zip'))
        if not candidats:
            sys.exit(f"Aucun eu-taric-*.zip dans {RAW_DIR} — passez le chemin en argument.")
        chemin = candidats[-1]
    print(f"[1/7] Source : {chemin}")
    return zipfile.ZipFile(chemin), chemin


def _version(chemin: Path) -> str:
    m = re.search(r'eu-taric-(\d{4}-\d{2})', chemin.name)
    return m.group(1) if m else chemin.stem


def _reference(chemin: Path) -> str:
    """Date de référence de l'extraction (1er jour du mois publié)."""
    v = _version(chemin)
    if re.fullmatch(r'\d{4}-\d{2}', v):
        return f'{v}-01'
    return date.today().isoformat()


# --- Lecture des tables officielles --------------------------------------------

def _lire_nomenclature(z: zipfile.ZipFile) -> list[dict]:
    """Hiérarchie des codes FR valides, désignations assemblées par indentation.

    Colonne « Hier. Pos. » : niveau du code (2 chapitre, 4 position HS, 6 sous-
    position HS, 8 CN8, 10 TARIC10) ; l'arbre réel suit l'indentation.
    """
    print('[2/7] Lecture de « Nomenclature FR »...')
    wb = load_workbook(io.BytesIO(z.read('Nomenclature FR.xlsx')), read_only=True)
    ws = wb[wb.sheetnames[0]]
    aujourd_hui = date.today()
    # code suffixé -> meilleure ligne valide (description la plus récente)
    lignes: dict[str, dict] = {}
    for code, debut, fin, lang, hier, indent, desc, desc_debut in ws.iter_rows(values_only=True):
        code = str(code or '')
        if not re.fullmatch(r'\d{10} \d{2}', code) or str(lang or '').upper() != 'FR':
            continue
        d_debut = _parse_date(debut)
        d_fin = _parse_date(fin)
        if not d_debut or d_debut > aujourd_hui or not _aujourdhui(d_fin):
            continue  # code non valide aujourd'hui
        cled = code
        cand = {'code10': code[:10], 'suffixe': code[11:], 'niveau': int(hier or 0),
                'profondeur': _profondeur(indent), 'designation': _nettoie_texte(desc),
                'desc_debut': _parse_date(desc_debut)}
        courante = lignes.get(cled)
        if courante is None or (cand['desc_debut'] or date.min) >= (courante['desc_debut'] or date.min):
            lignes[cled] = cand
    wb.close()
    # Ordre du fichier = ordre d'insertion (l'arbre suit l'indentation, cf. doc
    # CIRCABC : le suffixe de ligne « est nécessaire pour construire la structure
    # dans la bonne séquence ») ; le tri code+suffixe la reproduit.
    entrees = sorted(lignes.values(), key=lambda e: (e['code10'], e['suffixe']))
    print(f"      {len(entrees)} lignes valides.")
    return entrees


def _arbre(entrees: list[dict]) -> None:
    """Enrichit chaque entrée : designation_complete + chaîne des codes parents."""
    pile: list[dict] = []
    for e in entrees:
        while pile and pile[-1]['profondeur'] >= e['profondeur']:
            pile.pop()
        parents = list(pile)
        # On assemble depuis la position HS (niveau 4) — les chapitres (niveau 2)
        # portent un intitulé générique, comme dans la désignation CN usuelle.
        fragments = [p['designation'] for p in parents if p['niveau'] >= 4] + [e['designation']]
        e['designation_complete'] = ', '.join(x for x in fragments if x)
        e['codes_parents'] = [p['code10'] for p in parents]
        # Position tarifaire (fragment HS4) : le « nom » du produit ; sert à la
        # recherche par désignation à distinguer le produit de ses mentions
        # accessoires (ex. « casques » dans la position 8518 vs « en casque »
        # dans une désignation de viande).
        e['position'] = next((p['designation'] for p in parents if p['niveau'] >= 4),
                              e['designation'])
        pile.append(e)


def _lire_declarables(z: zipfile.ZipFile) -> set[str]:
    print('[3/7] Lecture de « Declarable codes »...')
    wb = load_workbook(io.BytesIO(z.read('Declarable codes.xlsx')), read_only=True)
    ws = wb[wb.sheetnames[0]]
    declarables = set()
    for code, _debut, _flag, leaf, fin in ws.iter_rows(values_only=True):
        code = str(code or '')
        if not re.fullmatch(r'\d{10} \d{2}', code):
            continue
        if str(leaf) == '1' and _aujourdhui(_parse_date(fin)):
            declarables.add(code)
    wb.close()
    print(f"      {len(declarables)} codes déclarables.")
    return declarables


def _lire_droits(z: zipfile.ZipFile) -> dict[str, dict]:
    """Droits de pays tiers (103, ERGA OMNES) par code 10 chiffres, valides aujourd'hui."""
    print('[4/7] Lecture de « Duties Import 01-99 » (mesure 103 ERGA OMNES)...')
    wb = load_workbook(io.BytesIO(z.read('Duties Import 01-99.xlsx')), read_only=True)
    ws = wb[wb.sheetnames[0]]
    aujourd_hui = date.today()
    meilleurs: dict[str, dict] = {}
    for code, _add, _order, debut, fin, _red, origine, mtype, legal, duty, _ocode, mcode in ws.iter_rows(values_only=True):
        code = str(code or '')
        if not re.fullmatch(r'\d{10}', code):
            continue
        if str(mcode) != THIRD_COUNTRY_DUTY_TYPE or str(origine) != ERGA_OMNES:
            continue
        d_debut = _parse_date(debut)
        if not d_debut or d_debut > aujourd_hui or not _aujourdhui(_parse_date(fin)):
            continue
        taux, brut = _parse_taux(duty)
        cand = {'taux': taux, 'brut': brut, 'legal': str(legal or '').strip(), 'depuis': d_debut}
        cour = meilleurs.get(code)
        if cour is None or cand['depuis'] >= cour['depuis']:
            meilleurs[code] = cand
    wb.close()
    print(f"      {len(meilleurs)} codes avec droit de pays tiers.")
    return meilleurs


def _droit_cascade(code10: str, parents: list[str], droits: dict[str, dict]) -> dict | None:
    """Droit applicable : sur le code lui-même sinon le premier parent en remontant."""
    for c in [code10] + list(parents)[::-1]:
        if c in droits:
            return droits[c]
    return None


# --- Écriture des sorties -------------------------------------------------------

def _ecrire_nomenclature(entrees, declarables, droits, version, reference):
    print(f"[7/8] Écriture de {OUT_NOMENCLATURE.name} et {OUT_BASE.name}...")
    codes = []
    for e in entrees:
        # Codes déclarables en douane (suffixe 80 + IS_LEAF=1) : CN8 et TARIC10.
        # Le « niveau » hiérarchique TARIC ne suit pas la longueur usuelle : un
        # code CN8 terminé par 00 (ex. 6402 19 00 00) est de niveau 6 (doc
        # CIRCABC §6.2 : niveau = dernière paire de chiffres différente de 00).
        if e['suffixe'] != '80' or f"{e['code10']} 80" not in declarables:
            continue
        droit = _droit_cascade(e['code10'], e['codes_parents'], droits)
        codes.append({
            'code': _formate_code(e['code10']),
            'code10': e['code10'],
            'niveau': e['niveau'],
            'designation': e['designation_complete'],
            'position': e['position'],
            'declarable': f"{e['code10']} 80" in declarables,
            'taux_pays_tiers': droit['taux'] if droit else None,
            'droit_pays_tiers_brut': droit['brut'] if droit else None,
            'base_legale': droit['legal'] if droit else None,
        })
    doc = {
        'version': f'TARIC {version}',
        'source': 'Extraction mensuelle officielle de la base TARIC (Commission européenne, '
                  'groupe CIRCABC « TARIC & Quota Data and Information »)',
        'date_reference': reference,
        'langue': 'FR',
        'note': 'Droit de pays tiers = mesure 103 « Third country duty », origine ERGA OMNES ; '
                'taux indicatif, le calcul fiscal dépend de l\'origine (accords, préférences, antidumping).',
        'codes': codes,
    }
    with open(OUT_NOMENCLATURE, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"      {len(codes)} codes CN8/TARIC10 -> {OUT_NOMENCLATURE.name} "
          f"({OUT_NOMENCLATURE.stat().st_size / 1e6:.1f} Mo)")
    return {c['code10']: c for c in codes}


def _ecrire_base(nomenclature: dict, version, reference):
    familles = {}
    erreurs = []
    for fam in FAMILLES:
        codes = []
        for code10, valeur, note in fam['codes']:
            e = nomenclature.get(code10)
            if e is None:
                erreurs.append(f"{fam['cle']}: code {code10} absent du TARIC !")
                continue
            entry = {
                'code': e['code'],
                'code10': e['code10'],
                'designation': e['designation'],
                fam['discriminant']: valeur,
                'taux_indicatif_droits': f"{e['taux_pays_tiers']:.3f}"
                if e['taux_pays_tiers'] is not None else None,
                'base_legale': e['base_legale'],
                'notes': note,
            }
            codes.append(entry)
        familles[fam['cle']] = {
            'natures': fam['natures'],
            'discriminant': fam['discriminant'],
            f"question_{fam['discriminant']}": fam['question'],
            'codes': codes,
        }
    if erreurs:
        sys.exit('Codes hors TARIC officiel (import refusé) :\n' + '\n'.join(erreurs))
    base = {
        'version': f'TARIC {version}',
        'source': 'Base TARIC officielle (Commission européenne, extraction CIRCABC '
                  '« TARIC & Quota Data and Information ») — désignations FR et droits de '
                  'pays tiers (mesure 103, ERGA OMNES)',
        'date_validite': reference,
        'familles': familles,
    }
    OUT_BASE.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"      {len(familles)} familles -> {OUT_BASE.name}")


# --- Base fiscale (§16) ----------------------------------------------------------

def _ecrire_fiscal(z: zipfile.ZipFile, version: str, reference: str) -> None:
    """fiscal.sqlite : mesures fiscales par code + appartenance aux groupes d'origine.

    Tables :
    * mesures(code10, geo, geo_nom, type, type_nom, taux, brut, legal, add_code,
      order_no, debut, fin) — lignes valides aujourd'hui, types 103/142/552/117.
    * aires_geo(geo, pays_iso, nom) — membres des groupes d'origine (ex. Mercosur).
    * groupes(geo, nom) — nom FR des groupes d'origine.
    * meta(clé, valeur) — version TARIC et date de référence.
    """
    print('[5/8] Construction de la base fiscale...')
    aujourd_hui = date.today()
    OUT_FISCAL.unlink(missing_ok=True)
    con = sqlite3.connect(OUT_FISCAL)
    con.executescript("""
        CREATE TABLE mesures (code10 TEXT, geo TEXT, geo_nom TEXT, type TEXT,
            type_nom TEXT, taux REAL, brut TEXT, legal TEXT, add_code TEXT,
            order_no TEXT, debut TEXT, fin TEXT);
        CREATE INDEX idx_mesures_code ON mesures(code10);
        CREATE TABLE aires_geo (geo TEXT, pays_iso TEXT, nom TEXT);
        CREATE INDEX idx_aires_pays ON aires_geo(pays_iso);
        CREATE TABLE groupes (geo TEXT, nom TEXT);
        CREATE TABLE meta (cle TEXT, valeur TEXT);
    """)
    # Mesures fiscales valides aujourd'hui (Duties Import) — la cascade
    # code -> parents est appliquée au calcul par le moteur fiscal.
    nb = 0
    wb = load_workbook(io.BytesIO(z.read('Duties Import 01-99.xlsx')), read_only=True)
    ws = wb[wb.sheetnames[0]]
    for code, add, order, debut, fin, _red, origine, mtype, legal, duty, ocode, mcode in ws.iter_rows(values_only=True):
        code = str(code or '')
        if not re.fullmatch(r'\d{10}', code) or str(mcode) not in TYPES_FISCAL:
            continue
        d_debut = _parse_date(debut)
        if not d_debut or d_debut > aujourd_hui or not _aujourdhui(_parse_date(fin)):
            continue
        taux, brut = _parse_taux(duty)
        con.execute('INSERT INTO mesures VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (code, str(ocode or ''), str(origine or ''), str(mcode), str(mtype or ''),
                     taux, brut, str(legal or '').strip(), str(add or ''), str(order or ''),
                     str(debut or ''), str(fin or '')))
        nb += 1
    wb.close()
    # Appartenance aux groupes d'origine (membres actuels).
    wb = load_workbook(io.BytesIO(z.read('Geographical areas composition.xlsx')), read_only=True)
    ws = wb[wb.sheetnames[0]]
    for geo, _debut, _lang, _abbr, _descr, pays, _abbr2, nom, m_debut, m_fin, fin in ws.iter_rows(values_only=True):
        geo, pays = str(geo or ''), str(pays or '')
        if not geo or not pays:
            continue
        if not _aujourdhui(_parse_date(fin)) or not _aujourdhui(_parse_date(m_fin)):
            continue
        if _parse_date(m_debut) and _parse_date(m_debut) > aujourd_hui:
            continue
        con.execute('INSERT INTO aires_geo VALUES (?,?,?)', (geo, pays, str(nom or '')))
    wb.close()
    # Noms FR des groupes d'origine.
    wb = load_workbook(io.BytesIO(z.read('Geographical areas description.xlsx')), read_only=True)
    ws = wb[wb.sheetnames[0]]
    vus = set()
    for geo, lang, _abbr, nom, _debut, _ddebut, fin in ws.iter_rows(values_only=True):
        geo = str(geo or '')
        if not geo or str(lang or '').upper() != 'FR' or geo in vus:
            continue
        if not _aujourdhui(_parse_date(fin)):
            continue
        con.execute('INSERT INTO groupes VALUES (?,?)', (geo, _nettoie_texte(nom)))
        vus.add(geo)
    wb.close()
    con.executemany('INSERT INTO meta VALUES (?,?)',
                    [('version', f'TARIC {version}'), ('date_reference', reference),
                     ('source', 'Commission européenne, extraction CIRCABC « TARIC & Quota Data »')])
    con.commit()
    con.close()
    print(f'      {nb} mesures fiscales -> {OUT_FISCAL.name} ({OUT_FISCAL.stat().st_size / 1e6:.1f} Mo)')


# --- Notes explicatives de la CN (vocabulaire officiel d'interprétation) --------

def _ecrire_notes() -> None:
    """notes_cn_fr.json : notes explicatives de la nomenclature combinée (FR).

    Source : texte consolidé FR des NENC (CELEX 52019XC0329(02), Office des
    publications de l'UE) déposé dans data/tariff/raw/cnen-fr*.html. Les notes
    explicatives utilisent le vocabulaire courant absent de la nomenclature
    (ex. « chaudières électriques qui produisent uniquement de l'eau chaude »
    — les bouilloires — pour 8516 10 11/80) : elles font le pont entre le
    langage courant et les désignations officielles.

    Le fichier est un tableau : 1re cellule = code(s) (parfois une plage « à »),
    2e cellule = texte officiel.
    """
    candidats_html = sorted(RAW_DIR.glob('cnen-fr*.html'))
    if not candidats_html:
        print('[6/8] Notes explicatives : aucun cnen-fr*.html dans data/tariff/raw/ — ignorées.')
        OUT_NOTES.unlink(missing_ok=True)
        return
    chemin = candidats_html[-1]
    print(f'[6/8] Notes explicatives : {chemin.name}...')
    t = chemin.read_bytes().decode('utf-8', errors='replace')
    code_re = re.compile(r'\b\d{4}(?: \d{2}){0,2}\b')

    def _texte(td: str) -> str:
        x = re.sub(r'<[^>]+>', ' ', td)
        return re.sub(r'\s+', ' ', html.unescape(x)).strip()

    segments = []
    for m in re.finditer(r'<tr>(.*?)</tr>', t, re.S):
        row = m.group(1)
        tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        if len(tds) < 2:
            continue
        codes = _texte(tds[0])
        corps = _texte(tds[1])
        # En-tête = codes courts (plages « à », listes « et ») + texte ; on
        # écarte les cellules de texte long qui ne sont pas des codes.
        if not corps or len(codes) > 60 or not code_re.search(codes):
            continue
        segments.append({'codes': codes, 'texte': corps})
    # Métadonnées de version depuis le titre du document.
    m = re.search(r'<title>(.*?)</title>', t, re.S)
    titre = _nettoie_texte(m.group(1)) if m else ''
    doc = {
        'source': 'Notes explicatives de la nomenclature combinée (NENC), texte consolidé '
                  'FR — Office des publications de l\'UE (publications.europa.eu)',
        'reference': titre,
        'note': 'Les NENC sont des textes officiels d\'interprétation ; elles ne modifient '
                'pas la nomenclature, elles documentent son application.',
        'segments': segments,
    }
    # Libération avant sérialisation (machine cible : peu de RAM).
    del t
    gc.collect()
    with open(OUT_NOTES, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"      {len(segments)} segments -> {OUT_NOTES.name} ({OUT_NOTES.stat().st_size / 1e6:.1f} Mo)")


# --- Renseignements tarifaires contraignants (RTC/EBTI) ------------------------

def _ecrire_ebti() -> None:
    """ebti.sqlite : décisions RTC valides (EBTI, langue FR) — niveau 3 de preuve.

    Source : DDS2-EBTI_Full.zip (base publique des renseignements tarifaires
    contraignants, miroir taric-opendata) déposé dans data/tariff/raw/.
    Un RTC décide du classement d'un bien précis ; RITA ne l'utilise que pour
    CONFORTER un candidat dont le code est couvert par un RTC à la description
    similaire — jamais pour classer à la place de l'utilisateur (§29).

    Code de nomenclature : 10 chiffres + jokers '*' (positions non spécifiées)
    ; `mask10` garde les 10 premières positions, `prefix` les chiffres certains.
    Mémoire : lecture CSV en flux (machine cible : 6 Go de RAM).
    """
    candidats = sorted(RAW_DIR.glob('ebti-full*.zip'))
    if not candidats:
        print('[8/8] EBTI : aucun ebti-full*.zip dans data/tariff/raw/ — ignoré.')
        OUT_EBTI.unlink(missing_ok=True)
        return
    print(f'[8/8] EBTI : {candidats[-1].name}...')
    OUT_EBTI.unlink(missing_ok=True)
    con = sqlite3.connect(OUT_EBTI)
    con.executescript("""
        CREATE TABLE rti (ref TEXT, pays TEXT, debut TEXT, fin TEXT,
            mask10 TEXT, prefix TEXT, description TEXT);
        CREATE INDEX idx_rti_prefix ON rti(prefix);
        CREATE TABLE meta (cle TEXT, valeur TEXT);
    """)
    aujourdhui = date.today()
    total = garde = 0
    lot: list[tuple] = []
    z = zipfile.ZipFile(candidats[-1])
    for nom in sorted(n for n in z.namelist() if re.fullmatch(r'EBTI_\d{4}\.csv', n)):
        with z.open(nom) as f:
            lecteur = csv.reader(io.TextIOWrapper(f, encoding='utf-8-sig', newline=''))
            entete = next(lecteur, None)
            if not entete:
                continue
            # L'en-tête contient une coquille (« DATE_OF _ISSUE ») : indexer par nom.
            idx = {c.strip().upper(): i for i, c in enumerate(entete)}
            for row in lecteur:
                if len(row) != len(entete):
                    continue
                total += 1
                if row[idx['STATUS']] != 'VALID' or row[idx['LANGUAGE']].lower() != 'fr':
                    continue
                fin = _parse_date(row[idx['END_DATE_OF_VALIDITY']]) or None
                if fin and fin < aujourdhui:
                    continue
                brut = row[idx['NOMENCLATURE_CODE']] or ''
                digits = re.sub(r'[^0-9]', '', brut)
                if len(digits) < 8:
                    continue  # au moins une position CN8 doit être spécifiée
                mask10 = (brut + '*' * 10)[:10]
                etoile = mask10.find('*')
                prefix = mask10 if etoile == -1 else mask10[:etoile]
                if not re.fullmatch(r'\d+', prefix):
                    continue
                description = _nettoie_texte(row[idx['DESCRIPTION_OF_GOODS']])[:2000]
                lot.append((row[idx['BTI_REFERENCE']], row[idx['ISSUING_COUNTRY']],
                            row[idx['START_DATE_OF_VALIDITY']] or '',
                            row[idx['END_DATE_OF_VALIDITY']] or '',
                            mask10, prefix, description))
                garde += 1
                if len(lot) >= 2000:
                    con.executemany('INSERT INTO rti VALUES (?,?,?,?,?,?,?)', lot)
                    lot.clear()
        con.commit()
        print(f'      {nom} : {garde} RTC conservées (cumul)')
    z.close()
    if lot:
        con.executemany('INSERT INTO rti VALUES (?,?,?,?,?,?,?)', lot)
    con.executemany('INSERT INTO meta VALUES (?,?)',
                    [('source', 'Base publique EBTI (DDS2-EBTI_Full) — RTC valides, langue FR'),
                     ('date_import', date.today().isoformat())])
    con.commit()
    con.close()
    print(f'      {garde}/{total} lignes -> {OUT_EBTI.name} ({OUT_EBTI.stat().st_size / 1e6:.1f} Mo)')


def main() -> None:
    z, chemin = _lire_zip()
    version, reference = _version(chemin), _reference(chemin)
    entrees = _lire_nomenclature(z)
    _arbre(entrees)
    declarables = _lire_declarables(z)
    droits = _lire_droits(z)
    # Écriture immédiate puis libération : la machine cible a peu de RAM et
    # les étapes suivantes (fiscal, notes) n'ont pas besoin de la nomenclature.
    nomenclature = _ecrire_nomenclature(entrees, declarables, droits, version, reference)
    _ecrire_base(nomenclature, version, reference)
    del entrees, declarables, droits, nomenclature
    gc.collect()
    _ecrire_fiscal(z, version, reference)
    z.close()
    _ecrire_notes()
    _ecrire_ebti()
    print('Terminé.')


if __name__ == '__main__':
    main()
