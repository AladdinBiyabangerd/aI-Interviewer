# ADR 0002: Python 3.12 API runtime

- **Status:** Accepted
- **Date:** 2026-08-23

## Context

The core product work will include document extraction, retrieval evaluation, model orchestration, rubric experiments, and later realtime provider adapters. The API runtime needs strict external contracts and strong access to the Python AI/data ecosystem without coupling domain code directly to providers.

## Decision

Use Python 3.12, FastAPI, Pydantic Settings, and Uvicorn for the initial API and workers. Use `uv` with a committed lockfile for dependency resolution and reproducible environments. External input/output uses validated models; domain and application modules remain ordinary Python and must not depend on FastAPI request objects.

The production image is a pinned, multi-stage Alpine build. Build tooling is excluded from the runtime stage, and the process runs as numeric UID/GID 10001.

## Consequences

- Profiling, evaluation, and retrieval experiments can use the same language as the application layer.
- Async code must be kept honest: blocking parsing or model SDK calls belong in bounded threads/workers.
- Runtime and framework upgrades are automated through dependency update proposals but remain gated by tests and vulnerability scans.
- This decision does not select the frontend framework, PostgreSQL access library, queue, object store, authentication provider, LLM provider, or realtime vendors; those choices require their own phase-specific evidence.
