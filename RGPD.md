# Politique RGPD — RITA Vision V3.8.0+

## 📋 Contexte (§9.1 du cahier des charges général)

RITA Vision traite des **photos de marchandises** pour proposer un classement tarifaire.
Les exigences RGPD s'appliquent dès qu'une photo contient ou pourrait contenir des
données à caractère personnel (DCP) :

- **Photos de clients** : peuvent contenir des informations personnelles (visage, nom sur
  emballage, adresse, etc.) ;
- **Métadonnées EXIF** : certaines photos contiennent des coordonnées GPS, dates,
  informations sur l'appareil photo ;
- **Textes OCR** : peuvent extraire des noms, adresses, numéros de téléphone depuis
  des étiquettes ou documents.

## ✅ Mesures implémentées

### 1. **Pas de stockage des photos** (§25 du cahier des charges)
- Les photos uploadées sont **traitées en mémoire** et **supprimées immédiatement**
  après analyse ;
- Seuls les résultats textuels (classement, candidats, métadonnées de traitement) sont
  conservés en base (SQLite par défaut) ;
- La base ne contient **aucune image** — uniquement des JSON de résultats.

### 2. **Traitement local par défaut**
- Les moteurs de vision (Florence-2) et OCR (PaddleOCR) tournent **localement**
  (CPU, sans envoi externe) ;
- Les photos ne quittent pas le poste de travail par défaut.

### 3. **Avertissements avant envoi aux API externes**
- Quand `VISION_ENGINE=mistral` ou `OCR_ENGINE=mistral`, un avertissement dans
  le README et les logs rappelle de **vérifier les conditions de La Plateforme**
  (Mistral AI) concernant :
  - la **rétention** des données ;
  - la **réutilisation** des images ;
  - la **localisation** des serveurs (UE recommandée).

### 4. **Journalisation minimaliste**
- La journalisation d'accès (`RITA_LOG_ACCESS=1`) log **uniquement** :
  - IP client (peut être anonymisée via proxy) ;
  - méthode HTTP, chemin, code de retour, durée ;
  - **pas de corps de requête par défaut** (`RITA_LOG_REQUEST_BODY=0`) ;
- Option `RITA_LOG_REQUEST_BODY=1` désactivée par défaut pour éviter de logger
  des DCP.

### 5. **Authentification obligatoire avant exposition**
- L'API exige une **clé API** (`RITA_API_AUTH_ENABLED=1` + `RITA_API_KEY`) avant
  toute exposition publique ;
- Cela limite l'accès aux utilisateurs autorisés.

## ⚠️ Responsabilités de l'opérateur

### Avant d'activer les API externes (Mistral)
1. **Lire et accepter** les Conditions Générales de La Plateforme Mistral AI ;
2. **Vérifier** que les photos traitées ne contiennent pas de DCP ou que vous avez
   obtenu le consentement des personnes concernées ;
3. **Configurer** un proxy de sortie (egress) dédié si nécessaire pour contrôler
   le flux des données.

### En cas de déploiement public
1. **Activer l'authentification** : `RITA_API_AUTH_ENABLED=1` + `RITA_API_KEY` ;
2. **Activer le rate limiting** : `RITA_RATE_LIMIT=60` (défaut) ;
3. **Anonymiser les IPs** dans les logs via un proxy (ex: Nginx avec `set $remote_addr
   $http_x_forwarded_for`) ;
4. **Ne pas activer** `RITA_LOG_REQUEST_BODY=1` sans analyse d'impact RGPD ;
5. **Informer** les utilisateurs via une notice de confidentialité.

## 🗑️ Conservation des données

| Donnée | Conservation | Localisation | Base légale |
|--------|--------------|-------------|-------------|
| Photos uploadées | **Aucune** (suppression immédiate après traitement) | Mémoire locale | Intérêt légitime (traitement) |
| Résultats d'analyse | 30 jours (rotation des logs) | SQLite local | Intérêt légitime (tracabilité) |
| Logs d'accès | 30 jours (rotation automatique) | Fichier local | Obligation légale (sécurité) |
| Photos envoyées à Mistral API | Selon conditions Mistral AI | Serveurs Mistral | Consentement (à vérifier par l'opérateur) |

## 🔧 Configuration RGPD

```bash
# Dans .env
# Désactiver la journalisation des corps de requête (défaut)
RITA_LOG_REQUEST_BODY=0

# Activer l'authentification
RITA_API_AUTH_ENABLED=1
RITA_API_KEY=votre_cle_secrete_ici

# Limiter le débit
RITA_RATE_LIMIT=60
```

## 📄 Notice type pour les utilisateurs finaux

> **Confidentialité des données**
> 
> RITA Vision traite vos photos localement par défaut. Si vous utilisez le mode
> API externe (Mistral), vos photos sont envoyées à Mistral AI selon leurs
> propres conditions. Aucune photo n'est stockée par RITA Vision. Les résultats
> d'analyse sont conservés 30 jours maximum pour traçabilité. L'accès à l'API
> est protégé par clé. Pour plus d'informations, consultez le RGPD.md du
> projet.

## 🎯 Checklist avant mise en production

- [ ] Authentification activée (`RITA_API_AUTH_ENABLED=1`)
- [ ] Clé API sécurisée (`RITA_API_KEY` dans .env, jamais commité)
- [ ] Rate limiting activé (`RITA_RATE_LIMIT` configuré)
- [ ] `RITA_LOG_REQUEST_BODY=0` (pas de logging des corps de requête)
- [ ] Proxy d'anonymisation des IPs configuré (si logs activés)
- [ ] Notice de confidentialité affichée aux utilisateurs
- [ ] Vérification des conditions Mistral AI si `VISION_ENGINE=mistral` ou
  `OCR_ENGINE=mistral`
- [ ] Test de conformité RGPD effectué

## 📞 Contact RGPD

Responsable du traitement : [À COMPLÉTER PAR L'OPÉRATEUR]
DPO : [À COMPLÉTER PAR L'OPÉRATEUR]

---

*Document version 1.0 — V3.8.0 — À adapter selon votre contexte juridique.*
