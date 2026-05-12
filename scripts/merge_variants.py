#!/usr/bin/env python3
"""
Merge variants from non-canonical duplicates into the canonical doc.

For each dedup_key group with ≥2 docs:
  - Collect all variants from all docs in the group
  - Dedupe by GTIN (preferred), fallback to (pack_size + label_name)
  - Sort by numeric pack_size ascending (for nicer UI chip order)
  - Write the merged array onto the canonical doc only
  - Also copy image_url to canonical if it doesn't have one but a duplicate does

Outputs /tmp/merge_variants_updates.js for mongosh.
"""
import json
import re
import sys


def numeric_head(pack: str) -> float:
    if not pack:
        return 0.0
    m = re.match(r"^(\d+(?:[\.,]\d+)?)", str(pack).strip())
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            return 0.0
    return 0.0


def variant_dedup_key(v: dict) -> str:
    gtin = (v.get("gtin") or "").strip()
    if gtin:
        return f"g:{gtin}"
    # Fallback: pack_size + label_name (covers ESKLP records w/o GTIN)
    return "p:" + (v.get("pack_size") or "").strip() + "|" + (v.get("label_name") or "").strip()


def main(inp: str, out: str):
    docs = []
    with open(inp) as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    print(f"Loaded {len(docs)} docs", file=sys.stderr)

    # Group by dedup_key
    by_key = {}
    for d in docs:
        k = d.get("dedup_key")
        if k:
            by_key.setdefault(k, []).append(d)

    updates = []
    merged_groups = 0
    extra_variants_total = 0
    img_copies = 0

    for key, group in by_key.items():
        if len(group) < 2:
            continue
        canonical = next((g for g in group if g.get("is_canonical")), None)
        if not canonical:
            continue
        # Collect all variants from group
        seen = {}  # key -> variant
        order = []
        for g in group:
            for v in g.get("variants") or []:
                vk = variant_dedup_key(v)
                if vk not in seen:
                    seen[vk] = v
                    order.append(vk)
        merged = [seen[k] for k in order]
        # Sort numerically by pack_size
        merged.sort(key=lambda v: numeric_head(v.get("pack_size")))

        original_count = len(canonical.get("variants") or [])
        if len(merged) <= original_count:
            # Nothing new
            pass
        else:
            extra_variants_total += len(merged) - original_count
            merged_groups += 1

        # Build update — escape JSON for mongosh
        variants_js = json.dumps(merged, ensure_ascii=False).replace("'", "\\'")
        update_set = {"variants_js": variants_js}

        # Copy image_url to canonical if missing
        if not canonical.get("image_url"):
            for g in group:
                img = g.get("image_url")
                if img:
                    update_set["image_url"] = img
                    img_copies += 1
                    break

        slug_esc = canonical["slug"].replace("'", "\\'")
        set_clauses = [f"variants: {variants_js}"]
        if "image_url" in update_set:
            set_clauses.append(f"image_url: {json.dumps(update_set['image_url'], ensure_ascii=False)}")
        updates.append(
            "db.medications.updateOne({slug:" + json.dumps(canonical["slug"], ensure_ascii=False)
            + "},{$set:{" + ",".join(set_clauses) + "}});"
        )

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(updates))
        f.write(f'\nprint("applied " + {len(updates)} + " variant-merge updates");\n')

    print(f"groups merged: {merged_groups}", file=sys.stderr)
    print(f"extra variants surfaced on canonical: {extra_variants_total}", file=sys.stderr)
    print(f"image_url backfills: {img_copies}", file=sys.stderr)
    print(f"updates: {len(updates)} → {out}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
