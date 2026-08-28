# Phase 1A-C completion record: authenticated upload and paste

- Status: Complete
- Completion date: 2026-08-27
- Schema revision: `20260827_0007`
- Next gated part: Phase 1A-D sandboxed extraction and user correction

## Scope completed

Phase 1A-C adds the first authenticated CV/job-description mutation boundary. A candidate
can send a bounded raw PDF, DOCX, or UTF-8 text upload, or paste UTF-8 text, to an owned
draft preparation. The command durably coordinates the already completed privacy,
file-security, scan/release, and immutable document-version services.

This is not a parser or AI feature. The application does not yet extract or persist
source text, redact PII, invoke a model, create an interview, evaluate an answer, or
generate a report.

## API contract

- `POST /api/v1/preparations/{preparation_id}/documents/{document_type}/upload`
  requires `preparation:write`, `Idempotency-Key`, and an allowlisted raw-body
  `Content-Type`.
- `POST /api/v1/preparations/{preparation_id}/documents/{document_type}/paste` requires
  the same scope/key and exact UTF-8 plain text.
- `GET /api/v1/preparations/{preparation_id}/document-intakes/{intake_id}` requires
  `preparation:read` and exposes only an owner-matched durable status.
- Encoded bodies, unsupported media, missing keys, invalid charsets, empty content,
  corrupt/signature-mismatched documents, and both declared/streamed oversized bodies
  fail through bounded problem responses.
- The service never accepts a browser filename or multipart field and never returns an
  object key, KMS identifier, policy record ID, request/content digest, processing token,
  or body content.

## Durable saga and recovery

- `candidate_document_intakes` stores a hashed owner-scoped idempotency key, canonical
  request digest, controlled request metadata, privacy/retention snapshot, exact reserved
  UUIDv7 asset, attempt count, five-minute lease/token, safe error, and completion IDs.
- Database constraints enforce state/error/completion consistency, reservation equality,
  owner/preparation integrity, digest shape, delete-only retention, and uniqueness of
  idempotency, reserved/current asset, and attached immutable version.
- An exact active retry returns `processing`; an expired claim can be recovered. Completed
  and rejected requests replay deterministically; a different request under the same key
  returns a conflict.
- Storage failure enters the existing durable asset cleanup path and rotates only the
  failed reservation. Scanner/read failure preserves the same quarantined asset. A
  post-attachment failure reuses the same released asset and the Phase 1A-B idempotent
  attach result, so no duplicate version is appended.
- Infected content is never released or attached. It yields a durable terminal rejection.

The rationale and rejected alternatives are recorded in
[ADR 0012](../adr/0012-durable-authenticated-document-intake.md).

## Privacy, retention, and deletion

- Export schema `phase-1a-c.1` includes safe owned intake metadata and excludes raw keys,
  digests, bytes, object locations, internal policy IDs, and lease tokens.
- Account deletion erases intakes, then document lineage, then preparation context. File
  objects remain a durable prerequisite for final account deletion.
- The file-deletion transaction releases both document-version and intake references
  before deleting an asset. Empty logical document aggregates are removed; surviving
  immutable lineage retains its correct latest ordinal.
- Status-only rejected intake rows can be removed by their stored due-retention deadline.
- Audit and outbox events contain only controlled document/source/status/error codes,
  attempt count, and opaque intake ID. Raw keys and candidate content are excluded.

## Migration and recovery

Alembic revision `20260827_0007` adds the intake table, three operational indexes, owner
and lifecycle foreign keys, unique saga/asset/version constraints, and controlled state,
digest, lease, completion, error, and retention checks.

A clean database upgraded through all seven revisions, and `alembic check` found no
missing operation. The backup/restore rehearsal passed at `20260827_0007`; it compared
all tracked source/restored row counts and verified 24 required tables, 25 selected
indexes, 57 selected critical constraints, both audit triggers, the immutable-version
trigger, and exact-schema readiness.

## Verification evidence

| Gate | Result |
|---|---|
| Dependency lock | `uv lock --check` passed |
| Lint and format | Ruff passed; 136 files formatted |
| Static typing | Strict mypy passed for 61 source files |
| Automated tests | 318 passed |
| PostgreSQL integration tests | 45 passed against an isolated real PostgreSQL database |
| Branch-aware coverage | 95.43%; required minimum 95% passed |
| Migration parity | Clean upgrade to `20260827_0007`; `alembic check` clean |
| Dependency compatibility | `uv pip check` passed for 72 installed packages |
| Python vulnerability audit | No known vulnerabilities found |
| Backup/restore | Passed with row-count, schema-object, trigger, and readiness checks |
| Local release image contract | Passed for `ai-interviewer-platform:phase1a-c`; embedded `0007`, baseline schema, and `10001:10001` verified |
| Local image ID / size | `sha256:0af6da9796ebf6166efb5181ecaeaf6020bdd93eb584f8bb795c42fc3c5da83d`; 72,842,201 bytes |

The new tests cover HTTP scopes/status/cache headers and safe errors; raw-body limits;
exact replay and conflicting reuse; upload/paste version append; owner isolation;
scanner retry; storage reservation rotation; infected/corrupt rejection; worker
cancellation and expired-lease recovery; post-attachment idempotent recovery; privacy
export/deletion; retention; and reference release before asset deletion.

Two defects were found and fixed during real-database testing. Updated optimistic rows
are explicitly refreshed before building a response, preventing async implicit I/O after
database-generated values expire. Asset rotation is now phase-aware: an early failed
storage reservation rotates, while a downstream failure reuses the released asset and
existing immutable version.

## Remaining limits

- The platform is not production-ready. The deferred live 28-day baseline, alerts,
  incident exercises, traffic/concurrency protection, provider IaC, PITR, capacity, and
  launch approval remain mandatory under ADR 0010 and the Phase 0D gates.
- The local image used a synthetic 40-character rehearsal revision because this
  worktree is not committed. It is not a promotable release. CI-owned Trivy scans,
  retained CycloneDX SBOM, real source SHA, registry digest, and approvals remain part
  of the later production gate.
- The current request executes synchronously. Its durable lease/status supports safe
  retry, but Phase 0D-D must validate topology, concurrency, overload, and queue choices
  before production traffic.
- There is no parser sandbox, extracted/source-text schema, PII-redacted representation,
  user correction, model call, or interview behavior.

## Next part

Phase 1A-D1 has now completed under
[ADR 0013](../adr/0013-encrypted-immutable-candidate-source-text.md). The remaining
order is:

1. implement the isolated parser adapter/version/resource/network contract;
2. execute only against released assets through the existing parser-release policy;
3. validate bounded PDF/DOCX/text extraction failure modes;
4. expose owner-scoped inspection and correction without invoking AI;
5. integrate privacy export, retention, deletion, audit, and recovery;
6. complete real-database, sandbox, security, and migration verification.
