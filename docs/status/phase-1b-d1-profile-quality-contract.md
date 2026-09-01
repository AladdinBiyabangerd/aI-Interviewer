# Phase 1B-D1 status: deterministic profile quality contract

- Status: Complete (repository-wide local release verification passed)
- Date: 2026-09-01
- Schema revision: unchanged at `20260901_0012`
- Scope completed: strict offline evidence/adjudication schema, deterministic metrics,
  fixed threshold policy, safe CLI, separate digest-bound approval contract, synthetic
  AZ/EN CV/JD seed
- Next gate: Phase 1B-D2 (real provider corpus, error analysis, and named approval)

## Implemented

- `ai-interviewer-profile-quality` exposes evidence/approval schemas, the current
  prompt-contract digest, threshold evaluation, and final approval verification.
- Evidence binds an exact model release and both current CV/JD prompt/schema contracts.
  Prompt drift blocks eligibility.
- Gold/predicted claim adjudication is exhaustive and field-consistent. The evaluator
  calculates field, AZ/EN x CV/JD, prompt-injection, and unsupported-claim slices without
  inferring semantic matches.
- Strict model failures contribute false negatives and execution-success loss. Invalid
  predicted source offsets/quotes reduce measured span coverage; the gate requires 100%.
- Version `1.0.0` defines minimum corpus/slice/field support, precision/recall,
  prediction-success, review-coverage, and owner-correction thresholds.
- Evaluation is never approval. A separate evidence-digest-bound record requires unique
  product, engineering, Azerbaijani, and English reviewer roles.
- The bounded loader and CLI do not print source text, profile statements, evidence
  quotes, paths, or raw invalid input.
- Four repository-safe synthetic fixtures cover AZ/EN CV/JD, Unicode offsets,
  prompt-injection, and unsupported-claim handling. They deliberately return `blocked`
  because a seed is not a release corpus.

## Deliberately not implemented

- No concrete provider adapter, credential, endpoint, outbound model call, or worker
  supervisor was introduced.
- No claim is made about real model precision, recall, correction rate, or regression
  quality. D2 requires reviewed real-provider evidence and four named approvals.
- No sensitive or licensed CV/JD corpus is committed to the repository.

## Verification

- `./scripts/verify.ps1` passed with `554` tests, one platform-specific skip, and
  `95.41%` branch-aware coverage.
- Ruff lint/format passed for `209` files and strict mypy passed for `85` source files.
- Sixteen focused tests cover a fully eligible 40-fixture corpus, separate approval,
  under-sized seeds, failed/invalid predictions, false positives, bad source spans,
  prompt drift, correction/review failure, relationship validation, bounded loading,
  safe CLI output, schemas, and the checked-in seed.
- The checked-in seed validates successfully and returns `blocked` with the expected
  corpus, slice, and field-support reasons.
- Empty-database migration, downgrade/upgrade round trip, Alembic model parity,
  dependency compatibility, and the Python vulnerability audit passed with unchanged
  schema head `20260901_0012`.
- Logical backup/restore rehearsal passed with source/restored count parity, append-only
  audit enforcement, and all source/profile/job triggers.
- The rebuilt release image passed numeric `10001:10001`, read-only/capability checks,
  exact migration head, baseline schema, profile-quality evidence/approval schemas, and
  prompt-contract digest
  `c62321d636cba9cf8ffd8115b6318bd05c8b8c67d58bdaef3c78bfdac924e9d2`.

## Next part

Phase 1B-D2 activates a separately reviewed provider adapter for an offline evaluation
run, assembles a rights-cleared corpus meeting every minimum, records slice/error
analysis, obtains four named digest-bound approvals, and proves `gate` returns
`approved`. Only then can Phase 1B close and Phase 1C begin.
