# Phase 1A-D1 status: encrypted immutable source-text domain

- Status: Complete
- Date: 2026-08-27
- Schema revision: `20260827_0008`
- Scope completed: internal encrypted source-text persistence only
- Next gate: Phase 1A-D2.2 isolated parser worker and bounded PDF/DOCX/TXT adapters

## Purpose

Create the secure and reproducible persistence boundary required before untrusted
document parsers can run. This subphase does not parse a file, expose extracted content
over HTTP, or invoke AI.

## Dependencies verified

- Phase 1A-B exact immutable document versions and same-owner database constraints.
- Phase 1A-C clean released asset and snapshotted parser-release policy.
- Phase 0C-B purpose/privacy/retention authorization and versioned application keyring.
- Phase 0C-C coordinated file-reference deletion.
- Phase 0D-A release-owned forward-only migration and restore contracts.

## Implemented modules

### Domain and cryptography

- `CandidateSourceText` provides one stable owner-bound aggregate per exact candidate
  document version.
- `CandidateSourceTextVersion` stores append-only encrypted revisions. The first revision
  must be parser output; the schema already reserves a strictly linked shape for later
  owner corrections without exposing that operation prematurely.
- Candidate text is AES-256-GCM encrypted with versioned application keys. AAD binds the
  complete identity, origin, parser provenance, counts, and keyed digest.
- The keyed content digest uses a separate subject-HMAC key and owner/document context.
  Neither plaintext nor an unkeyed extracted-text digest is retained.
- Content is bounded to 500,000 characters and 2,000,000 UTF-8 bytes, uses LF newlines,
  and rejects unsafe Unicode control/format/surrogate input.

### Processing-state validation

- Parser-result storage rechecks the active account, draft/unexpired preparation,
  latest exact document version, released owner-matched asset, byte/media/digest
  snapshots, delete-only retention, current purpose authorization, and exact active
  parser policy.
- Parser policy ID, adapter, version, isolation profile, media type, size allowance,
  malware-scan requirement, privacy policy, category, and purpose must all match.
- Exact retries return the existing encrypted lineage. A changed result or provenance
  conflicts instead of overwriting history.

### Database integrity and lifecycle

- Alembic revision `20260827_0008` creates `candidate_source_texts` and
  `candidate_source_text_versions` plus the owner/document composite key required by
  their foreign key.
- Database constraints enforce revision origin/provenance shape, bounds, encryption
  metadata completeness, owner lineage, and unique ordinals.
- A trigger prevents stable source identity reassignment; another rejects every text
  version update; a third verifies correction-chain predecessor order.
- `ON DELETE CASCADE` from the exact candidate document version ensures account erasure
  and coordinated file retention remove encrypted text as one lineage.
- A downgrade fails closed while any encrypted source text exists.
- Backup/restore inventory now tracks both tables, their indexes, constraints, and all
  three triggers.

### Operational metadata

- One content-free privacy audit event and one content-free outbox event are written in
  the same transaction as a new parser result.
- Audit/outbox metadata contains only opaque IDs and allowlisted parser/version/origin
  codes. It excludes content, ciphertext, nonce, keyed digest, counts, object keys, and
  document SHA-256.
- The application factory owns a fail-closed source-text runtime, but no route or worker
  can invoke it in this gate.

## Completion criteria and evidence

- Exact multilingual text encrypts, persists, decrypts, and round-trips without content
  loss.
- Plaintext is absent from the stored ciphertext and operational metadata.
- Exact retry is idempotent; different content or parser provenance fails closed.
- Cross-owner reads return opaque not-found behavior.
- Direct database updates to source identity or version content are rejected.
- Deleting the referenced file/document lineage removes both encrypted source tables.
- Unit validation, strict lint/format/type checks, real PostgreSQL migration tests, full
  regression tests, dependency checks, and vulnerability audit have passed locally:

  | Check | Evidence |
  |---|---|
  | Full test suite | 329 passed, including 47 real PostgreSQL integration tests |
  | Branch-aware coverage | 95.03% (required minimum: 95%) |
  | Strict typing | mypy passed for 63 source files |
  | Lint and format | Ruff check and format check passed |
  | Dependency/release checks | `uv pip check`, `pip-audit`, Alembic round-trip, and model parity passed at `20260827_0008` |

- The clean backup/restore rehearsal is still a release gate. It could not be rerun in
  this local handoff because Docker Desktop's PostgreSQL engine was unavailable. The
  rehearsal script and inventory are updated for both source-text tables, 27 indexes,
  86 constraints, and all three lineage triggers; it must pass on a running Docker
  engine before a production promotion.

## Deliberately not implemented

- No PDF, DOCX, or text parser dependency or execution.
- No parser subprocess/container, network namespace, CPU/memory/time/output budget, or
  worker execution.
- No inspection or correction HTTP endpoint.
- No PII-redacted representation, model call, prompt, profile, embedding, or RAG.
- No extracted-text export payload yet. The runtime is unreachable from product traffic;
  export/retention/recovery integration is a mandatory Phase 1A-D4 gate before parser
  execution is enabled for product use.

## Next part

Phase 1A-D2.1 has now frozen and implemented the durable job/lease/retry contract in
`candidate_extraction_jobs`. The next parser-execution gate is D2.2; before any adapter
is connected it must:

1. enforce no-network, read-only, non-root isolation and CPU/memory/wall/output limits;
2. fetch bytes only through `read_for_parser` with the exact released policy identity;
3. implement production PDF, DOCX, and UTF-8 text adapters as separately approved
  versions;
4. map corrupt, encrypted/password-protected, unsupported, timeout, resource, and empty
  output failures to bounded safe codes;
5. persist a successful result only through the D1 service and prove crash-safe retry.

Stop here until the next explicit continuation request.
