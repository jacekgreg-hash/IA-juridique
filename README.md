# RITA Vision V2.13.7 — Florence-2-base + PaddleOCR

## Pipeline

PHOTO → Florence-2-base (légende) ‖ PaddleOCR (texte, service séparé) → enrichissement déterministe
(marque, catégorie, couleurs, caractéristiques) → candidats catalogue → SearXNG → extraction déterministe
→ LLM texte uniquement si nécessaire → fusion Python → décision conservatrice.

Florence décrit, PaddleOCR lit : ce sont des **preuves**. Ni l'un ni l'autre ne confirme seul un modèle ou une
référence. Rien dans cette chaîne n'est encore un classement tarifaire.

## Démarrage (Windows)

1. Dépendances de l'API (Python 3.14 ou autre) :
   `python -m pip install -r requirements.txt -r requirements_florence.txt`
2. Dépendances OCR, une fois, avec Python 3.12 :
   `%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe -m pip install -r requirements_paddle.txt`
3. Copier `.env.example` vers `.env` et l'adapter.
4. Lancer `run_all.bat` (si Python 3.12 est ailleurs : `set PY312=C:\chemin\python.exe` avant).
5. API : http://127.0.0.1:8000/docs — santé OCR : http://127.0.0.1:8010/health

Attendre « Ready » de PaddleOCR avant la première analyse. Au démarrage, l'API précharge Florence
(désactivable avec `RITA_PRELOAD=0`).

## Tests

`python -m pip install -r requirements-dev.txt` puis `python -m pytest tests` (tests unitaires sans réseau,
sans Florence ni PaddleOCR). `test_v213_florence.py` reste le test manuel de la légende Florence.

## Changements V2.13.7

Voir `CHANGELOG_V2_13_7.md`.

## Notes

* Le modèle texte par défaut est `TEXT_MODEL=qwen3:0.6b` (voir `.env.example`).
* Le service OCR reçoit l'image brute en `application/octet-stream` (plus de `cgi`, donc plus lié à Python 3.12
  par ce module — PaddlePaddle reste, lui, à valider selon la version de Python).
* Avant toute exposition hors poste local : durcir `visual_web.py` (rebinding DNS), authentification,
  limitation de débit, politique de conservation (RGPD).
