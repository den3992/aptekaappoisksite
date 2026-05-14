"""
Security: security headers + admin auth helper (constant-time, header-based).
"""
from __future__ import annotations

import os
import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import HTTPException, Request, Header
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


logger = logging.getLogger("security")

JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = 8


# ---------------------------------------------------------------------------
# Admin auth.
#
# Two compatible mechanisms:
#   1. Bearer JWT in Authorization header — issued by /api/admin/login.
#      Preferred. Carries username + expiry.
#   2. X-Admin-Token header / `token_query` — legacy shared-secret used by
#      partner-upload IMAP integrations. Kept active during migration.
# ---------------------------------------------------------------------------
def _expected_admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", "")


def _jwt_secret() -> str:
    s = os.environ.get("JWT_SECRET", "")
    if not s:
        raise HTTPException(500, "JWT secret not configured on the server")
    return s


def _admin_username() -> str:
    return os.environ.get("ADMIN_USERNAME", "")


def _admin_password_hash() -> str:
    return os.environ.get("ADMIN_PASSWORD_HASH", "")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def issue_admin_jwt(username: str) -> tuple[str, datetime]:
    """Create signed JWT for an admin session. Returns (token, expires_at)."""
    expires_at = datetime.now(timezone.utc) + timedelta(hours=JWT_TTL_HOURS)
    payload = {
        "sub": username,
        "role": "admin",
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, expires_at


def _verify_admin_jwt(token: str) -> bool:
    try:
        payload = jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return False
    except jwt.InvalidTokenError:
        return False
    expected_user = _admin_username()
    if payload.get("role") != "admin":
        return False
    if expected_user and payload.get("sub") != expected_user:
        return False
    return True


def verify_admin(
    authorization: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
    token_query: Optional[str] = None,
) -> None:
    """Dependency: 403 unless Bearer JWT or legacy shared-secret matches."""
    # 1. Bearer JWT
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token and _verify_admin_jwt(token):
            return
    # 2. Legacy shared-secret header / query
    expected = _expected_admin_token()
    if expected:
        candidate = x_admin_token or token_query or ""
        if candidate and secrets.compare_digest(candidate, expected):
            return
    raise HTTPException(403, "Bad admin credentials")


def verify_admin_path(path_token: str) -> None:
    """Backward-compat for old /admin/.../{token}/... paths."""
    expected = _expected_admin_token()
    if not expected or not path_token or not secrets.compare_digest(path_token, expected):
        raise HTTPException(403, "Bad admin token")


# ---------------------------------------------------------------------------
# Security headers middleware. Applied to every response.
#
# CSP is intentionally permissive towards Yandex (maps + speechkit), our own
# cdn.jsdelivr and inline styles emitted by SSR for crawlers. Tighten further
# once we move all third-party scripts to a known list of hosts.
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        # Block clickjacking
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        # MIME-sniffing protection
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Referrer leak control
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Permissions: block legacy features we never use
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(self), microphone=(self), camera=(), payment=()",
        )
        # Force HTTPS for one year (only meaningful behind TLS proxy)
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
        # Content Security Policy — relaxed for SSR HTML and Yandex Maps/SpeechKit
        if not response.headers.get("Content-Security-Policy"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://api-maps.yandex.ru https://*.yandex.ru https://*.yandex.net; "
                "style-src 'self' 'unsafe-inline' https://*.yandex.ru https://*.yandex.net; "
                "img-src 'self' data: blob: https://*.yandex.ru https://*.yandex.net "
                "https://customer-assets.emergentagent.com; "
                "font-src 'self' data: https://*.yandex.ru https://*.yandex.net; "
                "connect-src 'self' https://*.yandex.ru https://*.yandex.net "
                "https://tts.api.cloud.yandex.net wss:; "
                "frame-src 'self' https://yandex.ru https://*.yandex.ru; "
                "media-src 'self' data: blob: https://*.yandex.net; "
                "object-src 'none'; base-uri 'self'; form-action 'self';"
            )
        return response
