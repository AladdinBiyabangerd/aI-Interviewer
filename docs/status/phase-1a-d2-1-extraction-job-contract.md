# Phase 1A-D2.1 status: durable extraction-job contract

- Status: Complete
- Date: 2026-08-28
- Schema revision: `20260828_0009`
- Scope completed: durable scheduling, lease fencing, retry state, and failure taxonomy
- Next gate: Phase 1A-D2.2 isolated parser worker and bounded PDF/DOCX/TXT adapters

## Purpose

Create a durable asynchronous boundary between clean immutable document versions and the
future untrusted parser. This subphase does not read object bytes, parse a document, or
write extracted text.

## Implemented

- `CandidateExtractionJob` stores one owner-bound job per exact document version with
  immutable document/file/parser/privacy/retention snapshots.
- `CandidateExtractionJobService.schedule_extraction` repeats active-account, draft,
  latest-version, released-asset, delete-only retention, current privacy decision, and
  exact parser-policy checks before creating work.
- `claim_jobs` uses `FOR UPDATE SKIP LOCKED`, a five-minute lease, bounded worker IDs,
  UUID fencing tokens, and a maximum of five attempts.
- `mark_succeeded` requires the current worker lease and the matching D1 source-text
  aggregate. `mark_failed` accepts only the closed safe taxonomy and applies capped
  exponential retry for transient failures.
- Database state constraints reject incoherent lease/result/error combinations. Composite
  owner foreign keys and an identity trigger protect the job snapshot from reassignment.
- Scheduling and state transitions emit content-free audit/outbox metadata. The runtime
  is fail-closed until privacy, file security, and the application keyring are configured.
- Migration and restore inventory now include the job table, two operational indexes,
  two unique indexes, 24 new constraints, its insert-time snapshot-validation trigger,
  and its identity trigger.

## Deliberately not implemented

- No parser subprocess/container, adapter dependency, object-byte read, network namespace,
  CPU/memory/time/output limit, or extraction result is implemented.
- No product route, owner inspection/correction, PII-redacted representation, model call,
  export integration, or job cancellation API exists yet.

## Verification

- Ruff lint and format, strict mypy, Python compilation, D1/D2.1 unit tests, and Alembic
  offline SQL generation pass locally.
- D2.1-specific unit tests: `8` passed. The full non-integration suite currently has
  `290` passed tests; the existing D1 PostgreSQL suite plus two D2.1 integration tests
  totals `49` integration tests awaiting a running disposable database.
- PostgreSQL migration parity, lease concurrency, stale-worker fencing, retry transitions,
  and backup/restore rehearsal require the disposable PostgreSQL service. Docker Desktop
  was unavailable during this handoff, so those checks remain a release gate.

## Next part

Phase 1A-D2.2 will implement the isolated parser worker only after this contract is
accepted: fetch through `read_for_parser`, enforce no-network/read-only/non-root resource
limits, run separately versioned PDF/DOCX/TXT adapters, map bounded safe errors, and
persist successful output through D1 plus the current lease token.

Stop here until the next explicit continuation request.
