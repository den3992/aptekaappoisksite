# Retained instruction originals

The default delivery path first validates the existing canonical document, then
checks `/var/lib/aptekaa-instruction-originals/<original_sha256>.pdf`. The route's
existing active-binding gate remains before delivery. Production takes neither
the directory nor a file path from a document or request. The constructor path
override is for offline tests. Deployments without this directory preserve the
existing LRU and network fallback.

The store must be mounted read-only, with0700directory and0600regular files.
The reader uses stable directory/file descriptors, O_NOFOLLOW and O_NONBLOCK,
64KiB reads bounded by the exact expected length plus one byte, a deadline,
the32MiB per-file limit, header/EOF checks and full expected SHA256. It checks
descriptor and directory-entry stability after reading. It never touches
mtime, writes a lock, scans the whole store or parses an archive. A present bad
file fails closed even if the LRU contains a good copy. Missing local files
retain the existing source-stop, rate, timeout and TLS behavior. A good retained
file remains readable while its external source is stopped.

`python -m scripts.seed_instruction_original_store --plan <private-plan.json>
--store <private-absolute-directory>` performs a read-only plan by default.
The reviewed plan schema is `aptekaa-original-store-seed-v1`, with explicit
`sources` entries of kind `immutable_source_archive_unpack_v1`, directory and
manifest_sha256; expected_unique_pdf, expected_unique_pdf_bytes and budget_bytes
are mandatory. Existing source archives are not extracted by the helper.

The helper validates every manifest member's safe path, regular type,0600mode,
length and SHA, and checks each PDF's header/EOF. Only the two existing source
manifest schemas are accepted. It bounds sources128, unique PDFs4096, manifest
entries32768, manifest bytes4MiB, all source bytes1GiB, each file32MiB and work
time300seconds. Logical store budget cannot exceed512MiB. Free disk must retain
256MiB plus32MiB metadata reserve; inode availability is checked too. These
limits allocate no corresponding RAM. Reads and copies use64KiB chunks.

`--apply` obtains a private exclusive lock and rechecks existing files before
publishing. Unknown/corrupt/symlink store entries require an audit; the helper
never deletes or overwrites them. It accepts only reviewed immutable unpacks,
never an LRU source or destination, and never writes inside those source roots.
The default publication uses a private temporary hardlink, checks its inode
against the stable source descriptor, then an atomic no-replace final link and
a full post-publication SHA check. It never chmods a shared inode. Hardlinking
preserves source bytes, inode, mode and mtime; nlink and ctime necessarily change
and are recorded honestly. An explicit `--allow-copy` permits bounded EXDEV
fallback after reserving the full new-file disk requirement. Only the helper's
own temporary file can be cleaned up. Successfully published known files remain
after a later failure; rerun with the complete reviewed source union to verify
and finish, without deleting earlier files.

Before production cutover, all initial280 PDFs/118941781bytes require fresh
content verification, an actual read-only mount check, actual-image256MiB tests
and published-PDF checks under intact source-stop markers. The old3578240 image
and128MiB cache cover the initial280 cohort while that cache remains intact.
They do not promise access to future cohorts beyond that cache or to future
manufacturer/dosage proof modes. Before those imports, record the exact
compatible reader/image and binding rollback scope separately.

This change does not authorize source deletion, LRU-cap changes, old release
cleanup, clinical edits, new document approvals, DNS/nginx changes or purchases.
