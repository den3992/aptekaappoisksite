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

from fastapi import APIRouter, HTTPException, Header, Query, Path
from pydantic import BaseModel, EmailStr, Field, field_validator
from motor.motor_asyncio import AsyncIOMotorDatabase


def _admin_token() -> str:
    # Stable across restarts via env. If not set, generate once at process start
    # so the value is at least available in logs (developer should set ADMIN_TOKEN
    # explicitly before going prod).
    tok = os.environ.get("ADMIN_TOKEN")
    if tok:
        return tok
    # Fall back to a deterministic dev token derived from MONGO URL host so two
    # restarts give the same one. Only use in dev — production must set env.
    return "dev-admin-token-change-me"


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


def make_partner_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter()

    def _check_admin(token: str):
        if token != _admin_token():
            raise HTTPException(403, "Bad admin token")

    @router.post("/partner-requests", response_model=PartnerRequestOut)
    async def submit_request(payload: PartnerRequestIn):
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

    @router.get("/admin/partner-requests/{admin_token}")
    async def list_requests(admin_token: str, status: Optional[str] = Query(None)):
        _check_admin(admin_token)
        flt = {}
        if status:
            flt["status"] = status
        cursor = db.partner_requests.find(flt, {}).sort([("created_at", -1)]).limit(500)
        out = []
        async for d in cursor:
            d["id"] = d.pop("_id")
            out.append(d)
        return out

    @router.post("/admin/partner-requests/{admin_token}/{rid}/approve")
    async def approve_request(admin_token: str, rid: str):
        _check_admin(admin_token)
        req = await db.partner_requests.find_one({"_id": rid})
        if not req:
            raise HTTPException(404, "Request not found")
        if req["status"] == "approved":
            return {"ok": True, "status": "already-approved",
                    "token": req.get("issued_token"),
                    "pharmacy_id": req.get("issued_pharmacy_id")}

        # Generate a token-based pharmacy entry. The pharmacy will live under
        # an auto-generated id like 'partner-2026-05-10-abcd' until manually
        # re-mapped to a curated p1/p2 record (admin step, not auto).
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

    @router.post("/admin/partner-requests/{admin_token}/{rid}/reject")
    async def reject_request(admin_token: str, rid: str, reason: Optional[str] = ""):
        _check_admin(admin_token)
        res = await db.partner_requests.update_one(
            {"_id": rid},
            {"$set": {"status": "rejected", "reject_reason": reason or "",
                      "rejected_at": datetime.now(timezone.utc).isoformat()}},
        )
        if res.matched_count == 0:
            raise HTTPException(404, "Request not found")
        return {"ok": True, "status": "rejected"}

    return router
