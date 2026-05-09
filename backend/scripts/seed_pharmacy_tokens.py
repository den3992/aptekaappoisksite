"""
Seed pharmacy upload tokens. Idempotent — re-running keeps existing tokens.

Usage:
    python -m scripts.seed_pharmacy_tokens
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# Three demo pharmacy partners. The token is generated once and printed
# so you can share it with the partner. Re-running this script does NOT
# rotate existing tokens (so the partner's link keeps working).
PARTNERS = [
    {"pharmacy_id": "p1", "pharmacy_name": "Аптека «Здоровье»", "city": "msk", "chain": "Здоровье"},
    {"pharmacy_id": "p2", "pharmacy_name": "Аптека «36,6»", "city": "msk", "chain": "36,6"},
    {"pharmacy_id": "p13", "pharmacy_name": "Аптека «Первая помощь»", "city": "spb", "chain": "Первая помощь"},
]


def main():
    client = MongoClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    print(f"→ Seeding pharmacy_tokens in {os.environ['DB_NAME']}")
    db.pharmacy_tokens.create_index([("token", 1)], unique=True)
    db.pharmacy_tokens.create_index([("pharmacy_id", 1)], unique=True)

    for p in PARTNERS:
        existing = db.pharmacy_tokens.find_one({"pharmacy_id": p["pharmacy_id"]})
        if existing:
            print(f"  · {p['pharmacy_name']:30} → token: {existing['token']}  (kept)")
            continue
        token = secrets.token_urlsafe(24)
        db.pharmacy_tokens.insert_one({**p, "token": token, "active": True})
        print(f"  · {p['pharmacy_name']:30} → token: {token}  (NEW)")

    print()
    print("Partner upload URL pattern (hidden, not linked from main site):")
    print("  https://aptekaa.ru/partner-upload?token=<TOKEN>")


if __name__ == "__main__":
    main()
