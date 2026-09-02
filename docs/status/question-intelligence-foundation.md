# Question intelligence foundation record

Date: 2026-09-02

## Outcome

The backend now treats question selection as a separate evidence and ranking problem.
It includes:

- strict source, rights, provenance, normalized evidence, competency graph, question
  concept, and company fingerprint contracts;
- deep RAG expansion, CV claim probing, and reusable Data/AI, backend, and general-role
  competency graphs;
- transparent banking, financial-services, e-commerce, and telecom cold-start patterns;
- configurable multi-signal scoring with a per-question score breakdown;
- competency quotas and redundancy control for budget-complete, diverse blueprints;
- explicit origin labels, evidence IDs, High/Medium/Limited specificity, and uncertainty
  language;
- deterministic evaluation metrics for JD/role/round relevance, company-claim precision,
  diversity, duplicates, retrieval precision proxy, source confidence, and major-JD
  coverage;
- seven normalized PostgreSQL tables with source-to-evidence-to-concept/fingerprint
  lineage; and
- an idempotent database adapter for versioned application-authored concept catalogs.

The engine makes no network or OpenAI call and does not rely on an API secret.

## Verified scenarios

- A JD requiring production RAG activates the full RAG subgraph rather than one keyword.
- A CV claim about RAG, FAISS, and OpenAI creates vacancy- and CV-derived probe concepts.
- A banking ML role without company reports still receives fraud/risk, imbalance,
  explainability, security, monitoring, and reliability emphasis labeled as industry
  evidence.
- One weak source cannot create High company specificity; corroborated official plus
  independent evidence can.
- Metadata-only or otherwise non-permitted sources are excluded from derived claims.
- A 20-question selection is budget complete, covers activated major JD competencies, and
  has zero detected duplicate concepts in the deterministic fixture.
- PostgreSQL migration upgrade/downgrade, model parity, table discovery, and idempotent
  concept synchronization pass against PostgreSQL 17.

## Deliberate limits and remaining gates

This record does not declare Phase 1B-D2.2b2, Phase 1C, or Phase 2 complete. It introduces
a dormant foundation so retrieval quality can be developed and measured early.

Still required are a reviewed Source Policy Registry, production ingestion connectors,
company identity/alias administration, richer role graphs, stored evidence repository
commands, hybrid retrieval, labeled precision-at-K fixtures, post-interview feedback,
authenticated owner blueprint APIs, question rendering, and the existing real-document
profiling evidence plus named approvals.

See [ADR 0029](../adr/0029-evidence-ranked-question-intelligence-foundation.md).

## Full repository verification

`./scripts/verify.ps1` completed with `648 passed, 1 skipped`, `95.61%` combined
branch coverage, Ruff check/format across `243` files, strict mypy across `99` source
files, a clean 13-migration PostgreSQL release, dependency compatibility, and no known
dependency vulnerabilities.
