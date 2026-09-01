# AI Interviewer Platform - Development Roadmap

## 1. Product interpretation and immutable guardrails

The source plan describes a candidate-preparation product, not an employer decision system and not a generic question chatbot. The durable product is an evidence-grounded interview intelligence and decision engine that combines company context, role and seniority, interview round, job description, CV claims, and later candidate skill state.

The following rules apply across every phase:

1. Company-specific claims must be traceable to permitted evidence. Insufficient evidence results in a visible `Limited` specificity level and a JD/CV/role fallback, never invented company knowledge.
2. Simulation mode does not reveal per-answer scores during the interview. Coach mode is a later, explicit behavior.
3. Evaluations must contain rubric dimensions, observable evidence, confidence, and model/prompt version metadata. A bare score is not an acceptable result.
4. CV, audio, video, gaze, and report data are sensitive. Data minimisation, purpose limitation, retention, deletion, encryption, and consent are architecture requirements.
5. Raw video storage is off by default. Future face/head-pose processing should remain in the browser where practical, sending only transparent practice events.
6. The product must not infer emotion or label cheating. Integrity output is limited to factual events with uncertainty and context.
7. Source ingestion is allowlist-based. Rights, provenance, permitted uses, retention, and attribution are stored before content can enter production retrieval.
8. Coding answers require sandboxed execution where possible; an LLM alone is not the correctness oracle.
9. Azerbaijan is the initial/home market and Azerbaijani and English are first-class launch languages. Privacy, provenance, policy, and source-rights models remain global and jurisdiction-aware; schemas store canonical concepts separately from localized display text.
10. Employer-facing use is out of scope and requires a new legal, privacy, and product-risk assessment.

## 2. Target architecture

Start as a modular monolith with separately runnable workers. This keeps transactional boundaries and operations understandable while preserving module interfaces that can be extracted if measured scale requires it.

| Module | Responsibility | Owns data | Must not do |
|---|---|---|---|
| Identity and privacy | Account boundary, consent, export/deletion, retention policy | Users, consents, deletion jobs | Interview scoring |
| Candidate inputs | Company/role/round input, CV/JD upload and redaction | Documents and input metadata | Infer company facts |
| Profiling | Structured CV/JD skills, responsibilities, requirements, projects, and claims | Versioned profiles and extraction evidence | Run interview sessions |
| Knowledge | Company/role/round taxonomy, concepts, evidence, rights, confidence | Sources, evidence, concepts, fingerprints | Generate unsupported claims |
| Retrieval | Metadata filtering, keyword/vector retrieval, reranking, fallback, specificity | Retrieval traces and evaluation artifacts | Mutate source evidence |
| Blueprint | Section, competency, rubric, time, and question budgets | Versioned interview blueprints | Conduct free-form orchestration |
| Session | Deterministic state machine, idempotency, turn/order/time budgets | Sessions, turns, transitions | Hide state in LLM context only |
| Interviewer | Ask, clarify, probe, and transition within an approved plan | Generated question artifacts | Produce final scores |
| Evaluator | Structured rubric evaluation and confidence | Per-answer evidence and evaluations | Speak directly as interviewer |
| Skill state | Per-competency mastery/confidence updates | Versioned skill observations | Override the orchestrator |
| Reporting | Readiness, JD coverage, skill matrix, CV risks, probes, action plan | Immutable report snapshots | Invent evidence absent from a session |
| Model gateway | Provider abstraction, structured-output validation, safety, budgets | Model-call metadata with redacted payload policy | Become a domain service |
| Operations | Jobs, outbox, telemetry, audit, rate/cost controls | Operational metadata | Store raw sensitive payloads in logs |

Core infrastructure is PostgreSQL for relational state, object storage for encrypted documents, a queue/outbox for durable asynchronous work, and later `pgvector` for the first retrieval implementation. A dedicated search/vector service is introduced only after measurements justify it.

## 3. Delivery sequence

### Phase 0 - Production foundation

#### 0A. Engineering foundation - implemented

- **Purpose:** establish a safe, testable runtime and repository contract before product logic appears.
- **Dependencies:** none.
- **Modules:** Python service package, typed environment configuration, application factory, liveness/readiness contracts, correlation IDs, structured logging, safe problem responses, security headers, lint/type/test/coverage gates, CI definition, non-root container.
- **Completion criteria:** dependency lock is reproducible; lint, format check, type check, tests, and coverage pass; the API starts; health contracts work; production configuration rejects unsafe host/docs/debug settings; container builds and runs as a non-root user.
- **Explicitly deferred:** database, authentication, user data, CV/JD handling, LLM calls, interviews, RAG, frontend, voice, and video.

#### 0B. Persistence and transaction foundation - implemented

- **Purpose:** create durable data ownership and migration rules before storing candidate data.
- **Dependencies:** 0A.
- **Modules:** PostgreSQL development environment; SQLAlchemy/Alembic; user-owned aggregate conventions; UUIDv7 or equivalent identifiers; UTC timestamps; optimistic concurrency; outbox; audit-event schema; backup/restore procedure.
- **Completion criteria:** migrations work both on an empty database and as an upgrade; rollback/forward strategy is documented; transaction and concurrency tests pass; backup and restore are exercised; no vector/RAG schema is added yet.

#### 0C. Identity, privacy, and file-security foundation

- **Purpose:** make the platform safe to receive candidate data.
- **Dependencies:** 0B and legal/privacy decisions for launch geography.
- **Modules:** standards-based authentication boundary; authorization/ownership checks; consent records; retention classes; export and deletion workflow; encrypted object storage; upload size/type/content validation; malware-scanning quarantine; secret management; security audit log.
- **Completion criteria:** cross-user access tests fail closed; deletion removes or irreversibly schedules every owned artifact; expired artifacts are removed by policy; unsafe files never reach parsing; logs contain no CV/JD text or credentials; threat-model controls are tested.

Delivery inside 0C is gated further:

1. **0C-A - identity and access foundation:** OIDC JWT resource-server validation, minimal local account mapping, active/disabled status, scope policies, ownership guard, and cross-user fail-closed tests.
2. **0C-B - privacy lifecycle - implemented:** layered jurisdiction routing; approved policy versions; exact consent and withdrawal; purpose/legal-basis decisions; category retention; access/export/deletion requests; anonymization; processor inventory and deletion propagation; backup deletion manifests and restore replay; minimal retention-bounded audit evidence. Country-specific legal approval remains a deployment gate, not a hard-coded domain rule.
3. **0C-C - file and secret security - implemented:** startup-only secret-file delivery; versioned application keyring; encrypted private object storage; bounded signature/container validation; quarantine and malware scanning; exact parser-release policy; durable version-aware deletion; privacy export/deletion/restore integration. Depends on 0C-A and the 0C-B data/retention classification. User-facing upload endpoints and parsing remain correctly deferred to 1A.

#### 0D. Delivery and observability baseline

- **Purpose:** make changes deployable and failures diagnosable before external users.
- **Dependencies:** 0A-0C.
- **Modules:** deployment environments, migrations as a release step, metrics/traces, redacted structured logs, SLOs, alerting, dependency and container scanning, rate limits, runbooks, disaster recovery.
- **Completion criteria:** staging deployment is repeatable; rollback and restore are rehearsed; dashboards show request/error/latency saturation without sensitive payloads; critical alerts and on-call runbooks are exercised.

Delivery inside 0D is gated further so deployment mechanics are proven before telemetry or traffic controls are layered onto them:

1. **0D-A - release and deployment foundation - implemented:** staging/production safety equivalence; immutable release identity; application and migration artifacts in one OCI image; a least-privilege, forward-only migration entrypoint; PostgreSQL advisory-lock serialization; exact release-to-schema readiness; pinned CI actions; image vulnerability gates; CycloneDX SBOM retention; release/rollback ADR and runbook. Cloud/orchestrator manifests remain deferred until a provider is selected.
2. **0D-B - telemetry baseline - implemented:** low-cardinality RED/USE metrics; W3C trace-context propagation; release/environment resources; strict route-template and payload exclusion; trace-correlated redacted JSON logs; bounded background OTLP/HTTP export; exporter failure isolation; database-pool and durable deletion-queue snapshots; instrumented object-store/scanner/deletion operations; retention/access policy; and a provider-neutral dashboard contract.
3. **0D-C - reliability objectives and response - in progress:** measured SLIs, approved SLO/error budgets, actionable multi-window alerts, ownership/escalation, and exercised dependency/file-security incident runbooks.
   - **0D-C-A - SLI measurement contract and integrity - implemented:** exact product/operations/other request populations; occurrence-based API availability semantics; latency and dependency/file/deletion diagnostic definitions; monitor-attempt and last-success freshness signals; 28-day staging evidence and no-data/gap rules.
   - **0D-C-B - staging baseline and objective approval - in progress:** collect the complete evidence window and obtain named product, engineering, and operations approval for numeric SLOs and an enforceable error-budget policy.
     - **0D-C-B1 - baseline evidence tooling - implemented:** strict payload-free 28-day evidence schema; shared histogram contract; deterministic availability/latency summary; gap, canary, route-drift and no-data eligibility gates; bounded offline CLI and safe exit contract.
     - **0D-C-B2 - live collection and approval, deferred pre-production gate:** select the reviewed measurement source/adapter, collect the full window from a feature-stable text release, retain immutable evidence, and obtain named approvals. By the user-approved [ADR 0010](adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md), this external gate follows the local Phase 1 text MVP but remains mandatory before production. No target exists before this gate.
   - **0D-C-C - actionable alert implementation:** compile the approved objectives into backend-specific recording and multi-window burn-rate rules, test them, and route page/ticket/no-data notifications to reviewed destinations.
   - **0D-C-D - exercised reliability response:** run dependency, telemetry, scanner, object-store/KMS, and deletion-work incidents; verify escalation, recovery, evidence, and postmortem actions.
4. **0D-D - traffic and resource protection:** identity/IP-aware rate controls, upload/concurrency/work-queue budgets, safe overload behavior, cost ceilings, and abuse/load tests. Distributed enforcement is selected from measured topology needs.
5. **0D-E - staging, recovery, and production gate:** reviewed provider-specific manifests/IaC, workload identities and network policy, zero-downtime deployment rehearsal, compatibility rollback, PITR/restore and deletion-ledger replay, failure injection, capacity evidence, and launch sign-off.

### Phase 1 - Core text MVP

#### 1A. Candidate onboarding and input model - in progress

- **Purpose:** securely collect company, role, seniority, country/office, interview round, JD, and CV.
- **Dependencies:** completed 0C boundary and provider-neutral 0D-A/0D-B/0D-C-A/0D-C-B1. Hosted 0D-C-B2 through 0D-E remain a hard pre-production gate under ADR 0010.
- **Modules:** controlled vocabularies plus user-entered fallback; paste/upload flow; optional PII-redacted CV representation; immutable document versions; processing status and recoverable errors.
- **Completion criteria:** supported inputs round-trip without loss; ownership and deletion tests pass; corrupt/password-protected/oversized documents fail safely; users can inspect and correct extracted text before AI processing.

Delivery inside 1A is gated further:

1. **1A-A - preparation target context - implemented:** owner-bound company, role-family/title, seniority, target country/office, interview-round, and AZ/EN language context; controlled codes plus exact `other` fallbacks; idempotent create; bounded keyset listing; ETag/`If-Match` replacement; archive; policy/retention snapshots; privacy export/immediate local deletion; append-only content-free audit/outbox evidence.
2. **1A-B - immutable candidate document versions - implemented:** one logical CV/JD aggregate per preparation/type; immutable version rows referencing released owner-matched assets; database owner invariants and update-rejection trigger; privacy export/erasure; file-retention reference release; owner-scoped metadata reads; no public intake or parser output yet.
3. **1A-C - authenticated upload and paste - implemented:** bounded raw-body upload and UTF-8 paste; owner-scoped hashed idempotency; durable lease/status saga; exact reserved asset; quarantine/validation/scan/release; safe immutable replacement; storage/scan/post-attachment recovery; privacy export/retention/deletion propagation; no parser output yet.
4. **1A-D - sandboxed extraction and user correction - in progress:** exact approved parser worker, source-text versions, bounded extraction errors, and user inspection/correction before AI processing.
   - **1A-D1 - encrypted immutable source-text domain - implemented:** one owner-bound aggregate per exact document version; AES-256-GCM content with metadata-bound AAD; keyed rotation-aware integrity digest; immutable parser/correction revision shape; exact active document/asset/privacy/parser-policy checks; idempotent parser-result persistence; cascade erasure; content-free audit/outbox. No parser or public endpoint exists yet.
   - **1A-D2.1 - durable extraction job contract - implemented:** one idempotent owner-bound job per exact document version; immutable parser/privacy/retention snapshots; UUID lease fencing; `SKIP LOCKED` claims; bounded attempts and safe failure codes; exponential retry; content-free audit/outbox transitions; no parser execution yet.
   - **1A-D2.2 - isolated parser execution - implemented:** exact released-policy-only reads through `read_for_parser`; no-network/resource-bounded child-process isolation (POSIX resource limits; the production target is Linux); separately versioned PDF/DOCX/TXT adapters; bounded safe failure taxonomy; crash-safe delivery into D1 through the new `CandidateExtractionWorker`. A later disabled-by-default shared supervisor now supplies one-shot and continuous execution; no product route or default activation exists.
   - **1A-D3 - owner inspection and correction - implemented:** authenticated owner-scoped reads validating the full preparation/document-version chain; safe combined display contract returning full decrypted version lineage; optimistic (`If-Match`) and idempotent immutable correction append; the route is registered in the reviewed SLI product-route population. No AI processing reads this text yet.
   - **1A-D4 - lifecycle and phase gate - implemented and locally release-verified:** privacy access/export integration for source-text (real decrypted content) and extraction-job (operational metadata) data is provided through two narrow lifecycle adapters; erasure remains covered by the existing `ON DELETE CASCADE` chains; parametrized supported-input fixtures pass through the real isolated worker for parseable PDF, DOCX, and text documents. The PostgreSQL integration suite, migration round-trip/model parity, logical backup/restore rehearsal, and release-image artifact check all passed at `20260828_0009`.

#### 1B. CV/JD profiling - in progress

- **Purpose:** create evidence-linked structured profiles without RAG.
- **Dependencies:** 1A and model gateway.
- **Modules:** text extraction; skill/project/responsibility/claim extraction; must-have/nice-to-have JD requirements; seniority hints; AZ/EN handling; strict schemas; retries and dead-letter handling; user corrections.
- **Completion criteria:** a labeled CV/JD fixture set meets agreed field precision/recall thresholds; every extracted claim points to a source span; invalid model output cannot persist; model/prompt versions are reproducible.

Delivery inside 1B is gated further:

1. **1B-A - provider-neutral model gateway - implemented and locally verified:** disabled-by-default
   provider port; exact provider/model/version and prompt/schema identity; canonical
   instruction/schema digests; strict extra-forbid structured output; bounded input,
   output, token, timeout, retry, and failure contracts; payload-free representations;
   no provider SDK, credential, endpoint, or external call.
2. **1B-B1 - evidence profile contracts - implemented and locally verified:** separate
   strict CV/JD schemas; bounded skills/projects/responsibilities/claims and
   must-have/nice-to-have requirements; AZ/EN language shape; mandatory exact
   `[start,end)` Unicode source quotes; duplicate/unsafe-text rejection; payload-safe
   verified result; no storage, provider, or external call.
3. **1B-B2 - durable profile domain and jobs - implemented and locally release-verified:**
   - **1B-B2.1 - encrypted immutable profile persistence - implemented and locally
     release-verified:** one owner-bound aggregate per exact latest source-text revision;
     canonical strict JSON protected by AES-256-GCM, metadata-bound AAD, and keyed
     integrity; exact model/prompt/schema and privacy/legal/retention provenance;
     same-transaction source decryption and evidence revalidation; idempotent exact
     replay; database-protected immutable version chains; privacy export and cascade
     erasure. No provider adapter, outbound model call, or public route.
   - **1B-B2.2 - fenced profiling jobs and dead-letter state - implemented and locally
     release-verified:** one idempotent job per exact source revision; immutable
     owner/source, privacy/retention, model/prompt/schema and digest snapshots;
     `SKIP LOCKED` claim, UUID lease fencing, stale-lease recovery, bounded exponential
     retry and explicit dead-letter state; success only against the exact matching
     encrypted profile release; content-free audit/outbox; privacy export and cascade
     erasure. No provider adapter, worker, or outbound model call is enabled.
4. **1B-C - profiling execution and correction - implemented and locally release-verified:**
   - **1B-C1 - policy-gated profiling worker - implemented and locally release-verified:**
     code-owned CV/JD prompt releases; exact provider request correlation; mandatory
     immutable processor-activity snapshot; pre-call processor reauthorization and
     encrypted deletion-locator registration; strict gateway execution; repeated exact
     evidence verification; encrypted idempotent profile persistence; live lease-token
     completion; payload-blind failures and cancellation. Runtime is separately disabled
      by default; D2.1 now supplies the OpenAI adapter, while no credential is shipped.
      A later shared worker process can supervise this runtime only after its separate
      enablement and deployment gates are satisfied.
   - **1B-C2 - owner profile inspection and immutable correction - implemented and
     locally release-verified:** authenticated owner-scoped safe job status and completed
     profile-history reads; strong ETag/`If-Match`; optimistic and exact-retry-idempotent
     encrypted `user_correction` append; exact retained-source evidence revalidation;
     content-free audit/outbox; and `phase-1b-c2` privacy export. Generated revisions
     remain immutable, unfinished worker results are not exposed, and no schema migration
     was required.
5. **1B-D - quality gate - in progress:** labeled AZ/EN CV/JD fixtures, agreed
   field-level precision/recall and source-span coverage thresholds, slice/error
   analysis, and regression approval.
   - **1B-D1 - deterministic quality contract and synthetic seed - implemented and
     locally release-verified:** strict offline corpus/prediction/adjudication schemas;
     exact model plus prompt/schema digest binding; deterministic field, AZ/EN x CV/JD,
     prompt-injection, and unsupported-claim metrics; fixed minimum support and quality
     thresholds; payload-safe CLI; separate evidence-digest-bound product, engineering,
     Azerbaijani, and English approval roles. The checked-in four-fixture synthetic seed
     is deliberately blocked as too small and field-sparse; it cannot claim model quality.
   - **1B-D2 - reviewed release evidence and approval - in progress:**
     - **1B-D2.1 - OpenAI Responses adapter - implemented and locally verified:** fixed
       OpenAI Responses endpoint; strict non-stored structured output; deterministic
       schema normalization; exact response-model drift detection; bounded payload-free
       failures; UUID request correlation; server-only secret/file delivery; disabled by
       default; mock-transport tests only, with no credential or external call.
     - **1B-D2.2a - authorized offline quality runner - implemented and locally verified:**
      separate strict corpus, time-bounded authorization, prediction, and unadjudicated
      review-draft artifacts; exact corpus/prompt/OpenAI-release binding; explicit external
      processing confirmation; deterministic request IDs; sequential bounded calls;
      create-only private output and payload-free summaries. No live call was made.
     - **1B-D2.2b1 - exact review finalization - implemented and locally verified:**
       local-only finalization binds a human-completed review back to the exact corpus and
       prediction run; rejects source, provenance, gold, prediction, coordinate, and order
       drift; requires exhaustive field-consistent adjudication plus every owner outcome;
       creates private evidence without overwrite and emits only counts/digests.
     - **1B-D2.2b2 - full evidence and approval - pending:** rights-cleared corpus meeting
      every minimum; outputs from one approved exact OpenAI release; exhaustive human
      adjudication and owner-review outcomes; recorded slice/error analysis; all
      thresholds met; four named approvals bound to the exact evidence digest. Product
       activation and production deployment of the disabled-by-default supervisor remain
       separate reviewed decisions.

#### 1C. Baseline interview blueprint

- **Purpose:** make each session bounded and reviewable before any question is asked.
- **Dependencies:** 1B.
- **Modules:** section and competency selection; time/question budgets; CV-risk selection; baseline technical/behavioral rubrics; explicit `Limited` company specificity; blueprint preview.
- **Completion criteria:** deterministic fixtures produce valid, budget-complete blueprints; all questions are grounded in JD/CV/role patterns; no company-specific assertion is emitted without knowledge evidence.

#### 1D. Deterministic text session

- **Purpose:** prove the complete interview flow using a simple, non-adaptive policy.
- **Dependencies:** 1C.
- **Modules:** persisted session state machine; start/answer/advance/finish commands; turn idempotency; time and question budgets; interviewer generation constrained by the blueprint; resume and failure recovery.
- **Completion criteria:** state-transition/property tests reject illegal transitions and duplicate answers; interrupted sessions resume; concurrent turns do not fork history; Simulation mode never exposes evaluator output mid-session.

#### 1E. Baseline evaluator and final report

- **Purpose:** provide useful, evidence-based results and establish evaluation measurement.
- **Dependencies:** 1D plus domain-advisor rubric approval.
- **Modules:** technical and behavioral rubric schemas; answer-to-evidence citations; confidence; readiness, JD coverage, skill matrix, CV risks, likely probes, and 3-7 day plan; human review dataset.
- **Completion criteria:** every score maps to quoted candidate evidence or an explicit missing signal; report arithmetic and schemas are deterministic; a human-labeled benchmark establishes baseline agreement and known failure modes; report generation is replayable.

#### 1F. MVP experience and launch gate

- **Purpose:** make the complete text flow usable and measurable.
- **Dependencies:** 1A-1E.
- **Modules:** accessible responsive web UI; progress and recovery states; interview history; analytics events with consent; support/admin diagnostics without content leakage; abuse and cost controls.
- **Completion criteria:** end-to-end browser tests pass; accessibility/security/performance reviews pass; completion, realism, error, latency, evaluator-agreement, and cost metrics are captured; product and engineering sign the Phase 1 gate.

### Phase 2 - Interview Knowledge Base and RAG

#### 2A. Global taxonomy, Source Policy Registry, provenance, and rights model

- **Dependencies:** Phase 1 stable schemas and legal source policy.
- **Modules:** companies/offices; role families and aliases; seniority; rounds; competencies; question concepts rather than verbatim proprietary questions; evidence frequency/recency/confidence; and a global Source Policy Registry. Every source policy records provider, acquisition method, API/license/permission status, robots/automation restrictions, commercial-use permission, copyright/license, permitted stored fields, full-content versus metadata/link-only storage, derived-fact permission, attribution, deletion/takedown, refresh, provenance, quality/confidence, and geographic/language relevance.
- **Completion criteria:** ambiguous or missing rights fail closed; every knowledge item and derived claim is traceable to source and rights versions; takedown can locate and remove affected material; taxonomy/source-policy changes are versioned and migration-tested; duplicate concepts are measured and reviewable. Public visibility alone never grants reuse rights.

#### 2B. Compliant allowlisted multi-source ingestion

- **Dependencies:** 2A.
- **Modules:** policy-gated connectors for approved company career/engineering pages, public job descriptions, official guides, technical documentation, engineering blogs, open datasets, compatible GitHub repositories, permitted Stack Exchange/Reddit APIs or datasets, research and career-center sources, licensed communities, and user/recruiter contributions; search engines are discovery only. Acquisition uses licensed/API/permission routes, metadata/reference-only records, user submissions, or independently authored equivalents when content reuse is not permitted. Snapshots, normalization, deduplication, attribution, review, refresh, takedown, and provenance reconciliation are mandatory.
- **Completion criteria:** every connector is enabled by an approved Source Policy Registry version; authentication, CAPTCHA, access controls, rate limits, robots restrictions, and technical controls are never bypassed; LinkedIn, LeetCode, Glassdoor, Reddit, and similar services are never blindly scraped; proprietary questions are not copied merely because visible; replay is idempotent; removed or rights-changed material and derived items can be traced and reconciled.

#### 2C. Hybrid retrieval and fallback hierarchy

- **Dependencies:** 2A-2B.
- **Modules:** PostgreSQL metadata filters; keyword and `pgvector` search; reranking; exact-company-to-JD/CV fallback ladder; retrieval traces; source diversity and recency weighting.
- **Completion criteria:** offline labeled queries meet target precision at K; metadata leakage is zero; fallbacks are deterministic; latency and cost budgets pass; retrieved evidence is visible for audit.

#### 2D. Company fingerprint and specificity UX

- **Dependencies:** 2C.
- **Modules:** company/role/round distributions; corroboration; High/Medium/Limited rules; user-facing evidence explanation; blueprint integration.
- **Completion criteria:** specificity levels are calibrated against coverage; single weak reports cannot create High confidence; unsupported company claims regression tests remain zero.

### Phase 3 - Adaptive interview engine

#### 3A. Planner and role-separated model execution

- **Dependencies:** Phase 2 retrieval quality gate.
- **Modules:** mutable section plan; independent interviewer/evaluator executions behind existing ports; strict structured outputs; deterministic orchestrator authority.
- **Completion criteria:** model calls cannot bypass state transitions or budgets; interviewer prompts cannot see hidden feedback content beyond approved policy inputs; replay/audit is possible.

#### 3B. Candidate skill state

- **Dependencies:** 3A and calibrated evaluator observations.
- **Modules:** per-competency mastery and confidence; evidence history; decay/update policy; missing-signal handling.
- **Completion criteria:** updates are explainable, bounded, and reproducible; confidence never rises without evidence; order-sensitivity tests are understood and approved.

#### 3C. Adaptive policy and two modes

- **Dependencies:** 3B.
- **Modules:** deepen, probe, clarify, diagnose, and move-on decisions; difficulty progression; coverage optimization; Simulation and Coach presentation rules.
- **Completion criteria:** policy simulation beats the baseline on coverage/realism without increasing unsafe or irrelevant questions; Simulation leakage tests pass; Coach feedback is explicitly enabled and accessible.

#### 3D. Evaluation calibration

- **Dependencies:** 3A-3C and expanded human annotations.
- **Modules:** evaluator agreement metrics, per-rubric error analysis, bias/slice analysis, model routing, regression suites, confidence calibration.
- **Completion criteria:** human/AI agreement and confidence targets pass for AZ and EN; material regressions block releases; unsupported high-confidence scores remain below the agreed ceiling.

### Phase 4 - Global contribution flywheel (Azerbaijan first)

#### 4A. Structured post-interview contribution

- **Dependencies:** trusted Phase 1 user base and privacy/legal approval.
- **Modules:** 60-90 second report; company/role/round/topic/difficulty/CV-question fields; purpose-specific consent; contribution withdrawal; incentives ledger.
- **Completion criteria:** contribution is voluntary and reversible; exact confidential questions and identities are discouraged; deletion propagates to derived data according to policy.

#### 4B. Anonymisation, moderation, and corroboration

- **Dependencies:** 4A and 2A.
- **Modules:** PII/interviewer-name/secret detection; quarantine and review; source trust; independent-report counting; recency; abuse/poisoning detection.
- **Completion criteria:** red-team corpus meets removal thresholds; one source cannot manufacture confidence; reviewer actions are audited; unsafe reports never enter retrieval.

#### 4C. Local company packs and partnerships

- **Dependencies:** 4B.
- **Modules:** corroborated fingerprints; university/community/employer programs; published competency and stage data, not confidential exact questions.
- **Completion criteria:** each pack has documented rights, coverage, freshness, and owner; user realism feedback validates uplift over generic fallback.

### Phase 5 - Voice and premium video

#### 5A. Voice readiness and realtime voice

- **Dependencies:** Phase 3 engine quality and privacy approval.
- **Modules:** AZ/EN/code-switching STT benchmark; streaming STT/TTS; interruption/turn-taking; reconnect; transcript correction; latency/cost monitoring.
- **Completion criteria:** word/error and semantic preservation targets pass by language slice; p95 turn latency, failure rate, accessibility fallback, and cost budgets pass; audio retention follows consent.

#### 5B. Video rendering adapter

- **Dependencies:** 5A.
- **Modules:** vendor-neutral realtime avatar interface; WebRTC lifecycle; degradation to voice/text; regional processing and vendor data controls.
- **Completion criteria:** vendor outage/degradation tests pass; engine remains independent from the renderer; privacy/security/vendor reviews pass; completed-session cost is within Premium economics.

#### 5C. Practice-only integrity events

- **Dependencies:** 5B and explicit opt-in design review.
- **Modules:** local face-presence/head-pose signals; tab/focus/fullscreen events; time-window event fusion; transparent event timeline; no raw video by default.
- **Completion criteria:** output contains factual events only, never emotion/dishonesty/cheating labels; false-positive testing covers lighting, disability, camera position, and natural gaze variation; opt-out and deletion work.

### Phase 6 - Global scale

#### 6A. Languages, countries, and connectors

- **Dependencies:** measured demand and proven rights workflow.
- **Modules:** localized taxonomies and rubrics; country/office fingerprints; additional allowlisted ATS connectors; locale-aware evaluation benchmarks.
- **Completion criteria:** each locale meets quality/privacy/legal gates independently; missing coverage visibly falls back instead of translating unsupported claims.

#### 6B. Scale, reliability, and cost evolution

- **Dependencies:** production bottleneck evidence.
- **Modules:** search/vector extraction only if justified; partitioning/read replicas; regional deployment; model routing/caching; queue isolation; chaos and load testing.
- **Completion criteria:** capacity and failure targets pass at forecast peak; cost per completed interview meets unit economics; no architecture split occurs without a measured bottleneck and migration plan.

## 4. Dependency chain and release gates

The original dependency chain remains the architectural ordering of capabilities. ADR 0010 moves the hosted reliability/production gate after the feature-stable Phase 1 text flow:

`0A -> 0B -> 0C -> 0D-A/B/C-A/B1 -> 1A -> 1B -> 1C -> 1D -> 1E -> 1F -> 0D-C-B2/C/D -> 0D-D -> 0D-E -> production`

Phase 2 and later product work begins only after the Phase 1 and pre-production gates are reviewed unless a later ADR explicitly changes that boundary.

Phase 4 may begin only after 2A defines provenance/rights and 0C proves consent/deletion. Phase 5 may begin only after the text engine and evaluator pass Phase 3 quality gates. Phase 6 is driven by measured demand and bottlenecks, not the calendar.

Every phase gate requires:

- all automated lint, type, unit, integration, security, and migration checks appropriate to the phase;
- an updated threat model and data inventory;
- no unresolved critical/high security issue;
- dashboards and runbooks for new failure modes;
- product metric baselines and explicit pass/fail thresholds before experimentation;
- architecture decision records for irreversible or high-cost choices;
- a rollback and data-migration plan;
- written confirmation that deferred features were not silently introduced.

## 5. Product quality metrics

| Area | Primary measures |
|---|---|
| End-to-end value | interview completion, user-rated realism, post-real-interview similarity |
| Profiling | field precision/recall, source-span coverage, user correction rate |
| Retrieval | precision at K, unsupported-company-claim rate, specificity calibration, fallback frequency |
| Evaluation | human/AI agreement, confidence calibration, rubric-level error and language/seniority slices |
| Reliability | availability, p95/p99 latency, session failure/resume rate, queue age |
| Privacy/security | deletion completion, access-control failures, sensitive-log findings, incident rate |
| Economics | model cost and infrastructure cost per completed interview |
| Realtime | STT quality by language, turn latency, reconnect success, video failure/degradation rate |

Numeric thresholds are established with real baseline data before each relevant gate; inventing targets before measurement would produce false confidence.

## 6. Current stop point

Phases 0A, 0B, 0C-A, 0C-B, 0C-C, 0D-A, 0D-B, 0D-C-A, 0D-C-B1, and 1A-A through 1A-D4 are complete and locally release-verified, closing Phase 1A. Phase 1B is now in progress: 1B-A provides the provider-neutral model gateway, 1B-B1 provides strict exact-evidence CV/JD output contracts, 1B-B2 provides encrypted immutable profile persistence and durable fenced jobs, 1B-C1 provides policy-gated worker execution with immutable processor authorization, encrypted usage registration, exact prompts, repeated evidence validation, and lease-fenced completion, 1B-C2 provides authenticated owner status/inspection plus immutable evidence-revalidated correction, and 1B-D1 provides the deterministic offline quality contract. Phase 1B-D2.1 provides a concrete disabled-by-default OpenAI Responses adapter, D2.2a provides an exact-authorization private offline runner and unadjudicated review draft, and D2.2b1 provides exact, drift-resistant human-review finalization. A separate payload-blind worker process now provides bounded one-shot or continuous supervision for explicitly enabled extraction/profiling workers; both remain disabled by default and production activation is not approved. No credential or real corpus was stored and no external call was made. The next gate is D2.2b2: run a rights-cleared full corpus, complete human adjudication and error analysis, pass every threshold, and obtain four named approvals. Under ADR 0010, live staging measurement and the remaining 0D production gates are deferred until the Phase 1 text contract is feature-stable, but remain mandatory before any production release. Country enablement and every real model processor still require approved legal policy records and activity-specific authorization; product and worker activation remain separate reviewed decisions.
