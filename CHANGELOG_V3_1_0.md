# V3.1.0 — base tarifaire officielle TARIC (remplace le prototype)

Le moteur tarifaire V3.0.0 tournait sur une base d'essai à 4 familles avec des
taux approximatifs. Cette version importe la **base TARIC officielle** (Commission
européenne, extraction mensuelle CIRCABC « TARIC & Quota Data and Information »).

Vérifié : `python -m pytest tests` 41/41 ; classement testé sur 9 scénarios
(chaussures cuir/textile/plastique, montre automatique/quartz/numérique,
téléphone à clavier, commode en bois, nature inconnue).

## Nouveautés

### 1. Import officiel TARIC (`tools/import_taric.py`)
* Source : extraction mensuelle officielle (miroir public
  `github.com/rousseauxy/taric-opendata`, release `eu-2026-10`) téléchargée dans
  `data/tariff/raw/` (ignoré par git, 79 Mo, régénérable).
* Format documenté par le PDF officiel CIRCABC « Explanation for the Taric
  database extractions » : le code est « 10 chiffres + suffixe de ligne »
  (suffixe 80 = ligne de biens réelle, autres suffixes = lignes intermédiaires) ;
  la hiérarchie suit l'**indentation**, pas les préfixes (les branches « autres »
  changent de chiffres par rapport à leur parent).
* `data/tariff/nomenclature_fr.json` : **16 725 codes déclarables** (CN8/TARIC10)
  avec désignations FR assemblées depuis la hiérarchie et droits de pays tiers
  (mesure 103 « Third country duty », origine ERGA OMNES) + base légale.
* `data/tariff/tariff_base.json` régénéré : mêmes familles et discriminants
  (logique RITA §9/§11), mais codes, désignations, taux et bases légales issus
  du TARIC ; l'importeur **refuse de produire la base** si un code famille
  manque du TARIC officiel (aucune invention).

### 2. Erreurs du prototype corrigées par les données officielles
* **6403 40 00** était désigné « chaussures de sport tige cuir » à tort : c'est
  « chaussures avec coquille de protection métallique » (sécurité). Les
  chaussures de sport tige cuir = **6403 19 00** (taux réel 8 %, pas 0 %).
* **9102 21 00** était « affichage numérique » à tort : c'est le remontage
  automatique non électrique. Quartz analogique = **9102 11 00** (« à affichage
  mécanique seulement »), numérique = **9102 19 00** (« autres » électriques).
* **9403 60 00** et **9403 20 00** ont été subdivisés dans la CN : remplacés par
  9403 60 90 (autres meubles en bois) et 9403 20 80 80 (autres meubles en métal).
* Taux réels importés : chaussures plastique/caoutchouc 16,9 % (le prototype
  affichait 0 %), textile 16,9 %, montres 4,5 %, meubles 0 %.

### 3. Moteur : égalité => question (§9, §11, §29)
`engine.py` : quand plusieurs codes arrivent à égalité parfaite (ex. montre à
remontage automatique : 9101 21 00 boîte précieuse vs 9102 21 00 autre), le
moteur ne tranche plus — statut `candidats_a_departager` + question sur le
critère qui départage (matière de la boîte ici), au lieu de l'ancien
`candidat_dominant` trompeur.

## Points à connaître
* Le droit affiché reste le droit de pays tiers indicatif (ERGA OMNES, sans
  préférence) — le moteur fiscal (§16) dépend de l'origine et reste à développer.
* Actualisation : re-télécharger l'extraction du mois puis
  `python tools/import_taric.py` (les fichiers générés sont versionnés par la
  date de référence TARIC).
* `nomenclature_fr.json` (~9 Mo) ouvre la voie à la recherche par désignation
  au-delà des 4 familles codées — non encore branchée au moteur.

## Non traité
* Moteur fiscal (§16) : taux préférentiels, antidumping, suspensions.
* Garde SSRF (rebinding DNS), authentification, rate limiting avant exposition.
* Calibrage des seuils (§26) sur le banc d'essai.
