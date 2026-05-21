#!/usr/bin/env python3
"""Match Veropharm catalog products -> medications in DB by normalised name."""
import json, os, re, subprocess

MANIFEST = "/tmp/vp_products.json"
OUT = "/tmp/vp_updates.js"
IMG_DIR_DEST = "/home/ubuntu/aptekaa/frontend/public/img/meds"

MANUFACTURER_REGEX = "ВЕРОФАРМ"
PREFIX = "vp_"


def norm(s):
    if not s: return ""
    s = s.lower().strip()
    s = s.replace("®", "").replace("™", "")
    # cyrillic 'ё' -> 'е'
    s = s.replace("ё", "е")
    # remove dosage / form / quantity hints
    s = re.sub(r"\b\d+([\.,]\d+)?\s*(мг|мл|г|мкг|ме|ед|%|таб|капс|тб)\b", "", s)
    s = re.sub(r"\bn?\d+\b", "", s)
    # remove suffix "верофарм" / "вертекс"
    s = re.sub(r"[-\s]*верофарм\s*$", "", s)
    s = re.sub(r"[-\s]*вертекс\s*$", "", s)
    # normalise punctuation
    s = re.sub(r"[®©™\.,;:]", " ", s)
    s = re.sub(r"[-_]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main():
    products = json.load(open(MANIFEST))
    print(f"products: {len(products)}")

    # 1) fetch DB cards (manufacturer ВЕРОФАРМ, canonical)
    cmd = [
        "docker","exec","deploy-mongo-1","mongoexport",
        "-u","aptekaa_admin","-p","KSkYbEOOdb3nIaGZAdh7WqFQFHJbr7n1AymsdV_2U9Q",
        "--authenticationDatabase","admin","-d","aptekaa","-c","medications",
        "--query",'{"manufacturer":{"$regex":"'+MANUFACTURER_REGEX+'"},"is_canonical":{"$ne":false}}',
        "--type","json","--fields","slug,name,form,dosage,image_url",
    ]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    meds = [json.loads(l) for l in out.strip().split("\n") if l.strip()]
    print(f"DB canonical meds ({MANUFACTURER_REGEX}): {len(meds)}")

    # 2) match
    by_norm = {}
    for p in products:
        n = norm(p.get("trade_name", ""))
        by_norm.setdefault(n, p)
        # also key on slug as fallback
        by_norm.setdefault(p["slug"].replace("-", " "), p)

    matched = []
    for m in meds:
        med_n = norm(m["name"])
        chosen = by_norm.get(med_n)
        if not chosen:
            # try substring containment (medname contains product name or vice versa)
            for pn, pv in by_norm.items():
                if not pn or len(pn) < 4: continue
                if pn in med_n or med_n in pn:
                    chosen = pv; break
        if chosen:
            matched.append({"slug": m["slug"], "image": chosen})

    print(f"Matched: {len(matched)} / {len(meds)} ({len(matched)*100//max(1,len(meds))}%)")

    # 3) prepare mongo updates JS + copy images
    seen_images = set()
    lines = []
    for it in matched:
        webp = os.path.basename(it["image"]["image_local"])
        # ensure prefix
        if not webp.startswith(PREFIX):
            webp = PREFIX + webp.lstrip("vp_").lstrip("_")
        seen_images.add(webp)
        url = f"/img/meds/{webp}"
        lines.append(f'db.medications.updateOne({{slug:{json.dumps(it["slug"])}}}, {{$set:{{image_url:{json.dumps(url)}}}}});')

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write(f'\nprint("applied " + {len(lines)} + " veropharm image updates");\n')
    print(f"[done] {len(lines)} DB updates queued | {len(seen_images)} unique webp files")
    print(f"Output: {OUT}")
    print(f"Copy: cp -n /tmp/vp_img/vp_*.webp {IMG_DIR_DEST}/")


if __name__ == "__main__":
    main()
