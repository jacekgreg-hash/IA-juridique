# V3.2.0 — moteur fiscal : droits d'importation par origine (§16)

Le moteur tarifaire proposait des codes avec un droit de pays tiers indicatif ;
les droits réels dépendent de l'origine (accords de préférence, GSP,
antidumping). Cette version ajoute le **moteur fiscal**, séparé du moteur de
classement (§16), entièrement alimenté par le TARIC officiel.

Vérifié : `python -m pytest tests` 51/51 (10 tests fiscaux : préférences
Viêt Nam/Mercosur, erga omnes, antidumping Chine, résolution de noms FR,
normalisation de codes, route API) ; scénarios manuels complémentaires
(Ukraine 0 %, « Chine » → CN, bicyclette CN 4,7 % + AD 48,5 %).

## Nouveautés

### 1. Base fiscale (`data/tariff/fiscal.sqlite`, générée par l'importeur)
* 101 551 mesures valides importées de « Duties Import 01-99 » :
  103 droit de pays tiers, 142 préférence tarifaire, 552 antidumping
  définitif, 117 suspension.
* Appartenance des pays aux groupes d'origine (« Geographical areas
  composition ») : résolution pays → groupe (Mercosur, GSP, accords...).
* Versionnée dans le dépôt (comme nomenclature_fr.json) ; régénérable par
  `python tools/import_taric.py`.

### 2. Moteur fiscal (`server/tariff/fiscal.py`)
* `taux_estime(code, origine)` applique le principe de cascade TARIC
  (une mesure définie à un niveau couvre les niveaux subordonnés) :
  * droit de pays tiers (ERGA OMNES) ;
  * préférence si l'origine appartient au groupe de la mesure — la plus
    basse retenue, les autres signalées ; sous réserve de preuves d'origine ;
  * antidumping : s'ajoute au droit de base ; les taux par entreprise
    (codes additionnels) sont listés, l'estimation retient le maximum
    (prudent) ;
  * suspension : information (champ d'application restreint).
* Sortie : composants (taux, montant brut, base légale, groupe), explication
  pas à pas, taux estimé ad valorem, **avertissement de vérification
  officielle** — jamais une certitude fiscale (§29) ; les droits non ad
  valorem (spécifiques) ne sont pas sommés en pourcentage.

### 3. API : `GET /api/v1/duty?code=6403190000&origine=CN`
* Code accepté en CN8 (« 6403 19 00 ») ou 10 chiffres ; origine en ISO2
  (« VN ») ou nom (« Chine », y compris noms français usuels).
* 503 si la base fiscale est absente (importeur non exécuté).
* APP_VERSION 3.2.0.

## Exemples vérifiés (référence TARIC 2026-10)
* 6403 19 00 (chaussures sport cuir) : Viêt Nam 0 % (accord UE-VN),
  Brésil 7 % (Mercosur), Ukraine 0 %, Chine/États-Unis 8 % (erga omnes).
* 8714911031 (éléments de bicyclette) Chine : 4,7 % + antidumping
  0-48,5 % selon l'entreprise → estimation prudente 53,2 %.

## Limites documentées
* La préférence suppose des règles d'origine respectées (preuve d'origine) —
  non vérifiable par l'outil.
* Contingents tarifaires (122), mesures agricoles (Meursing) et contrôles
  non intégrés — signalés dans l'avertissement.
* La cascade par préfixe ne couvre pas les branches « autres » du TARIC
  (intermédiaires) — approximation documentée, sans effet sur les codes
  déclarables testés.

## Non traité
* Intégration de l'origine dans le flux d'analyse (question ciblée puis
  appel du moteur fiscal) — le point d'entrée est l'API pour l'instant.
* Recherche par désignation sur nomenclature_fr.json.
* SSRF / auth / rate limiting avant exposition ; calibrage des seuils (§26).
