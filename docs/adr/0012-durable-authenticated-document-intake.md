# ADR 0012: Durable authenticated document intake

- Status: Accepted
- Date: 2026-08-27
- Decision owners: application, data, privacy, security, and operations engineering
- Scope: Phase 1A-C only

## Context

Phase 1A-B established immutable CV/job-description lineage, but intentionally exposed
no public mutation. Phase 1A-C must accept highly sensitive PDF, DOCX, or UTF-8 text,
pass it through the existing quarantine and malware-scan authority, and attach exactly
one released asset version. A request can be interrupted between those systems. HTTP
retries, process termination, scanner unavailability, object-store failure, and a
response lost after the document transaction must not create duplicate assets or
document versions.

The intake boundary must also avoid collecting metadata that the product does not need.
Browser filenames, multipart field names, raw idempotency keys, body bytes, object keys,
and extracted text are not required to coordinate this phase and should not enter
PostgreSQL, audit, outbox, logs, telemetry, or API responses.

## Decision

1. Upload and paste use an authenticated raw-body HTTP contract. Upload accepts only
   allowlisted media types; paste accepts only `text/plain` with absent or exact UTF-8
   charset. Content encoding is rejected, both declared and streamed body length are
   bounded, and no filename is accepted or retained.
2. Every submission requires an 8-128 character `Idempotency-Key`. PostgreSQL stores
   only its SHA-256 digest, unique per owner. A separate request digest binds the owned
   preparation, controlled document type/source, normalized media type, and content
   SHA-256. Reusing a key with a different request is a conflict.
3. `candidate_document_intakes` is the durable saga authority. It snapshots owner,
   preparation, policy/jurisdiction/legal basis, delete-only retention, request metadata,
   reserved asset ID, attempt count, processing lease/token, safe error code, and final
   document/version IDs. It never stores body bytes, original filename, object locator,
   raw idempotency key, or extracted text.
4. The controlled states are `processing`, `scan_failed`, `rejected`, and `completed`.
   `processing` requires both a bounded five-minute lease and an opaque processing
   token; non-processing states permit neither. `scan_failed` is retryable, `rejected`
   is terminal for that exact request, and `completed` identifies the immutable version.
5. A claim reserves a UUIDv7 file-asset ID before external storage work. File staging
   accepts that exact ID and resumes only when owner, policy, purpose/category, media,
   length, digest, parser-release policy, retention, and state still match. This closes
   the database/object-store gap without a second content authority.
6. Account locking serializes an owner's claim creation with the owner-scoped unique
   idempotency constraint. An active unexpired claim returns its durable status instead
   of running the pipeline twice. An expired lease may be claimed with a new token and
   incremented attempt count.
7. Object-store upload failure marks the attempt retryable and rotates the reservation,
   because the failed asset is already on its durable deletion path. Scan failure keeps
   the same quarantined asset for a later retry. A failure after an asset is released or
   even after its document version is attached keeps the same reservation; the existing
   attach contract then makes recovery idempotent rather than appending a duplicate.
8. Only a clean `released` asset reaches the Phase 1A-B attach boundary. Infected or
   otherwise unsafe content becomes a terminal safe rejection. Changes to account,
   preparation, privacy, parser, ownership, or retention state fail closed.
9. HTTP status follows durable state: new completion is `201`, completed replay is
   `200`, processing/retryable scan failure is `202` with `Retry-After`, terminal input
   rejection is `422`, and state/idempotency conflict is `409`. Responses include an
   owner-scoped status location, aggregate ETag, and `no-store` cache control.
10. Privacy export includes only intake metadata under schema `phase-1a-c.1`. Account
    erasure removes intake rows before document lineage and preparation context. File
    deletion releases both immutable-version and intake references in its transaction;
    due intake retention also removes status-only rows that have no surviving asset.

## Consequences

- A client can safely retry the exact body and key after timeout, scanner outage, worker
  cancellation, storage failure, or a lost post-attachment response.
- The synchronous API call currently drives the bounded pipeline, but correctness does
  not depend on the process surviving. The stored lease/status is deliberately suitable
  for a later queue worker without changing the public idempotency contract.
- Locking the account serializes intake claims for one owner. This is intentionally
  conservative for the current MVP; Phase 0D-D load evidence must justify any narrower
  distributed-concurrency design before production traffic.
- Rejected bodies retain minimal status metadata until its policy snapshot expires so
  exact retries remain deterministic; the invalid body itself is never retained.
- Original bytes live only in the file-security object boundary and remain subject to
  its durable version-aware deletion workflow.
- This phase does not execute a parser, persist extracted/source text, redact PII,
  invoke a model, or expose a correction UI. Those remain Phase 1A-D or later work.

## Rejected alternatives

- Multipart upload with a client filename: collects unnecessary user-controlled
  metadata and complicates canonical idempotency without product benefit.
- In-memory retry coordination: loses state on restart and cannot distinguish a lost
  response from a request that never committed.
- Creating an arbitrary new asset on every retry: can orphan objects and append duplicate
  immutable versions.
- Storing the raw idempotency key or body in PostgreSQL: expands the sensitive-data and
  credential-like metadata boundary without a recovery need.
- Parsing immediately after scan: crosses the explicit Phase 1A-D sandbox and user
  correction gate.

