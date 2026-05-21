"""Shared library for matching scraped trade names to MongoDB medications.

Uses ONE mongosh call to perform bulk regex matching. The JS script iterates over
all input trade names and emits a JSON map { trade_name: [docs] }.
"""
import json, os, re, subprocess

SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
SSH_HOST = "ubuntu@89.169.137.36"
MONGO_URI = "mongodb://aptekaa_admin:KSkYbEOOdb3nIaGZAdh7WqFQFHJbr7n1AymsdV_2U9Q@localhost:27017/aptekaa?authSource=admin"

# Whitelist of form descriptor prefixes (lowercase, Cyrillic).
FORM_PREFIXES = ("таблет|табл|капс|раствор|р-р|р/р|мазь|крем|сироп|спрей|капли|гель|"
                 "лиоф|концентрат|конц|порош|пор|суспенз|сусп|гран|эмульс|пастил|"
                 "субстанц|инъекц|инф|свеч|супп|шприц|стик|саше|пласт|пена|"
                 "имплант|вагин|глазн|ушн|драже|жидк|жев|шипуч|плёнк|пленк|желе|лак|"
                 "пакет|пак|однораз|обол|вакцин|пары|пастил")


def regex_for_trade(name, mode="strict"):
    """Build PCRE2 pattern for matching trade name in label_name."""
    name = re.sub(r"[®™]", "", name).strip()
    parts = re.split(r"\s+", name)
    parts_esc = [re.escape(p) for p in parts if p]
    body = r"[®™]?\s+".join(parts_esc)
    tail = (f"[®™]?(\\s+({FORM_PREFIXES})"
            f"|\\s+[(\\[\"«0-9]"
            f"|[,;.\\/()\\[\\]\"«»][,;.\\/()\\[\\]\"«»\\s]*"
            f"|\\s*$)")
    if mode == "strict":
        return f"^{body}{tail}"
    return f"(^|[^А-Яа-яЁё]){body}{tail}"


def find_db_matches_bulk(trade_names, manufacturer_pattern=None, exclude_manufacturers=None):
    """Bulk-match trade names. If manufacturer_pattern is set, restrict to that
    manufacturer (positive filter). If exclude_manufacturers is set, exclude
    records whose manufacturer matches it (negative filter).
    """
    items = []
    for name in trade_names:
        items.append({
            "name": name,
            "strict": regex_for_trade(name, "strict"),
            "loose": regex_for_trade(name, "loose"),
        })
    js_items = json.dumps(items, ensure_ascii=False)
    mfg_pos = json.dumps(manufacturer_pattern) if manufacturer_pattern else "null"
    mfg_neg = json.dumps(exclude_manufacturers) if exclude_manufacturers else "null"
    js = (
        f"const items = {js_items};\n"
        f"const mfgPos = {mfg_pos};\n"
        f"const mfgNeg = {mfg_neg};\n"
        "function baseFilter() {\n"
        "  const f = {};\n"
        "  if (mfgPos) f.manufacturer = { $regex: mfgPos, $options: 'i' };\n"
        "  if (mfgNeg) {\n"
        "    if (f.manufacturer) f.manufacturer.$not = new RegExp(mfgNeg, 'i');\n"
        "    else f.manufacturer = { $not: new RegExp(mfgNeg, 'i') };\n"
        "  }\n"
        "  return f;\n"
        "}\n"
        "const out = {};\n"
        "for (const it of items) {\n"
        "  let q1 = Object.assign({ label_name: { $regex: it.strict, $options: 'i' } }, baseFilter());\n"
        "  let docs = db.medications.find(q1, { slug:1, label_name:1, image_url:1, manufacturer:1, _id:0 }).limit(50).toArray();\n"
        "  if (!docs.length) {\n"
        "    let q2 = Object.assign({ label_name: { $regex: it.loose, $options: 'i' } }, baseFilter());\n"
        "    docs = db.medications.find(q2, { slug:1, label_name:1, image_url:1, manufacturer:1, _id:0 }).limit(50).toArray();\n"
        "  }\n"
        "  out[it.name] = docs;\n"
        "}\n"
        "print('===BULK_RESULT_BEGIN===');\n"
        "print(JSON.stringify(out));\n"
        "print('===BULK_RESULT_END===');\n"
    )
    cmd = ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", SSH_HOST,
           "docker", "exec", "-i", "deploy-mongo-1", "mongosh", MONGO_URI, "--quiet"]
    r = subprocess.run(cmd, input=js, capture_output=True, text=True, timeout=180)
    text = r.stdout
    m = re.search(r"===BULK_RESULT_BEGIN===\s*(.*?)\s*===BULK_RESULT_END===", text, re.S)
    if not m:
        raise RuntimeError(f"bulk match failed; stdout={text[:500]} stderr={r.stderr[:300]}")
    blob = re.sub(r"^\w+>\s*", "", m.group(1), flags=re.M).strip()
    return json.loads(blob)
