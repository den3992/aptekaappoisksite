#!/usr/bin/env python3
"""Vertex round 2: probe direct /products/<slug>/ URLs for each med name in DB
that has manufacturer=ВЕРТЕКС and no image_url. Uses transliterated name."""
import json, os, re, subprocess, time, urllib.parse, urllib.request

UA = "Mozilla/5.0 (compatible; AptekaA-image-bot/1.0; +https://aptekaa.ru)"
HOST = "https://vertex.spb.ru"
IMG_DIR = "/tmp/vx_img"
MANIFEST_EXISTING = "/tmp/vx_products.json"
MANIFEST_NEW = "/tmp/vx_products_round2.json"

# Simple Russian -> latin (mirroring slugger used by aptekaa)
TR = {
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"yo","ж":"zh","з":"z",
    "и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r",
    "с":"s","т":"t","у":"u","ф":"f","х":"kh","ц":"ts","ч":"ch","ш":"sh","щ":"shch",
    "ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
}

def translit(s):
    s = (s or "").lower()
    out = []
    for ch in s:
        out.append(TR.get(ch, ch))
    s = "".join(out)
    # remove non [a-z0-9-] -> dashes, collapse
    s = re.sub(r"[^a-z0-9-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s

def candidate_slugs(name):
    """Generate candidate /products/<slug>/ for a given drug name."""
    n = re.sub(r"[®™]", "", name or "").strip()
    # variants without "Вертекс" suffix
    bases = set()
    base = re.sub(r"\s*[-–\s]*вертекс\s*$", "", n, flags=re.I).strip()
    bases.add(n)
    if base and base != n:
        bases.add(base)
    # also full lowercase translit forms
    cands = set()
    for b in bases:
        s = translit(b)
        cands.add(s)
        # version with -vertex
        if "vertex" not in s:
            cands.add(s + "-vertex")
    # drop empties
    return [c for c in cands if c and c != "-"]

def http_get(url, binary=False, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read() if binary else r.read().decode("utf-8", "replace")


def main():
    os.makedirs(IMG_DIR, exist_ok=True)

    # 1) load list of missing-image med names (canonical, manufacturer ВЕРТЕКС)
    cmd = [
        "docker","exec","deploy-mongo-1","mongoexport",
        "-u","aptekaa_admin","-p","KSkYbEOOdb3nIaGZAdh7WqFQFHJbr7n1AymsdV_2U9Q",
        "--authenticationDatabase","admin","-d","aptekaa","-c","medications",
        "--query",'{"manufacturer":{"$regex":"ВЕРТЕКС"},"is_canonical":{"$ne":false},'
                  '"$or":[{"image_url":{"$exists":false}},{"image_url":null},{"image_url":""}]}',
        "--type","json","--fields","slug,name,form,dosage",
    ]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    meds = [json.loads(l) for l in out.strip().split("\n") if l.strip()]
    print(f"meds missing image: {len(meds)}")

    # unique names
    names = sorted(set(m["name"] for m in meds))
    print(f"unique names: {len(names)}")

    # already-scraped products
    existing = set()
    if os.path.exists(MANIFEST_EXISTING):
        for p in json.load(open(MANIFEST_EXISTING)):
            existing.add(p["slug"])

    found = []
    seen_slugs = set()
    for i, name in enumerate(names, 1):
        for cand in candidate_slugs(name):
            if cand in existing or cand in seen_slugs:
                continue
            url = f"{HOST}/products/{cand}/"
            try:
                html = http_get(url)
            except urllib.error.HTTPError as e:
                continue
            except Exception as e:
                print(f"  [{i}/{len(names)}] {name!r}: {e!s:.80}")
                continue
            # extract og:image
            m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html)
            mt = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
            if not m:
                continue
            img_url = m.group(1)
            if "logo" in img_url.lower() or "default" in img_url.lower():
                continue
            ext = os.path.splitext(img_url)[1].lower().lstrip(".") or "jpg"
            tmp_src = f"{IMG_DIR}/_src_{cand}.{ext}"
            out_webp = f"{IMG_DIR}/vx_{cand}.webp"
            if not os.path.exists(out_webp):
                try:
                    with open(tmp_src, "wb") as f:
                        f.write(http_get(img_url, binary=True, timeout=30))
                    r = subprocess.run(
                        ["cwebp","-quiet","-q","80","-resize","800","0",tmp_src,"-o",out_webp],
                        capture_output=True, text=True
                    )
                    os.remove(tmp_src)
                    if r.returncode != 0:
                        continue
                except Exception:
                    continue
            seen_slugs.add(cand)
            found.append({"slug": cand, "trade_name": (mt.group(1).strip() if mt else name),
                          "image_url": img_url, "image_local": out_webp, "from_med_name": name})
            print(f"  [{i}/{len(names)}] OK {name!r} -> {cand}")
            time.sleep(0.2)
            break  # don't try other candidates for same name once found

    json.dump(found, open(MANIFEST_NEW, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nDONE: {len(found)} new product pages scraped")


if __name__ == "__main__":
    main()
