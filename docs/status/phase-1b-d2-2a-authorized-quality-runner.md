# Phase 1B-D2.2a completion record: authorized quality runner

Date: 2026-09-01

## Outcome

The repository can now generate OpenAI profile-quality predictions only from a strict
private corpus paired with a separate, active, digest-bound authorization. It can then
prepare an explicitly unadjudicated human-review draft. No live request, credential,
real corpus, human adjudication, quality pass, or release approval was produced.

## Implemented controls

- strict corpus validation for dataset/version, prompt digest, per-fixture provenance,
  language/document/risk shape, gold profile, and exact source evidence;
- active authorization bound to the complete corpus SHA-256, exact OpenAI release,
  prompt digest, processor activity, data controls, approver, and validity window;
- mandatory `--confirm-external-processing` before configuration or corpus processing;
- deterministic request UUIDs, sequential bounded execution, strict response contracts,
  repeated exact evidence validation, and safe per-fixture failure records;
- prediction output bound to both corpus and authorization digests;
- review preparation that refuses corpus/run drift and never invents adjudication or
  owner-review outcomes;
- bounded private input loading, create-only private artifact output, no partial output,
  and content/path-free command summaries and invalid-input errors;
- unit tests use only an in-memory provider and make no external request.

## Explicitly not completed

- rights-cleared full AZ/EN CV/JD corpus and exact processor/data-control approval;
- a newly rotated server credential and funded, operator-confirmed OpenAI execution;
- human claim adjudication, owner-review outcomes, slice/error analysis, threshold pass;
- four named digest-bound reviewer approvals, product activation, or supervision.

## Verification

- `./scripts/verify.ps1`: 608 passed, 1 skipped;
- combined branch coverage: 95.53%;
- Ruff check/format: 217 files;
- strict mypy: 87 source files;
- all 12 PostgreSQL migrations applied from zero with model/migration parity checks;
- dependency compatibility and vulnerability audit: no known vulnerability;
- repository scan: no OpenAI project-key token and no local `.env` file present.

The next gate is Phase 1B-D2.2b, the approved real-corpus run and human quality decision.
