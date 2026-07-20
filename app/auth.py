"""Shared-password gate for the whole app.

A single, shared HTTP Basic Auth password protects every route except
/healthz (which the CI/CD pipeline's post-deploy smoke test hits without
credentials). If SITE_PASSWORD isn't set (local dev), the gate is a no-op
so local development never needs a password.
"""

import base64
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings

_EXCLUDED_PATHS = {"/healthz"}


def _extract_password(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    scheme, _, credentials = auth_header.partition(" ")
    if scheme.lower() != "basic" or not credentials:
        return None
    try:
        decoded = base64.b64decode(credentials).decode("utf-8")
    except Exception:
        return None
    _, _, password = decoded.partition(":")
    return password


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.site_password or request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)

        password = _extract_password(request.headers.get("Authorization"))
        if password is not None and secrets.compare_digest(password, settings.site_password):
            return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Resume Updater"'},
        )
