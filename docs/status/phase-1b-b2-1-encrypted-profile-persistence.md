# Phase 1B-B2.1 status: encrypted immutable profile persistence

- Status: Complete (repository-wide local release verification passed)
- Date: 2026-09-01
- Schema revision: `20260831_0010`
- Scope completed: exact-source owner-bound aggregates, encrypted append-only profile
  revisions, same-transaction evidence revalidation, lifecycle export/erasure, database
  invariants, restore and release-image verification
- Next gate: Phase 1B-B2.2 (fenced durable profiling jobs and bounded dead-letter state)

## Implemented

- `candidate_profiles` binds one owner and exact latest corrected-source revision to the
  matching document version/type and immutable privacy, jurisdiction, legal-basis, and
  delete-only retention snapshots.
- `candidate_profile_versions` stores canonical strict CV/JD JSON only as AES-256-GCM
  ciphertext with metadata-bound AAD and a keyed rotation-aware integrity digest.
- The immutable first revision records schema ID/version, exact provider/model/version,
  prompt/version, instruction/schema SHA-256 values, model attempts, and bounded
  content-free claim/evidence counts.
- The persistence transaction locks and reauthorizes the exact lineage, decrypts the
  exact latest source revision, checks release/document identity, and independently
  repeats exact evidence-span validation before insertion.
- Exact replay is idempotent. A changed profile or model/prompt/schema release conflicts
  rather than replacing the stored result. Reads fail closed on ciphertext, digest,
  schema, count, or lineage inconsistency.
- Database constraints and triggers protect aggregate identity and snapshots, reject
  all version updates, and enforce valid predecessor/version shape.
- Privacy access/export includes decrypted owner profiles under schema
  `phase-1b-b2.1`; account, document, and source cascades erase both profile tables.
- Application wiring uses a fail-closed service unless privacy/file security and the
  application keyring are ready. Audit/outbox details remain content-free.

## Deliberately not implemented

- No profiling-job table, lease claim, retry/dead-letter worker, provider SDK/adapter,
  credential, endpoint, outbound model call, public profile route, or correction API.
- The reserved `user_correction` version shape is database groundwork only; no command
  can create it in this phase.
- Exact textual grounding does not prove semantic correctness or prompt-injection
  safety. Reviewed prompts/processors and labeled adversarial quality gates remain
  Phase 1B-C/1B-D work.

## Verification

- `./scripts/verify.ps1` passed with `484` tests, one platform-specific skip, and
  `95.09%` branch-aware coverage. Ruff lint/format, strict mypy for `78` source files,
  empty-database migration, migration round-trip/model parity, dependency
  compatibility, and the Python vulnerability audit all passed.
- Focused unit and PostgreSQL integration tests cover encryption/non-plaintext storage,
  exact replay/conflict, wrong owner, stale source, release mismatch, trigger-protected
  updates, integrity failure, lifecycle export/decryption, and cascade erasure.
- The local database was migrated to `20260831_0010`. Logical backup/restore rehearsal
  passed with required profile tables, indexes, constraints, and all four profile
  triggers; append-only audit verification also passed.
- The release image passed non-root runtime, embedded exact migration head, migration
  job, read-only/capability restrictions, baseline schema, and release metadata checks.

## Next part

Phase 1B-B2.2 adds one idempotent durable job per exact source revision with immutable
privacy/model/prompt/schema snapshots, `SKIP LOCKED` claiming, UUID lease fencing,
bounded attempts/backoff, safe terminal failure, and content-free operational evidence.
The provider boundary remains disabled until that gate is complete.
