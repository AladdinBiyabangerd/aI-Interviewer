# ADR 0023: Owner profile inspection and immutable correction

- Status: Accepted
- Scope: Phase 1B-C2 only
- Date: 2026-09-01
- Depends on: ADR 0019 evidence contracts, ADR 0020 encrypted profile persistence,
  ADR 0021 profiling jobs, and ADR 0022 policy-gated execution

## Context

Phase 1B-C1 could produce a strictly validated encrypted CV/JD profile for one exact
source-text revision, but the owner could not see the durable job state or inspect and
correct the result. The persistence schema already reserved chained `user_correction`
versions. Exposing direct updates would have destroyed generated provenance, while
exposing a worker result before its lease-fenced success transition could have presented
an incomplete execution as final.

## Decision

1. One authenticated resource represents profiling state for an exact preparation,
   document version, and source-text version:
   `/preparations/{preparation_id}/document-versions/{document_version_id}/profiles/{source_text_version_id}`.
   `GET` requires `preparation:read`; `PUT` requires `preparation:write`. Every lookup
   includes the authenticated account and full lineage, so cross-owner and nonexistent
   resources share an opaque `404` response.
2. The read response exposes only bounded job status, attempt count, safe failure code,
   retryability, availability/completion timestamps, and the completed profile history.
   Worker IDs, lease tokens, processor locators, policy IDs, digests, ciphertext, nonces,
   raw provider detail, source text, and prompts are excluded. A profile is returned only
   after the job is durably `succeeded` and its result ID matches the exact profile.
3. Completed profile responses use `Cache-Control: no-store` and a strong ETag derived
   from the profile aggregate version. Active jobs return `Retry-After` without exposing
   a profile that may have been persisted but not yet lease-fenced as successful.
4. A correction is a strict CV or job-description profile, not an unrestricted patch.
   It must match the document type, pass the same extra-forbid schema, and revalidate
   every evidence quote and Unicode `[start,end)` span against the retained exact source
   revision inside the write transaction.
5. `PUT` requires a quoted positive `If-Match`. A stale aggregate returns `412`; a
   retry after exactly one successful append returns the existing correction only when
   the decrypted strict profile is identical. A changed retry cannot overwrite or append
   behind newer history.
6. Corrections append encrypted `candidate_profile_versions` rows with origin
   `user_correction`, the exact schema ID/version, predecessor ID, recomputed evidence
   counts, context-bound HMAC, and AES-256-GCM ciphertext. Provider/model/prompt fields
   remain null. The generated version and all prior corrections are never updated.
7. The command repeats active-account, draft/latest-source, privacy, legal-basis, and
   delete-only retention checks. Audit and outbox record only bounded provenance/counts
   and opaque IDs; the authenticated account is the audit actor. Profile content,
   evidence quotes, ciphertext, nonce, and digest are excluded.
8. Privacy export advances to `phase-1b-c2` and includes every decrypted and revalidated
   generated/corrected profile version. Existing account/document/source cascades erase
   the full lineage. The schema and database triggers from ADR 0020 already enforce the
   required correction shape and chain, so no new migration is introduced.
9. The profile routes join the reviewed product SLI population. This phase does not add
   a public scheduling command, provider adapter, credential, outbound call, or
   continuous worker supervisor.

## Consequences

The owner can safely see whether profiling is pending, retrying, complete, or terminal,
inspect exact generated provenance, and correct derived claims without losing history.
Consumers must explicitly select the latest profile version while retaining the
generated baseline for review and future quality measurement.

Phase 1B-D remains responsible for labeled Azerbaijani/English precision, recall,
source-span coverage, correction-rate, slice, and regression thresholds. C2 proves the
safe product contract, not semantic model quality.
