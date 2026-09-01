# ADR 0026: Authorized offline quality prediction run

- Status: Accepted
- Date: 2026-09-01

## Context

ADR 0024 defined deterministic evidence and approval, while ADR 0025 supplied the
disabled OpenAI transport. Running a rights-restricted CV/JD corpus is a materially
different external-processing action. A corpus file, a configured key, or a generic
operator confirmation alone cannot prove that the exact data, release, prompt, and
processor controls were approved. Predictions also must not be mistaken for completed
human adjudication.

## Decision

Use four strict private artifact stages:

1. corpus: source, gold profile, rights provenance, dataset/version, prompt digest;
2. authorization: approved purpose and validity window bound to the canonical corpus
   digest, exact OpenAI model release, prompt digest, processor activity, data-control
   review, and approver;
3. predictions: deterministic per-fixture request UUID plus strict profile or safe
   failure, bound to both corpus and authorization digests;
4. review draft: exact corpus/prediction join with no synthesized adjudications and every
   owner-review outcome set to `not_reviewed`.

The operator must additionally pass `--confirm-external-processing`. Authorization is
checked before the first call. Fixtures execute sequentially within a 200-fixture bound.
Outputs are canonical JSON written with create-only semantics and a private file mode;
stdout and errors contain only types, counts, status, and digests. The command does not
resume a partial run or overwrite an artifact.

A provider-free `preflight` command exposes the same corpus digest, current prompt,
dataset/version, and active-window validation before an operator configures a credential
or confirms external processing. It returns only exact model coordinates, counts,
timestamps, and canonical digests; paths, approver identity, data-control references,
source text, gold profiles, and credentials remain excluded.

## Consequences

- Corpus or prompt changes require a new authorization.
- Model aliases/drift and inactive approvals fail before data transfer.
- Operators can prove authorization readiness without constructing a provider gateway.
- A completed prediction file may include safe failures and grants no release approval.
- Humans must exhaustively adjudicate claims and record owner review before the D1
  evaluator accepts the final evidence shape.
- Operators still own encrypted storage, access, retention, deletion, transfer/region,
  provider-contract, budget, and rights controls outside this repository.
- No real corpus, key, prediction, or approval is shipped with this decision.
