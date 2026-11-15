"""Split a read-only catalog manifest into reproducible, disjoint work batches."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.audit_medication_instructions import load_manifest


def partition_catalog(manifest: Path, destination: Path, batch_size=1000) -> dict:
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    records = sorted((med for med in load_manifest(manifest)
                      if med.get("is_canonical") is not False), key=lambda med: med["slug"])
    slugs = [med["slug"] for med in records]
    if len(slugs) != len(set(slugs)):
        raise ValueError("catalog contains duplicate slugs")
    destination.mkdir(parents=True, exist_ok=True)
    batches = []
    for offset in range(0, len(records), batch_size):
        selected = records[offset:offset + batch_size]
        name = f"batch-{offset // batch_size + 1:03d}.jsonl"
        text = "".join(json.dumps({"record_type": "medication", "medication": med},
                                  ensure_ascii=False, sort_keys=True) + "\n" for med in selected)
        path = destination / name
        if path.exists() and path.read_text(encoding="utf-8") != text:
            raise ValueError(f"refusing to replace a different work batch: {name}")
        path.write_text(text, encoding="utf-8")
        batches.append({"file": name, "cards": len(selected),
                        "variants": sum(len(med.get("variants") or []) for med in selected),
                        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        "first_slug": selected[0]["slug"], "last_slug": selected[-1]["slug"]})
    report = {"catalog_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
              "cards": len(records), "batch_size": batch_size, "batches": batches}
    (destination / "index.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args(argv)
    report = partition_catalog(args.manifest, args.destination, args.batch_size)
    print(json.dumps({"cards": report["cards"], "batches": len(report["batches"]),
                      "batch_size": report["batch_size"], "destination": str(args.destination)}))


if __name__ == "__main__":
    main()
