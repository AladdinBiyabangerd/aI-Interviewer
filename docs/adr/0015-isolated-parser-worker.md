# ADR 0015: Isolated parser worker and closed adapter taxonomy

- Status: Accepted
- Scope: Phase 1A-D2.2 only
- Date: 2026-08-30
- Depends on: ADR 0006, ADR 0013, ADR 0014, and the Phase 1A-D2.1 job contract

## Context

Phase 1A-D2.1 created a durable, fenced job record for exactly one document version but
deliberately ran no parser. An approved clean PDF/DOCX/text asset is still untrusted
content: a parser bug, a crafted document, or a resource-exhaustion attempt must never
reach the database, object storage, cryptography keyring, or the network from inside
parsing code.

## Decision

1. Text extraction lives in `ai_interviewer.extraction_runtime`, a package independent
   of `ai_interviewer.candidate_inputs`. Importing it never pulls in SQLAlchemy, boto3,
   cryptography, or FastAPI, so the isolated child process loads only the interpreter,
   `pypdf`, and `python-docx` — nothing that can reach a credential or a live
   connection.
2. Each adapter (`isolated-pdf-parser`, `isolated-docx-parser`, `isolated-text-parser`,
   version `1`) is a pure function: bytes in, sanitized Unicode text out, or one of a
   closed set of exceptions (`input_unsupported`, `input_corrupt`, `input_encrypted`,
   `input_empty`, `resource_exceeded`). Adapters never touch the filesystem, network, or
   database, so they can run unmodified inside the isolated child.
3. `run_isolated_extraction` runs the resolved adapter in a `multiprocessing` `spawn`
   child process, never `fork`, so the child never inherits open sockets, database
   connections, or threads from the caller. The parent enforces a wall-clock timeout,
   classifies an unexpected exit as `parser_crashed`, and classifies a signal-killed
   exit (POSIX) as `resource_exceeded`.
4. Inside the child, before any adapter code runs: process resource limits are lowered
   (CPU time, address space, and zero file-size, POSIX only, since the production
   target is the Linux container from ADR 0007), the socket module is replaced so any
   attempted network call raises immediately, and the process refuses to continue if it
   is running as root. Resource-limit enforcement is unavailable on native Windows
   development; the production and CI target is Linux.
5. The result crossing the process boundary is either sanitized text or one fixed
   string code — never a raw exception, traceback, or partial content. This preserves
   the content-free operational-metadata rule from ADR 0006 and ADR 0014.
6. `CandidateExtractionWorker` is the only caller allowed to chain the three existing
   boundaries: `claim_jobs`, `read_for_parser`, and `store_parser_extraction`. It maps a
   release-boundary failure to `source_unavailable`, an isolation failure to the child's
   own code, and a stale-policy conflict at persistence time to `policy_unavailable`,
   then calls `mark_succeeded` or `mark_failed` with the current lease token. It never
   queries object storage or writes source text directly.
7. mypy strict type-checks this codebase against the Linux platform (`platform =
   "linux"`) because that is the only supported production target; POSIX-only standard
   library modules must type-check even though local development happens on Windows.

## Consequences

A parser crash, hang, or memory blow-up now terminates or times out one isolated child
process; it cannot corrupt the worker's database session, hold a stale connection, or
exhaust the worker process's own memory. No product route, owner inspection/correction,
or continuous supervisor loop is introduced by this decision; `CandidateExtractionWorker`
is an importable, directly testable unit that a future operational entrypoint will drive.
PostgreSQL-backed verification of the end-to-end worker path (Phase 1A-D2.1's existing
gap) remains blocked on a locally available disposable database.
