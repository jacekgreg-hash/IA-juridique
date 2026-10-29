"""Authentification par API Key pour RITA Vision (§9.1 du cahier des charges).

Principes :
- L'authentification est OPTIONNELLE par défaut (pour développement local) ;
- elle s'active par RITA_API_AUTH_ENABLED=1 ;
- la clé est attendue dans l'en-tête X-API-Key ou le paramètre query api_key ;
- les endpoints /health et /docs restent publics (sans auth).

À configurer avant toute exposition publique (mentionné dans V2.14, V3.2,
V3.6, V3.7 comme bloquant).
"""
import os
import secrets
from functools import wraps
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import APIKeyHeader

# Configuration
AUTH_ENABLED = os.getenv('RITA_API_AUTH_ENABLED', '0').lower() in ('1', 'true', 'yes')
EXPECTED_API_KEY = os.getenv('RITA_API_KEY', '').strip()

# Génération d'une clé aléatoire si RITA_API_KEY non définie (développement uniquement)
if AUTH_ENABLED and not EXPECTED_API_KEY:
    EXPECTED_API_KEY = secrets.token_urlsafe(32)
    import warnings
    warnings.warn(
        f"RITA_API_AUTH_ENABLED=1 mais RITA_API_KEY non définie. "
        f"Clé générée automatiquement pour ce démarrage : {EXPECTED_API_KEY}\n"
        "DEVELOPPEMENT UNIQUEMENT — à remplacer par une clé sécurisée en production.",
        UserWarning,
        stacklevel=2
    )

# Schéma FastAPI pour la clé API
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    request: Request = None,
) -> Optional[str]:
    """Récupère la clé API depuis l'en-tête X-API-Key ou le query param api_key."""
    if not AUTH_ENABLED:
        return None  # Auth désactivée
    
    # Vérifier le query param aussi (pour compatibilité)
    api_key = x_api_key or request.query_params.get('api_key')
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise. Fournissez une clé API valide via "
                   "l'en-tête X-API-Key ou le paramètre api_key.",
        )
    
    if api_key != EXPECTED_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clé API invalide.",
        )
    
    return api_key


def require_auth(func: Callable) -> Callable:
    """Décorateur pour exiger l'authentification sur une route spécifique."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        if AUTH_ENABLED:
            # Extraire la clé de la requête
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            
            api_key = None
            if request:
                api_key = request.headers.get('X-API-Key') or request.query_params.get('api_key')
            
            if not api_key:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentification requise.",
                )
            
            if api_key != EXPECTED_API_KEY:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Clé API invalide.",
                )
        
        return await func(*args, **kwargs)
    
    return wrapper


def get_auth_status() -> dict:
    """Retourne le statut de l'authentification (pour /health)."""
    return {
        'auth_enabled': AUTH_ENABLED,
        'auth_required': AUTH_ENABLED,
    }
