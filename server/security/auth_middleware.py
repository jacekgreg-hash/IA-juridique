"""Middleware d'authentification pour RITA Vision.

FastAPI-compatible middleware qui vérifie la clé API sur chaque requête
(sauf endpoints publics).
"""
import os
from typing import Callable, Awaitable

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse

from server.security.auth import AUTH_ENABLED, EXPECTED_API_KEY

# Endpoints publics (pas d'auth requise)
PUBLIC_PATHS = {'/health', '/docs', '/openapi.json', '/favicon.ico'}


class AuthMiddleware:
    """Middleware FastAPI pour l'authentification par API Key."""
    
    def __init__(self, app=None):
        # Pour compatibilité avec app.add_middleware()
        pass
        self.enabled = AUTH_ENABLED
        self.expected_key = EXPECTED_API_KEY
    
    async def __call__(self, request: Request, call_next: Callable[[Request], Awaitable]) -> JSONResponse:
        if not self.enabled:
            return await call_next(request)
        
        # Vérifier si le chemin est public
        if self._is_public_path(request.url.path):
            return await call_next(request)
        
        # Extraire la clé API
        api_key = request.headers.get('X-API-Key') or request.query_params.get('api_key')
        
        if not api_key:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    'detail': "Authentification requise. Fournissez une clé API valide via "
                             "l'en-tête X-API-Key ou le paramètre api_key.",
                },
            )
        
        if api_key != self.expected_key:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={'detail': 'Clé API invalide.'},
            )
        
        return await call_next(request)
    
    def _is_public_path(self, path: str) -> bool:
        """Vérifie si le chemin est public."""
        return any(path.startswith(p) for p in PUBLIC_PATHS)
