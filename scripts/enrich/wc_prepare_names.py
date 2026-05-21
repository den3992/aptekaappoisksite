#!/usr/bin/env python3
"""Step 1: prepare list of {name, mnn, slugs:[...]} for medications WITHOUT image.

Groups by `name` (trade brand) and includes the MNN of the first record.
Writes /tmp/wc_names.json sorted by slug count descending (most-impact first).
"""
import json, os, subprocess, re

SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
SSH_HOST = "ubuntu@89.169.137.36"
MONGO_URI = "mongodb://aptekaa_admin:KSkYbEOOdb3nIaGZAdh7WqFQFHJbr7n1AymsdV_2U9Q@localhost:27017/aptekaa?authSource=admin"

OUT = "/tmp/wc_names.json"


def main():
    js = """
const r = db.medications.aggregate([
  { $match: { image_url: { $in: [null, "", undefined] } } },
  { $group: { _id: "$name", mnn: { $first: "$mnn" }, slugs: { $push: "$slug" } } },
  { $project: { _id: 0, name: "$_id", mnn: 1, slugs: 1, count: { $size: "$slugs" } } },
  { $sort: { count: -1 } }
]).toArray();
print('===RESULT_BEGIN===');
print(JSON.stringify(r));
print('===RESULT_END===');
"""
    cmd = ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", SSH_HOST,
           "docker", "exec", "-i", "deploy-mongo-1", "mongosh", MONGO_URI, "--quiet"]
    r = subprocess.run(cmd, input=js, capture_output=True, text=True, timeout=120)
    text = r.stdout
    m = re.search(r"===RESULT_BEGIN===\s*(.*?)\s*===RESULT_END===", text, re.S)
    if not m:
        print("FAIL:", text[:500])
        return
    blob = re.sub(r"^\w+>\s*", "", m.group(1), flags=re.M).strip()
    data = json.loads(blob)
    print(f"unique names without image: {len(data)}")
    print(f"top 5 by impact:")
    for d in data[:5]:
        print(f"  {d['count']:4d}  {d['name']!r}  mnn={d.get('mnn')!r}")
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"saved -> {OUT}")


if __name__ == "__main__":
    main()
