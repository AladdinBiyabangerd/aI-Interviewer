# Phase 0B Completion Record - Persistence and Transaction Foundation

- **Status:** Complete
- **Completed:** 2026-08-23
- **Next authorized unit:** None until user review
- **Next proposed unit:** Phase 0C - Identity, privacy, and file-security foundation

## Delivered scope

- Digest-pinned PostgreSQL 17.11 local environment, hardened as a non-root, capability-free, read-only-root service
- Typed database configuration with production TLS/credential safeguards and bounded pool, connection, statement, and readiness timeouts
- SQLAlchemy 2 async engine/session lifecycle and explicit atomic transaction boundary
- Alembic baseline migration with naming conventions and model/migration drift detection
- UUIDv7 application identifiers, UTC timestamp, non-null owner, and optimistic-concurrency conventions for future aggregates
- Transactional outbox enqueue, competing-worker `SKIP LOCKED` claim, lease recovery, bounded batch, retry, and publish operations
- Append-only audit metadata with database-enforced UPDATE/DELETE/TRUNCATE rejection
- Recursive operational-metadata guards for known candidate-content and credential fields
- Real PostgreSQL integration tests for rollback, competing workers, stale writes, migration round trips, audit immutability, and application readiness
- Automated isolated backup/restore rehearsal with revision, row-count, table, index, constraint, trigger, immutability, and readiness validation
- Cross-platform API and migration runners compatible with async PostgreSQL on Windows and Linux
- Updated CI, threat model, data inventory, ADR, recovery runbook, and local verification workflow

## Review findings fixed during this unit

1. The initial async migration and server checks used Windows' incompatible Proactor loop. Migration, test, readiness, and API process entrypoints now select a psycopg-compatible loop and have regression coverage.
2. Explicit Alembic check-constraint names were initially passed through the naming convention twice. Final names are marked as resolved, and `alembic check` reports no drift.
3. The first restore rehearsal assumed an existing audit row and used an unsupported long `rm` flag in Alpine. It now inserts an isolated recovery-only probe and verifies cleanup with the supported exact path.
4. The official PostgreSQL image contained an unused `gosu` binary with high/critical Go runtime findings. The final derivative starts directly as PostgreSQL UID/GID 70, removes that unreachable helper, drops every capability, uses a read-only root filesystem, and rescans cleanly.
5. The cross-platform process entrypoint initially lacked direct tests. Normal loop selection and operator-interrupt behavior are now covered.

## Final verification evidence

| Check | Result |
|---|---|
| Lock consistency | `uv lock --check` passed |
| Lint and formatting | Ruff checks passed |
| Static typing | Strict mypy passed for 16 source files |
| Automated tests | 47 passed against a disposable real PostgreSQL database |
| Coverage | 98.35% branch-aware coverage; 95% gate passed |
| Migration behavior | Empty upgrade, downgrade/upgrade round trip, repeat upgrade, and drift check passed |
| Transaction/concurrency | Rollback, competing outbox workers, lease retry, publish ownership, and optimistic stale-write tests passed |
| Audit protection | Repository content guard and database UPDATE/DELETE/TRUNCATE rejection passed |
| Dependency integrity | `uv pip check` passed; pinned `pip-audit` reported no known vulnerabilities |
| Backup/restore | Isolated custom-format restore passed at revision `20260823_0001`; source/restored operational counts matched; 2 audit triggers and application readiness verified |
| API container | Built from pinned Python Alpine digest; UID/GID `10001:10001`; liveness, readiness, and real database check passed |
| PostgreSQL container | UID/GID `70:70`; read-only root, all capabilities dropped, `no-new-privileges`; persisted data survived hardened-image recreation |
| Runtime image scans | API and hardened PostgreSQL images each reported 0 high/critical findings |

## Intentionally absent

No account/authentication aggregate, authorization policy, consent, retention/deletion job, encrypted object storage, upload handling, CV/JD schema or parser, broker/worker process, interview logic, model call, evaluator, RAG/vector schema, frontend, voice, video, or integrity signal was introduced.

The outbox is a durable transaction contract, not a partially implemented message broker. Ownership is a schema convention, not a claim that authorization exists. Both distinctions prevent later phases from relying on controls that have not yet been built.

## Next part: Phase 0C

Phase 0C should establish the identity and privacy boundary before the product receives candidate data:

- standards-based authentication and deny-by-default owner authorization;
- consent records and approved retention classes;
- export, deletion, backup-expiry, and derived-data lineage workflows;
- production secret management;
- encrypted object storage plus upload validation, quarantine, and malware scanning;
- cross-user, deletion, unsafe-file, and sensitive-log tests.

It depends on explicit launch-geography privacy/legal decisions and is not started by this completion record.
