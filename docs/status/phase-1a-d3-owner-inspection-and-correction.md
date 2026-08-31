# Phase 1A-D3 status: owner inspection and correction

- Status: Complete (local verification; PostgreSQL-backed checks pending Docker)
- Date: 2026-08-30
- Schema revision: unchanged from `20260828_0009` (no new tables or columns)
- Scope completed: authenticated owner-scoped source-text read, safe display contract,
  and optimistic/idempotent immutable correction append
- Next gate: Phase 1A-D4 lifecycle and phase gate

## Purpose

Let the document owner see exactly what the isolated parser (or a prior correction)
produced, and fix mistakes, before any AI processing is built on top of this text.

## Implemented

- `CandidateSourceTextService.get_source_text` now validates the full
  `account_id -> preparation_id -> document_version_id` ownership chain (previously
  only `account_id -> document_version_id`), matching the convention already used by
  preparations, documents, and document-intakes.
- `CandidateSourceTextService.append_correction` validates the same chain plus the
  document/preparation eligibility rule (draft, non-expired, matching privacy
  snapshot, latest document version only), re-checks the live privacy decision, and
  appends one new `CandidateSourceTextVersion` with `origin="user_correction"`,
  `parser_*` fields `NULL`, and `previous_version_id` set to the prior latest version.
- Optimistic concurrency reuses the aggregate's existing `version` column (already an
  ETag source for other resources): a correction requires a strong quoted `If-Match`
  and returns `412` on a real conflict. A retry with the exact same `If-Match` and
  content that was already applied returns the current state instead of appending a
  duplicate or erroring, by decrypting and comparing the current latest version.
- New HTTP contract:
  `GET/PUT /api/v1/preparations/{preparation_id}/document-versions/{document_version_id}/source-text`,
  scoped to `preparation:read`/`preparation:write`. GET returns the full decrypted
  version lineage (content included) with an `ETag` header; PUT requires `If-Match` and
  a `{"content": str}` body bounded to 500,000 characters.
- `CandidateSourceTextPreconditionError` is a new exception mapped to HTTP `412`,
  distinct from the existing `CandidateSourceTextConflictError` (`409`) used for
  document/policy-state conflicts.
- The new route is registered in the reviewed SLI product-route population
  (`core/reliability.py`); the existing route-drift regression test enforces this for
  every future route change.

## Deliberately not implemented

- No raw-text `Content-Type: text/plain` download variant; the JSON response already
  carries full content and is sufficient for both display and client-side "save as
  file" use cases.
- No correction history diff/rollback UI contract beyond the existing immutable
  version list already returned by the GET response.
- No export/deletion/audit *review* pass for this new write path — D1's cascade
  erasure and privacy-audit wiring already cover it structurally, but the full
  Phase 1A lifecycle sign-off is D4's job, not D3's.
- No AI processing of any kind reads this text yet.

## Verification

- Ruff lint and format, strict mypy (Linux platform target), and the full
  non-integration unit/component suite pass locally.
- New unit coverage: content validation before database access for corrections;
  builder/fail-closed behavior for both new runtime methods.
- New integration coverage (`tests/integration/test_candidate_source_texts.py`):
  end-to-end correction append, idempotent retry, stale-version precondition,
  future-version precondition, wrong-preparation and wrong-owner rejection, and a
  second sequential correction chaining `previous_version_id` correctly. Docker Desktop
  was unavailable during this handoff, so these remain unexecuted locally, matching the
  same gap already recorded for D2.1 and D2.2.
- New HTTP-level coverage (`tests/test_source_texts_api.py`): scope enforcement, ETag
  round-trip, `428`/`400`/`412` `If-Match` handling, `404`/`503`/`409` error mapping
  without leaking internal exception text, and `422` on empty correction content.

## Next part

Phase 1A-D4 (lifecycle and phase gate) closes out Phase 1A: privacy access/export
integration review for the source-text and correction data introduced across D1-D3,
concurrency/security/migration/restore verification once Docker is available, and a
supported-input fixture pass across the full 1A flow before Phase 1B (CV/JD profiling)
can begin.

Stop here until the next explicit continuation request.
