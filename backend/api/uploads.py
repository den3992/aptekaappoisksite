"""
Pharmacy price-list ingestion: parser + REST endpoints.

Accepts XLSX or CSV files with the canonical column set:
    gtin, name, qty, price          (required)
    pharmacy_id, expiry_date         (optional)

English and Russian column names are both accepted (case- and whitespace-
insensitive). Each row is validated, looked up against `medications_raw`
by GTIN, and either:
    • inserted into `prices` (matched by GTIN), or
    • parked in `unmatched_items` for manual review.

Auth: simple per-pharmacy token (`pharmacy_tokens` collection).
The upload page lives at a hidden route on the frontend and is NOT linked
from the main site. Tokens are created with the seed script.
"""
from __future__ import annotations

import csv
import io
import os
import re
import uuid
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any, Tuple

import openpyxl
from fastapi import APIRouter, HTTPException, UploadFile, File, Path, Request
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase

import time
from collections import defaultdict
_RATE_BUCKETS: Dict[str, List[float]] = defaultdict(list)


async def _rate_limit_or_403(request: Request, key: str, limit: int, per_seconds: int) -> None:
    now = time.time()
    bucket = _RATE_BUCKETS[key]
    cutoff = now - per_seconds
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        raise HTTPException(429, "Слишком много загрузок, попробуйте позже")
    bucket.append(now)


# ---------- Column header normalization ----------
# Multiple synonyms per canonical column. Comparison is normalized
# (lowercase, no punctuation, ru→en transliteration not needed since we
# match the original Cyrillic).
HEADER_ALIASES = {
    "gtin": [
        "gtin", "штрихкод", "штрих-код", "штрих код", "barcode", "ean",
        "штрихкод gtin", "код товара",
    ],
    "name": [
        "name", "название", "наименование", "товар", "наименование товара",
        "название препарата", "препарат",
    ],
    "qty": [
        "qty", "quantity", "количество", "кол-во", "колво", "остаток", "остатки",
        "наличие", "stock", "запас",
    ],
    "price": [
        "price", "цена", "стоимость", "цена руб", "цена, руб", "цена ₽", "rrp",
    ],
    "pharmacy_id": [
        "pharmacy_id", "код аптеки", "id аптеки", "магазин", "точка",
        "branch_id", "shop_id", "store_id",
    ],
    "expiry_date": [
        "expiry_date", "срок годности", "годен до", "expires", "expiry",
        "valid_until", "valid until",
    ],
}


def _norm_header(s: Any) -> str:
    if s is None:
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"[\s\-_,./()]+", " ", s)
    return s.strip()


def _build_header_map(headers: List[Any]) -> Dict[str, int]:
    """Return mapping {canonical_col: column_index} based on aliases."""
    norm_headers = [_norm_header(h) for h in headers]
    out: Dict[str, int] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        normalized_aliases = [_norm_header(a) for a in aliases]
        for idx, h in enumerate(norm_headers):
            if h in normalized_aliases:
                out[canonical] = idx
                break
    return out


# ---------- Cell parsers ----------

def _to_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _to_int_qty(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", ".").replace(" ", ""))
        if f < 0:
            return None
        return int(round(f))
    except Exception:
        return None


def _to_float_price(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        s = str(v).replace(",", ".").replace(" ", "").replace("₽", "").replace("руб", "")
        f = float(s)
        if f <= 0:
            return None
        return round(f, 2)
    except Exception:
        return None


_GTIN_RE = re.compile(r"^\d{8}$|^\d{12}$|^\d{13}$|^\d{14}$")


def _normalize_gtin(v: Any) -> Optional[str]:
    if v is None:
        return None
    raw = re.sub(r"\D+", "", str(v))
    if not raw:
        return None
    # Pad short codes to 13 (EAN-13) when feasible
    if len(raw) in (8, 12, 13, 14):
        return raw
    if len(raw) < 8:
        return None
    return raw  # let downstream lookup decide


def _parse_expiry(v: Any) -> Optional[str]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    # Try common formats
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%m/%Y", "%m.%Y", "%Y-%m"):
        try:
            d = datetime.strptime(s, fmt)
            return d.date().isoformat()
        except ValueError:
            continue
    return None


# ---------- File readers ----------

def read_xlsx_rows(content: bytes) -> Tuple[List[Any], List[List[Any]]]:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = []
    for r in ws.iter_rows(values_only=True):
        rows.append(list(r))
    wb.close()
    if not rows:
        return [], []
    return rows[0], rows[1:]


def read_csv_rows(content: bytes) -> Tuple[List[Any], List[List[Any]]]:
    # Try UTF-8 then cp1251 (legacy Russian)
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(400, "Не удалось определить кодировку CSV (поддерживается UTF-8 и Windows-1251)")
    # Sniff delimiter
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


# ---------- Core parsing ----------

class ParsedRow(BaseModel):
    row_num: int
    gtin: Optional[str] = None
    name: Optional[str] = None
    qty: Optional[int] = None
    price: Optional[float] = None
    pharmacy_id: Optional[str] = None
    expiry_date: Optional[str] = None
    error: Optional[str] = None


class ParseSummary(BaseModel):
    total_rows: int
    valid_rows: int
    invalid_rows: int
    matched: int
    unmatched: int


def parse_file(filename: str, content: bytes) -> Tuple[Dict[str, int], List[ParsedRow]]:
    """Parse a price-list file and return (header_map, parsed_rows).

    header_map indicates which canonical columns we managed to identify.
    Each parsed row carries either real values or an `error` describing why
    it cannot be processed.
    """
    name_lower = filename.lower()
    if name_lower.endswith(".xlsx"):
        header, data_rows = read_xlsx_rows(content)
    elif name_lower.endswith(".csv"):
        header, data_rows = read_csv_rows(content)
    else:
        raise HTTPException(400, "Поддерживаются форматы XLSX и CSV")

    if not header:
        raise HTTPException(400, "Файл пуст")

    hmap = _build_header_map(header)
    required = ("gtin", "name", "qty", "price")
    missing = [c for c in required if c not in hmap]
    if missing:
        raise HTTPException(
            400,
            f"В файле не найдены обязательные колонки: {', '.join(missing)}. "
            "Допустимы английские (gtin, name, qty, price) или русские "
            "(штрихкод, название, количество, цена) заголовки."
        )

    parsed: List[ParsedRow] = []
    for i, row in enumerate(data_rows, start=2):  # +2 because row 1 is header
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue
        gtin = _normalize_gtin(row[hmap["gtin"]] if hmap["gtin"] < len(row) else None)
        name = _to_str(row[hmap["name"]] if hmap["name"] < len(row) else None)
        qty = _to_int_qty(row[hmap["qty"]] if hmap["qty"] < len(row) else None)
        price = _to_float_price(row[hmap["price"]] if hmap["price"] < len(row) else None)
        pharmacy_id = _to_str(row[hmap["pharmacy_id"]]) if "pharmacy_id" in hmap and hmap["pharmacy_id"] < len(row) else None
        expiry = _parse_expiry(row[hmap["expiry_date"]]) if "expiry_date" in hmap and hmap["expiry_date"] < len(row) else None

        err = None
        if not gtin:
            err = "Отсутствует или некорректный штрихкод"
        elif not name:
            err = "Отсутствует название"
        elif qty is None:
            err = "Некорректное количество"
        elif price is None:
            err = "Некорректная цена"

        parsed.append(ParsedRow(
            row_num=i, gtin=gtin, name=name, qty=qty, price=price,
            pharmacy_id=pharmacy_id, expiry_date=expiry, error=err,
        ))

    return hmap, parsed


# ---------- Router ----------

class UploadResponse(BaseModel):
    upload_id: str
    pharmacy_id: str
    pharmacy_name: str
    summary: ParseSummary
    sample_errors: List[ParsedRow]
    sample_unmatched: List[ParsedRow]


def make_uploads_router(db: AsyncIOMotorDatabase) -> APIRouter:
    router = APIRouter()

    async def _resolve_token(token: str) -> Dict[str, Any]:
        rec = await db.pharmacy_tokens.find_one({"token": token, "active": True}, {"_id": 0})
        if not rec:
            raise HTTPException(403, "Недействительный или отключённый токен")
        return rec

    @router.get("/me/{token}")
    async def me(token: str):
        rec = await _resolve_token(token)
        # Surface only what the partner page needs.
        return {
            "pharmacy_id": rec["pharmacy_id"],
            "pharmacy_name": rec.get("pharmacy_name", rec["pharmacy_id"]),
            "city": rec.get("city"),
            "chain": rec.get("chain"),
        }

    @router.post("/prices/{token}", response_model=UploadResponse)
    async def upload_prices(request: Request, token: str, file: UploadFile = File(...)):
        # Rate-limit manually (slowapi decorator conflicts with UploadFile signature)
        await _rate_limit_or_403(request, key=f"upload:{token}", limit=10, per_seconds=3600)
        rec = await _resolve_token(token)
        pharmacy_id = rec["pharmacy_id"]

        # Sanitize filename — strip path components, keep only the basename
        safe_name = os.path.basename(file.filename or "")
        if not safe_name or not re.fullmatch(r"[\w\-. \(\)А-Яа-яЁё]{1,200}\.(xlsx|csv)", safe_name, re.IGNORECASE):
            raise HTTPException(400, "Имя файла содержит недопустимые символы или неверное расширение")

        content = await file.read()
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(413, "Размер файла больше 25 МБ")
        if not content:
            raise HTTPException(400, "Пустой файл")

        hmap, rows = parse_file(safe_name, content)

        valid_rows = [r for r in rows if not r.error]
        invalid_rows = [r for r in rows if r.error]

        # Match against known GTINs
        gtins = list({r.gtin for r in valid_rows if r.gtin})
        gtin_to_slug: Dict[str, str] = {}
        if gtins:
            cursor = db.medications_raw.find(
                {"gtin": {"$in": gtins}},
                {"_id": 0, "gtin": 1, "trade_name": 1, "manufacturer": 1, "dosage_std": 1, "form_std": 1},
            )
            raw_records = {d["gtin"]: d async for d in cursor if d.get("gtin")}
            if raw_records:
                rt = list(raw_records.keys())
                cards = db.medications.find(
                    {"variants.gtin": {"$in": rt}},
                    {"_id": 0, "slug": 1, "variants": 1},
                )
                async for c in cards:
                    slug = c["slug"]
                    for v in c.get("variants", []):
                        g = v.get("gtin")
                        if g in rt:
                            gtin_to_slug[g] = slug

        # Generate a sub-second unique upload id (uuid suffix prevents collisions
        # when a partner uploads two files within the same second).
        upload_id = (
            f"up-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            f"-{pharmacy_id}-{uuid.uuid4().hex[:8]}"
        )
        now = datetime.now(timezone.utc).isoformat()

        # Persist prices (matched) and unmatched (manual review)
        matched_docs = []
        unmatched_docs = []
        for r in valid_rows:
            slug = gtin_to_slug.get(r.gtin)
            base = {
                "pharmacy_id": pharmacy_id,
                "gtin": r.gtin,
                "name_in_file": r.name,
                "qty": r.qty,
                "price": r.price,
                "expiry_date": r.expiry_date,
                "branch_id": r.pharmacy_id,
                "upload_id": upload_id,
                "uploaded_at": now,
            }
            if slug:
                matched_docs.append({**base, "slug": slug})
            else:
                unmatched_docs.append(base)

        # Clear stale unmatched rows for this pharmacy & GTINs being re-uploaded
        # so the "Требуют разбора" tab does not accumulate duplicates after
        # partial re-uploads.
        if unmatched_docs:
            await db.unmatched_items.delete_many({
                "pharmacy_id": pharmacy_id,
                "gtin": {"$in": [d["gtin"] for d in unmatched_docs]},
            })
            await db.unmatched_items.insert_many(unmatched_docs, ordered=False)

        if matched_docs:
            # Replace prices for this pharmacy & gtin pair (latest upload wins)
            for doc in matched_docs:
                await db.prices.update_one(
                    {"pharmacy_id": doc["pharmacy_id"], "gtin": doc["gtin"]},
                    {"$set": doc},
                    upsert=True,
                )
            # If a previously-unmatched GTIN now matches (mdlp updated), remove it
            await db.unmatched_items.delete_many({
                "pharmacy_id": pharmacy_id,
                "gtin": {"$in": [d["gtin"] for d in matched_docs]},
            })

        # Persist upload meta
        await db.pharmacy_uploads.insert_one({
            "_id": upload_id,
            "pharmacy_id": pharmacy_id,
            "filename": safe_name,
            "size": len(content),
            "uploaded_at": now,
            "summary": {
                "total_rows": len(rows),
                "valid_rows": len(valid_rows),
                "invalid_rows": len(invalid_rows),
                "matched": len(matched_docs),
                "unmatched": len(unmatched_docs),
            },
        })

        # Ensure indexes (idempotent)
        await db.prices.create_index([("pharmacy_id", 1), ("gtin", 1)], unique=True)
        await db.prices.create_index([("slug", 1)])
        await db.unmatched_items.create_index([("upload_id", 1)])

        return UploadResponse(
            upload_id=upload_id,
            pharmacy_id=pharmacy_id,
            pharmacy_name=rec.get("pharmacy_name", pharmacy_id),
            summary=ParseSummary(
                total_rows=len(rows),
                valid_rows=len(valid_rows),
                invalid_rows=len(invalid_rows),
                matched=len(matched_docs),
                unmatched=len(unmatched_docs),
            ),
            sample_errors=invalid_rows[:20],
            sample_unmatched=[ParsedRow(
                row_num=0, gtin=u["gtin"], name=u["name_in_file"],
                qty=u["qty"], price=u["price"]
            ) for u in unmatched_docs[:20]],
        )

    @router.get("/history/{token}")
    async def history(token: str, limit: int = 20):
        rec = await _resolve_token(token)
        cursor = db.pharmacy_uploads.find(
            {"pharmacy_id": rec["pharmacy_id"]},
            {"_id": 1, "filename": 1, "size": 1, "uploaded_at": 1, "summary": 1},
        ).sort([("uploaded_at", -1)]).limit(limit)
        out = []
        async for d in cursor:
            d["upload_id"] = d.pop("_id")
            out.append(d)
        return out

    @router.get("/unmatched/{token}")
    async def unmatched(token: str, limit: int = 100):
        rec = await _resolve_token(token)
        cursor = db.unmatched_items.find(
            {"pharmacy_id": rec["pharmacy_id"]},
            {"_id": 0},
        ).sort([("uploaded_at", -1)]).limit(limit)
        return [d async for d in cursor]

    return router
