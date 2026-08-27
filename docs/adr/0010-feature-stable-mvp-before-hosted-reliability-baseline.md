# ADR 0010: Feature-stable text MVP before the hosted reliability baseline

- **Status:** Accepted by product owner direction
- **Date:** 2026-08-26

## Context

Phase 0D-C-B1 completed the provider-neutral 28-day evidence contract, but no cloud,
monitoring backend, staging identity provider, or named product/engineering/operations
reviewers have been selected. The currently measurable product routes cover only the
identity and privacy foundation. Phase 1 will add candidate onboarding, document,
profiling, interview-session, evaluation, and report routes.

Collecting and approving a numeric objective now would describe the foundation routes,
not the intended interview experience. The code-owned route-population digest would
also change as Phase 1 routes are reviewed, invalidating the evidence cohort or requiring
a new comparable contract and collection window.

The user has requested a complete, inspectable text-product sample before paying for and
provisioning production-oriented AWS/Grafana infrastructure. This changes delivery order,
not the production-quality standard or the launch gate.

## Decision

1. Defer 0D-C-B2 live staging collection, 0D-C-C alerts, 0D-C-D incident exercises,
   0D-D traffic/capacity enforcement, and 0D-E provider/recovery sign-off until the
   Phase 1 text flow is feature-stable.
2. Permit Phase 1 development after the completed 0C security/privacy boundary and the
   completed provider-neutral 0D-A, 0D-B, 0D-C-A, and 0D-C-B1 foundations.
3. Continue building Phase 1 in independently verified production-quality modules. A
   local sample is not permission for fake providers, placeholder domain behavior,
   weakened ownership, untracked sensitive data, or bypassed deletion/retention.
4. Keep telemetry, route classification, release/schema compatibility, evidence tooling,
   threat-model updates, and tests current as Phase 1 adds routes and data categories.
5. Treat all deferred 0D work as a hard **pre-production** gate. No public production
   release, production-readiness claim, numeric SLO, error budget, pager route, or
   capacity claim is allowed before those gates complete.
6. Start the qualifying staging window only from a reviewed, feature-stable release.
   Allow at least 28 consecutive UTC days plus remediation buffer before launch; a route,
   query, telemetry-contract, or material measurement change may restart the window.

The revised high-level order is:

```text
0A -> 0B -> 0C -> 0D-A/B/C-A/B1
   -> Phase 1 text MVP
   -> 0D-C-B2/C/D -> 0D-D -> 0D-E
   -> production launch
```

## Consequences

- The team can inspect a real end-to-end text product before committing to provider cost.
- The reliability baseline will measure representative product routes instead of an
  identity/privacy-only proxy.
- A public launch is at least one valid 28-day window away after feature freeze; this
  delay must be included in release planning.
- Hosted integration risks are discovered later than in the original sequence. The
  provider-neutral container, migration, telemetry, security, and evidence contracts
  reduce but do not eliminate that risk.
- Phase status must say `local/non-production` until the deferred gates are complete.

## Rejected interpretations

- "Do reliability after production launch" is rejected. It remains a pre-production
  requirement.
- "Build a disposable prototype" is rejected. Every Phase 1 unit retains its ownership,
  privacy, migration, error-handling, test, and documentation exit gate.
- Numeric objectives based on unit tests, local traffic, or fabricated evidence remain
  prohibited.
