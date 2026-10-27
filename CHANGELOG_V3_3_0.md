# V3.3.0 — origine dans le flux d'analyse ; préférence jamais automatique

Le moteur fiscal (V3.2.0) était interrogé via `GET /api/v1/duty`. Il est
maintenant branché sur le flux d'analyse, avec une règle cardinale issue de la
pratique douanière : **l'origine préférentielle n'est pas automatique** — elle
exige des justificatifs et le respect des règles d'origine de l'accord.

Vérifié : `python -m pytest tests` 57/57 (+6 : justificatifs Viêt Nam, mention
REX pour le SPG, question d'origine, enrichissement avec/sans origine).

## Nouveautés

### 1. Moteur fiscal : les deux taux, jamais un remplacement silencieux
`server/tariff/fiscal.py` :
* `taux_sans_preference` — le droit de pays tiers, toujours visible ;
* `justificatifs_requis` — preuve d'origine (EUR.1 ou déclaration sur la
  facture ; **registre REX pour le SPG**), respect des règles d'origine
  (transformation suffisante, non-altération, transport direct) ;
* `taux_sans_justificatif` — quand une préférence existe, l'estimation donne
  les DEUX taux : « AVEC justificatif = 0 % ; SANS justificatif = 8 % » ;
* explication reformulée : « Préférence POSSIBLE — uniquement sur
  justificatif ; sans justificatif, le droit applicable est X % ».

### 2. Analyse : champ `origine` facultatif + question ciblée (§31.3)
* `POST /api/v1/analysis` accepte un champ formulaire `origine` (pays ISO2 ou
  nom, y compris français) ; fournie → `response['droits']` contient
  l'estimation par candidat (3 premiers) avec justificatifs et les deux taux.
* Sans origine → question ciblée ajoutée au classement (« quel est le pays
  d'origine — lieu de production, pas simplement le pays d'expédition ? »)
  et `origine` listée dans `informations_manquantes` ; le droit de pays tiers
  indicatif reste seul affiché.
* Toute erreur du moteur fiscal est non bloquante (statut `indisponible`),
  même politique que la persistance. APP_VERSION 3.3.0.

## Points à connaître
* La forme exacte de la preuve d'origine dépend de l'accord : EUR.1,
  déclaration d'origine sur facture, REX (SPG) — le moteur la précise pour
  les cas connus et renvoie sinon à la documentation de l'accord.
* Le SPG exige l'inscription de l'exportateur au registre REX — couvert par
  `justificatifs_requis` dès que le groupe contient « GSP ».
* L'origine préférentielle (droit à la préférence) est un concept juridique
  distinct de l'origine non préférentielle (marquage, mesures antidumping) ;
  la question posée précise « lieu de production ».

## Non traité
* Recherche par désignation sur nomenclature_fr.json.
* SSRF rebinding DNS / authentification / limitation de débit avant exposition.
* Calibrage des seuils sur le banc d'essai (§26).
