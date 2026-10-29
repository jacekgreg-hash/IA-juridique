"""Middleware combiné pour la sécurité RITA Vision.

Intègre dans un seul middleware (pour optimiser les performances) :
- Authentification (si activée)
- Rate limiting (toujours actif)
- Journalisation d'accès (si activée)

Ordre d'exécution :
1. Rate limiting (rejet rapide si limite dépassée)
2. Authentification (si activée)
3. Traitement de la requête
4. Journalisation (si activée)
"""
import os
import time
from typing import Callable

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse

from server.security.auth import AUTH_ENABLED, EXPECTED_API_KEY, get_auth_status
from server.security.rate_limit import (
    RateLimitMiddleware, 
    get_rate_limit_status,
    is_excluded as is_rate_limit_excluded,
    record_request,
    get_retry_after,
    RATE_LIMIT,
)
from server.security.logging import AccessLogMiddleware, get_logging_status, LOG_ACCESS_ENABLED


class SecurityMiddleware:
    """Middleware unifié pour auth + rate limiting + logging."""
    
    def __init__(self, app):
        self.app = app
        self.rate_limiter = RateLimitMiddleware()
        self.access_logger = AccessLogMiddleware()
    
    async def __call__(self, request: Request, call_next: Callable):
        # Étape 1 : Rate limiting (toujours vérifier en premier pour un rejet rapide)
        if not is_rate_limit_excluded(request.url.path):
            client_ip = self._get_client_ip(request)
            if not record_request(client_ip):
                retry_after = get_retry_after(client_ip)
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        'detail': f"Trop de requêtes. Limite : {RATE_LIMIT} requêtes/minute par IP.",
                        'retry_after': retry_after,
                    },
                    headers={'Retry-After': str(retry_after)},
                )
        
        # Étape 2 : Authentification (si activée et endpoint non public)
        if AUTH_ENABLED and not self._is_public_path(request.url.path):
            api_key = request.headers.get('X-API-Key') or request.query_params.get('api_key')
            
            if not api_key:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={
                        'detail': "Authentification requise. Fournissez une clé API valide via "
                                 "l'en-tête X-API-Key ou le paramètre api_key.",
                    },
                )
            
            if api_key != EXPECTED_API_KEY:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={'detail': 'Clé API invalide.'},
                )
        
        # Étape 3 : Journalisation (avant le traitement pour capturer la requête)
        if LOG_ACCESS_ENABLED:
            start_time = time.time()
            request.state.log_start_time = start_time
        
        # Étape 4 : Traitement de la requête
        response = await call_next(request)
        
        # Étape 5 : Journalisation (après le traitement pour capturer la réponse)
        if LOG_ACCESS_ENABLED and hasattr(request.state, 'log_start_time'):
            # Le AccessLogMiddleware va logger, mais on ajoute les en-têtes de rate limiting
            remaining = 0
            reset = 0
            if not is_rate_limit_excluded(request.url.path):
                client_ip = self._get_client_ip(request)
                from server.security.rate_limit import get_remaining_requests, get_retry_after
                remaining = get_remaining_requests(client_ip)
                reset = get_retry_after(client_ip)
            
            response.headers['X-RateLimit-Limit'] = str(RATE_LIMIT)
            response.headers['X-RateLimit-Remaining'] = str(remaining)
            response.headers['X-RateLimit-Reset'] = str(reset)
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Extrait l'IP client."""
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
    
    def _is_public_path(self, path: str) -> bool:
        """Vérifie si le chemin est public (pas d'auth requise)."""
        public_paths = {'/health', '/docs', '/openapi.json'}
        return any(path.startswith(p) for p in public_paths)


def get_security_status() -> dict:
    """Retourne le statut complet de la sécurité (pour /health)."""
    return {
        'auth': get_auth_status(),
        'rate_limit': get_rate_limit_status(),
        'logging': get_logging_status(),
    }
