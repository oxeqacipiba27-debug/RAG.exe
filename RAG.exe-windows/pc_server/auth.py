"""
Authentication and security middleware for PC Server remote access.
Supports:
- Optional Bearer token or X-API-Key authentication
- Public /health liveness probe option for desktop status bars (Waybar)
- Standard OpenAI 401 JSON error responses
"""

import logging
import os
from typing import Optional
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("pc_server.auth")

security_bearer = HTTPBearer(auto_error=False)


def get_configured_api_key() -> Optional[str]:
    """Retrieve API key from environment or config."""
    key = os.getenv("PC_SERVER_API_KEY", "").strip()
    return key if key else None


def allow_unauth_health() -> bool:
    """Whether /health is allowed without authentication (default: True for Waybar)."""
    val = os.getenv("PC_SERVER_ALLOW_UNAUTH_HEALTH", "true").lower()
    return val in ("true", "1", "yes")


async def verify_api_key(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer)) -> bool:
    """
    Validate incoming request against configured API key.
    If no API key is configured on server, allows all requests.
    """
    configured_key = get_configured_api_key()
    if not configured_key:
        return True

    # Check path whitelist for Waybar liveness monitoring
    path = request.url.path.rstrip("/")
    if path in ("/health", "") and allow_unauth_health():
        return True

    # 1. Bearer token in Authorization header
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()

    # 2. X-API-Key header fallback
    if not token:
        token = request.headers.get("X-API-Key", "").strip() or None

    # 3. Query parameter fallback
    if not token:
        token = request.query_params.get("api_key", "").strip() or None

    if token == configured_key:
        return True

    logger.warning(f"Unauthorized access attempt to {path} from {request.client.host if request.client else 'unknown'}")
    raise HTTPException(
        status_code=401,
        detail={
            "error": {
                "message": "Incorrect API key provided or missing Authorization header.",
                "type": "invalid_request_error",
                "param": None,
                "code": "invalid_api_key",
            }
        },
    )
