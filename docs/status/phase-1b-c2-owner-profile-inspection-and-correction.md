# Phase 1B-C2 status: owner profile inspection and immutable correction

- Status: Complete (repository-wide local release verification passed)
- Date: 2026-09-01
- Schema revision: unchanged at `20260901_0012`
- Scope completed: owner-scoped safe profiling status, completed profile-history read,
  strong ETag correction contract, encrypted immutable correction append, lifecycle and
  audit coverage
- Next gate: Phase 1B-D (labeled AZ/EN profile quality evaluation)

## Implemented

- `GET` and `PUT` now expose one authenticated profile resource for an exact
  preparation, document version, and source-text version. Reads require
  `preparation:read`; corrections require `preparation:write`.
- The GET contract returns bounded job status, attempts, safe failure code,
  retryability, and availability/completion timestamps. Worker/lease/processor details,
  release digests, source text, prompt, and raw provider detail are excluded.
- A profile is visible only after the durable job is `succeeded` and its result ID
  matches the exact encrypted profile. Active jobs return `Retry-After` with no profile;
  all responses are `no-store`.
- Completed histories carry a strong aggregate ETag. PUT requires a quoted positive
  `If-Match`; stale state returns `412`. An exact immediate retry returns the existing
  correction without creating another revision.
- Corrections use the same strict CV/JD schemas and independently revalidate document
  type plus every exact Unicode evidence span against the retained source revision in
  the transaction.
- The service repeats active-account, draft/latest lineage, privacy, legal-basis, and
  delete-only retention checks before appending an encrypted `user_correction` row.
  Generated and earlier corrected versions remain immutable.
- Correction audit/outbox evidence contains only opaque IDs, bounded origin/schema and
  evidence counts; the owner is the audit actor. Candidate content and cryptographic
  material are excluded.
- Privacy export schema is `phase-1b-c2` and includes the complete decrypted,
  revalidated generated/corrected profile history. Existing owner/document/source
  cascades erase the lineage.
- The route is part of the reviewed product SLI population. The existing profile schema
  and triggers already reserved and protected correction rows, so no migration was
  required and Alembic head remains `20260901_0012`.

## Deliberately not implemented

- No public profiling-schedule command, concrete provider SDK, credential, endpoint,
  outbound model call in the shipped configuration, or continuous worker supervisor.
- C2 proves confidentiality, integrity, ownership, concurrency, and lifecycle behavior;
  it does not establish semantic model quality. Thresholded AZ/EN evaluation remains
  Phase 1B-D.

## Verification

- `./scripts/verify.ps1` passed with `538` tests, one platform-specific skip, and
  `95.15%` branch-aware coverage.
- Ruff lint/format and strict mypy passed for `83` source files.
- Real PostgreSQL tests prove encrypted correction persistence, exact retry
  idempotency, stale-version rejection, generated-history preservation, content-free
  owner-attributed audit/outbox, privacy export, and owner-scoped job status reads.
- API tests cover owner scopes, opaque not-found, pending/dead-letter/succeeded status,
  hidden pre-success profiles, ETag/`If-Match`, strict body validation, mismatch and
  unavailable fail-closed behavior, and payload-safe problem responses.
- Empty-database migration, downgrade/upgrade round trip, Alembic model parity,
  dependency compatibility, and the Python vulnerability audit passed with unchanged
  schema head `20260901_0012`.
- Logical backup/restore rehearsal passed with all source/profile/profiling-job rows,
  `4` profile triggers, `4` profiling-job triggers, and the exact named constraint
  inventory. The rehearsal checker was corrected to use the explicit parser-policy FK
  name defined by both migration and ORM metadata.
- The C2 release image was rebuilt and passed embedded schema `20260901_0012`, baseline
  artifact, numeric `10001:10001` runtime, migration job, read-only filesystem,
  capability drop, and `no-new-privileges` checks.

## Next part

Phase 1B-D defines the labeled Azerbaijani/English fixture corpus, field precision and
recall, exact source-span coverage, user-correction rate, adversarial/slice analysis,
thresholds, and regression approval. A real provider remains separately gated by its
reviewed adapter, credentials, processor inventory/activity, and operational supervisor.
