# ADR 0027: Exact human-review finalization

- Status: Accepted
- Date: 2026-09-01

## Context

The authorized quality runner produces an exact prediction artifact and an
unadjudicated review draft. Allowing operators to hand-edit that draft directly into
final evidence would leave no executable check that source text, provenance, gold
profiles, model predictions, fixture order, and release coordinates remained identical
to the authorized corpus and prediction run.

## Decision

Add a local-only `finalize-review` transition. It accepts the original corpus, exact
prediction run, and a completed review draft; reconstructs the canonical unreviewed
draft; rejects any change outside `adjudications` and `owner_review_outcome`; requires
an owner outcome for every fixture; and relies on the strict evidence model to require
exhaustive, field-consistent claim adjudication. It creates a new private evidence file
without overwriting an existing artifact and prints only counts and digests.

This transition makes no provider or backend call and does not decide whether quality
is sufficient. Evaluation and four-role approval remain separate commands and records.

## Consequences

- Human decisions can be added without permitting corpus or prediction drift.
- Final evidence is reproducibly derived from the exact authorized run.
- Incomplete review, reordered fixtures, changed source/gold/prediction content, and
  output overwrite attempts fail closed.
- The real rights-cleared corpus, approved OpenAI run, human error analysis, threshold
  pass, and four named approvals remain mandatory external work.
