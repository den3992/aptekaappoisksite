"""
Partner requests: pharmacies submit a contact form via the public site.
Admins approve them via a hidden /partner-admin?token=<ADMIN_TOKEN> page.
On approval, a per-pharmacy upload token is generated and returned.
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Header, Query, Path, Request, Depends, Body
from pydantic import BaseModel, EmailStr, Field, field_validator
from motor.motor_asyncio import AsyncIOMotorDatabase

from security import verify_admin, verify_password, issue_admin_jwt
import os

import time
from collections import defaultdict
_RATE_BUCKETS = defaultdict(list)


def _rate_limit_or_429(request: Request, key: str, limit: int, per_seconds: int) -> None:
    ip = request.client.host if request.client else "anon"
    bkey = f"{key}:{ip}"
    now = time.time()
    bucket = _RATE_BUCKETS[bkey]
    cutoff = now - per_seconds
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        raise HTTPException(429, "Слишком много запросов. Попробуйте позже.")
    bucket.append(now)


class PartnerRequestIn(BaseModel):
    chain: str = Field(..., min_length=1, max_length=200)
    city: Optional[str] = Field(None, max_length=120)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=40)
    count: Optional[str] = Field(None, max_length=40)
    comment: Optional[str] = Field(None, max_length=2000)

    @field_validator("chain", "city", "phone", "count", "comment", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class PartnerRequestOut(BaseModel):
    id: str
    status: str
    created_at: str


class AdminLoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=200)


def make_partner_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter()

    # ---- Admin login (username + password → JWT) ----------------------------
    @router.post("/admin/login")
    async def admin_login(payload: AdminLoginIn = Body(...), request: Request = None):
        # Rate limit: 10 attempts / 5 min per IP — nginx already enforces a
        # zone-level limit, this is a defense in depth.
        _rate_limit_or_429(request, "admin_login", limit=10, per_seconds=300)
        expected_user = os.environ.get("ADMIN_USERNAME", "")
        expected_hash = os.environ.get("ADMIN_PASSWORD_HASH", "")
        if not expected_user or not expected_hash:
            raise HTTPException(500, "Admin credentials not configured")
        # Constant-time compare for username, bcrypt verify for password
        u_ok = secrets.compare_digest(payload.username, expected_user)
        p_ok = verify_password(payload.password, expected_hash)
        if not (u_ok and p_ok):
            raise HTTPException(401, "Неверный логин или пароль")
        token, exp = issue_admin_jwt(expected_user)
        return {"token": token, "expires_at": exp.isoformat(), "username": expected_user}

    @router.post("/partner-requests", response_model=PartnerRequestOut)
    async def submit_request(request: Request, payload: PartnerRequestIn):
        _rate_limit_or_429(request, "partner_req", limit=5, per_seconds=3600)
        rid = f"pr-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"
        doc = {
            "_id": rid,
            "status": "new",  # new | approved | rejected
            "created_at": datetime.now(timezone.utc).isoformat(),
            **payload.model_dump(),
        }
        await db.partner_requests.insert_one(doc)
        await db.partner_requests.create_index([("status", 1), ("created_at", -1)])
        return PartnerRequestOut(id=rid, status="new", created_at=doc["created_at"])

    # ---- Admin endpoints -----------------------------------------------------
    # Authentication: X-Admin-Token header (verify_admin dep).
    # Legacy path-based token endpoints were removed for security — tokens in
    # URLs leak via nginx access logs, browser history and Referer headers.

    @router.get("/admin/partner-requests")
    async def list_requests(_: None = Depends(verify_admin), status: Optional[str] = Query(None)):
        flt = {}
        if status:
            flt["status"] = status
        cursor = db.partner_requests.find(flt, {}).sort([("created_at", -1)]).limit(500)
        out = []
        async for d in cursor:
            d["id"] = d.pop("_id")
            out.append(d)
        return out

    @router.post("/admin/partner-requests/{rid}/approve")
    async def approve_request(rid: str, _: None = Depends(verify_admin)):
        req = await db.partner_requests.find_one({"_id": rid})
        if not req:
            raise HTTPException(404, "Request not found")
        if req["status"] == "approved":
            return {"ok": True, "status": "already-approved",
                    "token": req.get("issued_token"),
                    "pharmacy_id": req.get("issued_pharmacy_id")}

        pharmacy_id = f"partner-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{secrets.token_hex(3)}"
        upload_token = secrets.token_urlsafe(24)
        await db.pharmacy_tokens.insert_one({
            "pharmacy_id": pharmacy_id,
            "pharmacy_name": req["chain"],
            "city": req.get("city"),
            "chain": req["chain"],
            "token": upload_token,
            "active": True,
            "allowed_emails": [req["email"].lower()],
            "created_from_request": rid,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.partner_requests.update_one(
            {"_id": rid},
            {"$set": {
                "status": "approved",
                "issued_token": upload_token,
                "issued_pharmacy_id": pharmacy_id,
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        return {"ok": True, "status": "approved",
                "token": upload_token, "pharmacy_id": pharmacy_id}

    @router.post("/admin/partner-requests/{rid}/reject")
    async def reject_request(rid: str, reason: Optional[str] = "", _: None = Depends(verify_admin)):
        res = await db.partner_requests.update_one(
            {"_id": rid},
            {"$set": {"status": "rejected", "reject_reason": reason or "",
                      "rejected_at": datetime.now(timezone.utc).isoformat()}},
        )
        if res.matched_count == 0:
            raise HTTPException(404, "Request not found")
        return {"ok": True, "status": "rejected"}

    return router
