# ADR 0024: Deterministic profile quality and separate approval

- Status: Accepted for Phase 1B-D1
- Date: 2026-09-01
- Depends on: ADR 0018 through ADR 0023

## Context

Phase 1B-C2 proves strict output validation, evidence integrity, encrypted immutable
persistence, safe execution, and owner correction. None of those controls demonstrates
semantic extraction quality. The shipped application has no concrete provider adapter,
so a synthetic fixture pass must not be represented as real model validation.

## Decision

1. Phase 1B-D is split into D1 (offline deterministic contract and synthetic seed) and
   D2 (reviewed real-provider corpus, regression evidence, and named approval).
2. Evidence binds the exact model release, current prompt/schema contract digest,
   versioned corpus, per-fixture rights, strict gold/predicted profiles, exhaustive human
   claim adjudication, and owner-review outcome.
3. Claim matching is human-labeled and exhaustive; the evaluator does not use fuzzy or
   model-based semantic matching. Languages are compared as exact sets.
4. Gold evidence mismatch invalidates the bundle. Predicted evidence mismatch lowers
   source-span coverage, and the fixed policy requires 100% exact coverage.
5. Fixed minimum corpus/slice/field support, precision, recall, execution-success,
   review-coverage, and correction-rate thresholds are versioned in application code
   and documented in the quality contract.
6. Evaluation output is content-free and can only be `eligible_for_approval` or
   `blocked`. It never approves a model.
7. A separate approval record binds the complete evidence digest, model release, and
   policy version. Product, engineering, Azerbaijani, and English reviewers are all
   required for an `approved` result.
8. Repository fixtures are synthetic. Sensitive or rights-restricted quality corpora
   stay outside version control in an approved access-controlled boundary.
9. No database schema, product route, provider SDK, credential, external call, or
   worker supervisor is introduced by D1.

## Consequences

Every candidate model/prompt release can be measured with the same deterministic
formula, while unsupported claims, prompt injection, language/document slices, invalid
spans, model failures, and owner interventions remain visible. A small or copied-gold
seed cannot satisfy the release gate, and human approval cannot silently carry across a
changed evidence bundle.

Phase 1B-D2 remains blocked until real reviewed outputs and four named approvals exist.
