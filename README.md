# RITA Vision V2.14.0 — moteurs interchangeables (Florence/PaddleOCR ou Mistral en API)

## Pipeline

PHOTO → vision (légende : Florence-2 local **ou** Mistral en API) ‖ OCR (PaddleOCR local **ou** Mistral OCR)
→ enrichissement déterministe (marque, catégorie, couleurs, caractéristiques) → candidats catalogue
→ SearXNG → extraction déterministe → LLM texte uniquement si nécessaire → fusion Python
→ décision conservatrice.

La vision décrit, l'OCR lit : ce sont des **preuves**. Ni l'un ni l'autre ne confirme seul
un modèle ou une référence. Rien dans cette chaîne n'est encore un classement tarifaire.

## Moteurs interchangeables (V2.14 — §4 du cahier des charges)

Chaque moteur bascule par variable d'environnement, sans toucher au code :

| Moteur | Variable | Local (défaut, gratuit) | API Mistral |
|---|---|---|---|
| Vision | `VISION_ENGINE=florence\|mistral` | Florence-2-base (CPU) | modèle vision (légende FR) |
| OCR | `OCR_ENGINE=paddle\|mistral` | service PaddleOCR (port 8010) | Mistral OCR |
| LLM texte | `TEXT_LLM_PROVIDER=ollama\|mistral` | Ollama `qwen3:0.6b` | Mistral (JSON forcé) |

Les appels API nécessitent `MISTRAL_API_KEY=` dans `.env` (jamais commité).
Vérifier les conditions de La Plateforme (rétention, réutilisation, localisation)
avant d'y envoyer des photos de clients (§9.1 du cahier des charges général).

## Démarrage (Windows)

1. Dépendances de l'API (Python 3.14 ou autre) :
  `python -m pip install -r requirements.txt -r requirements_florence.txt`
2. Dépendances OCR, une fois, avec Python 3.12 :
  `%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe -m pip install -r requirements_paddle.txt`
3. Copier `.env.example` vers `.env` et l'adapter.
4. Lancer `run_all.bat` (si Python 3.12 est ailleurs : `set PY312=C:\chemin\python.exe` avant).
5. API : http://127.0.0.1:8000/docs — santé OCR : http://127.0.0.1:8010/health

Attendre « Ready » de PaddleOCR avant la première analyse. Au démarrage, l'API précharge
Florence (désactivable avec `RITA_PRELOAD=0`, inutile si `VISION_ENGINE=mistral`).

## Tests

`python -m pip install -r requirements-dev.txt` puis `python -m pytest tests` (tests
unitaires sans réseau, sans Florence ni PaddleOCR). `test_v213_florence.py` reste le
test manuel de la légende Florence ; `test_api.py` le test manuel de bout en bout.

## Budget de temps et coûts (V2.14 — §22)

* `EXTERNAL_DEADLINE_S` : budget global de la recherche externe (défaut 20 s) ; les
  images au-delà sont sautées et comptées dans `meta.nb_images_non_evaluees`.
* `meta.suivi_couts` : comptage des appels par analyse (vision, OCR, requêtes web,
  images, LLM) — base du coût par dossier exigé par le cahier des charges.

## Changements V2.14.0

Voir `CHANGELOG_V2_14_0.md` (et `CHANGELOG_V2_13_7.md` pour la version précédente).

## Notes

* Le modèle texte par défaut est `TEXT_MODEL=qwen3:0.6b` (voir `.env.example`).
* Le service OCR reçoit l'image brute en `application/octet-stream`.
* Avant toute exposition hors poste local : durcir `visual_web.py` (rebinding DNS),
  authentification, limitation de débit, politique de conservation (RGPD).
