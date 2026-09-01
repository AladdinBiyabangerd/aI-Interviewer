# ADR 0019: Evidence-linked CV and JD profile contracts

- Status: Accepted
- Scope: Phase 1B-B1 only
- Date: 2026-08-31
- Depends on: Phase 1A corrected source text and ADR 0018 model gateway

## Context

The model gateway can reject malformed structured output, but Phase 1B still lacked an
application-owned definition of an acceptable CV or job-description profile. A generic
JSON object could silently collect unnecessary direct identity/contact data, merge
must-have and nice-to-have requirements, coerce types, or present unsupported model
claims without a verifiable link to the exact corrected source text.

## Decision

1. CV and job descriptions use separate frozen, strict, extra-forbid output models.
   CV output contains only skills, projects, responsibilities, career claims, and
   seniority hints. JD output contains must-have requirements, nice-to-have
   requirements, responsibilities, and seniority hints. Direct person name, email,
   phone, address, and contact fields are intentionally absent.
2. Every extracted item has a bounded stable-within-output `claim_id`, a bounded
   derived statement, an `explicit` or `inferred` marker, and one to five evidence
   spans. Unknown fields and type coercion fail validation.
3. A span uses half-open `[start, end)` offsets measured in Python Unicode code points
   over one exact decrypted source-text version. It includes the exact source `quote`;
   `end - start` must equal the quote length and a separate verifier requires
   `source_text[start:end] == quote` before persistence is allowed.
4. Derived statements/names are single-line, trimmed, and reject control, format,
   surrogate, line-separator, and paragraph-separator characters. Evidence quotes are
   not normalized because byte-for-character identity with source text is required.
5. Profiles declare one or both supported document languages (`az`, `en`) without
   duplicates. Claim IDs are unique across the whole profile. CV skill names are
   unique case-insensitively, and a JD requirement cannot appear in both priority
   groups under case-insensitive statement equality.
6. Claim collections, evidence per claim, quote length, offsets, project technologies,
   and all derived strings have explicit upper bounds. Profile and verified-result
   representations omit model-derived/source content.
7. Schema IDs `cv-profile` and `job-description-profile` begin at version `1.0.0`.
   Document type deterministically selects exactly one output class; the gateway still
   records the canonical JSON-schema digest for every execution.

## Consequences

Invalid or ungrounded model output now has no valid application representation and can
be rejected before a transaction writes derived data. This phase makes no model call,
stores no profile, and introduces no schema migration. Semantic PII minimization and
prompt-injection resistance still require reviewed prompts/adapters and adversarial
fixtures; a strict schema alone cannot determine whether arbitrary evidence text is
appropriate. Phase 1B-B2 must bind a verified profile to exact owner, document,
source-text version, privacy/retention, model, prompt, and schema lineage in encrypted
durable storage with fenced jobs and dead-letter handling.
