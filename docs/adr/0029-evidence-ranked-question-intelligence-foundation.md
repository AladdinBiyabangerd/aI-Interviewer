# ADR 0029: evidence-ranked question intelligence foundation

- Status: Accepted
- Date: 2026-09-02
- Scope: dormant knowledge and retrieval foundation before production activation

## Context

Interview value depends primarily on selecting useful preparation areas for the user's
actual vacancy, role, round, seniority, industry, and CV. A chat-shaped interface or a
semantic-nearest-question list cannot provide that value. Exact-company interview data is
also sparse for many Azerbaijani and small companies, so missing reports must be treated
as a normal input condition rather than an exceptional fallback to generic questions.

The existing roadmap still requires Phase 1B-D2.2b2 real-document profiling evidence and
named approval before Phase 1C can be declared complete. It also requires a legal source
policy before production ingestion. We can establish the deterministic, disabled product
boundary now without claiming either gate has passed.

## Decision

1. `knowledge` owns source/rights snapshots, normalized evidence, role competency graphs,
   question concepts, and evidence-derived company fingerprints. It never stores copied
   proprietary question wording as the primary object.
2. Sources are usable for derived facts only when their exact policy snapshot says
   `permitted_full` or `permitted_derived`. Public visibility, metadata-only access,
   pending review, prohibition, and withdrawal do not authorize retrieval-derived claims.
3. Company claims require explicit company evidence. High specificity requires at least
   two independent source groups, sufficient confidence, and official evidence. One weak
   anonymous report can remain visible as low-confidence evidence but cannot produce High.
4. JD requirements activate a reusable role competency graph. A production RAG requirement
   therefore expands into ingestion, chunking, embeddings, dense/sparse/hybrid retrieval,
   filtering, reranking, context construction, evaluation, hallucination mitigation,
   latency/cost, monitoring, failure, and scale concepts.
5. CV claims activate probe branches against the same graph. The blueprint contains only
   claim IDs and concept/probe metadata; it does not copy CV text into logs or rationales.
6. Industry patterns are application-owned, rights-cleared evidence with an explicit
   `industry_derived` origin. They never masquerade as company observations.
7. Ranking uses a versionable weight contract across JD importance, role, company, round,
   seniority, industry, CV, source trust, frequency, recency, and corroboration. Semantic
   similarity is not the sole ranking authority.
8. A deterministic quota allocator follows the activated competency distribution and a
   redundancy guard prevents repeated subtopics or highly overlapping concepts.
9. Outputs use probabilistic labels (`high_likelihood`, `strong_match`, and
   `worth_preparing`) plus High/Medium/Limited company specificity. They never state that
   a private question will be asked.
10. PostgreSQL stores sources, evidence, source-evidence corroboration edges, versioned
    concept releases, concept-evidence edges, fingerprints, and fingerprint evidence
    lineage in separate tables. The authored seed catalog is synchronized idempotently.
11. Retrieval does not ingest sources, mutate evidence, call a model, render the final
    natural-language question, or own an HTTP endpoint. Those remain separate boundaries.

## Consequences

The project has an executable question-intelligence vertical slice for deterministic
fixtures and database-backed concept releases. It can be evaluated before model-based
question rendering exists and it behaves deliberately under company cold start.

The current seed covers deep `data_and_ai`, `software_engineering`, and transparent general
role baselines; it is not a complete global taxonomy. Production ingestion connectors,
source-policy administration, real company evidence, hybrid/embedding retrieval, labeled
precision-at-K evaluation, user report collection, feedback learning, authenticated
blueprint APIs, and final question rendering remain pending. Phase 1B-D2.2b2 and the Phase
2 legal/retrieval gates remain mandatory before production activation.
