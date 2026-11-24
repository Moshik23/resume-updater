"""Shared-password gate for the whole app.

A single, shared HTTP Basic Auth password protects every route except
/healthz (which the CI/CD pipeline's post-deploy smoke test hits without
credentials). If SITE_PASSWORD isn't set (local dev), the gate is a no-op
so local development never needs a password.

On AWS, CloudFront adds a secret x-origin-secret header to every request it
forwards. When ORIGIN_SECRET is set, requests without it (i.e. anyone calling
the Lambda function URL directly instead of going through CloudFront) are
rejected before the password check -- /healthz included.
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
        if settings.origin_secret and not secrets.compare_digest(
            request.headers.get("x-origin-secret", ""), settings.origin_secret
        ):
            return Response(status_code=403)

        if not settings.site_password or request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)

        password = _extract_password(request.headers.get("Authorization"))
        if password is not None and secrets.compare_digest(password, settings.site_password):
            return await call_next(request)

        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Resume Updater"'},
        )
