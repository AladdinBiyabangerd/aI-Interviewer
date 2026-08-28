# ADR 0014: Durable candidate extraction jobs and lease fencing

- Status: Accepted
- Scope: Phase 1A-D2.1 only
- Date: 2026-08-28
- Depends on: ADR 0011, ADR 0012, ADR 0013, and the Phase 0C-C file-release contract

## Context

An approved clean document must be processed asynchronously before an untrusted parser
is allowed to run. A queue message alone cannot provide recovery, ownership, policy
provenance, or protection against a worker completing after its lease has expired. The
job record must therefore be durable and safe even when the parser process, queue, or
database connection fails.

## Decision

1. `candidate_extraction_jobs` contains at most one job for each exact
   `candidate_document_versions` row. Scheduling is idempotent and owner-scoped.
2. The job stores immutable snapshots of the document version, released file asset,
   parser policy, privacy policy, jurisdiction, legal basis, retention rule, media type,
   byte length, and source digest. It stores no file bytes, object keys, filenames, raw
   exception text, or extracted content.
3. A claim changes `pending`/`retry` to `processing`, increments a bounded attempt
   counter, records a five-minute lease, and assigns a fresh UUID fencing token. Claims
   use PostgreSQL `FOR UPDATE SKIP LOCKED` so competing workers do not process the same
   row concurrently.
4. Completion and failure require both the worker ID and the current lease token. A
   reclaimed or stale worker cannot mutate the job. Successful completion requires the
   matching D1 source-text aggregate to exist.
5. Failure codes are a closed, content-free taxonomy. Transient failures retry with a
   capped exponential delay until five attempts; unsupported, corrupt, encrypted, empty,
   and unavailable-policy input failures terminate without automatic replay.
6. Database checks enforce legal status/lease/result/error combinations. An insert-time
   snapshot trigger validates that the job matches the exact document and parser policy;
   composite owner foreign keys and an identity trigger prevent cross-owner or
   cross-document reassignment even if application code is bypassed.
7. Scheduling and transitions write only opaque IDs and bounded codes to audit/outbox
   records. A parser worker, adapter, network namespace, resource limits, and product
   route remain outside this decision and belong to D2.2.

## Consequences

The worker can crash and be safely retried without creating duplicate jobs or allowing
stale writes. A job may be retained until the exact document version is erased, so D4
must include job export/deletion and recovery evidence. The D2.2 worker must call the
existing `read_for_parser` boundary and D1 persistence service; it must not query object
storage or write source text directly.
