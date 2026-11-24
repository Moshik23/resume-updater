"""Login gate for the whole app (HTTP Basic Auth).

Two modes:
- Per-person logins (USERS_JSON / SSM `users`): the Basic Auth *username* is
  the profile (moshik, indhu, guest) and each has its own password. The
  signed-in profile is put on request.state.profile and every profile/job
  route is locked to it, so people can't open each other's resume or tracker.
- Legacy shared password (SITE_PASSWORD): one password for everyone; the page
  shows a profile picker and request.state.profile stays None.

Neither set (local dev) -> the gate is a no-op. /healthz is always exempt
(the deploy smoke test hits it without credentials). /logout always answers
401, which makes the browser forget the login and ask again ("switch person").

On AWS, CloudFront adds a secret x-origin-secret header to every request it
forwards. When ORIGIN_SECRET is set, requests without it (i.e. anyone calling
the Lambda function URL directly instead of going through CloudFront) are
rejected before anything else -- /healthz included.
"""

import base64
import secrets

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import settings, users

_EXCLUDED_PATHS = {"/healthz"}
_REALM = 'Basic realm="Resume Tailor", charset="UTF-8"'


def _extract_credentials(auth_header: str | None) -> tuple[str, str] | None:
    if not auth_header:
        return None
    scheme, _, credentials = auth_header.partition(" ")
    if scheme.lower() != "basic" or not credentials:
        return None
    try:
        decoded = base64.b64decode(credentials).decode("utf-8")
    except Exception:
        return None
    username, _, password = decoded.partition(":")
    return username, password


def _challenge() -> Response:
    return Response(status_code=401, headers={"WWW-Authenticate": _REALM})


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if settings.origin_secret and not secrets.compare_digest(
            request.headers.get("x-origin-secret", ""), settings.origin_secret
        ):
            return Response(status_code=403)

        request.state.profile = None
        if request.url.path in _EXCLUDED_PATHS:
            return await call_next(request)
        if request.url.path == "/logout":
            return _challenge()

        logins = users()
        if not logins and not settings.site_password:
            return await call_next(request)

        creds = _extract_credentials(request.headers.get("Authorization"))
        if creds is None:
            return _challenge()
        username, password = creds

        if logins:
            profile = username.strip().lower()
            expected = logins.get(profile)
            # compare against something even for unknown names, so timing doesn't reveal valid usernames
            if secrets.compare_digest(password, expected or secrets.token_hex(16)) and expected:
                request.state.profile = profile
                return await call_next(request)
            return _challenge()

        if secrets.compare_digest(password, settings.site_password):
            return await call_next(request)
        return _challenge()


def resolve_profile(request: Request, requested: str | None) -> str:
    """The profile a request may act as: the signed-in one, or (shared-password mode) the one it names."""
    from app import profiles

    signed_in = getattr(request.state, "profile", None)
    if signed_in:
        if requested and requested != signed_in:
            raise HTTPException(403, "You can only use your own profile")
        return signed_in
    if not requested or not profiles.is_valid_profile(requested):
        raise HTTPException(400, "Unknown profile")
    return requested
