# ADR 0003: PostgreSQL persistence and transaction contract

- **Status:** Accepted
- **Date:** 2026-08-23

## Context

Candidate inputs, interview sessions, evaluations, source evidence, and deletion workflows will require strong ownership and transactional guarantees. The data model must remain understandable before retrieval/vector concerns are introduced. Asynchronous publication must not lose events when a database transaction succeeds but a broker call fails, and security/data-lifecycle audit records must not be silently rewritten.

## Decision

Use PostgreSQL 17 with SQLAlchemy 2 async sessions and Alembic migrations.

The local/containerized database is derived from the digest-pinned official Alpine image. It starts directly as the PostgreSQL UID with all Linux capabilities dropped, a read-only root filesystem, writable data and runtime mounts only, and `no-new-privileges`. The root-only `gosu` privilege-drop helper is removed because it is unreachable in this execution model; this also keeps known vulnerabilities in that unused binary out of the shipped image. Production should use a managed PostgreSQL service meeting the same or stronger isolation, TLS, backup, and recovery controls.

- Application-generated identifiers are UUIDv7; the database has an opaque UUID fallback for direct operational inserts.
- All future user-owned records carry a non-null `owner_id`. It intentionally has no foreign key until the Phase 0C identity aggregate is defined.
- Mutable aggregates use a version column and SQLAlchemy optimistic concurrency checks.
- Time is stored as timezone-aware timestamps; application and database operations use UTC.
- Application writes occur through an explicit transaction context.
- Cross-system events are inserted into `outbox_events` in the same transaction as future aggregate changes. Workers claim with `FOR UPDATE SKIP LOCKED`, bounded batches, leases, and explicit retry metadata.
- Security and lifecycle metadata is appended to `audit_events`. Database triggers reject UPDATE, DELETE, and TRUNCATE. Sensitive content keys are rejected before insert.
- PostgreSQL full-text search and `pgvector` are deferred to Phase 2; no vector schema or extension is installed in Phase 0B.

## Consequences

- Database availability becomes a readiness dependency, not a liveness dependency.
- A failed transaction rolls back both aggregate changes and its outbox event.
- Audit correction is represented by a new compensating event, never mutation.
- The outbox worker and broker are not selected or implemented yet; the durable handoff contract is ready for them.
- Production schema changes are roll-forward by default. Downgrades exist for disposable migration testing and require backup/recovery review before any data-bearing use.
