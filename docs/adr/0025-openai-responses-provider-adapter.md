# ADR 0025: OpenAI Responses provider adapter

- Status: Accepted for Phase 1B-D2 offline quality work
- Scope: Phase 1B-D2.1 only
- Date: 2026-09-01
- Depends on: ADR 0018 provider-neutral gateway, ADR 0022 policy-gated
  profiling execution, and ADR 0024 deterministic profile quality gate

## Context

Phase 1B-D2 needs predictions from one exact, separately reviewed model release. The
provider-neutral gateway and policy-gated worker already define the application boundary,
but no implementation could translate it to a real provider. OpenAI was selected for
this evaluation. Selection of a transport does not itself approve candidate data transfer,
a processor activity, a country, a model release, production traffic, or spend.

## Decision

1. The first concrete adapter targets only the OpenAI `POST /v1/responses` endpoint over
   TLS. It uses the existing async HTTP dependency directly and exposes no configurable
   base URL, redirects, ambient proxy settings, tools, search, files, or background mode.
2. The configured model version is the exact API `model` value sent. The adapter returns
   the response-reported model as the version, so the existing gateway rejects alias or
   release drift before any output is accepted.
3. Every request uses Responses Structured Outputs with `text.format.type=json_schema`,
   `strict=true`, an application-owned schema, `store=false`, `background=false`, and
   `truncation=disabled`. Provider normalization removes schema defaults and marks every
   object property required with `additionalProperties=false`; the original application
   schema remains the final validation authority.
4. The durable job UUID is sent as `X-Client-Request-Id`. Candidate source text and
   instructions are request-only payloads. Response bodies, provider error bodies, API
   keys, and authorization headers never enter application logs, telemetry, audit, or
   safe exception messages.
5. HTTP 408, 409, 429, other 4xx, 5xx, network errors, timeouts, malformed responses,
   incomplete output, content filtering, refusal, and unexpected response states map to
   the existing closed provider/gateway taxonomy. A successful raw response is bounded
   to 8 MiB before parsing and is validated again by the strict gateway.
6. The adapter is constructed only for an explicitly enabled `provider=openai`
   configuration. An OpenAI API key is mandatory and held as `SecretStr`; development may
   load it from a server environment value, while hosted environments require an absolute
   orchestrator-mounted secret file. Disabled or non-OpenAI configurations reject OpenAI
   credentials.
7. Model execution and profiling execution remain disabled by default. A real profiling
   call still requires the C1 processor-activity authorization, encrypted deletion-locator
   registration, exact job release snapshot, and live lease. Unit tests use a local mock
   transport and make no OpenAI request.

## Consequences

The repository can now translate a reviewed exact profiling release to OpenAI without
changing domain or persistence code. The fixed endpoint and closed payload reduce routing,
retention, prompt-truncation, and tool-use ambiguity. `store=false` is an API storage
setting, not a substitute for an approved processor contract, data-control review,
retention/deletion policy, or residency decision.

Phase 1B-D2 is not complete. It still requires a newly issued non-exposed credential,
an approved processor activity, a rights-cleared full AZ/EN CV/JD corpus, actual prediction
capture, exhaustive human adjudication, error analysis, threshold success, and four named
digest-bound approvals. Production activation and a continuous supervisor remain separate
reviewed gates.
