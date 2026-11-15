# Verified medication instructions

The catalogue and prices are never rewritten by these importers. All commands
default to preview. Keep the complete original source files and review evidence;
`.instruction-work/` is deliberately excluded from Git and Docker contexts.

## Two distinct publication formats

* `instructions` / `instruction_coverage`: complete verified inline source text,
  rendered in server HTML. This is the text available to Yandex before JavaScript.
* `instruction_originals` / `instruction_original_coverage`: a complete immutable
  official PDF. This does **not** assert verified OCR or inline text. Each PDF is
  bound to exact registration, manufacturer, form, strength and catalogue identity.

Both formats can cover different variants on one card. A matching PDF SHA alone
does not allow hiding a PDF whose variants are absent from the inline bindings.
Unverified candidates and short generated catalogue summaries count as neither.

## Offline preparation and preview

Use Python 3.11+ with the backend requirements for PDF import/structure checking.
The optional deterministic text verifier additionally uses
`scripts/requirements-instruction-verification.txt`; its tests additionally use
`tests/requirements-instruction-verification.txt`. Never run the repository's
unrelated legacy integration tests against production to validate these changes.

```sh
PYTHONPATH=backend python -m scripts.import_medication_instructions \
  --documents verified-text.jsonl --manifest catalog-identities.jsonl \
  --report text-preview.json

PYTHONPATH=backend python -m scripts.import_medication_originals \
  --documents verified-originals.jsonl --manifest catalog-identities.jsonl \
  --report originals-preview.json
```

Every row is `{"document": {...}, "original_file": "/retained/original.pdf"}`.
An apply requires that retained original, SHA equality, a current live identity
recheck and no overlapping active document scopes. The originals importer also
resolves PDF resources in a supervised subprocess (512 MiB RSS, 20 s CPU,
30 s wall, 32 MiB original, 256 pages). Scanned pages are not treated as OCR text.

`prepare_eaeu_original_pdfs.py --help` describes the resumable offline corpus
preparer. It requires actual official attachment paths, source metadata and a
current GRLS snapshot. Every strength and legal manufacturer alias must have
reproducible literal evidence. It rejects uncertain versions, projects, mismatched
forms or strengths, unrelated legal entities and missing source data. Retain its
verification checkpoints: repeated runs reuse the same immutable payload.

The complete EAEU index and its count/SHA validation are mandatory; uniqueness
cannot be inferred from downloaded PDFs alone. Explicit optional proof modes are
`--manufacturer-proof-mode eaeu_paired_entity_v1` (long/brief names from one
finished-product manufacturing entity) and `--dosage-proof-mode
eaeu_structured_solid_v1` (single-active solid form, exact quantity/mass unit,
explicit zero scale, pinned public classifiers, no unit conversions). The default
literal path and its old immutable payloads stay unchanged.

The separate `official_manufacturer` profile currently supports **Renewal only**.
It requires a visually reviewed complete PDF and exact current GRLS identity,
including a finished-product manufacturer stage. Store the raw official product
HTML beside `original_file` as `<html_sha256>.html`; both preview and apply verify
its hash and the actual selected href. Unknown additional product PDFs require
version review; only two explicitly reviewed legal footer links are excluded.
An unknown clinical revision date stays null. Conflicting versions remain draft.

## Apply and rollback

Supply `MONGO_URL` and `DB_NAME` only through the existing secret loader or an
in-memory local tunnel configuration; never print credentials or put them in Git.
Add `--apply` and retain `--report`. An optional local `--manifest` avoids a full
catalog read, while apply still rechecks each selected live identity and overlap.
Run bulk imports and production deployments outside 03:00–07:00 UTC.

Text writes use `instruction_documents` and `medication_instruction_bindings`.
PDF writes use `instruction_original_documents` and `medication_original_bindings`.
The same lease, immutable document check, fresh variant check and per-batch audit
machinery is used in both namespaces. Partial failed batches disable their own new
bindings. Rollback retains original documents and audit records:

```sh
PYTHONPATH=backend python -m scripts.import_medication_originals \
  --apply --rollback BATCH_ID --report rollback.json
```

Use the text importer instead for a text batch. PDF HTTP delivery requires an
active verified binding, so disabled original batches stop being served.

## Public PDF delivery

The endpoint accepts only an internal document ID. It never accepts a URL or a
temporary source token. The observed public EAEU workflow is fetched with TLS,
fixed hosts, no redirects, cross-process source serialization and one request
start per second. The complete bounded file is checked against its recorded
length and SHA **before** any bytes are sent. A source revision with a new SHA
requires a new audit; it cannot silently replace an existing document.

Renewal uses a separate fixed-host HTTPS `/upload/*.pdf` branch with redirects
disabled and the same byte/hash/cache/concurrency limits. A denial stops only
that source; it does not stop the independent EAEU source.

Only a reconstructible cache under `/tmp/aptekaa-official-instruction-pdfs` is
written by the API (128 MiB maximum). Requests have bounded concurrency, including
background threads after client cancellation. Access denials or actual browser
challenges stop further source access; they are never bypassed. A transient
upstream failure returns 503 without claiming instruction coverage from OCR.

Rebuild backend images after script changes, rebuild Next after UI changes, and
restart `edge` after recreating backend. Keep rollback images and import receipts.
