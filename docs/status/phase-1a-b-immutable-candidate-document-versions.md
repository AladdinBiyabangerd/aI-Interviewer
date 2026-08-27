# Phase 1A-B completion record: immutable candidate document versions

- Status: Complete
- Completion date: 2026-08-27
- Schema revision: `20260827_0006`
- Next gated part: Phase 1A-C authenticated upload and paste

## Scope completed

Phase 1A-B introduces the product-domain identity and immutable metadata lineage for a
candidate's CV and job description. It deliberately consumes the Phase 0C-C file
security boundary instead of duplicating object-storage or scan state. A version can be
attached only after its exact owner-matched asset is clean and released under the
approved parser policy and current delete-only privacy decision.

This phase does not add a public upload or paste command, parser execution, extracted
text, correction UI, model request, interview behavior, evaluation, or report.

## Domain and database contract

- One preparation can own at most one logical `cv` and one logical
  `job_description` aggregate.
- Every accepted replacement appends a UUIDv7 `candidate_document_versions` row with a
  stable ordinal. Earlier versions are never rewritten.
- Each version references exactly one file asset and snapshots source kind, media type,
  byte length, SHA-256, parser-release policy, privacy policy, jurisdiction, legal basis,
  retention rule, deadline, and delete-only action.
- Composite foreign keys enforce the same owner across preparation, logical document,
  immutable version, and file asset. Unique constraints prevent asset reuse and duplicate
  ordinals even if future code bypasses the service.
- A PostgreSQL trigger rejects every update to an immutable version with SQLSTATE
  `55000`. Explicit deletion remains possible for privacy and retention compliance.
- The logical document remains a mutable aggregate only for `latest_version_number`,
  `updated_at`, and optimistic `version` progression.

The rationale, rejected alternatives, and consequences are recorded in
[ADR 0011](../adr/0011-immutable-candidate-document-lineage.md).

## Service and API behavior

- The internal attach service locks account, preparation, file asset, and logical
  document state before appending. It requires an active account, a draft owned
  preparation, an owner-matched released asset, compatible category/purpose, unexpired
  retention, exact release metadata, and a matching current privacy decision.
- Retrying the same asset against the same type/source is idempotent. Reusing it for a
  different preparation, type, or source is a conflict.
- Audit and outbox evidence contains only canonical type/source/media metadata, ordinal,
  and opaque IDs. It excludes company/role text, document digest, object keys, and bytes.
- `GET /api/v1/preparations/{preparation_id}/documents` lists owned lineage metadata.
- `GET /api/v1/preparations/{preparation_id}/documents/{document_id}` returns one owned
  lineage and a strong ETag based on the aggregate version.
- Both routes require `preparation:read`. Missing and cross-owner resources are opaque
  `404` responses; a disabled boundary returns `503` without dependency details.

There is intentionally no document mutation route in this phase. Phase 1A-C will own
the authenticated upload/paste HTTP contract and call the completed internal attach
boundary only after validation, quarantine, scan, and release succeed.

## Privacy, retention, and deletion

- Owner export schema is now `phase-1a-b.1` and includes preparation-scoped document
  lineage metadata without storage bucket/key, KMS key, or internal legal record IDs.
- Account deletion erases document lineage before preparation context. This avoids
  losing explicit document counts through the preparation's database cascade.
- File object deletion remains durable and happens before final account deletion.
- Immediately before an asset row is deleted, the file worker invokes the narrow
  document-reference lifecycle adapter in the same database transaction. The referenced
  immutable version is removed; an empty logical aggregate is deleted, otherwise its
  latest surviving ordinal is recomputed.
- The same erasure ordering is applied during backup deletion-ledger replay.

## Migration and recovery

Alembic revision `20260827_0006` adds:

- `candidate_documents` and `candidate_document_versions`;
- owner-matching unique/composite foreign-key support on preparations and file assets;
- document/type, asset, ordinal, digest, retention, and controlled-code constraints;
- owner/preparation and document/creation indexes;
- the `candidate_document_versions_reject_update` trigger and its function.

A clean database upgraded through all six revisions. `alembic check` reported no missing
upgrade operation. The backup/restore rehearsal passed at `20260827_0006`, compared all
tracked source/restored row counts, found all 23 required tables, 22 required indexes,
47 selected critical constraints, both audit triggers, and the document-version update
trigger, then passed exact-schema database readiness.

## Verification evidence

| Gate | Result |
|---|---|
| Dependency lock | `uv lock --check` passed |
| Lint and format | Ruff passed; 127 files formatted |
| Static typing | Strict mypy passed for 57 source files |
| Automated tests | 290 passed |
| PostgreSQL integration tests | 37 passed against the real project PostgreSQL image |
| Branch-aware coverage | 95.47%; required minimum 95% passed |
| Migration parity | Clean upgrade to `20260827_0006`; `alembic check` clean |
| Dependency compatibility | `uv pip check` passed for 72 installed packages |
| Python vulnerability audit | No known vulnerabilities found |
| Backup/restore | Passed with exact revision, row counts, schema objects, triggers, and readiness |
| Release image contract | Passed for `ai-interviewer-platform:phase1a-b` as UID/GID `10001:10001` |
| Runtime image digest | Local Linux manifest `sha256:83d5166ba0e50ccc7460df11c8cbaf90967fdae7e894f5513508a42f4c750a8b` |
| Runtime image size | 72,814,601 bytes |
| Vulnerability scan | Refreshed 2026-08-27 Trivy DB; API and PostgreSQL images both reported 0 HIGH/CRITICAL |
| CycloneDX rehearsal SBOM | Valid JSON with 91 components |

The first full-suite run exposed test-state contamination: two new tests retained
synthetic assets long enough for a later global retention sweep to find them. The tests
were corrected to delete their own assets through the real durable retention workflow,
then the candidate-document plus file-security integration subset and the complete suite
both passed. No production behavior was weakened to accommodate the test.

## Review and remaining limits

- No original document byte is stored in PostgreSQL.
- No object key, filename, candidate text, or extracted text is returned by the document
  metadata routes or added to audit/telemetry.
- Immutability is enforced at the database, while explicit privacy/retention deletion is
  still supported.
- File deletion cannot violate the document-version foreign key because the product
  reference is released first in the same transaction.
- The runtime still fails closed unless both privacy and file security are enabled.
- This completes only Phase 1A-B. The platform is not production-ready; deferred hosted
  reliability, traffic/resource protection, IaC, recovery, and launch gates under
  ADR 0010 remain mandatory before production.

## Next part

Phase 1A-C will add only authenticated upload and paste intake. Its dependency order is:

1. define bounded request/idempotency/status/error contracts;
2. authorize owner, preparation, purpose, and privacy decision;
3. validate and stage bytes through quarantine;
4. scan and release under the exact file policy;
5. attach the released asset through the completed immutable lineage service;
6. verify replacement, retry, corrupt/password-protected/oversized input, cross-owner,
   scan-failure, and deletion behavior.

Phase 1A-D parsing and extracted-text correction must not begin until 1A-C completes.
