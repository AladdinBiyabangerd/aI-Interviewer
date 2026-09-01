# ADR 0018: Provider-neutral structured model gateway

- Status: Accepted
- Scope: Phase 1B-A only
- Date: 2026-08-31
- Depends on: completed Phase 1A, ADR 0005 (privacy lifecycle), ADR 0008
  (payload-blind telemetry), ADR 0010 (feature-stable text MVP sequencing)

## Context

Phase 1B must turn corrected CV/JD source text into evidence-linked structured data.
The application had no model execution boundary, and choosing a vendor SDK before a
provider, processor agreement, region, model release, and credentials are reviewed
would couple product logic to an unapproved external dependency. Invalid or mutable
model output also must not cross into durable profile state.

## Decision

1. Application code calls a provider-neutral `ModelGatewayRuntime`. A concrete adapter
   implements one `ModelProvider.generate` port and translates an exact request into
   the provider's structured-output API. No provider SDK, endpoint, key, or fallback
   routing is included in this phase.
2. Execution is disabled by default. Enabling it requires bounded provider, model ID,
   and immutable model-version coordinates plus an explicitly injected adapter. An
   enabled configuration without an adapter fails during application composition;
   coordinates on a disabled gateway are rejected.
3. Every call carries immutable prompt/schema coordinates and the exact expected model
   release. The provider response must report that same release. The result records
   canonical SHA-256 identities for the rendered instructions and generated JSON
   schema, making accidental reuse of a version label detectable.
4. Output types must inherit `StrictModelOutput`, which is frozen, coercion-free, and
   rejects unknown fields. The gateway supplies the application-owned JSON schema to
   the adapter and validates returned JSON again inside the application. Invalid JSON,
   wrong types, missing fields, extra fields, truncation, oversized output, filtering,
   and model-identity drift cannot produce a successful result.
5. Timeouts, maximum attempts, input/output bounds, and exponential retry are globally
   bounded. Only the closed transient taxonomy is retried. Provider rejection,
   content filtering, and model identity mismatch are terminal. Task cancellation is
   propagated rather than converted into a retry.
6. Instructions, source text, output schema, and provider output are excluded from
   request/response/result representations. Provider exceptions are converted to safe
   codes; unknown exception text is discarded. The gateway emits no payload logs or
   telemetry.

## Consequences

Phase 1B now has a deterministic model-execution port that can be tested with local
fakes. No external processor receives data and no profile is generated or persisted
until a reviewed adapter and the durable profiling domain are added. Phase 1B-B1 now
defines CV/JD evidence schemas and exact source-span verification. Phase 1B-B2 must add
owner/policy-bound jobs, encrypted derived-data persistence, dead-letter state, and
privacy export/erasure before an adapter may be used by product traffic.
