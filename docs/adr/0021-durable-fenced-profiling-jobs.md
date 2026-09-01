# ADR 0021: Durable fenced profiling jobs

- Status: Accepted
- Scope: Phase 1B-B2.2 only
- Date: 2026-09-01
- Depends on: ADR 0018 model gateway, ADR 0019 evidence-linked profile contracts,
  and ADR 0020 encrypted candidate-profile persistence

## Context

Phase 1B-B2.1 could persist a verified encrypted CV/JD profile for one exact corrected
source revision, but it had no durable execution coordinator. Enabling a provider-backed
worker without idempotent scheduling, immutable release and policy snapshots, lease
fencing, bounded retry, and a terminal failure state would allow crash recovery,
duplicate workers, or stale results to detach a profile from the source and decision
that authorized it.

## Decision

1. One `candidate_profiling_jobs` row represents the only profiling attempt stream for
   one immutable `candidate_source_text_versions` row. It also binds the matching owner,
   preparation, document version/type, and source aggregate. Exact rescheduling is
   idempotent; any release or policy drift conflicts.
2. Scheduling snapshots the approved privacy policy, jurisdiction, legal basis,
   delete-only retention rule/deadline, provider/model/version, prompt/version, schema
   ID/version, canonical instruction/schema SHA-256 values, and maximum output tokens.
   These coordinates cannot be reassigned after insertion.
3. The state machine is `pending -> processing -> retry|succeeded|dead_letter`, with
   `retry -> processing` for another attempt. Workers claim eligible rows using
   `FOR UPDATE SKIP LOCKED`, database time, and a fresh UUID lease token. Every
   processing mutation requires the current unexpired token.
4. A claim lasts five minutes. An expired claim is recoverable, but it still consumes an
   attempt. At most five claims are allowed. Retryable safe failures use exponential
   backoff starting at 60 seconds and capped at 3600 seconds; non-retryable or exhausted
   work enters explicit `dead_letter` state.
5. Failure state uses only a closed content-free taxonomy. Candidate text, prompt text,
   provider output, exact quotes, raw exception/provider detail, profile ciphertext,
   nonce, and keyed digest material never enter job, audit, outbox, log, or telemetry
   payloads.
6. A job can become `succeeded` only by referencing an encrypted candidate profile that
   matches the same owner, document/source/revision, and exact model/prompt/schema
   release coordinates. A stale worker or mismatched profile cannot finalize the job.
7. Database constraints plus four triggers validate insert snapshots, protect immutable
   identity/release/policy fields, enforce state transitions, and validate successful
   profile linkage independently of application code.
8. Owner privacy export includes safe profiling-job metadata under schema
   `phase-1b-b2.2`. Account, preparation, document-version, source-aggregate, and exact
   source-revision cascades erase the job.

## Consequences

The repository now has a durable, crash-recoverable, and race-safe execution contract
for exact-source profiling. A future provider worker can use it without inventing its
own idempotency, retry, or result-lineage rules. Operational evidence remains useful
without becoming another store for candidate or provider content.

This decision does not add a provider SDK/adapter, credential, endpoint, outbound model
call, continuous worker supervisor, public profile route, or correction workflow.
Phase 1B-C must add a reviewed provider-backed worker and preserve every snapshot,
fencing, evidence-validation, and processor-policy boundary defined here.
