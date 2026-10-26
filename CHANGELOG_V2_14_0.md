# V2.14.0 — moteurs interchangeables, budget de temps, suivi des coûts

Vérifié sans réseau ni modèles : compilation de tous les fichiers + 71 vérifications de
logique pure (fusion, décision, extraction, enrich, SSRF, filtres OCR, sélecteurs).
**Non vérifié ici** (nécessite votre machine) : `python -m pytest tests`, exécution réelle
de Florence/PaddleOCR, appels réels aux API Mistral et SearXNG.

## Nouveautés

### 1. Moteurs interchangeables (§4 du cahier des charges)
Trois moteurs peuvent désormais basculer vers Mistral **sans toucher au reste de la
chaîne** — validation concrète de l'exigence d'interchangeabilité :

| Moteur | Sélecteur | Local (défaut) | API Mistral |
|---|---|---|---|
| Vision | `VISION_ENGINE` | Florence-2-base | `server/vision/mistral_vision.py` (modèle vision, légende FR) |
| OCR | `OCR_ENGINE` | service PaddleOCR | `server/ocr/mistral_ocr.py` (markdown -> lignes) |
| LLM texte | `TEXT_LLM_PROVIDER` | Ollama (`qwen3:0.6b`) | chat completions avec `response_format` JSON |

Nouveaux fichiers : `server/vision/select.py`, `server/ocr/select.py`,
`server/vision/mistral_vision.py`, `server/ocr/mistral_ocr.py`.
`routes.py` ne connaît que les contrats (`analyze`, `ocr_detailed`), jamais les moteurs.

Différence documentée : Mistral OCR ne fournit pas de score par ligne ; `scores` est
vide, `seuil_score` vaut None et toutes les lignes sont retournées. Le filtrage par
score reste une capacité du service local Paddle uniquement.

### 2. Budget de temps de la recherche externe (§22)
`external.py` : les images web (jusqu'à 24, timeout 12 s chacune) étaient évaluées
**séquentiellement** — pire cas ~5 min, incompatible avec « analyse normale < 60 s ».
Désormais : téléchargements/évaluations **concurrents** (`EXTERNAL_IMAGE_WORKERS=4`)
sous **deadline globale** (`EXTERNAL_DEADLINE_S=20`), images au-delà du budget
simplement sautées et visibles dans `meta.nb_images_non_evaluees`.

### 3. Suivi des coûts par analyse (§22 + cahier des charges général)
`meta.suivi_couts` compte les appels de chaque analyse : vision (1), OCR (1),
requêtes web, images web évaluées, appels LLM texte. Le montant (`cout_estime`)
reste à remplir quand les tarifs seront validés.

### 4. Correctifs de performance
* `visual_web.py` : `score_image()` faisait la comparaison complète **deux fois par
  image** (`compare()` puis `compare_details()`, chacun recalculant
  `visual_feature_scores()`). Une seule passe désormais (`_analyze`) ; les fonctions
  mortes `_ahash/_phash/_cos/_edges/_hist` (duplicatas inutilisés de `engine.py`)
  sont supprimées ; `compare`/`compare_details` restent disponibles en compatibilité.
* `visual_web.py` : purge du cache **périodique** (tous les `WEB_IMAGE_CACHE_PURGE_EVERY`
  téléchargements) — l'ancien drapeau « une seule purge par vie du process » laissait
  le cache grossir sans limite sur un serveur longue durée.
* `llm_extractor.py` : `num_predict` 180 → 768 et `MAX_ITEMS` 16 → 8. 16 extractions
  JSON ne tenaient jamais dans 180 tokens : la réponse était tronquée et l'extraction
  tombait « indisponible » **silencieusement**.

### 5. Hygiène du dépôt
* `.gitignore` : `__pycache__/`, `*.pyc`, `.env`, `*.lnk`, `data/web_image_cache/`,
  `.pytest_cache/`. Les fichiers déjà commités sont supprimés dans ce commit.
* `main.py` : le préchargement de Florence est ignoré quand `VISION_ENGINE=mistral`.
* Statut « probable » à double sens (fusion vs evidence) : documenté dans
  `merge.py` (le champ ne porte jamais les deux à la fois, la fusion passe en dernier).
  Renommage écarté pour ne pas casser le contrat existant.

## Points à connaître
* Le prompt vision Mistral impose une phrase en français « sans rien inventer » ;
  l'enrichissement déterministe (`enrich.py`) reste inchangé et préserve la hiérarchie
  des preuves (la légende reste une preuve faible, plafonnée).
* Avant d'envoyer des photos clients aux API Mistral : vérifier les conditions de
  La Plateforme (rétention, réutilisation, localisation) — §9.1 du cahier général.
* `qwen3:0.6b` reste le modèle texte local par défaut ; la bascule
  `TEXT_LLM_PROVIDER=mistral` + `MISTRAL_TEXT_MODEL` améliore l'extraction sans
  toucher aux garde-fous (`_exact_in_source` reste la barrière décisive).

## Non traité
* Lien avec le moteur de classification tarifaire (toujours non développé).
* `GET /api/v1/history` (§20) et persistance : toujours absents.
* Garde SSRF : le rebinding DNS reste possible ; authentification, limitation de
  débit et RGPD à prévoir avant toute exposition.
* Calibrage : avec un moteur vision plus riche (Mistral), les seuils de confiance
  (0.15/0.25) et les bonus devront être recalibrés sur le banc d'essai (§26).
