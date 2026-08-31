# ADR 0016: Owner source-text inspection and correction

- Status: Accepted
- Scope: Phase 1A-D3 only
- Date: 2026-08-30
- Depends on: ADR 0013 (encrypted source-text domain) and ADR 0015 (isolated parser
  worker)

## Context

Phase 1A-D1 built an encrypted, immutable source-text lineage with an explicit
`user_correction` revision shape, but deliberately shipped no public endpoint. Phase
1A-D2.2 can now populate that lineage with real parser output. Before any AI processing
reads this text, the owner must be able to see exactly what the parser produced and fix
extraction mistakes without losing the original.

## Decision

1. `CandidateSourceTextService.get_source_text` and the new `append_correction` method
   both take `account_id`, `preparation_id`, and `document_version_id`, mirroring the
   existing preparation/document/intake convention of validating the full ownership
   chain rather than trusting a single opaque ID. `store_parser_extraction` (worker-only,
   never exposed over HTTP) is intentionally left unchanged.
2. A correction is an HTTP `PUT` on the source-text resource, addressed by
   `/preparations/{preparation_id}/document-versions/{document_version_id}/source-text`
   (flat under the preparation, matching the existing `document-intakes/{intake_id}`
   convention rather than nesting through the document resource). It requires a strong
   quoted `If-Match` value equal to the aggregate's current `version` (`428` missing,
   `400` malformed, `412` stale), exactly like `PUT /preparations/{id}`.
3. A correction is idempotent under retry without a separate `Idempotency-Key`: if the
   aggregate has already advanced by exactly one version and that version is a
   `user_correction` whose decrypted content matches the request, the retry returns the
   existing state instead of appending a duplicate. This mirrors the existing
   `store_parser_extraction` dedup pattern rather than introducing a new mechanism.
4. Only the latest document version's source text can be corrected, and only while the
   owning preparation is a non-expired `draft` whose privacy/retention snapshot still
   matches the document version — the same eligibility rule already enforced for
   extraction, minus the parser/file-asset checks that do not apply to a correction.
5. Correction rows always set `parser_release_policy_id`, `parser_adapter`,
   `parser_version`, and `isolation_profile` to `NULL`, matching the database
   `origin_provenance_consistent` constraint from ADR 0013; no schema change was needed
   for this phase.
6. The GET response returns the full decrypted version lineage (content included) in one
   call; there is no separate raw-download content type. A single JSON contract serves
   both display and "save the text" use cases without adding a second endpoint.

## Consequences

An owner can now see and fix extraction output before any downstream AI processing is
built, satisfying the Phase 1 completion criterion that users can inspect and correct
extracted text. No new database migration was required. Phase 1A-D4 must still add
export/deletion/audit integration review and the full lifecycle gate before Phase 1A is
considered complete.
