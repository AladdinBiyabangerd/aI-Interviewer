# Phase 1B-B1 status: evidence-linked profile contracts

- Status: Complete (repository-wide local verification passed)
- Date: 2026-08-31
- Schema revision: unchanged from `20260828_0009`
- Scope completed: strict CV/JD schemas, bounded claim taxonomy, AZ/EN language shape,
  exact source-span verification, payload-safe verified result
- Next gate: Phase 1B-B2 (encrypted durable profiles and fenced profiling jobs)

## Implemented

- Separate `CvProfileOutput` and `JobDescriptionProfileOutput` classes inherit the
  gateway's strict/frozen/extra-forbid output base.
- CV covers skills, projects, responsibilities, career claims, and seniority hints. JD
  covers must-have/nice-to-have requirements, responsibilities, and seniority hints.
- Every item carries a unique bounded claim ID, derived statement, explicit/inferred
  classification, and one to five exact evidence spans.
- Evidence uses `[start, end)` Python Unicode-code-point coordinates plus an exact quote.
  The in-memory verifier checks document type, source bounds, and substring equality,
  and returns content-free claim/span/covered-character counts.
- AZ/EN language lists, derived Unicode text, collection sizes, span sizes, project
  technologies, duplicate skills, duplicate claim IDs, and cross-priority duplicate JD
  requirements are all bounded or rejected.
- Direct identity/contact fields are absent. Structured output and verified-result
  representations do not expose candidate/model content.
- Versioned schema IDs and deterministic document-type routing prepare the contract for
  ADR 0018 gateway execution without adding a provider.

## Deliberately not implemented

- No model prompt, adapter, outbound call, durable profile/job row, encryption,
  dead-letter queue, product route, correction workflow, or privacy export change.
- Exact span verification proves textual grounding, not semantic correctness. Labeled
  quality thresholds and adversarial prompt-injection evaluation remain later gates.
- The schema omits direct contact fields, but semantic PII filtering of arbitrary
  statements/evidence remains a prompt/policy/quality responsibility in 1B-C/1B-D.

## Verification

- Focused tests cover English CV and Azerbaijani JD Unicode offsets, overlapping-span
  coverage accounting, strict JSON round-trip, extra/coerced fields, direct contact
  field rejection, source bounds/quote mismatch, duplicate languages/IDs/evidence/
  technologies/skills/requirements, unsafe Unicode, document-type mismatch, and
  payload-free representations.
- `./scripts/verify.ps1` passed: `470` tests passed, one Windows/POSIX-specific signal
  test skipped, and branch-aware coverage was `95.35%`. The new profiling modules have
  complete line/branch coverage.
- Ruff lint/format, strict mypy for `76` source files, empty-database migration, Alembic
  model-drift checks, dependency compatibility, and the Python vulnerability audit all
  passed. The schema revision remains `20260828_0009`.

## Next part

Phase 1B-B2 adds immutable encrypted profile revisions and durable fenced profiling
jobs. A successful row must reference the exact source-text version and retain model,
prompt, schema, privacy, legal-basis, and delete-only retention snapshots. Invalid or
unverified output must be unable to enter that transaction.
