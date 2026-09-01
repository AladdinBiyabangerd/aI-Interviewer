# ADR 0022: Policy-gated profiling execution

- Status: Accepted
- Scope: Phase 1B-C1 only
- Date: 2026-09-01
- Depends on: ADR 0018 model gateway, ADR 0019 evidence contracts, ADR 0020
  encrypted profiles, and ADR 0021 durable fenced profiling jobs

## Context

Phase 1B-B2.2 could durably coordinate an exact-source profiling job, but a provider
call still lacked two mandatory execution controls: a code-owned reproducible prompt
and an exact approved processor activity that could be reauthorized and registered for
deletion before candidate text crossed the external trust boundary. A generic worker
that trusted runtime provider settings alone would allow policy drift, untracked vendor
usage, or a stale release to receive candidate content.

## Decision

1. CV and job-description profiling use separate application-owned prompt IDs with
   immutable version `1.0.0`, strict schema IDs, canonical instruction/schema SHA-256
   digests, and a fixed maximum-output-token budget. The instructions treat the entire
   document as untrusted data, reject embedded commands, prohibit direct identity fields,
   and require exact Unicode source spans.
2. Every new profiling job must snapshot a non-null `processor_activity_id`. Scheduling
   requires the activity and its processor to be active, the processor key to equal the
   model provider, the privacy policy and origin/storage region to match the owner, and
   the data category/purpose to be `candidate_document/interview_preparation`.
3. Migration `20260901_0012` refuses to invent processor authorization for existing
   jobs. The new foreign key is restrictive and the existing snapshot-protection trigger
   makes the activity immutable.
4. The durable job UUID is also the provider request/correlation ID. The model-provider
   adapter contract must propagate it as the idempotency/deletion locator; arbitrary
   provider response metadata remains forbidden.
5. Immediately before each external attempt, the worker reauthorizes and registers the
   exact processor activity through the privacy lifecycle. The job UUID locator is
   stored only as AES-256-GCM ciphertext with a keyed digest. A suspended processor,
   policy mismatch, or unavailable privacy boundary dead-letters the job before the
   provider is called.
6. The worker validates the job against the current code-owned prompt and configured
   model release before decrypting/sending source text. It then calls the existing
   structured gateway, repeats application-owned exact-evidence validation, persists
   through the encrypted profile service, and commits success only with the same lease
   token. A lost lease returns a fenced outcome and cannot mutate job state.
7. Profiling execution has a separate disabled-by-default setting. Enabling it requires
   model gateway, privacy, and file-security boundaries, an explicitly injected provider
   adapter, and a worst-case gateway retry budget of at most 240 seconds inside the
   five-minute job lease.
8. Safe gateway failures map to the closed profiling-job taxonomy. Unexpected errors
   become `internal_failure`; cancellation propagates without committing a false
   failure. Candidate text, prompt text, model output, quotes, ciphertext, and raw errors
   remain absent from job, audit, outbox, log, and telemetry payloads.

## Consequences

The repository can execute a scheduled profiling job end to end when a reviewed adapter
and approved processor records are explicitly supplied, while the shipped configuration
still performs no outbound model call. Retries reuse one provider request/deletion
locator and one encrypted profile lineage, and processor revocation takes effect before
the next attempt.

This decision does not choose or implement a concrete provider SDK/credential transport,
start a continuous worker supervisor, expose public scheduling/profile routes, append
owner corrections, or claim semantic quality. Phase 1B-C2 adds owner profile inspection
and immutable correction; concrete provider activation and Phase 1B-D quality approval
remain separate reviewed gates.
