# Explicit Ozon legal-prefix evidence

`eaeu_ozon_ascii_legal_prefix_v1` is a separate opt-in manufacturer profile for
the observed catalog value `OOO ОЗОН`. It compares only the whole first token
`OOO` with `ООО`; the raw catalog value and Cyrillic core `ОЗОН` remain unchanged
in identity, proof and variant bindings. Default and existing paired-entity
profiles keep their previous derivation and canonical hashes.

The same current Russian EAEU record must contain the exact full/brief pair
`Общество с ограниченной ответственностью "Озон"` / `ООО "Озон"` in an explicit
stage25 manufacturing entity. The retained raw entity, SHA and source pointer
are validated by the existing paired-entity validator. Separate OzonFarm
source entities are excluded from this first profile.

This mode additionally requires the complete same GRLS company, the literal
role `Производитель (готовой ЛФ)`, a nonempty address and the literal country
`Россия` in the current GRLS row. Holder, packer and quality-control fragments
cannot provide this role. Address and jurisdiction are attributed exclusively
to GRLS: the paired EAEU raw entity supplies no independent physical-site proof.

The proof stores the explicit token comparison, raw source entity identity,
current GRLS row/hash and the full literal production fragment; validation
rederives every field. Existing current-RU, source uniqueness, name, form,
dosage, document type/version/project, binary and matcher guards still apply.
Only the existing literal or structured solid-dose modes can combine with this
profile; a concentration profile is excluded.

Enabling this code does not approve real wrappers or publication. Whole-binary
validation, independent data review, actual-image runtime checks, exact live
overlap checks and bounded cache capacity are separate requirements. No
clinical text is authored or extracted for publication by this profile.
