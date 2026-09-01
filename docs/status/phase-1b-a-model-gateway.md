# Phase 1B-A status: provider-neutral model gateway

- Status: Complete (repository-wide local verification passed)
- Date: 2026-08-31
- Schema revision: unchanged from `20260828_0009`
- Scope completed: strict provider port, reproducible execution identity, bounded
  retries/timeouts, fail-closed configuration, payload-safe representations
- Next gate at completion: Phase 1B-B1 evidence contracts (now implemented)

## Implemented

- `model_gateway` exposes strict request, provider, result, and error contracts without
  importing a provider SDK.
- Provider/model/version and prompt/schema identities are bounded. The returned model
  release must exactly match the configured release.
- Every output model inherits a frozen, strict, extra-forbid base. The application
  generates the JSON schema, passes it to the adapter, and validates returned JSON
  independently.
- The successful result includes exact model/prompt coordinates plus canonical
  instruction and schema SHA-256 digests.
- Attempts, per-attempt timeout, exponential retry delay, input characters, output
  characters, and requested output tokens are bounded. Retryability is a closed enum.
- Disabled execution fails closed. Enabled settings without all release coordinates or
  application composition without an explicit adapter fail before a call can occur.
- Sensitive instructions, CV/JD text, output schema, and raw model output are omitted
  from `repr`; raw provider exception details are never propagated.

## Deliberately not implemented

- No provider SDK, API endpoint, credential setting, model routing, fallback model,
  production processor registration, or outbound model call exists.
- No CV/JD profile schema, profiling table/job/worker, source-span verifier, correction
  route, privacy export, retention handler, or dead-letter queue exists yet.
- Model dependency metrics and cost/token accounting wait for a real adapter contract;
  content must remain excluded when those signals are introduced.

## Verification

- Focused gateway/config tests cover strict valid output, malformed JSON, coercion and
  extra-field rejection, release mismatch, filtered/truncated/oversized responses,
  safe provider failures, timeout, cancellation, exponential retry, disabled behavior,
  payload-free representations, builder wiring, and configuration validation.
- `./scripts/verify.ps1` passed: `443` tests passed, one Windows/POSIX-specific signal
  test skipped, and branch-aware coverage was `95.21%`.
- Ruff lint/format, strict mypy for `73` source files, empty-database migration, Alembic
  model-drift checks, dependency compatibility, and the Python vulnerability audit all
  passed. The schema revision remains `20260828_0009`.

## Next part

Phase 1B-B1 now defines application-owned CV and JD profile schemas where every
extracted claim references an exact source-text span. Phase 1B-B2 adds durable
owner/policy/source lineage and job fencing before any model adapter or product route
is enabled.
