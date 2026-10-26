# V2.13.7 — corrections de la revue de V2.13.6

Vérifié : compilation de tous les fichiers, 24 tests unitaires (sans réseau, sans Florence ni PaddleOCR).
**Non vérifié** (nécessite votre machine) : exécution réelle de Florence, de PaddleOCR et de SearXNG.

## Corrigé
| # | Sujet | Fichiers |
|---|-------|----------|
| 1 | Recherche externe dépendante de la marque : marque aussi cherchée dans l'OCR ; requêtes sans marque (preuves faibles) | `vision/enrich.py`, `utils/brands.py`, `candidates/web_search.py` |
| 2 | `caracteristiques`/`couleurs` vides : dérivées de la légende (lexique de départ) → bonus de caractéristiques, 3e requête et indice structurel de nouveau actifs | `vision/enrich.py` |
| 3 | Légende avec tokens spéciaux (`</s><s>…`) et phrase entière comme requête : décodage sans tokens spéciaux, `objet` = catégorie FR ou courte expression | `vision/florence.py`, `vision/enrich.py` |
| 4 | Marque par sous-chaîne (« pineapple » → Apple, « Evans » → Vans, « canonical » → Canon) : limites de mot | `utils/brands.py` |
| 5 | Fusion locale/web : un candidat web sans marque n'était pas regroupé avec le candidat catalogue (doublon, pas de convergence) | `candidates/merge.py` (extrait de `routes.py`) |
| 6 | `async def` bloquante → `def` ; Florence chargé sous verrou et préchargé au démarrage (`RITA_PRELOAD`) ; une génération à la fois | `api/routes.py`, `main.py`, `vision/florence.py` |
| 7 | Service OCR : plus de `cgi` (image brute en `application/octet-stream`), verrou sur l'instance unique, repli ×2 plafonné (3200 px), taille max ; scores OCR utilisés (seuil `PADDLE_OCR_MIN_SCORE`, lignes écartées conservées dans `ocr_details.rejetes`) | `tools/paddle_ocr_service.py`, `tools/ocr_utils.py`, `ocr/paddle_client.py` |
| 8 | Upload : taille max (`MAX_UPLOAD_MB`), contrôle du contenu (400/413/415) ; téléchargement d'images web : garde anti-SSRF + redirections revalidées ; purge du cache | `api/routes.py`, `candidates/visual_web.py` |
| 9 | Hygiène : version unique 2.13.7, chemins utilisateur retirés des `.bat`/README (`%LOCALAPPDATA%`, surcharge `PY312`), `.env.example` complété, `identification_confiance` et `produit.texte_visible` renseignés, faux modèles « Sportswear/Running… » | divers |

## Points à connaître
* `identification_confiance` : 0.15 (objet seul) ou 0.25 (objet + marque trouvée dans la légende). **Valeurs de départ à calibrer**, volontairement sous le plafond 0.30 des preuves « vision ».
* Lexiques de `enrich.py` (couleurs, matières, catégories) et liste de marques : graines à étendre avec le catalogue et le banc de test.
* La réponse JSON gagne `perception` et `candidats[].sources` ; `ocr_details` gagne `rejetes` et `seuil_score`.
* Compatibilité : `routes._merge_candidate_sources` et `routes._candidate_decision` existent toujours (alias).
* Le client OCR et le service changent de protocole ensemble : redémarrer les deux (`run_all.bat`).

## Non traité
* Lien avec le moteur de classification tarifaire (toujours non développé).
* Garde SSRF : le rebinding DNS reste possible ; authentification, limitation de débit et RGPD à prévoir avant toute exposition.
* `apply_candidate_decision_to_produit` réutilise le statut « probable » avec un sens différent de celui de `evidence/engine.py`.
* Vérifier dans les logs PaddleOCR quel modèle de reconnaissance est chargé pour `lang="fr"`.
