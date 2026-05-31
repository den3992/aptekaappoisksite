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


logger = logging.getLogger("security")

JWT_ALGORITHM = "HS256"
JWT_TTL_HOURS = 8


# ---------------------------------------------------------------------------
# Admin auth.
#
# Two compatible mechanisms:
#   1. Bearer JWT in Authorization header — issued by /api/admin/login.
#      Preferred. Carries username + expiry.
#   2. X-Admin-Token header — legacy shared-secret used by partner-upload
#      IMAP integrations. Header-only (query-param приёмку убрали: токен в
#      URL утекает в логи/историю/Referer).
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
) -> None:
    """Dependency: 403 unless Bearer JWT or legacy shared-secret (header) matches."""
    # 1. Bearer JWT
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token and _verify_admin_jwt(token):
            return
    # 2. Legacy shared-secret — ТОЛЬКО через заголовок X-Admin-Token.
    #    Приёмку токена из query-параметра убрали: токен в URL утекает в
    #    access-логи nginx, историю браузера и Referer.
    expected = _expected_admin_token()
    if expected:
        candidate = x_admin_token or ""
        if candidate and secrets.compare_digest(candidate, expected):
            return
    raise HTTPException(403, "Bad admin credentials")


def verify_admin_path(path_token: str) -> None:
    """Backward-compat for old /admin/.../{token}/... paths."""
    expected = _expected_admin_token()
    if not expected or not path_token or not secrets.compare_digest(path_token, expected):
        raise HTTPException(403, "Bad admin token")
