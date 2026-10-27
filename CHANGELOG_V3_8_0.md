# V3.8.0 — banc d'essai (§26) et premier calibrage mesuré

Le calibrage des seuils exigeait des mesures réelles : ce bâtiment livre le
**banc d'essai** (photo + résultats attendus -> analyse réelle -> verdicts) et
le premier calibrage qu'il a permis — deux défauts mesurés sur des légendes
Mistral réelles, corrigés, avec tests de régression.

Vérifié : `python -m pytest tests` 83/83 (+3) ; banc d'essai exécuté en réel
(API Mistral vision + OCR) : 2 exécutions d'un même cas -> 2 légendes
distinctes, **1 seul code top-1 après correctif** (avant : 2 codes différents).

## Nouveautés

### 1. Banc d'essai (`tools/banc_essai.py`, `data/banc_essai/`)
* Cas documentés (photo + attendus : nature, marque, codes acceptables,
  origine pour le moteur fiscal) ; `codes_acceptables` admet les classements
  légitimes (tige textile OU cuir selon la paire photographiée).
* Exécute la chaîne complète avec les moteurs configurés (.env) : vision ->
  OCR -> enrichissement -> fusion -> classement -> fiscal ; rapport JSON
  (rapports gitignorés, régénérables).
* **Répétitions** par cas (`repetitions`) : mesure la variance du moteur
  vision (légendes distinctes, codes top-1 distincts) — l'API reste
  non déterministe même à température 0 ; une graine (`MISTRAL_VISION_SEED`)
  est envoyée au mieux.
* Ajouter un cas = déposer une photo dans `images/` + une entrée dans
  `cases.json`. Premier cas : la fixture locale, rebaptisée honnêtement
  nike-air-max-tavas (la vision a lu le vrai nom — l'étiquette « P-6000 » du
  catalogue était erronée).

### 2. Calibrage mesuré : discriminateur de tige (`server/tariff/engine.py`)
Deux défauts découverts par les légendes réelles, corrigés :
* **Pluriels ratés** : « matières synthétiques et textile**s** » ne matchait
  pas `\btextile\b` (frontière de mot) — la tige textile la plus naturelle
  en français était ignorée. Tous les motifs tolèrent désormais le pluriel
  (`\bcuirs?\b`, `\bmétaux\b`...).
* **Éléments secondaires** : « **semelle** extérieure en caoutchouc »
  faisait classer la TIGE en caoutchouc (6402) ; « **renforts** en cuir » en
  cuir (6403) pour une tige mesh. Une matière n'est plus retenue si un
  élément secondaire (semelle, renforts, doublure, languette, œillets...) la
  précède dans les 45 caractères — « tige en cuir avec lacets » reste valable.
* Avant correctif : 2 exécutions -> 6402 19 00 puis 6403 19 00 ; après :
  2 exécutions -> 6404 11 00 (le code attendu d'une tige mesh), les deux
  légendes convergent. La variance de l'API ne se propage plus au code.

### 3. Vision : graine de reproductibilité
`MISTRAL_VISION_SEED` (optionnelle) envoyée comme `random_seed` à l'API —
au mieux de la reproductibilité ; le banc mesure la variance résiduelle
explicitement au lieu de la supposer nulle.

## Points à connaître
* Un seul cas au banc : ce calibrage est **partiel** — chaque photo ajoutée
  affine (chaussures cuir, montres, meubles, téléphones...). L'infrastructure
  et la méthode sont en place.
* La détection du modèle reste hors du périmètre du banc (la confirmation
  d'un modèle exige la recherche web, que le banc n'appelle pas pour rester
  déterministe et économe).
* Les seuils de fusion OCR (0.96/0.82/0.65) n'ont pas encore de cas les
  exerçant — à mesurer quand le banc comptera des photos avec texte produit
  lisible.
