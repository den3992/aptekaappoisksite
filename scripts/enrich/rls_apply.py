#!/usr/bin/env python3
"""Apply rls_match_plan.json:
1. SCP all webp files to remote /home/ubuntu/aptekaa/frontend/public/img/meds/
2. Run mongo updates: set image_url for each matched slug.
"""
import json, os, subprocess, sys

PLAN = "/tmp/rls_match_plan.json"
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
REMOTE = "ubuntu@89.169.137.36"
REMOTE_DIR = "/home/ubuntu/aptekaa/frontend/public/img/meds/"
MONGO_URI = "mongodb://aptekaa_admin:KSkYbEOOdb3nIaGZAdh7WqFQFHJbr7n1AymsdV_2U9Q@localhost:27017/aptekaa?authSource=admin"


def main():
    plan = json.load(open(PLAN))
    if not plan:
        print("Plan is empty, nothing to apply.")
        return
    print(f"Plan: {len(plan)} products / {sum(len(p['slugs']) for p in plan)} slugs")

    # 1) SCP images
    files = [p["image_local"] for p in plan]
    print(f"\n[1/2] SCP {len(files)} files to {REMOTE}:{REMOTE_DIR} ...")
    cmd = ["scp", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no"] + files + [f"{REMOTE}:{REMOTE_DIR}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print("SCP FAILED:", r.stderr[:300])
        sys.exit(1)
    print("  scp ok")

    # 2) Build a bulk update script
    print(f"\n[2/2] Apply image_url updates via mongosh ...")
    ops = []
    for p in plan:
        for slug in p["slugs"]:
            ops.append({"slug": slug, "image_url": p["image_url"]})
    js_ops = json.dumps(ops, ensure_ascii=False)
    js = (
        f"const ops = {js_ops};\n"
        "let updated = 0, missing = 0;\n"
        "for (const op of ops) {\n"
        "  const r = db.medications.updateOne({slug: op.slug}, {$set: {image_url: op.image_url}});\n"
        "  if (r.modifiedCount) updated++; else missing++;\n"
        "}\n"
        "print('updated=' + updated + ' unchanged=' + missing);\n"
    )
    cmd = ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", REMOTE,
           "docker", "exec", "-i", "deploy-mongo-1",
           "mongosh", MONGO_URI, "--quiet"]
    r = subprocess.run(cmd, input=js, capture_output=True, text=True, timeout=120)
    print("STDOUT:", r.stdout.strip())
    if r.stderr.strip():
        print("STDERR:", r.stderr.strip()[:400])


if __name__ == "__main__":
    main()
