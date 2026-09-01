# Profile quality gate

This document owns the deterministic Phase 1B-D quality contract for evidence-linked
CV and job-description profiles. The repository currently implements the D1 evaluator
and synthetic seed, the D2.2a explicitly authorized prediction runner, and the D2.2b1
exact human-review finalizer. It does not contain a real corpus and does not claim that
a real model release has passed D2.

## Inputs and trust boundary

The evaluator runs offline and accepts one strict JSON evidence bundle. A bundle binds:

- an exact provider, model ID, and immutable model version;
- the SHA-256 digest of both current code-owned CV/JD prompt and schema contracts;
- a versioned labeled corpus with explicit rights/provenance for every fixture;
- exact source text, one gold profile, and either a strict prediction or a bounded safe
  execution failure;
- exhaustive human adjudication linking each gold and predicted claim exactly once;
- an owner-review outcome for correction-rate measurement.

The `evaluate` and `gate` commands never call a provider or backend. Their JSON output contains counts,
ratios, release coordinates, safe failure codes, and digests only. It excludes source
text, evidence quotes, statements, paths, prompts, and raw provider output. Invalid
files also return only an error type.

Repository fixtures must be synthetic and explicitly marked `repository_safe=true`.
Consented/redacted or licensed corpora must remain in an approved access-controlled
location; the CLI can evaluate them locally but they must not be committed here.

## Explicitly authorized prediction workflow

Prediction generation is a separate, offline operator action. It requires three strict,
separately controlled artifacts:

1. A `corpus` containing source text, gold profiles, per-fixture rights provenance, and
   the current prompt/schema digest.
2. An `authorization` approved for `profile_quality_evaluation`, bound to the canonical
   corpus digest, dataset/version, exact OpenAI model release, prompt digest, processor
   activity, data-control review, approver, and a timezone-aware validity window.
3. A generated `predictions` artifact containing deterministic request UUIDs and either
   strict grounded profiles or bounded safe failure codes.

`generate` additionally requires `--confirm-external-processing`. It rejects a disabled
or mismatched gateway, stale/future approval, prompt drift, corpus drift, and an existing
output path before retaining a result. Fixtures run sequentially. The command writes only
after the bounded run completes, creates rather than overwrites the output, and prints a
content-free count/digest summary. This control does not replace processor, transfer,
region, retention, deletion, access, or corpus-rights review.

`prepare-review` joins the exact corpus and prediction run into a new private draft. It
intentionally leaves `adjudications=[]` and `owner_review_outcome=not_reviewed`; the draft
cannot validate as final evidence until qualified humans complete both. Corpus,
authorization, prediction, review-draft, and final-evidence files may contain highly
sensitive data and must remain outside the repository in an approved encrypted location.

`finalize-review` accepts the original corpus, exact prediction run, and a completed copy
of that draft. It permits only human `adjudications` and `owner_review_outcome` changes,
rejects all source/gold/prediction/provenance/order/release drift, requires every owner
outcome and exhaustive field-consistent claim adjudication, and creates a new private
evidence artifact. It makes no provider call and cannot grant approval.

## Deterministic adjudication

Claim IDs are not assumed to have semantic meaning across gold and predicted profiles.
A human reviewer maps them with `adjudications`:

- both IDs present: true positive;
- only a predicted ID: false positive;
- only a gold ID: false negative.

Every gold and predicted claim must appear exactly once, and both sides of a match must
belong to the same profile field. Languages are compared as exact sets. Gold evidence
must match the fixture source or the bundle is invalid. Predicted source spans are
measured individually, so a quote/offset mismatch deterministically lowers coverage.

## Version 1 thresholds

These fixed D1 policy values are the proposed release thresholds that the D2 named
reviewers must approve before activation:

| Measure | Threshold |
|---|---:|
| Total fixtures | at least 40 |
| Each AZ/EN x CV/JD primary slice | at least 8 fixtures |
| Prompt-injection and unsupported-claim slices | at least 4 fixtures each |
| Gold support for every field | at least 4 claims |
| Overall precision / recall | at least 0.90 / 0.85 |
| Supported field precision / recall | at least 0.80 / 0.75 |
| Populated slice precision / recall | at least 0.85 / 0.80 |
| Strict prediction success | at least 0.95 |
| Exact predicted source-span coverage | exactly 1.00 |
| Owner-review coverage | exactly 1.00 |
| Owner correction/rejection rate | at most 0.15 |

All fields are reported even when support is absent. Missing field support, an
under-populated required slice, prompt/schema drift, an undefined metric, or any failed
threshold blocks eligibility. `evaluate` can return only `eligible_for_approval` or
`blocked`; it can never grant human approval.

## Separate named approval

The approval record is a second strict JSON document bound to the canonical SHA-256 of
the complete evidence bundle, the exact model release, and policy version. The final
gate requires four unique approvals:

- product;
- engineering;
- Azerbaijani-language review;
- English-language review.

Changing any fixture, prediction, adjudication, review outcome, model coordinate, or
prompt digest invalidates the approval binding. The `gate` command returns `approved`
only when the evaluation is eligible and every required approval matches.

## Commands

```powershell
uv run ai-interviewer-profile-quality prompt-digest
uv run ai-interviewer-profile-quality schema corpus
uv run ai-interviewer-profile-quality schema authorization
uv run ai-interviewer-profile-quality schema predictions
uv run ai-interviewer-profile-quality schema review-draft
uv run ai-interviewer-profile-quality schema evidence
uv run ai-interviewer-profile-quality schema approval
uv run ai-interviewer-profile-quality generate <corpus.json> <authorization.json> <predictions.json> --confirm-external-processing
uv run ai-interviewer-profile-quality prepare-review <corpus.json> <predictions.json> <review-draft.json>
uv run ai-interviewer-profile-quality finalize-review <corpus.json> <predictions.json> <completed-review.json> <quality-evidence.json>
uv run ai-interviewer-profile-quality evaluate <quality-evidence.json>
uv run ai-interviewer-profile-quality gate <quality-evidence.json> <approval.json>
```

Exit codes are `0` for a completed generation/preparation/finalization or eligible/approved gate,
`2` for invalid input or authorization, `3` for a valid but blocked evaluation, and `4`
for a valid but blocked approval gate. A completed prediction run can contain safe
per-fixture failures; those are measured later instead of being mistaken for approval.

The checked-in
[`phase-1b-d1-seed.json`](fixtures/phase-1b-d1-seed.json) contains one synthetic fixture
for each AZ/EN x CV/JD primary slice plus prompt-injection and unsupported-claim cases.
It proves schema, Unicode-offset, adjudication, and safe-summary behavior. It is
deliberately too small and field-sparse, so `evaluate` must return `blocked`.

## D2 completion evidence

Phase 1B-D is complete only after an approved real provider adapter produces a reviewed
bundle that passes every threshold, slice/error analysis is recorded, the four named
roles sign the separate digest-bound approval, and the `gate` command returns
`approved`. Continuous worker activation remains a separate operational decision.
