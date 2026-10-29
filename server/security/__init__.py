"""Module de sécurité pour RITA Vision (§9.1 du cahier des charges général).

Ce module implémente les exigences de sécurité identifiées comme bloquantes
dans les changelogs V3.2 à V3.8 avant toute exposition publique :
- Authentification (API Key)
- Limitation de débit (rate limiting)
- Journalisation d'accès

À activer via les variables d'environnement :
- RITA_API_AUTH_ENABLED=1 : active l'authentification
- RITA_API_KEY : clé API attendue (si auth activée)
- RITA_RATE_LIMIT : requêtes/minute par IP (défaut 60)
- RITA_LOG_ACCESS=1 : active la journalisation des accès
"""
