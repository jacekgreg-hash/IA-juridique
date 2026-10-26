# RITA Vision V2.13 — Florence-2-base

Premier essai de remplacement du moteur vision Ollama/Qwen/Moondream par **Microsoft Florence-2-base**.

## Objectif du test
Tester uniquement le moteur de perception sur la photo Nike P-6000 avant de réintégrer toute la chaîne RITA Vision.

Le test lance :
1. `<MORE_DETAILED_CAPTION>` pour décrire le produit ;
2. `<OCR>` pour lire le texte visible.

Le même modèle est chargé une seule fois puis réutilisé pour les deux tâches.

## Installation Windows
Depuis le dossier du projet :

```powershell
python -m pip install -r requirements_florence.txt
```

Puis :

```powershell
python test_v213_florence.py
```

Le premier lancement téléchargera le modèle depuis Hugging Face.

## Important
Florence-2-base fait environ 0,23 milliard de paramètres et le dépôt officiel contient environ 3,12 Go de fichiers, dont ~463 Mo de poids safetensors. Il est donc nettement plus petit que Qwen3-VL 4B, mais il faudra vérifier la consommation RAM et le temps CPU sur la machine cible.

Le modèle officiel `microsoft/Florence-2-base` est sous licence MIT.


## V2.13.2

Cette version utilise Florence-2-base (0,23B) par défaut, adapté à une machine CPU/RAM limitée. Transformers est épinglé à 4.49.0 pour compatibilité avec le code Florence-2 original.
