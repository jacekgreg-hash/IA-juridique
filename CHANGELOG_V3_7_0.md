# V3.7.0 — renseignements tarifaires contraignants : niveau 3 de preuve

Un RTC (BTI) est une décision d'administration douanière, contraignante
dans toute l'UE, sur le classement d'un bien précis. C'est la source
d'autorité idéale pour le principe du cahier des charges : « l'IA propose,
les données officielles vérifient ». Cette version l'intègre comme
**confort** des candidats — jamais comme classement automatique (§29) : la
photo d'un produit ne prouve pas qu'il est identique au bien décrit dans la
décision.

Vérifié : `python -m pytest tests` 80/80 (+6) ; en réel sur la base complète —
baskets textile 6404 11 00 confortées par 15 RTC, bibliothèque MDF 9403 60 90
par 22 RTC (dont une décrivant quasi mot pour mot le produit test), montres et
étagères métalliques couvertes aussi.

## Nouveautés

### 1. Import EBTI (`data/tariff/ebti.sqlite`, ignoré par git)
* Source : base publique DDS2-EBTI_Full (miroir taric-opendata, 397 Mo de
  CSV annuels 2004-2026) déposée dans `data/tariff/raw/`.
* 19 061 RTC conservées : statut VALIDE, langue FR, validité non échue
  (les RTC d'avant 2023 sont expirés — durée de vie maximale 3 ans — et
  sont filtrés par la date de fin de validité).
* Code de nomenclature avec jokers `*` : `mask10` garde les 10 premières
  positions, `prefix` (chiffres certains) est indexé pour la recherche.
* Mémoire : lecture CSV en flux, insertion par lots — aucune structure
  complète en RAM (machine cible 6 Go, leçon de V3.5).

### 2. `server/tariff/rti.py` — confort, pas classement
* `conforter(candidats, textes)` : pour chaque candidat, les RTC dont le
  code couvre le candidat (jokers respectés) ET dont la description
  recoupe l'analyse (≥ 2 mots utiles communs, hors mots-outils) sont
  attachés : `candidat['rtc'] = {nb, exemples:[{ref, pays, valide_jusqua, extrait}]}`.
* Confiance +0,04 plafonnée à 0,75 ; raison « conforté par N renseignement(s)
  tarifaire(s) contraignant(s) » avec la référence citée.
* Un RTC sur le même code mais décrivant un bien sans rapport n'est PAS
  compté (le recoupement l'écarte) — la preuve reste sur le bien, pas le code.
* Silencieux sans base (import EBTI optionnel) ; ne lève jamais.

### 3. Moteur
* Les deux chemins (familles codées, recherche désignations/notes) appellent
  le confort RTC ; la nature (objet) fait partie du vocabulaire de
  recoupement — sans elle, les descriptions de RTC ne se recoupent pas.
* Les candidats des familles portent désormais `code10` (déjà présent pour
  les candidats de recherche).

## Points à connaître
* La base est ignorée par git (10,9 Mo régénérables) : un clone frais
  fonctionne sans RTC, le confort est simplement inactif.
* Recherche plein-texte dans les descriptions de RTC (pour proposer un code
  quand AUCUN candidat n'existe) : non traité — le confort du code déjà
  proposé est la valeur sûre ; la recherche texte sera évaluée avec le
  recul d'usage.
* Reste avant exposition publique : authentification, limitation de débit,
  journalisation, RGPD.
