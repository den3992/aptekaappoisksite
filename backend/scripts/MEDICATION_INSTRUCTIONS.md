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

The separate `official_manufacturer` profile explicitly supports **Renewal**,
**Canon**, and **Solopharm**; other providers, group companies and CDNs are not inferred.
It requires a visually reviewed complete PDF and exact current GRLS identity,
including a finished-product manufacturer stage. Store the raw official product
HTML beside `original_file` as `<html_sha256>.html`; both preview and apply verify
its hash and the actual selected href. Unknown additional product PDFs require
version review; Renewal excludes only its two reviewed legal footer links.
An unknown clinical revision date stays null. Conflicting versions remain draft.

Solopharm accepts only `https://solopharm.com`, product pages under `/products/`,
and PDFs under `/storage/files/products/`. Its selected empty-text anchor must
retain the literal `data-title="Читать инструкцию"` separately from inner text.
Additional PDF/document links, embedded documents, conflicting attributes or
unknown versions require review. Its producer address must literally agree with
the current GRLS finished-product entity; no new company aliases are inferred.
Scanned originals need the same complete physical visual review as other manual
originals. Original revision and approval dates stay null when unknown; the
version records the SHA. Provider support alone never approves a document.

Canon accepts only `https://canonpharma.ru` or `https://www.canonpharma.ru` on
port 443, product pages under `/catalog/`, and static PDFs under `/upload/`.
Its retained HTML must prove the exact `actual_href`, literal `actual_label`,
resolved `pdf_url` and HTML SHA. Canon has no footer-PDF exceptions. A page with
both patient and healthcare PDFs remains draft under the sole-PDF profile;
labels do not select one automatically. Any project/draft/proekt/проект marker
in the href, PDF path or link label quarantines it, including encoded markers
and filenames also saying final/stamp. The bounded original checker must also
explicitly find no such marker on the actual first physical PDF page. These
checks cannot be replaced by an approval/recovery claim. Canon has no legal-name
equivalence exception: manufacturer aliases must occur literally in the current
GRLS finished-product entity and in the manually reviewed PDF identity proof.

Canon-only `evidence.manufacturer_proof_mode=physical_pdf_finished_stage_v1` is
an explicit alternative when current GRLS lists the same literal production
company only in another role, such as quality control. It does not relabel that
GRLS role. The separate `physical_pdf_finished_stage` proof retains
`grls_role_raw` and `grls_production_fragment`, plus the actual
`pdf_manufacturer_raw`, `pdf_role_raw` and `pdf_producer_block_raw`. Its
`original_sha256`, `page_count` and `page_indices` must match the original and
the physical manufacturer identity field. The observed single producer block
must explicitly say **Производство готовой лекарственной формы** for that
literal company; a generic producer heading, QA, packaging or holder alone is
insufficient. Any explicit GRLS finished manufacturer makes this mode unnecessary
or conflicting and is rejected; there is no implicit version resolution. Missing
or unknown opt-in modes are rejected, and the default GRLS-finished-stage path
and existing Renewal/EAEU immutable payloads stay unchanged.

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

Renewal and Canon use explicit fixed-host HTTPS `/upload/*.pdf` branches;
Solopharm uses its separate `/storage/files/products/` branch, with
redirects disabled and the same byte/hash/cache/concurrency limits. Each has an
independent persistent source-stop marker; a denial does not stop the other
manufacturer or EAEU. The shared source lock and request-rate limit still apply.

Only a reconstructible cache under `/tmp/aptekaa-official-instruction-pdfs` is
written by the API (128 MiB maximum). Compose mounts `instruction_pdf_cache` there
so cache entries and source-stop markers survive container updates. Retain an
independent immutable archive of imported PDF originals, source HTML and document
metadata outside this LRU cache. Before the first mount, preserve any existing
`.source-stopped*` markers. Seed only SHA-verified PDF files atomically with mode
0600 before backend startup or under `.source.lock`; the union of existing and
seeded unique PDF bytes must fit the cache limit. Do not seed HTML/JSON into it.
Requests have bounded concurrency, including
background threads after client cancellation. Access denials or actual browser
challenges stop further source access; they are never bypassed. A transient
upstream failure returns 503 without claiming instruction coverage from OCR.

If an existing price parser is still running through `docker compose exec backend`,
keep that backend container alive. The temporary
`deploy/docker-compose.instructions.yml` overlay starts `backend_instructions`
from the reviewed `instructions-69e1746` image, with one worker, 256 MiB RAM and
one CPU. It inherits the existing private environment and persistent PDF cache;
it has no published ports. Use both compose files with `--no-deps` to start only
`backend_instructions`, verify its Mongo-backed readiness and memory use, then
replace only `next`. The overlay points Next server requests at that read service.
Restart `edge` after replacing Next so nginx resolves its current container IP.
Never run an unrestricted compose `up` or rebuild/recreate `backend` during this
sequence. Require at least 600 MiB `MemAvailable` before starting the read service,
and at least 300 MiB afterward; abort or restore the old Next image if readiness,
resource bounds or the original backend/parser identity checks fail.

The overlay is temporary: a standard Next deployment using only the base compose
file returns its internal API to `backend`. After the price job has finished,
update the main backend with the reviewed image and restart `edge` before removing
the temporary read service. For an earlier rollback, restore the saved Next image
using only the base compose file, restart `edge`, verify it against the original
backend, then stop `backend_instructions`. Retain the archive and PDF cache volume.

Rebuild backend images after script changes, rebuild Next after UI changes, and
restart `edge` after recreating backend. Keep rollback images and import receipts.
