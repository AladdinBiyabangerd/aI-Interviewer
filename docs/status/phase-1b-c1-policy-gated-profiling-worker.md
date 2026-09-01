# Phase 1B-C1 status: policy-gated profiling worker

- Status: Complete (repository-wide local release verification passed)
- Date: 2026-09-01
- Schema revision: `20260901_0012`
- Scope completed: deterministic CV/JD prompt registry, immutable processor-activity
  job snapshot, provider request correlation, pre-call privacy registration, fenced
  worker execution, fail-closed runtime wiring, PostgreSQL and release verification
- Next gate: Phase 1B-C2 (owner profile inspection and immutable correction)

## Implemented

- Code-owned CV/JD prompts have exact IDs/versions, strict output schemas, canonical
  instruction/schema digests, bounded output tokens, prompt-injection instructions, and
  no direct identity/contact output fields.
- `candidate_profiling_jobs.processor_activity_id` is mandatory for new jobs. Scheduling
  validates the active processor/activity, exact model-provider key, privacy policy,
  purpose/category, and origin region; divergent activity snapshots conflict.
- Migration `20260901_0012` refuses to upgrade a database with ambiguous existing jobs,
  adds the restrictive processor-activity foreign key, and extends immutable snapshot
  trigger protection. Downgrade also refuses while jobs exist.
- The job UUID flows through `ModelGatewayRequest` and `ModelProviderRequest` as the
  exact provider request/idempotency/deletion reference.
- Immediately before the provider call, the worker reauthorizes the processor activity
  and registers the job reference through the privacy lifecycle. The locator is stored
  encrypted with a keyed digest; policy revocation prevents the external call.
- The worker verifies prompt/schema/model snapshots before sending content, decrypts only
  the exact latest source revision, uses the strict model gateway, independently repeats
  evidence validation, persists through the encrypted profile boundary, and completes
  with the live UUID lease token.
- Safe provider failures use existing retry/dead-letter rules. Unexpected errors are
  content-free `internal_failure`; cancellation and stale leases cannot record a false
  result.
- Runtime execution remains separately disabled by default. Enabling it requires all
  upstream security boundaries and a gateway retry budget that fits inside the job lease.
- Privacy export schema is `phase-1b-c1` and includes the immutable processor activity
  identifier with safe profiling-job metadata.

## Deliberately not implemented

- No concrete provider SDK, endpoint, credential loader, vendor-specific adapter,
  continuous supervisor, or automatically started background loop is shipped.
- No public schedule/profile read route or owner profile-correction command is exposed.
- A passing strict schema/evidence check does not prove semantic quality or resistance to
  every prompt-injection strategy; labeled adversarial quality gates remain Phase 1B-D.

## Verification

- `./scripts/verify.ps1` passed with `524` tests, one platform-specific skip, and
  `95.09%` branch-aware coverage. Ruff lint/format, strict mypy for `82` source files,
  empty-database migration, migration round-trip/model parity, dependency compatibility,
  and the Python vulnerability audit all passed.
- Twenty-one focused worker tests cover deterministic CV/JD prompts, processor-before-
  provider ordering, request correlation, safe retry mapping, exact evidence rejection,
  release/source/profile conflicts, unexpected failure normalization, cancellation,
  stale lease fencing, and disabled runtime behavior.
- Two real PostgreSQL tests prove successful fake-provider execution through encrypted
  profile persistence and encrypted processor usage, plus provider revocation before the
  external call. Audit/outbox payloads remain content-free.
- The local database was migrated to `20260901_0012`. Logical backup/restore rehearsal
  passed with all profiling/profile constraints and triggers; the release image passed
  exact embedded schema head, non-root runtime, migration job, read-only/capability, and
  release metadata checks.

## Next part

Phase 1B-C2 exposes authenticated owner-scoped profile inspection and optimistic,
idempotent immutable correction without allowing edits to overwrite model history.
A real provider still requires an explicitly reviewed adapter, credential transport,
processor inventory/activity, and operational supervisor before activation.
