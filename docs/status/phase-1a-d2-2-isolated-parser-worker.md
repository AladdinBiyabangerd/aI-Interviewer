# Phase 1A-D2.2 status: isolated parser worker

- Status: Complete (local verification; PostgreSQL-backed checks pending Docker)
- Date: 2026-08-30
- Schema revision: unchanged from `20260828_0009` (no new tables or columns)
- Scope completed: versioned PDF/DOCX/TXT adapters, no-network/resource-bounded child
  process execution, and the worker that chains claim, read, isolate, and persist
- Next gate: Phase 1A-D3 owner inspection and correction

## Purpose

Run the exact approved parser adapter against exactly one released document version's
bytes, inside a child process that cannot reach the network, the database, object
storage, or the application keyring, and turn its result into either a D1 source-text
version or a closed D2.1 failure code.

## Implemented

- `ai_interviewer.extraction_runtime` is a new package, independent of
  `ai_interviewer.candidate_inputs`, containing only the adapters and the isolation
  boundary. Importing it never loads SQLAlchemy, boto3, cryptography, or FastAPI.
- `extraction_runtime.adapters` provides `isolated-pdf-parser`, `isolated-docx-parser`,
  and `isolated-text-parser` (version `1`), each a pure `bytes -> str` function backed by
  `pypdf` and `python-docx`. Output is normalized to the exact D1 content contract (LF
  newlines, no control/format/surrogate characters) and bounded to 500,000 characters.
  Encrypted PDFs, non-UTF-8 text, corrupt containers, and empty extracted text raise one
  of a closed set of typed errors.
- `extraction_runtime.isolation.run_isolated_extraction` runs the resolved adapter in a
  `multiprocessing` `spawn` child. The parent enforces a wall-clock timeout and
  classifies an unexpected exit as `parser_crashed` or (signal-killed, POSIX) as
  `resource_exceeded`. The child lowers CPU/memory/file-size resource limits (POSIX
  only), disables the socket module before running any adapter code, and refuses to
  continue if running as root.
- `ai_interviewer.candidate_inputs.extraction_worker.CandidateExtractionWorker` chains
  the three existing boundaries for one claimed job: `read_for_parser`, the isolated
  adapter, and `store_parser_extraction`, then calls `mark_succeeded` or `mark_failed`
  with the job's current lease token. Every failure path maps to the closed D2.1
  taxonomy; nothing but a fixed code and opaque IDs crosses into job state.
- mypy strict now type-checks against `platform = "linux"` (the only supported
  production target) so POSIX-only standard-library behavior (`resource`, `os.getuid`)
  is checked correctly regardless of the development OS.
- Dependencies: `pypdf` and `python-docx` were added; both are pure/near-pure Python
  with no native build requirements beyond the already-present `lxml` wheel.

## Deliberately not implemented

- No continuous supervisor process or CLI entrypoint drives the worker yet; it is an
  importable, directly testable unit, matching the existing `claim_deletion_tasks`
  precedent that also has no dedicated runner loop yet.
- No product route, owner inspection/correction, or export/deletion integration for
  worker-produced source text exists yet — that is Phase 1A-D3/D4.
- No true kernel-level sandboxing (seccomp, network namespaces, cgroups) is implemented;
  isolation is a separate `spawn` process with resource limits and a disabled socket
  module. Stronger OS-level isolation is an operational hardening decision for the
  container runtime, not an application-code decision.

## Verification

- Ruff lint and format, strict mypy (69 source files, Linux platform target), and the
  full non-integration unit suite pass locally: 324 passed, 1 skipped (a POSIX-only
  signal-kill test skipped on Windows), 0 failed.
- New unit coverage: adapter success/failure paths for all three formats including
  encrypted-PDF and empty/corrupt/oversized content; isolation success, timeout,
  crash, signal-kill (POSIX-only), network-disabled, and root-refusal behavior; worker
  orchestration success and all three failure-mapping paths (`source_unavailable`,
  the isolation-reported code, `policy_unavailable`), multi-job batches, and the
  defensive missing-lease-token guard.
- Two new integration tests exist (`tests/integration/test_extraction_worker.py`)
  covering an end-to-end success (text document, real encrypted D1 persistence) and an
  end-to-end failure (corrupt synthetic PDF fixture) through the real database, file
  security, and source-text services. Docker Desktop was unavailable during this
  handoff, so these tests currently skip locally; they must run against a disposable
  PostgreSQL instance before this phase is considered release-verified, matching the
  same gap Phase 1A-D2.1 recorded for its own PostgreSQL-backed checks.
- No new Alembic migration was required; this phase adds no tables or columns.

## Next part

Phase 1A-D3 (owner inspection and correction) can begin once this contract is accepted:
authenticated owner-scoped reads of source text, a safe display/download contract, and
an optimistic/idempotent immutable correction append. No AI processing may begin before
the owner-visible source text from this phase is available for review.

Stop here until the next explicit continuation request.
