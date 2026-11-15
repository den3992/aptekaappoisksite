# Explicit EAEU PDF caption dose

`eaeu_pdf_literal_caption_dose_v1` is an optional dose-evidence mode. It uses the exact first-page patient-leaflet caption containing trade name, dose and complete form. The medication, structured EAEU values and existing dose modes remain unchanged. A differing structured representation is retained in the registry snapshot, its hash and the scope's literal-source values; the mode performs no conversion or clinical-equivalence inference.

The mode retains current EAEU record and sole USAGE attachment, exact RU, current GRLS release form, manufacturer and strict catalog-form gates. It supports only default/paired manufacturer evidence and cannot combine with film/MDLP or Ozon modes. A printed RU is not claimed: the primary current attachment-to-RU association remains the authority.

The shared `instruction_pdf_caption.caption_fields` is the exact reviewed generic-preparer function moved without semantic change. `instruction_pdf_physical` contains only bounded actual-PDF reading, resources, text/project and printed-registration conflict checks; it does not import manufacturer source descriptors or grant publisher permissions. The existing structural checker and its fingerprint are unchanged.

Preparation reads the unchanged complete PDF in a bounded child (512 MiB, CPU20s, wall30s), stores exact original/page/caption evidence and a first-page text hash, and includes that proof in the preparation fingerprint. Archive validation rederives the proof from actual bytes before any structural-parser cache shortcut. Source SHA, header role, all-page structure/project checks and every scope caption must agree. Replaced files or altered proofs cannot reuse the physical cache. Metadata validation alone is not physical or publication approval.

The corpus preparer holds all eligible documents sharing an exact variant with different PDF SHAs; it does not choose the first. This is a reviewed-cohort scope check, not a claim that unobserved versions cannot exist. Existing immutable canonical payloads may be reused only byte for byte.

Use the existing `prepare_eaeu_original_pdfs` CLI with `--dosage-proof-mode eaeu_pdf_literal_caption_dose_v1`. Prepare into an owned source copy, because its existing verification checkpoint is written there. Existing DATA, native, actual-image, archive/store, fresh import and public checks still apply. Whole-original coverage does not imply a clinical transcription, latest revision, inferred approval date or full clinical-content review.
