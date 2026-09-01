# Phase 1B-B2.2 status: durable fenced profiling jobs

- Status: Complete (repository-wide local release verification passed)
- Date: 2026-09-01
- Schema revision: `20260901_0011`
- Scope completed: exact-source idempotent scheduling, immutable privacy/release
  snapshots, UUID lease fencing, bounded retry/backoff, explicit dead-letter state,
  exact encrypted-profile result linkage, lifecycle export/erasure, database invariants,
  restore and release-image verification
- Next gate: Phase 1B-C (reviewed provider-backed profiling worker)

## Implemented

- `candidate_profiling_jobs` binds one owner, preparation, document version/type, source
  aggregate, and immutable source revision to a single durable profiling attempt stream.
- Scheduling locks and reauthorizes the exact lineage and snapshots privacy policy,
  jurisdiction, legal basis, delete-only retention rule/deadline, provider/model/version,
  prompt/version, schema ID/version, instruction/schema SHA-256, and maximum output
  tokens. Exact replay is idempotent; divergent coordinates conflict.
- Eligible pending/retry work is claimed with `FOR UPDATE SKIP LOCKED`, database time,
  and a fresh UUID lease. Every state mutation is fenced by the current unexpired token;
  expired claims can recover without allowing stale workers to mutate the row.
- Attempts are capped at five. Retryable safe failure codes receive bounded exponential
  backoff; non-retryable or exhausted work enters explicit `dead_letter` state.
- Success requires an encrypted candidate profile for the same exact owner,
  document/source revision and model/prompt/schema release. Duplicate success is
  idempotent only for the same matching result.
- Database constraints and four triggers protect immutable snapshots, valid state
  shape/transitions, terminal immutability, and successful profile linkage.
- Audit and outbox events contain only opaque IDs, status/codes, attempt count, and
  document type. Candidate text, prompt/output, profile JSON/ciphertext, quote, nonce,
  digest, and raw provider errors are excluded.
- Privacy access/export includes safe owned profiling-job metadata under schema
  `phase-1b-b2.2`; account/document/source cascades erase the job.

## Deliberately not implemented

- No provider SDK/adapter, credential, endpoint, outbound model call, profiling worker,
  continuous supervisor, public profile route, or correction API was added.
- Exact textual grounding and durable coordination do not establish semantic quality or
  prompt-injection safety. Reviewed prompts/processors, adversarial fixtures, and quality
  gates remain Phase 1B-C/1B-D work.

## Verification

- `./scripts/verify.ps1` passed with `500` tests, one platform-specific skip, and
  `95.09%` branch-aware coverage. Ruff lint/format, strict mypy for `80` source files,
  empty-database migration, migration round-trip/model parity, dependency
  compatibility, and the Python vulnerability audit all passed.
- Fourteen focused unit tests and two real PostgreSQL integration tests cover exact
  scheduling replay/conflict, owner scope, claim/retry/reclaim, stale-token fencing,
  bounded dead-letter handling, exact encrypted-profile success, safe audit/outbox,
  immutable/terminal database triggers, privacy export, and cascade erasure.
- The local database was migrated to `20260901_0011`. Logical backup/restore rehearsal
  passed with the profiling-job table, required indexes/constraints, all four job
  triggers, the existing four profile triggers, and append-only audit verification.
- The release image passed non-root runtime, embedded exact migration head, migration
  job, read-only/capability restrictions, baseline schema, and release metadata checks.

## Next part

Phase 1B-C supplies the reviewed provider-backed worker that claims this durable job,
uses the existing exact-release model gateway, independently verifies the strict
evidence-linked result, persists it through the encrypted profile service, and commits
success with the same live lease token. Real processor coordinates and approved policy
records remain mandatory; the provider boundary stays disabled until they exist.
