# Optional original catalog form evidence

`eaeu_mdlp_original_catalog_film_v1` is an explicit original-PDF binding mode.
The workbook and `medications_raw` corroborate fields retained by the catalog
importer. They are not an authenticated medical publisher, proof of the original
import event, or current regulatory authority. The medical source remains the
unchanged official current EAEU original and its independently checked GRLS
identity. This code does not approve real new documents.

Only the observed complete form pair is accepted: raw `form_std` is
`ТАБЛЕТКИ, ПОКРЫТЫЕ ОБОЛОЧКОЙ`, raw `form_norm` is
`ТАБЛЕТКИ ПОКРЫТЫЕ ПЛЕНОЧНОЙ ОБОЛОЧКОЙ`, and source scope is
`таблетки, покрытые пленочной оболочкой`. There is no global comma or form alias.
Both raw dosage fields must equal the exact positive integer-mg source scope.
The existing structured SOLID mode and None/PAIRED manufacturer guards stay
mandatory. No combination, enteric, retard, concentration, unit conversion or
holder/finished-manufacturer substitution is added.

The optional proof pins the canonical source, original PDF, current registry and
GRLS row, original workbook/importer/lineage report, and each complete ten-field
raw projection and original row number. Per-binding IDs start `mdlp1-`; their
immutable Mongo `_id`, public ID, marker and proof digest prevent deletion of
the proof from becoming legacy active-only authorization. Existing IDs and
canonical medication/document hashes stay unchanged.

Use the offline `scripts.prepare_mdlp_variant_form_evidence` builder only after
separate source-generation and DATA review. Retain original typed workbook rows,
cleaned projections, old source proofs, current raw-page pointers and a new
nonadditive-generation ledger in private provenance. Do not rewrite old source
proofs or expand an existing canonical document. Reuse an existing document only
when its entire canonical payload is byte-equivalent; the PDF CAS can deduplicate
independently of document IDs.

The original-only importer requires `--allow-mdlp-raw-form`. Preview uses the
reviewed retained projection explicitly. Apply reads current raw fields before
preflight, immediately before each optional binding upsert, and before marking
the batch complete. An observed conflict disables this batch's newly inserted
rows. These separate-time cross-collection checks are not a Mongo transaction;
fresh API checks remain mandatory if a raw writer interleaves afterward.

API cold and warm MDLP reads bypass positive payload caching. They reload active
rows and compare fresh canonical identity/labels with the supplied medication,
without replacing its price data, then read raw projections afresh. Cached
ordinary results never contain MDLP-authorized positives. Missing, malformed,
duplicate or changed raw rows fail only that optional relation; independent
ordinary bindings survive. Ordinary paths perform no raw lookup.
The ordinary positive cache skips every MDLP binding row, including any strict
variant carried by that row; a missing discovery hint cannot revive it.

The fixed indexed-GTIN aggregate projects bounded raw fields on the server,
before deserialization: strings only, each at most 1024 UTF8 bytes and sum at most
8192 bytes; invalid rows become a small sentinel. Queries cap at 32 GTINs,
N+1 rows, one batch, 300ms server time and 300ms PyMongo CSOT. PyMongo 4.9.2
rewrites maxTimeMS from the remaining CSOT budget; the driver budget must not
raise the explicit 300ms command bound. A command-local dict guard rejects any
driver rewrite outside exact integer 1..300 before assignment and BSON encoding,
including a sub-millisecond remaining budget rounded to zero. It applies only
to this fixed raw aggregate; no driver-global hooks are installed. Actual wire
checks still require positive maxTimeMS <=300. Database.command
avoids the retryable-read helper; there is no application retry/getMore loop.
An N+1 row is an overflow sentinel: the complete optional query is rejected,
even with a closed cursor, because the limit could hide another duplicate.
Any unexpected open cursor is killed and rejected. Async callers wait at most
500ms; two slots track actual concurrent worker completion rather than wrapper
cancellation. A timed-out/cancelled caller cannot free a still-working slot.
These are fail-closed bounds, not an unmeasured latency or memory-headroom claim.

A direct request reaching the backend PDF route freshly authorizes MDLP-only
relations before any byte cache, permanent STORE or source fallback. A valid
independent ordinary relation can authorize mixed documents. Official PDF bytes
are public immutable documents: current Next278, body SHA, ETag and cache headers
are unchanged. Cached/saved browser/CDN/Next bytes do not prove a currently valid
card association, and no per-request browser reauthorization/revocation is
promised. No Next, edge or nginx changes are part of this release.

The initial reviewed metadata upper bound was 38 PDFs/55 cards/92 variants.
The separately approved source-preparation amendment adds two retained originals
within the same feature boundary: 40 PDFs/57 cards/95 variants, 563 pages and
20076465 original bytes. Five PDFs already exist in CAS, so the proposed full
union is 388 PDFs/170811711 bytes (35 new/18032595 bytes). Bicalutamide and
Ketonal remain excluded. This is source-preparation approval, not DATA or
publication approval; ready0. Separate native128 strict checks, full
compatible-image actual388 STORE runtime256MiB/noOOM, all371 legacy canonical
IDs/1513 keys, fresh raw
mutation/direct backend tests, source/store/live/public gates are still required.
