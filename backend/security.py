"""
Security: security headers + admin auth helper (constant-time, header-based).
"""
from __future__ import annotations

import os
import secrets
import logging
from typing import Optional

from fastapi import HTTPException, Request, Header
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


logger = logging.getLogger("security")


# ---------------------------------------------------------------------------
# Admin token — constant-time comparison + read from header OR query string
# (URL path is no longer the primary place; backward-compat preserved for
# existing admin endpoints during transition).
# ---------------------------------------------------------------------------
def _expected_admin_token() -> str:
    return os.environ.get("ADMIN_TOKEN", "")


def verify_admin(x_admin_token: Optional[str] = Header(default=None),
                 token_query: Optional[str] = None) -> None:
    """Dependency: 403 if neither header nor query token matches."""
    expected = _expected_admin_token()
    if not expected:
        raise HTTPException(500, "Admin token not configured on the server")
    candidate = x_admin_token or token_query or ""
    if not candidate or not secrets.compare_digest(candidate, expected):
        raise HTTPException(403, "Bad admin token")


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
