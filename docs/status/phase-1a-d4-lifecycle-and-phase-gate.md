# Phase 1A-D4 status: lifecycle and phase gate

- Status: Complete (PostgreSQL-backed release verification passed)
- Date: 2026-08-31
- Schema revision: unchanged from `20260828_0009` (no new tables or columns)
- Scope completed: privacy access/export integration for source-text and extraction-job
  data; verified cascade erasure; supported-input fixture pass for PDF/DOCX/text
- Next gate at completion: Phase 1B-A (the model-gateway dependency, now implemented)

## Purpose

Close Phase 1A: make every D1-D3 domain participate in the account-level privacy
access/export and deletion contract, and prove the full input pipeline for every
document format Phase 1A supports.

## Implemented

- `CandidateSourceTextService.export_account_source_text_metadata` and
  `CandidateExtractionJobService.export_account_job_metadata` are export-only methods
  on the public runtime protocols. Source-text export includes decrypted version
  content; job export contains operational metadata only.
- Fail-closed source-text and job services return an empty export rather than raising,
  so a disabled subsystem cannot break another account's export request.
- Narrow source-text and extraction-job lifecycle adapters are wired through
  `PrivacyLifecycleService`, `build_privacy_service`, and the application composition
  root. The export bundle now includes `candidate_source_texts` and
  `candidate_extraction_jobs`, with schema version `phase-1a-d4.1`.
- Source-text and extraction-job rows have no orphan path: existing owner-scoped
  `ON DELETE CASCADE` chains from `candidate_document_versions` complete erasure.
- The real isolated worker is exercised against parseable PDF, DOCX, and text fixtures;
  privacy export is exercised through schedule, claim, extraction, correction, and
  terminal job completion.

## Deliberately not implemented

- No continuous extraction-worker supervisor/CLI, product parser route, or AI profiling
  consumer was introduced. Those remain outside Phase 1A.
- No redundant erase path was added for source text or jobs; database cascade ownership
  already covers them.

## Verification

- `./scripts/verify.ps1` passed against a disposable PostgreSQL database: `407` tests
  passed, one Windows/POSIX-only signal test skipped, and branch-aware coverage was
  `95.02%`. The run also passed lock verification, Ruff lint/format, strict mypy for
  `70` source files, empty-database migration, Alembic model-drift check, dependency
  compatibility, and the Python vulnerability audit.
- Integration tests now rebuild the disposable schema for every test, preventing durable
  outbox/file/job rows from one test changing another test's queue assertions. Owner
  scope uses a real second active account. Worker fixtures use a test-only 60-second
  process limit to avoid Windows spawn flakiness; production isolation limits are
  unchanged.
- Lease expiry is covered. Claim results explicitly refresh server-managed ORM fields
  before dataclass serialization, preventing an async lazy-load failure.
- `./scripts/rehearse-database-restore.ps1` passed at `20260828_0009`: logical backup
  and recovery had matching row counts, with `2` audit, `1` document-version, `3`
  source-text, and `2` extraction-job triggers; readiness passed and the temporary
  recovery database/dump were removed. The script's extraction-job row count and current
  index/constraint expectations were corrected during this rehearsal.
- The local release image passed `./scripts/verify-release-image.ps1`, including the
  embedded `20260828_0009` migration artifact, baseline schema, and numeric non-root
  runtime identity `10001:10001`. The OneDrive-backed source workspace required a
  temporary materialized Docker build context; the repository itself was not altered.

## Next part

Phase 1A is feature-complete and locally release-verified. Phase 1B-A has now introduced
the model-gateway contract. Phase 1B-B must retain source-span evidence, reproducible
model/prompt/schema versions, strict output validation, and the existing privacy
boundary while adding durable profiles and jobs.
