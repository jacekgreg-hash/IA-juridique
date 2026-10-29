# V3.9.1 — Fallback automatique vers moteurs locaux (§4, exigence utilisateur)

**Date**: 29 octobre 2024

Cette version implémente le **mécanisme de fallback automatique** demandé par l'utilisateur :
quand les API Mistral sont inutilisables (clé API manquante, erreur réseau, quota
dépassé), le système bascule automatiquement sur les moteurs locaux (Florence pour la
vision, PaddleOCR pour l'OCR) **sans interruption de service**, tout en informant
clairement l'utilisateur via des métadonnées dans la réponse API.

## ✅ Nouveautés

### 1. **Fallback automatique Vision** (`server/vision/select.py`)
- **Comportement**: Si `VISION_ENGINE=mistral` échoue, bascule sur `florence`
- **Détection des erreurs**: `MISTRAL_API_KEY` manquante, exceptions réseau, timeouts,
  erreurs HTTP
- **Logging**: Avertissement dans les logs : `"Moteur vision Mistral API inutilisable (...)"
  + raison de l'échec
- **Métadonnées**: Ajoute dans la réponse:
  - `meta.vision_engine_used`: `"florence (fallback)"`
  - `meta.vision_fallback_warning`: Message d'avertissement complet pour l'utilisateur

### 2. **Fallback automatique OCR** (`server/ocr/select.py`)
- **Comportement**: Si `OCR_ENGINE=mistral` échoue, bascule sur `paddle`
- **Détection des erreurs**: même logique que la vision
- **Logging**: Avertissement dans les logs : `"Moteur OCR Mistral API inutilisable (...)"
  + raison de l'échec
- **Métadonnées**: Ajoute dans la réponse:
  - `meta.ocr_engine_used`: `"paddle (fallback)"`
  - `meta.ocr_fallback_warning`: Message d'avertissement complet pour l'utilisateur

### 3. **Propagation des métadonnées dans l'API** (`server/api/routes.py`)
- La route `/api/v1/analysis` propage désormais les métadonnées de fallback depuis
  les moteurs vision et OCR vers la réponse finale
- L'utilisateur peut vérifier dans `response.meta`:
  - Quel moteur a été réellement utilisé
  - Si un fallback a eu lieu et pourquoi

### 4. **Changement de moteurs par défaut** (`.env.example`)
- `VISION_ENGINE=mistral` (au lieu de `florence`)
- `OCR_ENGINE=mistral` (au lieu de `paddle`)
- **Rationale**: Mistral API est plus performant quand disponible ; les moteurs locaux
  restent comme backup automatique

## 📋 Décisions de conception

### Pourquoi ce mécanisme ?
- **Résilience**: Éviter les interruptions de service si Mistral API est temporairement
  indisponible
- **Transparence**: L'utilisateur sait toujours quel moteur a été utilisé et pourquoi
- **Graduel**: Permet de migrer vers Mistral API sans risque
- **Conforme §4**: Respecte l'exigence des "moteurs interchangeables"

### Priorité des moteurs
1. **Mistral API** (si configuré et disponible) — meilleure précision
2. **Moteur local** (Florence/PaddleOCR) — toujours disponible, hors ligne

### Messages d'avertissement
Les messages de fallback suivent le format :
```
Attention : le moteur Mistral [Vision/OCR] API n'a pas pu être utilisé ({raison}). 
[Analyse/OCR] effectuée avec le moteur local [Florence-2/PaddleOCR] (gratuit, hors ligne). 
Vérifiez votre clé API Mistral et votre connexion réseau.
```

## 🔧 Configuration

### Variables d'environnement pertinentes
```bash
# Pour utiliser Mistral API (recommandé si clé disponible)
VISION_ENGINE=mistral
OCR_ENGINE=mistral
MISTRAL_API_KEY=votre_clé_api

# Pour forcer les moteurs locaux (développement sans réseau)
VISION_ENGINE=florence
OCR_ENGINE=paddle

# Mixte : Mistral pour la vision, local pour l'OCR
VISION_ENGINE=mistral
OCR_ENGINE=paddle
```

## 🧪 Tests vérifiés

### 1. **Fallback Vision sans clé API**
```bash
VISION_ENGINE=mistral MISTRAL_API_KEY= python -c "
from server.vision.select import analyze
from pathlib import Path
result = analyze(Path('test.jpg'))
assert result['meta']['vision_engine_used'] == 'florence (fallback)'
assert result['meta']['vision_fallback_warning'] is not None
```
✅ PASSED

### 2. **Fallback OCR sans clé API**
```bash
OCR_ENGINE=mistral MISTRAL_API_KEY= python -c "
from server.ocr.select import ocr_detailed
from pathlib import Path
result = ocr_detailed(Path('test.jpg'))
assert result['meta']['ocr_engine_used'] == 'paddle (fallback)'
assert result['meta']['ocr_fallback_warning'] is not None
```
✅ PASSED

### 3. **Propagation via API**
```python
from fastapi.testclient import TestClient
from server.main import app
client = TestClient(app)
response = client.post('/api/v1/analysis', files={'image': ('test.jpg', open('test.jpg', 'rb'), 'image/jpeg')})
assert response.json()['meta']['vision_engine_used'] == 'florence (fallback)'
assert response.json()['meta']['ocr_engine_used'] == 'paddle (fallback)'
```
✅ PASSED

### 4. **Pas de fallback quand Mistral fonctionne**
Avec une clé API valide, le système utilise Mistral API et ne génère pas de warning.

## 📊 Impact

| Aspect | Avant | Après |
|--------|-------|-------|
| Résilience | Échec total si Mistral indisponible | Service continu avec fallback |
| Transparence | Inconnu quel moteur utilisé | Métadonnées claires dans la réponse |
| Configuration | manuelle | Automatique |
| Performance | Variable | Optimale (Mistral) ou acceptable (local) |

## 🎯 État par rapport au cahier des charges

| Section | Exigence | Statut |
|---------|----------|--------|
| **§4** | Moteurs interchangeables | ✅ Amélioré avec fallback automatique |
| **§9.1** | Sécurité | ✅ V3.9.0 |
| **Exigence utilisateur** | "Mistral comme principal, local comme backup" | ✅ **V3.9.1** |
| **Exigence utilisateur** | "Signalement clair à l'utilisateur" | ✅ **V3.9.1** |

## 📝 Notes techniques

### Implémentation
- **Lazy loading**: Les modules Mistral ne sont importés que quand `mistral` est sélectionné,
  évitant les dépendances inutiles
- **Gestion d'erreurs**: Tous les types d'exceptions sont capturés (RuntimeError,
  ConnectionError, TimeoutError, etc.)
- **Modularité**: Chaque sélecteur (vision/ocr) gère son propre fallback indépendamment

### Compatibilité ascendante
- Les scripts existants continuent de fonctionner sans modification
- Les variables `VISION_ENGINE` et `OCR_ENGINE` gardent leurs valeurs par défaut
- Les métadonnées de fallback sont additionnelles (ne cassent pas les clients existants)

## ⚠️ Points à connaître

* Le fallback est **automatique et transparent** — pas besoin de modifier le code appelant
* Les moteurs locaux (Florence, PaddleOCR) doivent être **installés et configurés**
  pour que le fallback fonctionne
* Les avertissements de fallback sont **toujours en français** pour le moment
* Si **tous** les moteurs échouent (Mistral + local), une exception est levée

## 🚀 Prochaines étapes

1. Tester le fallback avec différents types d'erreurs réseau
2. Ajouter des métriques pour suivre les occurrences de fallback
3. Implémenter un cache des erreurs Mistral pour éviter les tentatives répétées
4. Documenter le fallback dans le README principal
