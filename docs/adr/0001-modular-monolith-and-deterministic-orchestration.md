# ADR 0001: Modular monolith with deterministic orchestration

- **Status:** Accepted for the initial product stages
- **Date:** 2026-08-23

## Context

The product needs several clear responsibilities - profiling, knowledge, retrieval, planning, interviewing, evaluation, skill state, and reporting - but early operational scale and team boundaries are not yet known. The source plan also states that session state, time, and question budgets must be controlled deterministically rather than by an unsupervised agent swarm.

## Decision

Use a modular monolith for synchronous APIs and separately runnable workers for durable asynchronous jobs. Modules communicate through explicit application interfaces and own their schemas logically even while using one PostgreSQL cluster. Cross-module asynchronous effects use a transactional outbox when persistence is introduced.

The session orchestrator is the sole authority for state transitions, time, question budgets, and retries. LLM-backed components return validated proposals or evaluations; they cannot directly advance session state or write another module's records.

Begin retrieval with PostgreSQL metadata, full-text search, and `pgvector` only in Phase 2. Extract a service or dedicated search system only when production measurements demonstrate a scaling, isolation, or ownership need.

## Consequences

- Early deployments, transactions, debugging, and local development remain simple.
- Module boundaries and durable messages must be enforced in tests because process boundaries do not enforce them.
- Independent scaling is limited until a module is extracted.
- Provider adapters and structured output validation keep domain logic independent of any LLM, STT/TTS, avatar, or storage vendor.
- A microservice split is not a roadmap milestone by itself; it requires evidence and a migration ADR.
