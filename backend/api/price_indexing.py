"""Shared definition of a current, indexable pharmacy offer."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional


REAL_SOURCES = [
    "gorzdrav", "apteka366", "rigla", "maksavit", "aptechestvo",
    "zdorovie", "magnit", "farmakopeika",
]
MATCH_OK = ["matched", "mnn_match"]
AVAILABILITY_TTL_HOURS = 48


def availability_cutoff() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=AVAILABILITY_TTL_HOURS)


def indexable_pairs_pipeline(*, city: Optional[str] = None, slugs: Optional[List[str]] = None):
    match = {
        "source": {"$in": REAL_SOURCES},
        "price": {"$gt": 0},
        "stores_count": {"$gt": 0},
        "availability_observed_at": {"$gte": availability_cutoff()},
        "updated_at": {"$gte": availability_cutoff()},
        "$or": [
            {"source": {"$ne": "zdorovie"}},
            {"price_parse_version": 2},
        ],
    }
    if city:
        match["city"] = city
    if slugs is not None:
        match["slug"] = {"$in": slugs}
    return [
        {"$match": match},
        {"$lookup": {
            "from": "medications", "localField": "slug", "foreignField": "slug", "as": "med",
        }},
        {"$unwind": "$med"},
        {"$match": {
            "med.is_canonical": {"$ne": False},
            "$or": [
                {
                    "med.curated_source": "priority_medications_2026-09",
                    "match_status": "matched",
                    "identity_verified": True,
                },
                {
                    "med.curated_source": {"$ne": "priority_medications_2026-09"},
                    "match_status": {"$in": MATCH_OK},
                },
            ],
        }},
        {"$group": {
            "_id": {"city": "$city", "slug": "$slug"},
            "nets": {"$addToSet": "$source"},
            "med": {"$first": "$med"},
        }},
        {"$match": {"$expr": {"$gte": [{"$size": "$nets"}, 2]}}},
    ]
