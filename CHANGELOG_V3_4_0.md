# V3.4.0 — recherche par désignation : classer au-delà des 4 familles codées

Jusqu'ici, le moteur tarifaire ne proposait des positions que pour les familles
codées à la main (chaussures, téléphonie, horlogerie, meubles) ; toute autre
marchandise sortait « impossible ». La base officielle V3.1 (16 725 codes
déclarables avec désignations FR) restait inutilisée au-delà des familles.

Cette version ajoute la **recherche par désignation** : quand aucune famille ne
correspond, le moteur cherche les mots de l'analyse dans les désignations
officielles et propose des candidats — preuve faible, jamais une confirmation.

Vérifié : `python -m pytest tests` 67/67 (+11) ; scénarios manuels
(perceuse → 8467 21, vélo → 8712 00, casque audio → 8518 21, aspirateur →
8508 11, sac à dos → 4202 12, bouilloire → refus documenté).

## Nouveautés

### 1. `server/tariff/search.py` — recherche dans la nomenclature
* Index inversé mot -> codes, construit au chargement de
  `nomenclature_fr.json` (requêtes O(1) par mot).
* Normalisation linguistique : minuscules sans accents, pluriels français
  simplifiés ; mots-outils exclus ; synonymes explicites et limités
  (« vélo »/« bike » → bicyclette, « drill » → perceuse...).
* **Bonus de position tarifaire** : un mot du fragment HS4 (le « nom » du
  produit) pèse plus que sa simple présence dans la désignation — c'est ce
  qui départage les casque**s** audio (position 8518) de la viande « en
  **casque** ou demi-casque » (0204), ou les bicyclettes (8712) des pneus
  « pour bicyclettes » (4011).
* Pondération des preuves : nature > caractéristiques > légende/OCR.
* Confiance plafonnée à 0,60, statut toujours « propose » (§29).

### 2. Garde anti-bruit (§11 : ne pas inventer)
Si la **nature** identifiée est connue mais absente de la nomenclature
(ex. « bouilloire », mot que la CN n'utilise pas), la matière ou la couleur
seules ne produisent PAS de candidats (« acier inoxydable » pour une
bouilloire serait du bruit) : le moteur refuse et explique pourquoi, avec la
question de la nature précise. Le classement officiel de la bouilloire
électrique étant un vrai débat douanier, aucune opinion n'est codée en dur.

### 3. Intégration au moteur
`propose_classement` : hors familles codées → recherche par désignation →
candidats + question « quelle est la nature précise ? » (statut
`candidats_a_departager`, marqueur `recherche: designation`) ; sans
résultat, statut `impossible` avec la raison complète de la recherche.
Les familles codées gardent la priorité (discriminants curatés).

## Points à connaître
* La recherche porte sur les désignations FR du TARIC ; l'anglais passe par
  les synonymes explicites (liste courte, chaque entrée est une décision).
* `tools/import_taric.py` ajoute le champ `position` (fragment HS4) à
  `nomenclature_fr.json` — base régénérée et versionnée.
* La qualité dépend du vocabulaire de la vision : les natures hors
  nomenclature (bouilloire) sont refusées plutôt que devinées.

## Non traité
* Durcissement SSRF (rebinding DNS), authentification, limitation de débit —
  avant toute exposition réseau.
* Calibrage des seuils sur le banc d'essai (§26).
