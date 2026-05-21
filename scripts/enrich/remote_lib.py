"""Remote-side libraries (runs on aptekaa server itself).

Same API as match_lib + apply_lib, but uses LOCAL docker exec / cp / git
instead of SSH/SCP since this code runs ON the remote.
"""
import json, os, re, shutil, subprocess

MONGO_URI = "mongodb://aptekaa_admin:KSkYbEOOdb3nIaGZAdh7WqFQFHJbr7n1AymsdV_2U9Q@localhost:27017/aptekaa?authSource=admin"
REMOTE_DIR = "/home/ubuntu/aptekaa/frontend/public/img/meds/"
REMOTE_GIT = "/home/ubuntu/aptekaa"

FORM_PREFIXES = ("таблет|табл|капс|раствор|р-р|р/р|мазь|крем|сироп|спрей|капли|гель|"
                 "лиоф|концентрат|конц|порош|пор|суспенз|сусп|гран|эмульс|пастил|"
                 "субстанц|инъекц|инф|свеч|супп|шприц|стик|саше|пласт|пена|"
                 "имплант|вагин|глазн|ушн|драже|жидк|жев|шипуч|плёнк|пленк|желе|лак|"
                 "пакет|пак|однораз|обол|вакцин|пары|пастил")


def regex_for_trade(name, mode="strict"):
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


def _mongosh(js, timeout=180):
    cmd = ["docker", "exec", "-i", "deploy-mongo-1",
           "mongosh", MONGO_URI, "--quiet"]
    return subprocess.run(cmd, input=js, capture_output=True, text=True, timeout=timeout)


def find_db_matches_bulk(trade_names, manufacturer_pattern=None, exclude_manufacturers=None):
    """Bulk-match trade names. positive manufacturer filter or negative exclude list."""
    items = [{"name": n,
              "strict": regex_for_trade(n, "strict"),
              "loose": regex_for_trade(n, "loose")} for n in trade_names]
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
    r = _mongosh(js, timeout=180)
    m = re.search(r"===BULK_RESULT_BEGIN===\s*(.*?)\s*===BULK_RESULT_END===", r.stdout, re.S)
    if not m:
        raise RuntimeError(f"bulk match failed: {r.stdout[:400]} | {r.stderr[:300]}")
    blob = re.sub(r"^\w+>\s*", "", m.group(1), flags=re.M).strip()
    return json.loads(blob)


def bulk_update_image_urls(ops):
    if not ops:
        return {"updated": 0, "skipped": 0}
    js_ops = json.dumps(ops, ensure_ascii=False)
    js = (
        f"const ops = {js_ops};\n"
        "let updated = 0, skipped = 0;\n"
        "for (const op of ops) {\n"
        "  const r = db.medications.updateOne({slug: op.slug, image_url: {$in: [null, '', undefined]}}, {$set: {image_url: op.image_url}});\n"
        "  if (r.modifiedCount) updated++; else skipped++;\n"
        "}\n"
        "print('===UPDATE_RESULT===');\n"
        "print(JSON.stringify({updated, skipped}));\n"
    )
    r = _mongosh(js)
    m = re.search(r"===UPDATE_RESULT===\s*(?:\w+>\s*)*\s*(\{[^}]+\})", r.stdout, re.S)
    if not m:
        raise RuntimeError(f"bulk update failed: {r.stdout[:400]}")
    return json.loads(m.group(1))


def copy_files_to_dest(files):
    os.makedirs(REMOTE_DIR, exist_ok=True)
    for f in files:
        shutil.copy2(f, REMOTE_DIR)


def git_commit_push(prefix, message):
    cmd = ["bash", "-c",
           f"cd {REMOTE_GIT} && "
           f"git add frontend/public/img/meds/{prefix}*.webp 2>&1 && "
           f"(git diff --cached --quiet || git commit -m {json.dumps(message)} 2>&1 | tail -3) && "
           f"git push origin HEAD 2>&1 | tail -3"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


def apply_plan(plan, prefix, commit_msg):
    if not plan:
        print("Plan empty.")
        return
    files = [p["image_local"] for p in plan]
    print(f"[1/3] Copy {len(files)} files -> {REMOTE_DIR}")
    copy_files_to_dest(files)
    ops = []
    for p in plan:
        for slug in p["slugs"]:
            ops.append({"slug": slug, "image_url": p["image_url"]})
    print(f"[2/3] Bulk update {len(ops)} slugs")
    print(" ", bulk_update_image_urls(ops))
    print(f"[3/3] Git commit + push ({prefix})")
    print(git_commit_push(prefix, commit_msg))
