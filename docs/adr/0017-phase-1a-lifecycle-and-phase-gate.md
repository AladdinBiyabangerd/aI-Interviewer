# ADR 0017: Phase 1A-D4 lifecycle and phase gate

- Status: Accepted
- Scope: Phase 1A-D4 only (closes Phase 1A)
- Date: 2026-08-31
- Depends on: ADR 0005 (privacy lifecycle), ADR 0013 (source-text domain), ADR 0014
  (extraction jobs), ADR 0015 (isolated parser), ADR 0016 (owner correction)

## Context

Phases 1A-D1 through 1A-D3 introduced two data domains — `candidate_source_texts` and
`candidate_extraction_jobs` — that were never wired into the account-level privacy
access/export contract. `CandidateDocumentLifecycleAdapter.erase_account_document_metadata`
already deletes them correctly (both tables carry `ON DELETE CASCADE` foreign keys to
`candidate_document_versions`, which itself cascades from `candidate_documents`), but
export was a real, explicitly-flagged gap: `docs/status/phase-1a-d1-encrypted-source-text-domain.md`
called it a "mandatory Phase 1A-D4 gate."

## Decision

1. `CandidateSourceTextService` and `CandidateExtractionJobService` each gain one new
   export-only method — `export_account_source_text_metadata` and
   `export_account_job_metadata` — added directly to their existing public `Runtime`
   Protocols, matching the established convention (`CandidateDocumentRuntime` already
   carries its own `export_account_document_metadata`/`erase_account_document_metadata`
   pair). Both take the caller's already-open `AsyncSession` rather than opening their
   own transaction, matching every other export hook.
2. Two new narrow `Protocol`s in `privacy/lifecycle.py` —
   `CandidateSourceTextLifecycleAdapter` and `CandidateExtractionJobLifecycleAdapter` —
   declare only the export method. Neither declares an erase method: unlike
   `candidate_document_intakes` (which can hold rows for an upload that never produced a
   document, so cascade from `candidate_documents` cannot reach them), every
   `candidate_source_texts` and `candidate_extraction_jobs` row is created only after a
   `candidate_document_versions` row exists and is deleted the moment that row is, with
   no orphan path. A dedicated erase call would be redundant, not defense-in-depth.
3. Following the same precedent as `candidate_preparations`' export
   (`CandidateInputService._export_item` returns real field values, not just hashes),
   the source-text export includes each version's actual decrypted `content` — the
   point of a GDPR-style access/export request is to hand the data subject the data
   itself, not a fingerprint of it. The extraction-job export is metadata-only
   (status, attempts, parser identity, timestamps): jobs never store content.
4. The account export bundle's `schema_version` moves from `"phase-1a-c.1"` to
   `"phase-1a-d4.1"` because its shape changed (two new top-level keys,
   `candidate_source_texts` and `candidate_extraction_jobs`). Every export consumer
   test that asserts the schema version literal was updated in the same change.
5. A disabled `CandidateSourceTextService`/`CandidateExtractionJobService`
   (`FailClosedCandidateSourceTextService`/`FailClosedCandidateExtractionJobService`)
   returns an empty list from its export method rather than raising — an account whose
   privacy export runs while, say, file-security is disabled must still get a complete,
   uncrashed export of everything else, exactly like the existing
   `DisabledFileSecurity.export_account_metadata` precedent.
6. A new parametrized integration fixture
   (`test_extraction_worker_supports_every_documented_input_format`) proves the full
   pipeline for all three Phase 1A-supported formats using genuinely parseable
   fixtures — a hand-built single-page PDF with a real content stream and a real
   python-docx document, not the synthetic `%PDF-...%%EOF` byte-signature-only content
   used elsewhere for validation-boundary tests. This is the "supported-input fixture
   pass" the roadmap names as part of the D4 gate.

## Consequences

Phase 1A's access/export integration is now complete for every domain introduced
across D1-D3; erasure was already complete since D1. PostgreSQL-backed verification of
this change (and of D2.1 through D3's own still-unexecuted integration suites) remains
blocked on a locally available disposable database and is deferred to the same release
gate already recorded for those phases. Concurrency, security, migration, and restore
rehearsal against a real database, plus a final cross-phase Phase 1A completion review,
are the remaining items before Phase 1B (CV/JD profiling) can begin.
