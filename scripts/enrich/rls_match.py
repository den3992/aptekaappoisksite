#!/usr/bin/env python3
"""Match scraped RLS products to MongoDB medications by label_name prefix.

For each RLS product, find DB records where label_name starts with the trade name
(case-insensitive, ®/™ stripped). Output two artifacts:
  /tmp/rls_match_plan.json   - list of {rls_id, image_path, slugs:[...]}
  /tmp/rls_match.log         - human-readable summary

This runs on the REMOTE server via docker exec mongosh, so it must be invoked from
the local container with the SSH key. The plan is then executed by rls_apply.sh.
"""
import json, os, re, subprocess

MANIFEST = "/tmp/rls_products.json"
PLAN = "/tmp/rls_match_plan.json"
LOG = "/tmp/rls_match.log"
SSH = ["ssh", "-i", os.path.expanduser("~/.ssh/id_ed25519"), "-o", "StrictHostKeyChecking=no",
       "ubuntu@89.169.137.36"]
MONGO_URI = "mongodb://aptekaa_admin:KSkYbEOOdb3nIaGZAdh7WqFQFHJbr7n1AymsdV_2U9Q@localhost:27017/aptekaa?authSource=admin"


def normalize_trade(s):
    s = re.sub(r"[®™]", "", s)
    s = s.strip()
    return s


def regex_for_trade(name, mode="strict"):
    """Build regex pattern for matching trade name in label_name.

    The match requires what follows the trade name to be:
      - end of string, comma, semicolon, dot, slash, parenthesis
      - ® or ™
      - whitespace followed by a *lowercase* Cyrillic letter (form descriptor
        like "таблетки", "раствор", "капсулы")
    This rejects sub-brands (capitalized words like "Микро", "Стронг", "Форте").

    mode='strict' : prefix-anchored
    mode='loose'  : trade may appear anywhere preceded by non-letter
    """
    parts = re.split(r"\s+", name.strip())
    parts_esc = [re.escape(p) for p in parts if p]
    body = r"[®™]?\s+".join(parts_esc)
    # Tail: must end the brand "phrase" with a known pharmaceutical form descriptor,
    # punctuation, or end-of-string. We deliberately whitelist form prefixes (lowercase)
    # instead of [а-яё] because mongosh regex with $options:"i" treats [а-яё] as
    # case-insensitive (which would also match uppercase sub-brands like Стронг/Микро/Лонг).
    forms = ("таблет|табл|капс|раствор|р-р|р/р|мазь|крем|сироп|спрей|капли|гель|"
             "лиоф|концентрат|конц|порош|пор|суспенз|сусп|гран|эмульс|пастил|"
             "субстанц|инъекц|инф|свеч|супп|шприц|стик|саше|пласт|пены|пена|"
             "имплант|вагин|глазн|ушн|драже|жидк|жев|шипуч|плёнк|пленк|желе|лак|"
             "пакет|пак|разовая|однораз|обол|пакет|нумер|вакцин|концентр")
    # Tail: end of brand "phrase".
    # Accept:
    #   - ® or ™ optional
    #   - then form descriptor (whitelist lowercase prefix)
    #   - OR space + opening paren / bracket / quote / digit (dosage info)
    #   - OR direct punctuation
    #   - OR end of string
    tail = (f"[®™]?(\\s+({forms})"
            f"|\\s+[(\\[\"«0-9]"
            f"|[,;.\\/()\\[\\]\"«»][,;.\\/()\\[\\]\"«»\\s]*"
            f"|\\s*$)")
    if mode == "strict":
        return f"^{body}{tail}"
    return f"(^|[^А-Яа-яЁё]){body}{tail}"


def find_db_matches(trade_name):
    """Try strict prefix match first, then loose anywhere match if needed."""
    for mode in ("strict", "loose"):
        pattern = regex_for_trade(trade_name, mode=mode)
        js = (
            'const cur = db.medications.find('
            '{ label_name: { $regex: ' + json.dumps(pattern, ensure_ascii=False) + ', $options: "i" } },'
            '{ slug:1, label_name:1, form:1, dosage:1, image_url:1, _id:0 }'
            ').limit(50);\n'
            'print(JSON.stringify(cur.toArray()));\n'
        )
        cmd = SSH + ["docker", "exec", "-i", "deploy-mongo-1",
                     "mongosh", MONGO_URI, "--quiet"]
        try:
            r = subprocess.run(cmd, input=js, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            continue
        out = r.stdout
        out = re.sub(r"^\w+>\s*", "", out, flags=re.MULTILINE)
        for line in reversed(out.strip().splitlines()):
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                try:
                    data = json.loads(line)
                except Exception:
                    data = None
                if data:
                    return data
                break
    return []


def main():
    products = json.load(open(MANIFEST))
    products = [p for p in products if p.get("image_local")]
    print(f"products with images: {len(products)}")
    plan = []
    log_lines = []
    for p in products:
        trade = normalize_trade(p["trade_name"])
        matches = find_db_matches(trade)
        # Filter: skip records that already have image_url
        match_slugs = [m["slug"] for m in matches if not m.get("image_url")]
        already = [m["slug"] for m in matches if m.get("image_url")]
        log_lines.append(f"[{p['rls_id']}] '{trade}' -> matches={len(matches)} new={len(match_slugs)} already={len(already)}")
        if matches and not match_slugs:
            log_lines.append(f"   (all already have images)")
        for m in matches[:5]:
            log_lines.append(f"     - {m['slug']}  label='{m.get('label_name','')[:80]}'")
        if match_slugs:
            plan.append({
                "rls_id": p["rls_id"],
                "trade": trade,
                "image_local": p["image_local"],
                "image_remote_name": f"rls_{p['rls_id']}.webp",
                "image_url": f"/img/meds/rls_{p['rls_id']}.webp",
                "slugs": match_slugs,
            })
    json.dump(plan, open(PLAN, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    open(LOG, "w", encoding="utf-8").write("\n".join(log_lines))
    total_slugs = sum(len(p["slugs"]) for p in plan)
    print(f"plan: {len(plan)} products, {total_slugs} slugs to update")
    print(f"log: {LOG}")


if __name__ == "__main__":
    main()
