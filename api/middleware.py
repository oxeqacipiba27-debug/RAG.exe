"""
schoolX/api/middleware.py — Middleware аутентификации, логирования и обработки ошибок.
"""

import os
import time
import logging
from typing import Optional
from fastapi import Request, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("RAGApiMiddleware")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
http_bearer = HTTPBearer(auto_error=False)


def get_configured_api_key() -> Optional[str]:
    """Возвращает настроенный API-ключ из окружения."""
    key = os.getenv("RAG_API_KEY", "").strip()
    return key if key else None


async def verify_api_key(
    request: Request,
    api_key_header_val: Optional[str] = Security(api_key_header),
    bearer_token: Optional[HTTPAuthorizationCredentials] = Security(http_bearer),
) -> None:
    """Зависимость проверки API-ключа.
    
    Если RAG_API_KEY не задан в .env, проверка пропускается (открытый доступ для локальной сети).
    Если задан — сверяет X-API-Key или Bearer токен.
    """
    configured_key = get_configured_api_key()
    if not configured_key:
        return

    # Разрешаем запросы к health check и документации без ключа
    path = request.url.path
    if path in ("/health", "/api/v1/health", "/docs", "/openapi.json", "/redoc"):
        return

    provided_key = None
    if api_key_header_val:
        provided_key = api_key_header_val.strip()
    elif bearer_token:
        provided_key = bearer_token.credentials.strip()

    if not provided_key or provided_key != configured_key:
        logger.warning(f"Unauthorized access attempt to {path} from {request.client.host if request.client else 'unknown'}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный или отсутствующий API-ключ (X-API-Key или Bearer токен)."
        )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Логирование всех входящих запросов с замером времени выполнения."""

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000
            logger.info(f"{request.method} {path} | Status: {response.status_code} | Client: {client_ip} | {duration_ms:.1f}ms")
            return response
        except Exception as exc:
            duration_ms = (time.time() - start_time) * 1000
            logger.exception(f"Unhandled exception in {request.method} {path} after {duration_ms:.1f}ms: {exc}")
            return JSONResponse(
                status_code=500,
                content={
                    "error": "InternalServerError",
                    "detail": "Внутренняя ошибка сервиса RAG при обработке запроса.",
                    "status_code": 500
                }
            )
