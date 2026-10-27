# V3.6.0 — durcissement SSRF : épinglage DNS anti-rebinding

La garde anti-SSRF de V2.14 vérifiait les IP résolus (`is_public_url`) puis
lançait la requête avec `requests.get` — qui refaisait **sa propre résolution
DNS**. Un serveur malveillant pouvait donc répondre avec une IP publique au
moment de la vérification, puis résoudre vers une IP interne (loopback,
169.254.169.254, réseau local) au moment de la connexion : la classique
fenêtre TOCTOU « rebinding DNS ».

Vérifié : `python -m pytest tests` 74/74 (+5) ; en conditions réelles —
HTTPS épinglé sur un site réel (SNI + certificat vérifiés sur le nom d'hôte
pendant que la connexion se fait sur l'IP épinglé) et téléchargement complet
d'une image via redirections.

## Correctif (`server/candidates/visual_web.py`)

* **Épinglage DNS** : chaque saut (URL initiale + chaque redirection) est
  résolu UNE fois (`_resolve_public` : tous les IP doivent être publics, sinon
  refus), puis la connexion se fait **sur l'IP vérifié** — plus aucune
  résolution n'a lieu entre vérification et connexion.
* HTTP : connexion à l'IP épinglé avec en-tête `Host` d'origine (le routage
  virtuel des serveurs mutualisés en dépend).
* HTTPS : `http.client.HTTPSConnection` spécialisée — connexion à l'IP épinglé
  avec **SNI et vérification de certificat sur le vrai nom d'hôte** (pas
  l'IP) : sécurité accrue par rapport à `requests` (certificat vérifié même
  en cas de réponses DNS incohérentes).
* Redirections manuelles conservées, chaque saut re-résolu et re-vérifié.
* `requests` supprimé de ce module (stdlib uniquement : `http.client`,
  `ssl`, `socket`, `ipaddress`).
* `is_public_url` conservé comme indicateur (compatibilité) ; la vraie
  garantie est dans `_fetch`.

## Tests (+5)
* refus de `localhost` même avec un serveur local qui tourne réellement ;
* épinglage : la connexion se fait sur l'IP vérifié et l'en-tête `Host`
  d'origine est transmis (serveur local, résolution simulée) ;
* redirection vers un IP privé refusée au saut suivant ;
* code HTTP >= 400 refusé ;
* `_resolve_public('localhost')` → refus.

## Points à connaître
* La passe couvre les URL d'images issues de la recherche web (la surface
  manipulable par l'extérieur). Les fournisseurs de recherche (SearXNG,
  Brave) sont configurés par l'opérateur (variables d'environnement), hors
  surface SSRF.
* Restent à traiter avant une exposition publique : authentification,
  limitation de débit, journalisation d'accès, RGPD (§9.1 du cahier général).
* Un proxy de sortie (egress) dédié resterait la défense en profondeur
  recommandée pour un déploiement réseau.
