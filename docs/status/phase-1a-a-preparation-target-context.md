# Phase 1A-A completion record — preparation target context

- **Status:** Complete within the bounded preparation-context scope
- **Completed:** 2026-08-26
- **Current stop:** Before Phase 1A-B immutable candidate document versions

## Purpose and boundary

Phase 1A-A establishes the authenticated, owner-bound context that later CV/JD and
interview workflows will use: target company, role family/title, seniority, country,
optional office, interview round, and AZ/EN language.

This unit does not accept or store document bytes and does not implement upload,
paste, parsing, extracted text, model calls, interview sessions, scoring, or reports.
Those capabilities remain separately gated; no placeholder implementation was added.

## Delivered

- A `candidate_preparations` aggregate with UUIDv7 identity, exact owner FK,
  `draft/archived` lifecycle, UTC timestamps, optimistic version, privacy/legal basis
  snapshot, delete-only retention snapshot, and owner-scoped idempotency digest.
- Controlled role-family, seniority, interview-round, and AZ/EN language codes with
  strict, separate `other` fallback fields. Company, role, location, and fallback text
  are NFKC-normalized, trimmed, length-bounded, and reject Unicode control, format,
  and surrogate categories. Country is exactly two uppercase ASCII letters.
- A fail-closed service layer for idempotent create, bounded UUIDv7 keyset listing,
  owned detail, full replacement, archive, privacy export/erasure, and due retention.
- Atomic `INSERT ... ON CONFLICT DO NOTHING` creation. The same owner/key and same
  normalized input returns the existing record; a different input conflicts.
- Content-free append-only audit and transactional outbox events. Only canonical
  codes/status, opaque resource ID, and version are emitted; user company, role,
  office, and fallback text are excluded.
- Privacy authorization for exact `candidate_preparation_context` /
  `interview_preparation` processing, with missing/denied/non-delete decisions failing
  closed. Export schema is versioned as `phase-1a-a.1`; local rows are erased during
  account-deletion initiation and restore deletion-ledger replay.
- Alembic revision `20260826_0005`, including database checks, critical indexes,
  owner cascade, privacy-policy/retention-rule references, and unique owner/idempotency
  enforcement.

## HTTP contract

| Method and route | Authorization and concurrency behavior |
|---|---|
| `POST /api/v1/preparations` | `preparation:write`, bounded `Idempotency-Key`; `201` new / `200` exact retry; ETag |
| `GET /api/v1/preparations` | `preparation:read`; bounded `limit <= 100`, UUIDv7 keyset cursor |
| `GET /api/v1/preparations/{id}` | `preparation:read`; owner-only opaque lookup; ETag |
| `PUT /api/v1/preparations/{id}` | `preparation:write`; full replacement and strong positive `If-Match` |
| `POST /api/v1/preparations/{id}/archive` | `preparation:write`; archive state transition and strong positive `If-Match` |

Missing `If-Match` returns `428`, malformed input returns `400`, a stale version
returns `412`, invalid preparation input returns opaque `422`, state/idempotency
conflict returns opaque `409`, and cross-owner/missing records share opaque `404`.

## Verification evidence

- `282` tests pass under Python 3.12, including `33` real-PostgreSQL integration
  tests. Branch-aware coverage is `95.64%`, above the mandatory `95%` gate.
- Ruff lint/format and strict mypy pass for `54` source files. Alembic upgrade on an
  empty database and model-drift check pass; the graph has exactly one head.
- Dependency lock and compatibility checks pass. `pip-audit` reports no known Python
  package vulnerability.
- Restore rehearsal passes at `20260826_0005`: all tracked source/restored row counts
  match, `21` required tables, `20` critical indexes, `34` critical constraints, and
  `2` audit immutability triggers are present. The final local backup checksum is
  `49b6d5a34be2361d81c0d3f8b2aa9c3f71f8456ebc04f975d56aa1c61f09786a` and the run
  took `13.55s`; the recovery database and dump were removed.
- `ai-interviewer-platform:phase1a-a` passes OCI identity, embedded schema, baseline
  contract, and numeric `10001:10001` checks. Its local Linux/amd64 rehearsal digest
  is `sha256:6967cd69f79a99dc4a82636bd46246c0adea2318ad627f8fff0886a3ac07bec7`.
- The image itself migrates a clean database to `20260826_0005`, then reaches HTTP
  readiness with a read-only root filesystem, all capabilities dropped, and
  `no-new-privileges`; a query canary is absent from logs.
- Trivy reports `0 HIGH/CRITICAL` vulnerabilities in both the API and hardened
  PostgreSQL images. The final PostgreSQL local digest is
  `sha256:2816e23ff3904ee43bf5b7bb028cf1707a7747fa63ed0e9c35106ac5ef6d9dcc`.
  CycloneDX generation produces a valid `91`-component SBOM.

The local release revision used for rehearsal is a synthetic 40-character value,
not a Git commit or production release attestation.

## Review findings fixed before completion

- A retention integration fixture initially placed `created_at` before the synthetic
  policy effective date. The fixture now creates a legally valid record and advances
  its timestamps/deadline consistently before testing due deletion.
- OneDrive rejected `uvx` cache hardlinks during dependency audit. Verification now
  temporarily uses `UV_LINK_MODE=copy` only for audit-tool installation and restores
  the caller's setting afterward; the audited environment is unchanged.
- Restore rehearsal initially queried the new table from a source database still at
  the previous revision. The script now verifies source revision against the
  release-owned schema contract before any schema-specific query and fails with an
  actionable migration message.
- Final code review found that a leading/trailing newline could be removed before the
  control-category check. Normalization now rejects control/format/surrogate
  characters before trimming, with a regression test for trailing newline input.
- The vulnerability gate found `CVE-2026-14456` in the pinned Alpine base layers.
  API and PostgreSQL runtime builds now pin patched `libcrypto3` and `libssl3`
  `3.5.8-r0`; both images were rebuilt, rescanned, and regression-tested.

## Deferred and mandatory later work

- Phase 1A-B: immutable owner-bound CV/JD document versions and deletion lineage.
- Phase 1A-C: authenticated upload/paste connected to quarantine, scan, and release.
- Phase 1A-D: no-network, resource-bounded parsing and user-correction lineage.
- No real legal policy, country enablement, cloud bucket/KMS/scanner, or production
  identity/configuration has been provisioned.
- Under [ADR 0010](../adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md),
  0D-C-B2 through 0D-E are deferred until the text MVP contract is feature-stable.
  The real 28-day staging window, named approvals, alerts, incident drills, traffic
  protection, IaC/recovery, and launch sign-off remain mandatory before production.

## Completion criteria result

The bounded Phase 1A-A unit is complete: model, migration, owner/scope/API contract,
privacy lifecycle, retention, audit/outbox minimization, tests, restore, hardened
container smoke, vulnerability scan, SBOM, and documentation all pass. Work stops
before Phase 1A-B and requires a separate go-ahead.
