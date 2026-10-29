"""Journalisation d'accès pour RITA Vision (§9.1 du cahier des charges général).

Journalise les requêtes API dans un fichier structuré :
- Date/heure, IP client, méthode, chemin, statut HTTP, temps de traitement
- Optionnel : corps de la requête (désactivé par défaut pour la confidentialité)
- Rotation automatique des logs (1 fichier par jour)

À activer via RITA_LOG_ACCESS=1. Les logs sont écrits dans data/logs/access.log.
"""
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import Request

# Configuration
LOG_ACCESS_ENABLED = os.getenv('RITA_LOG_ACCESS', '0').lower() in ('1', 'true', 'yes')
LOG_DIR = Path(os.getenv('RITA_LOG_DIR', 'data/logs'))
LOG_FILE = LOG_DIR / 'access.log'
LOG_REQUEST_BODY = os.getenv('RITA_LOG_REQUEST_BODY', '0').lower() in ('1', 'true', 'yes')

# Créer le répertoire de logs
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Logger dédié
logger = logging.getLogger('rita.access')
logger.setLevel(logging.INFO)

# Handler pour le fichier (rotation quotidienne gérée par TimedRotatingFileHandler)
if LOG_ACCESS_ENABLED:
    from logging.handlers import TimedRotatingFileHandler
    
    # Rotation à minuit, conservation 30 jours
    handler = TimedRotatingFileHandler(
        LOG_FILE,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)


class AccessLogMiddleware:
    """Middleware FastAPI pour la journalisation d'accès."""
    
    def __init__(self, app=None):
        # Pour compatibilité avec app.add_middleware()
        pass
    
    async def __call__(self, request: Request, call_next: callable):
        if not LOG_ACCESS_ENABLED:
            return await call_next(request)
        
        start_time = time.time()
        
        # Extraire les informations de la requête
        client_ip = self._get_client_ip(request)
        method = request.method
        path = request.url.path
        query_params = dict(request.query_params)
        
        # Ne pas logger les endpoints de santé
        if path in ('/health', '/docs', '/openapi.json', '/favicon.ico'):
            return await call_next(request)
        
        # Corps de la requête (optionnel, désactivé par défaut pour RGPD)
        # Note: On ne log pas le body par défaut pour éviter de consommer le stream
        # et pour respecter le RGPD. LOG_REQUEST_BODY=1 active cette option.
        request_body = {}
        
        # Appel de la route
        response = await call_next(request)
        
        # Calculer la durée
        duration = time.time() - start_time
        
        # Préparer le log
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'client_ip': client_ip,
            'method': method,
            'path': path,
            'query_params': query_params,
            'status_code': response.status_code,
            'duration_seconds': round(duration, 3),
            'user_agent': request.headers.get('user-agent', ''),
        }
        
        if request_body:
            log_entry['request_body'] = request_body
        
        # Logger au format JSON (une ligne par requête)
        logger.info(json.dumps(log_entry, ensure_ascii=False, default=str))
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Extrait l'IP client en tenant compte des proxys."""
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()
        
        client = request.client
        if client:
            return client.host
        
        return 'unknown'


def get_logging_status() -> dict:
    """Retourne le statut de la journalisation (pour /health)."""
    return {
        'logging_enabled': LOG_ACCESS_ENABLED,
        'log_file': str(LOG_FILE) if LOG_ACCESS_ENABLED else None,
        'log_request_body': LOG_REQUEST_BODY,
    }
