# V3.5.0 — notes explicatives de la CN : le pont entre langage courant et nomenclature

Certaines natures identifiées par la vision utilisent un vocabulaire que la
nomenclature n'emploie jamais : « bouilloire » n'apparaît dans aucune des
16 725 désignations officielles. Les **notes explicatives de la nomenclature
combinée** (NENC — textes officiels d'interprétation publiés au JO, art. 9 du
règlement 2658/87) utilisent, elles, le vocabulaire courant : c'est la note de
8516 10 11/80 qui dit que relèvent de ces sous-positions « les chaudières
électriques qui produisent uniquement de l'eau chaude » — les bouilloires.

V3.4 refusait ces cas (« nature non trouvée »). V3.5 ajoute un **second
niveau de preuve** : quand la nature est absente des désignations, le moteur
cherche dans les notes explicatives et propose les positions avec la
**citation officielle** qui les justifie.

Vérifié : `python -m pytest tests` 69/69 (+2) ; cas manuels — bouilloire
électrique → 8516 10 11 / 8516 10 80 (citation exacte citée), perceuse/vélo/
casque/aspirateur/sac inchangés (V3.4), familles codées inchangées.

## Nouveautés

### 1. Import des NENC (`data/tariff/notes_cn_fr.json`, 2 595 segments)
* Source : texte consolidé FR (CELEX 52019XC0329(02), Office des publications
  de l'UE) déposé dans `data/tariff/raw/cnen-fr*.html` (ignoré par git).
* Tableau officiel parsé : cellule codes (exactes, listes « et », plages
  « à ») + texte ; régénérable par `python tools/import_taric.py`.
* Importeur rendu sobre en mémoire (écriture en flux `json.dump`,
  libération des structures entre phases, parsing itératif) — la machine
  cible a 6 Go de RAM, l'ancien enchaînement saturait.

### 2. `server/tariff/search.py` — recherche par phrase dans les notes
* Granularité **phrase** : les NENC énumèrent des exemples, et la phrase qui
  matche est la justification citée mot pour mot.
* Départage sémantique de trois signaux :
  * mot de la nature (poids 2) — via `SYNONYMES_NOTES` ancré dans un texte
    officiel (« bouilloire » → chaudière, NENC 8516 10) ;
  * proximité avec un mot de la légende/OCR (poids 0,25 + bonus 0,5) :
    « chaudières électriques » (le produit) bat « ...pour les centrales
    électriques » (mention lointaine) ;
  * pénalité de mention de contexte (« pour/de/dans » devant la forme :
    tubes POUR chaudières, fours DE cimenterie) ;
  * matières exclues du signal (acier, inox... ne départagent pas).
* Confiance plafonnée à 0,45 — preuve plus faible que la désignation (0,60),
  statut toujours « propose », citation tronquée à 220 caractères.

### 3. Intégration
* `rechercher()` : garde V3.4 conservée — nature absente des désignations →
  essai des notes avant refus ; le refus final reste documenté.
* Moteur : `result['recherche']` vaut `notes_explicatives` pour distinguer
  les deux niveaux ; question « nature précise » conservée.
* Codes CN8 subdivisés (ex. 8516 10 80) résolus vers leurs fils TARIC10.

## Exemple (bouilloire électrique, inox, légende « bouilloire électrique »)
```
8516 10 11     conf=0.45  note explicative de la CN : « les chaudières
8516 10 80 10             électriques qui produisent uniquement de l'eau
8516 10 80 90             chaude ou bien à la fois de l'eau chaude et la
                          vapeur à basse pression »
7304 31 20 30  conf=0.43  « ...chaudières, surchauffeurs... pour les
                          centrales électriques » (mention de contexte)
```

## Points à connaître
* La version FR consolidée des NENC date de 2019 (consolidation Cellar) ;
  les amendements postérieurs publiés au JO série C ne sont pas dedans — le
  pont lexical reste valide, à mettre à jour si une nouvelle consolidation
  FR est publiée.
* `SYNONYMES_NOTES` reste volontairement minuscule : chaque entrée est une
  décision ancrée dans un texte officiel, pas un dictionnaire général.

## Non traité
* Durcissement SSRF (rebinding DNS), authentification, limitation de débit —
  avant toute exposition réseau.
* Calibrage des seuils sur le banc d'essai (§26).
