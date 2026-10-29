"""Limitation de débit (rate limiting) pour RITA Vision (§9.1 du cahier des charges).

Implémentation simple et légère (stdib uniquement) :
- Limite configurable par IP (RITA_RATE_LIMIT, défaut 60 requêtes/minute) ;
- Fenêtre glissante pour une précision optimale ;
- Liste blanche pour /health et /docs ;
- Retourne HTTP 429 avec en-tête Retry-After.

À activer avant toute exposition publique (mentionné dans V2.14, V3.2, V3.6,
V3.7 comme bloquant avec l'authentification).
"""
import os
import time
from collections import defaultdict
from threading import Lock
from typing import Optional

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse

# Configuration
RATE_LIMIT = int(os.getenv('RITA_RATE_LIMIT', '60'))  # requêtes par minute par IP
RATE_WINDOW = 60  # secondes

# Stockage : {ip: [timestamps des requêtes dans la fenêtre]}
_requests = defaultdict(list)
_lock = Lock()

# Endpoints exclus (pas de rate limiting)
EXCLUDED_PATHS = {'/health', '/docs', '/openapi.json'}


def is_excluded(path: str) -> bool:
    """Vérifie si le chemin est exclu du rate limiting."""
    return any(path.startswith(excluded) for excluded in EXCLUDED_PATHS)


def _cleanup_old_requests(ip: str, now: float) -> None:
    """Nettoie les timestamps trop anciens pour un IP donné (appelé avec verrou déjà acquis)."""
    _requests[ip] = [t for t in _requests[ip] if now - t < RATE_WINDOW]


def get_remaining_requests(ip: str) -> int:
    """Retourne le nombre de requêtes restantes pour un IP."""
    with _lock:
        now = time.time()
        _cleanup_old_requests(ip, now)
        return max(0, RATE_LIMIT - len(_requests[ip]))


def record_request(ip: str) -> bool:
    """Enregistre une requête pour un IP. Retourne True si autorisée, False sinon."""
    now = time.time()
    with _lock:
        _cleanup_old_requests(ip, now)
        if len(_requests[ip]) >= RATE_LIMIT:
            return False
        _requests[ip].append(now)
        return True


def get_retry_after(ip: str) -> int:
    """Retourne le nombre de secondes à attendre avant la prochaine requête autorisée."""
    with _lock:
        if not _requests[ip]:
            return 0
        now = time.time()
        oldest = min(_requests[ip])
        elapsed = now - oldest
        if elapsed >= RATE_WINDOW:
            return 0
        # Temps restant jusqu'à ce que la plus ancienne requête sorte de la fenêtre
        return int(RATE_WINDOW - elapsed) + 1


class RateLimitMiddleware:
    """Middleware FastAPI pour la limitation de débit.
    
    Compatible avec FastAPI : peut être ajouté via app.add_middleware() ou app.middleware('http').
    """
    
    def __init__(self, app=None):
        # Pour compatibilité avec app.add_middleware()
        pass
    
    async def __call__(self, request: Request, call_next: callable):
        # Extraire l'IP client (dernier proxy de confiance)
        client_ip = self._get_client_ip(request)
        
        # Vérifier si le chemin est exclu
        if is_excluded(request.url.path):
            response = await call_next(request)
            return response
        
        # Vérifier la limite
        if not record_request(client_ip):
            retry_after = get_retry_after(client_ip)
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    'detail': f"Trop de requêtes. Limite : {RATE_LIMIT} requêtes/minute par IP.",
                    'retry_after': retry_after,
                },
                headers={'Retry-After': str(retry_after)},
            )
        
        response = await call_next(request)
        
        # Ajouter les en-têtes de rate limiting
        remaining = get_remaining_requests(client_ip)
        reset = get_retry_after(client_ip)
        
        response.headers['X-RateLimit-Limit'] = str(RATE_LIMIT)
        response.headers['X-RateLimit-Remaining'] = str(remaining)
        response.headers['X-RateLimit-Reset'] = str(reset)
        
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Extrait l'IP client en tenant compte des proxys (X-Forwarded-For, X-Real-IP)."""
        # ordre de confiance : X-Forwarded-For (premier IP) > X-Real-IP > Remote Address
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            # X-Forwarded-For peut contenir plusieurs IPs, la première est le client original
            return forwarded_for.split(',')[0].strip()
        
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()
        
        # Par défaut, utiliser l'adresse distante
        # Pour les connexions IPv4, on utilise directement
        # Pour IPv6, on peut simplifier
        client = request.client
        if client:
            return client.host
        
        return 'unknown'


def get_rate_limit_status() -> dict:
    """Retourne le statut du rate limiting (pour /health)."""
    return {
        'rate_limit_enabled': True,
        'limit': RATE_LIMIT,
        'window_seconds': RATE_WINDOW,
    }
