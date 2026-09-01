# Phase 1B-D2.1 completion record: OpenAI Responses adapter

Date: 2026-09-01

## Outcome

The concrete OpenAI Responses transport is implemented behind the existing
provider-neutral gateway and remains disabled by default. Application startup can now
construct it only for explicit `provider=openai` settings with a server-side secret.
No API key is committed, no real candidate data is included, and verification makes no
external request.

## Implemented controls

- fixed `https://api.openai.com/v1/responses` destination with TLS verification,
  redirects and ambient proxy inheritance disabled;
- Bearer credential held by `SecretStr`, optional startup-only secret-file loading, and
  mandatory absolute secret-file delivery in staging/production;
- exact configured model version sent and response-reported version returned to the
  gateway's existing identity-drift check;
- strict Responses JSON Schema format with defaults removed, all object properties
  required, and `additionalProperties=false` at every object level;
- `store=false`, `background=false`, `truncation=disabled`, no provider tools, and no
  server-side continuation chain;
- durable job UUID propagation through `X-Client-Request-Id`;
- bounded raw response parsing and closed, payload-free HTTP/network/timeout/refusal/
  incomplete/malformed-response failure mapping;
- mock-transport contract tests for request shape, key redaction, strict schema
  normalization, model drift, refusal/incomplete states, status mapping, transport
  failures, malformed responses, size bounds, secret-file loading, and fail-closed
  composition.

## Explicitly not completed

- no pasted or otherwise exposed credential was used or stored;
- no OpenAI call, billing event, model prediction, or quality claim was produced;
- no rights-cleared production-scale AZ/EN CV/JD corpus or exhaustive adjudication exists;
- no processor agreement, region/data-control approval, country activation, public job
  scheduling route, or continuous worker supervisor was added by D2.1; the later
  disabled-by-default runtime is governed by
  [ADR 0028](../adr/0028-disabled-by-default-worker-supervision.md);
- no four-role Phase 1B-D2 approval exists.

## Local verification

- `./scripts/verify.ps1`: 578 passed, 1 skipped;
- combined branch coverage: 95.42%;
- Ruff check/format: 213 files;
- strict mypy: 86 source files;
- all 12 PostgreSQL migrations applied from zero with model/migration parity checks;
- dependency compatibility and vulnerability audit: no known vulnerability;
- repository scan: no OpenAI project-key token and no local `.env` file present.

The next gate is Phase 1B-D2.2: run an approved exact OpenAI model release over the
rights-cleared offline corpus, record predictions and owner-review outcomes, complete
human adjudication and slice/error analysis, meet every fixed D1 threshold, and bind the
four named approvals to the resulting evidence digest.
