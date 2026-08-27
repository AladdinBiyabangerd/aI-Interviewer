# ADR 0009: Measure service indicators before approving objectives

- **Status:** Accepted for Phase 0D-C-A
- **Date:** 2026-08-24

## Context

Phase 0D-B provides bounded telemetry, but the platform has no hosted monitoring backend, sustained staging history, production traffic, product owner, or named on-call owner. A numeric objective selected from local tests would not describe user experience and an alert without an accountable responder would not be actionable.

The current API exposes identity and privacy foundation routes. Candidate onboarding, upload, parsing, interviews, and reports do not exist yet, so an end-to-end interview-journey SLO cannot be measured in this phase.

## Decision

1. Phase 0D-C is split into four gates: A) SLI measurement contract and integrity, B) staging baseline plus stakeholder-approved SLO/error-budget policy, C) backend-specific alert rules and routing, and D) exercised incident response.
2. Product HTTP routes are an explicit code-owned set. `http.server.request.duration` records the bounded `ai_interviewer.request.population=product|operations|other` attribute. Unknown routes fail outside the product SLI until reviewed; health, documentation, and unmatched traffic cannot improve product availability.
3. The initial API availability indicator uses occurrence counting: eligible product requests are total events; HTTP 5xx responses are bad events; non-5xx responses are good events. An empty denominator is `no data`, never 100% availability.
4. Latency is collected as a distribution over the same product population. A latency SLI cannot be finalized until a user-relevant threshold is selected from staging evidence and approved in 0D-C-B.
5. Dependency outcomes, scan execution, deletion queues, and operational-snapshot freshness are diagnostic indicators. They do not independently claim user availability or share the product error budget.
6. An SLO proposal requires a continuous 28-day staging evidence window, weekly/day-of-week breakdowns, exact release/environment filters, documented telemetry gaps and restarts, request volume, and reviewed query definitions. Test/local results are never relabeled as staging evidence.
7. Numeric targets, budget policy, burn-rate windows, pager routes, and on-call names remain absent until the responsible product, engineering, and operations stakeholders approve them.

## Consequences

- Every API route addition or template change must update the reviewed population set and its test.
- The operational database monitor publishes attempt outcome and last-success age, so stale queue gauges cannot silently appear current.
- The first availability SLI is a server-side proxy. A later browser/client journey SLI may supersede or complement it when the product experience exists.
- 0D-C-A can be completed without pretending that an SLO or production response capability exists. Phase 0D-C remains open until B-D are complete.

