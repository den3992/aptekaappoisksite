#!/usr/bin/env python3
"""
Compute (dedup_key, is_canonical) for every medication.

Group by (name_lower, dosage, form, brand_normalized). Within each group,
pick one canonical doc (most variants, tiebreak by earliest slug). All others
become is_canonical = False. Listings (search, suggest, sitemap, category SSR)
filter on is_canonical = True.

This script generates a JS file with bulk updates to apply via mongosh.
Idempotent: running again rewrites the same fields.
"""
import json
import re
import sys
import hashlib

# Legal-form prefixes (stripped iteratively; handles "ООО ПФК ОБНОВЛЕНИЕ" etc.)
LEGAL = re.compile(
    r"^\s*(ооо|ао|оао|зао|пао|ип|пфк|фгуп|нпп|нпо|чп|тоо|тов|унп|нпк|ткк|"
    r"ooo|jsc|ltd|llc|gmbh|inc|corp)\s*[\.,]?\s*",
    re.I,
)
# Common suffix words that are noise for brand identity.
SUFFIX = re.compile(
    r"\b(фарм|пфк|производство|групп|group|pharma|pharm|"
    r"laboratoires|laboratorios|laboratories|labs|s\.?a|holding)\b",
    re.I,
)
QUOTES = re.compile(r"[«»\"\u201c\u201d\u2018\u2019]")


def normalize_brand(m: str) -> str:
    """ "OOO ОЗОН" / "ООО ОЗОН ФАРМ" / "ООО ОЗОН" → "озон"  """
    if not m:
        return ""
    s = m.strip().lower()
    s = QUOTES.sub("", s)
    # Map common Latin→Cyrillic homoglyphs (handles "OOO ОЗОН" / "Ozon" mixed).
    # Only the most common confusables — keeps legitimate Latin brand names stable.
    s = s.translate(str.maketrans("oaec", "оаес"))
    # Iteratively strip legal-form prefix
    prev = None
    while prev != s:
        prev = s
        s = LEGAL.sub("", s).strip(" .,-")
    # Strip noise suffixes
    s = SUFFIX.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" .,-")
    return s


def dedup_key(doc: dict) -> str:
    parts = [
        (doc.get("name") or "").strip().lower(),
        (doc.get("dosage") or "").strip(),
        (doc.get("form") or "").strip(),
        normalize_brand(doc.get("manufacturer") or ""),
    ]
    raw = "|".join(parts)
    # Short stable hash — easier to index than the raw string with spaces/cyrillic
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


def main(inp_path: str, out_path: str):
    docs = []
    with open(inp_path) as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    print(f"Loaded {len(docs)} docs", file=sys.stderr)

    # Group
    groups = {}
    for d in docs:
        key = dedup_key(d)
        groups.setdefault(key, []).append(d)

    # Pick canonical per group: max(len(variants)), tiebreak by shortest slug then alpha
    canonical_slug_by_key = {}
    for key, items in groups.items():
        def score(d):
            v = len(d.get("variants") or [])
            slug = d.get("slug") or ""
            # Prefer slug without numeric suffix ("-2", "-13") — those are dedup artifacts.
            has_suffix = bool(re.search(r"-\d+$", slug))
            return (-v, has_suffix, len(slug), slug)
        winner = sorted(items, key=score)[0]
        canonical_slug_by_key[key] = winner["slug"]

    # Generate updates
    with open(out_path, "w", encoding="utf-8") as f:
        for d in docs:
            key = dedup_key(d)
            canonical = canonical_slug_by_key[key]
            is_canon = (d["slug"] == canonical)
            slug_esc = d["slug"].replace('"', '\\"')
            f.write(
                'db.medications.updateOne({slug:"%s"},{$set:{dedup_key:"%s",is_canonical:%s,canonical_slug:"%s"}});\n'
                % (slug_esc, key, "true" if is_canon else "false", canonical.replace('"', '\\"'))
            )
        f.write(f'print("applied {len(docs)} dedup-field updates");\n')
    # Stats
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    hidden = sum(len(v) - 1 for v in dup_groups.values())
    print(f"groups: {len(groups)}", file=sys.stderr)
    print(f"dup groups (≥2 docs): {len(dup_groups)}", file=sys.stderr)
    print(f"docs that will be hidden in listings: {hidden}", file=sys.stderr)
    print(f"updates written: {len(docs)} → {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
