# ADR 0028: disabled-by-default worker supervision

- Status: Accepted
- Date: 2026-09-01
- Scope: operational execution of existing extraction and profiling job contracts

## Context

The extraction and profiling domains already supplied durable job claiming, bounded
retry, dead-letter state, UUID lease fencing, and single-batch `run_once()` workers.
However, extraction was not wired into the application runtime and no standalone
process could drain either queue. Starting work inside the API lifespan would couple
request serving to expensive parser/provider activity and make activation implicit.

Profiling has additional legal, privacy, processor, model-release, and quality gates.
Adding a process must not turn the existence of worker code into permission to execute
candidate data or make an external provider call.

## Decision

1. Extraction and profiling retain independent disabled-by-default configuration flags
   and bounded worker identities. An eligible worker is still inert unless the separate
   worker process is explicitly started.
2. Extraction worker construction is part of the normal application composition so it
   uses the exact database, secure-file read, source-text, privacy, and lifecycle
   boundaries already reviewed for the API.
3. `ai-interviewer-workers --once` performs one bounded operator sweep. Without
   `--once`, the same command polls continuously using bounded batch, idle-poll, and
   runtime-error-backoff settings.
4. The supervisor attempts enabled worker types independently. A runtime failure in one
   worker does not starve the other. Cancellation propagates and the application
   lifespan closes database and telemetry resources on termination.
5. Lease-transition conflicts are safe `fenced` outcomes. They do not crash extraction
   supervision or overwrite the winning worker's state.
6. Supervisor logs contain only fixed worker names, bounded status counts, and exception
   class names. Candidate text, profile content, identifiers, paths, object keys,
   provider bodies, and exception messages are excluded.
7. The API process does not start the supervisor. No configuration default enables a
   worker, model gateway, provider request, or processor activity.

## Consequences

The existing queues can now be operated and tested through one release-owned process,
including a deterministic one-sweep health check. Deploying that process and enabling
either worker remain explicit operational decisions. Profiling activation still cannot
precede the Phase 1B-D2.2b2 quality evidence, named approval, and activity-specific legal
and processor authorization required by the roadmap.

No schema migration, credential, live provider call, or new candidate-data category is
introduced by this decision.
