# Baseline Threat Model

## Scope

Candidate-preparation web application, API, workers, PostgreSQL, object storage, model providers, future source connectors, and future voice/video vendors. Employer screening and hiring decisions are explicitly excluded.

## Sensitive assets

- Account identifiers and authentication material
- Candidate preparation targets: company, role, seniority, location, round, and language
- CV and JD originals, extracted text, projects, employment history, and contact details
- Interview answers, transcripts, evaluations, skill state, and reports
- Consents, deletion/export records, and audit events
- Company-source evidence, rights metadata, and contributor reports
- Model/provider credentials, prompts, operational secrets, and cost controls
- Future audio, video, and practice integrity events

## Trust boundaries

1. Browser to public API
2. API to database, object storage, and job queue
3. Workers to model and document-processing providers
4. Ingestion workers to allowlisted public sources
5. Realtime browser to STT/TTS/avatar providers
6. Support/admin access to operational tooling

## Principal threats and required controls

| Threat | Required controls | Earliest phase |
|---|---|---|
| Cross-user data access | deny-by-default ownership checks, non-enumerable IDs, integration tests | 0C |
| Candidate-context tampering, replay, or Unicode ambiguity | bounded normalization, controlled codes, owner-scoped idempotency, optimistic concurrency, immutable privacy snapshots | 1A |
| Credential/session theft | standards-based auth, secure cookies/tokens, rotation, revocation, CSRF where applicable | 0C |
| Malicious or oversized upload | size/type/signature checks, quarantine, malware scan, parser isolation, time/memory limits | 0C/1A |
| Duplicate/orphaned upload after timeout or worker crash | hashed request-bound idempotency, durable lease/token, exact asset reservation, resumable state checks, idempotent immutable attachment, durable deletion | 1A |
| Prompt injection in CV/JD/source text | treat documents as data, strict schemas, tool allowlists, instruction isolation, adversarial fixtures | 1B/2B |
| Sensitive logging/telemetry | payload exclusion, redaction, structured metadata allowlist, retention and access controls | 0A onward |
| SSRF through JD/source URLs | allowlisted schemes, DNS/IP validation, redirect limits, egress controls, response limits | 1A/2B |
| Model output changes state incorrectly | schema validation, deterministic application commands, idempotency, state-machine authority | 1B/1D |
| Hallucinated company claims | provenance requirement, retrieval traces, confidence-aware fallback, regression tests | 2C/2D |
| Poisoned community reports | PII/secret scrubbing, quarantine, corroboration, source diversity, audit and abuse controls | 4B |
| Data retained beyond purpose | retention classes, deletion/export workflows, derived-data lineage, backup expiry | 0C onward |
| Vendor reuse or geographic transfer | provider contracts/settings, minimised payloads, regional review, explicit consent where needed | 1B/5A |
| Realtime false accusations | factual event timeline only, no emotion/cheating labels, opt-in, local processing, slice testing | 5C |
| Cost/resource abuse | authentication, quotas, rate limits, input and token budgets, cancellation, cost alerts | 0D onward |
| Dependency/build compromise | lockfiles, automated scanning, minimal non-root image, controlled CI permissions | 0A onward |
| Concurrent or mismatched schema release | single-head artifact, serialized forward migration, exact schema readiness, compatibility rollout | 0D |
| Mutable/untraceable release artifact | build-once digest promotion, source/release labels, pinned CI actions, SBOM and vulnerability gates | 0D |
| Telemetry content or identifier leakage | explicit attribute allowlists, route templates, message suppression/redaction, no auto-instrumentation, canary tests, bounded retention/access | 0D |
| Telemetry outage affects serving | background bounded export, exception-isolated exporters, collector-independent readiness, stdout logs | 0D |
| Metric cardinality/cost abuse | fixed enum attributes, normalized methods/routes, no IDs/trace IDs/request IDs as metric labels, documented budget | 0D |
| False reliability claim from stale/missing telemetry | explicit measurement heartbeat, no-data semantics, exact release/environment cohort, gap/reset evidence, reviewed SLI population | 0D |

## Phase 0A controls implemented

- Production configuration rejects wildcard hosts, interactive docs, and debug logging.
- Request identifiers are validated or regenerated and returned for support correlation.
- Logs are structured and contain request metadata, not request/response bodies.
- Unhandled exceptions return an opaque problem response.
- Baseline browser/security headers are attached to API responses.
- A locked dependency graph, automated checks, and non-root runtime container are defined.

## Phase 0B controls implemented

- PostgreSQL connections use bounded pool, connect, health-check, and statement timeouts; production configuration requires database TLS and rejects local credentials.
- Application transaction boundaries commit atomically and roll back on exceptions.
- Future user-owned records have a non-null ownership convention, UUIDv7 identifiers, UTC timestamps, and optimistic concurrency; identity foreign keys and authorization remain correctly deferred to Phase 0C.
- Outbox claims use bounded batches, leases, and `FOR UPDATE SKIP LOCKED`; operational payload guards reject known candidate-content and credential fields.
- Audit metadata is append-only at the database layer and recursively rejects known sensitive fields before insertion.
- Migration drift, downgrade/upgrade behavior, competing writes, transaction rollback, audit mutation, dependency vulnerabilities, and real database readiness are tested.
- The local PostgreSQL image runs as UID/GID 70 with no capabilities, a read-only root filesystem, `no-new-privileges`, and no unused privilege-drop binary. The API remains non-root.
- Logical backup/restore is rehearsed against an isolated database, including schema, row counts, audit triggers, and application readiness; temporary recovery artifacts are removed.
- The [current data inventory](data-inventory.md) records the exact storage boundary and deferrals.

## Phase 0C-A controls implemented

- Production cannot start without explicit OIDC authentication, HTTPS issuer/JWKS endpoints, and an API audience.
- JWT access tokens require asymmetric allowlisted signatures, `at+jwt` typing, bounded `kid`, exact issuer/audience, required standard claims, bounded lifetime, and valid scope syntax.
- Signing keys are cached and rotated through a bounded-time JWKS lookup; lookup and token failures fail closed and return opaque errors.
- Tokens, token claims beyond the minimal issuer/subject mapping, and provider profiles are never persisted or logged.
- Concurrent first authentication creates one UUIDv7 account and one append-only provisioning audit event.
- Disabled accounts, missing/invalid tokens, missing scopes, and cross-owner requests fail closed; cross-owner denial does not reveal resource existence.
- Machine identities are not granted candidate ownership by local role inference; provider scope policy and a later explicit service-account type are required.
- The [current data inventory](data-inventory.md) classifies the issuer/subject mapping and transient bearer/JWKS data.

## Phase 0C-B controls implemented

- Jurisdiction routing is versioned and layered; missing approved policy, processing, retention, consent, or processor records fail closed. Registry entries are not represented as legal-compliance claims.
- The product gate is 18+ and stores an attestation timestamp, not a date of birth. Country/subdivision and storage region are explicit policy inputs.
- Consent binds to an exact notice/policy/content digest and purpose. Withdrawal is timestamped, audited, and immediately blocks consent-dependent processing.
- Access/export/deletion requests use owner-bound queries, per-type scopes, hashed idempotency keys, explicit states, deadlines, and minimal audit evidence.
- Account deletion removes the external identity mapping and local consent/vendor locators; retained request/task evidence is deleted or unlinked under its stored policy action.
- Processor use requires an approved versioned activity covering purpose, category, regions, transfer mechanism, contract reference, deletion mechanism, and SLA. Deletion propagation is transactional, leased, retried with bounded backoff, escalated, and manually recoverable.
- Backup markers use keyed HMAC rather than raw identity. Restore replay requires matching UUID, fingerprint, and pre-cutoff creation time, preventing both resurrection and accidental deletion of a new registration.
- Audit updates, truncation, and premature deletion remain database-blocked. Privacy audit deletion is permitted only after the recorded retention deadline according to the database clock.
- Operational metadata excludes consent text, raw identity claims, vendor payloads, and user content. HMAC key injection is required when privacy is enabled and placeholder/short keys are rejected.
- The [Phase 0C-B data inventory](data-inventory.md) and [legal review register](../legal/phase-0c-b-unresolved-legal-questions.md) define remaining deployment gates.

## Phase 0C-C controls implemented

- Production database and privacy keys are accepted only through bounded, absolute, permission-checked startup secret files; raw environment values and the legacy single HMAC key are rejected.
- A versioned application keyring separates subject HMAC, AES-256-GCM field encryption, and manifest HMAC purposes. Ciphertext authentication binds processor locators to account and processor identifiers, and rotation retains explicit key IDs.
- Object-store readiness fails closed unless bucket versioning, all public-access blocks, and default SSE-KMS are active. Every write also requests the approved KMS key and a SHA-256 checksum.
- Upload validation is byte-based and bounded. It permits PDF, DOCX, and UTF-8 text only; verifies PDF termination; and rejects unsafe paths, duplicates, encryption, active content, invalid CRC, oversized expansion, excessive entries, and high compression ratios in DOCX containers.
- New objects enter an opaque quarantine key. A bounded ClamAV `INSTREAM` scan with a freshness-checked signature database must return an exact clean verdict before an explicit copy reaches a released key/version. Infected and unverifiable objects remain unavailable to parsers and enter retry or deletion paths.
- Parser access rechecks owner, released state, exact object version/hash, and an approved active parser adapter/version/isolation profile. The actual resource-constrained parser runtime remains a Phase 1A gate.
- Durable file-deletion tasks use leases, bounded exponential retry, escalation, and manual requeue. The S3 adapter enumerates and deletes every exact-key version and delete marker; privacy deletion and restore replay cannot finalize while file deletion is pending.
- Restore manifests are canonical and HMAC-signed. The key ID is verified before replay, and restored file artifacts require the same durable external deletion acknowledgement loop.
- Readiness includes both storage-control verification and scanner/signature freshness. Logs, outbox payloads, exports, and scan evidence contain metadata/digests only, never file bytes or processor plaintext locators.
- The [current data inventory](data-inventory.md), [ADR 0006](../adr/0006-file-secret-security.md), and [secure-file runbook](../runbooks/secure-file-operations.md) define remaining provider and operations gates.

## Phase 0D-A controls implemented

- Staging and production share one hosted safety contract and require a non-default release label plus a full source SHA.
- Application code and its sole-head Alembic graph ship in one image. A dedicated command verifies the artifact without database access and supports forward upgrade only.
- A bounded session-level PostgreSQL advisory lock serializes migration jobs on the same connection Alembic uses. The job verifies the exact final revision and emits no exception details or DSN.
- API readiness rejects a database whose `alembic_version` differs from the release's compiled schema contract, preventing traffic from reaching a mismatched binary/schema pair.
- OCI labels, lifecycle logs, migration events, and retained SBOMs carry bounded operational release metadata only.
- CI actions are pinned by full commit SHA; dependency and image vulnerability gates remain mandatory; the image's numeric non-root identity and embedded migration artifact are checked.
- Provider provisioning must separate the short-lived DDL migration identity from the long-lived least-privilege API identity. This remains an explicit 0D-E infrastructure gate.
- The [release ADR](../adr/0007-release-and-migration-contract.md) and [release runbook](../runbooks/release-and-rollback.md) define promotion, failure, compatibility rollback, and evidence handling.

## Phase 0D-B controls implemented

- Hosted environments require bounded OTLP metrics/traces with release/environment resources, nonzero sampling, HTTPS or loopback transport, and no credential-bearing endpoint.
- HTTP signals use route templates and fixed method/scheme/status attributes. Raw URLs, queries, hosts, client addresses, headers, bodies, identities, and baggage are never attached.
- Auto-instrumentation is not enabled for HTTP, SQLAlchemy, boto, or provider clients. Dependency decorators record only fixed operation/outcome names, never SQL, DSN, object keys, malware names, vendor locators, or content.
- JSON logs suppress third-party and parameterized messages, redact a tested secret/token/URL/email corpus, and replace exception text/locals/full paths with exception type and bounded frame metadata.
- Canonical UUID request IDs plus valid trace/span IDs support correlation without making high-cardinality identifiers metric attributes.
- Exporters run behind bounded batch/periodic processors and convert transport faults to fixed warnings. Application readiness and business/file/deletion transactions do not depend on collector availability.
- Database pool and deletion queue gauges have fixed label sets; deletion snapshots expose only type/state/count/age based on database time.
- The [telemetry ADR](../adr/0008-payload-blind-opentelemetry.md), [operations runbook](../runbooks/telemetry-operations.md), and [dashboard specification](../operations/telemetry-dashboard-spec.md) define access, retention, canary verification, and remaining backend gates.

## Phase 0D-C-A controls implemented

- Product, operational, and unknown HTTP route templates are separated by a fixed three-value metric attribute. New API routes fail a regression test until their SLI population is explicitly reviewed.
- API availability has an exact occurrence-based good/total definition; 5xx is bad, 4xx is reported separately, health traffic cannot improve the denominator, and no data is never treated as success.
- Operational snapshot attempts and last-success age expose failed or stale deletion-queue collection. The last-success series remains absent before the first successful database snapshot.
- Dependency, scanner, deletion-work, and database-pool signals are explicitly diagnostic and cannot be presented as a user-facing SLO without a later approved objective.
- A 28-day staging evidence gate requires exact release cohorts, counts/buckets, telemetry gaps/resets, low-traffic disclosure, privacy/cardinality checks, and real stakeholder approval before targets or alert rules exist.
- [ADR 0009](../adr/0009-measure-before-objective.md) and the [SLI measurement contract](../reliability/sli-measurement-contract.md) define the remaining 0D-C gates.

## Phase 0D-C-B1 controls implemented

- Baseline input accepts only bounded aggregate operational fields through a frozen extra-forbid schema. There is no free-text, path, URL, request event, identifier, trace, log, or content field.
- Evidence is bound to exact release cohorts, the SLI contract, route-population digest, fixed histogram boundaries, query/export digests, and a contiguous 28-day staging window.
- Empty traffic, measurement gaps, route drift, sensitive-canary matches, unexpected attributes, and missing daily snapshot success block review eligibility instead of being interpreted as good service.
- Histogram/count relationships, daily ordering, release uniqueness, and snapshot age relationships fail closed. Overflow latency remains explicitly unknown above the largest bound.
- File reads are bounded to 2 MiB. CLI failures expose only a fixed status and exception type, never evidence contents or paths.
- The safe summary cannot approve a target; live evidence, named stakeholders, budget policy, backend queries, and alert delivery remain mandatory later gates.

## Phase 1A-A controls implemented

- Preparation aggregates are authenticated, scope-protected, owner-bound, UUIDv7-addressed, and non-enumerable across owners. List traversal uses a bounded UUIDv7 keyset cursor rather than an unbounded offset.
- User text is NFKC-normalized, trimmed, length-bounded, and rejects control, format, and surrogate categories. Country is a strict two-letter ASCII code; role family, seniority, interview round, language, and status use controlled values with explicit bounded `other` text where applicable.
- Creation is authorized against the exact `candidate_preparation_context` / `interview_preparation` privacy policy and stores immutable policy, jurisdiction, legal-basis, retention-action, and retention-deadline snapshots. Missing or non-delete policy decisions fail closed.
- Owner-scoped hashed idempotency prevents duplicate creation without retaining raw request keys. A retry with different normalized input conflicts. Full replacement and archive commands require a strong positive version precondition and update atomically.
- Audit and outbox events contain only canonical codes, status, opaque resource ID, and version. Company, role, office, and fallback text are excluded from audit, outbox, logs, and telemetry.
- Privacy export includes the owner's preparation context through a versioned schema. Account erasure and restore-ledger replay delete local preparation rows immediately; due retention deletes expired rows under the stored delete-only decision.
- Phase 1A-A stores no file bytes, CV/JD content, extracted text, prompt, model output, answer, score, audio, or video. Immutable document versions, upload/paste, and sandboxed extraction remain separately gated work.
- The hosted 28-day reliability baseline and remaining alert/incident/traffic/production work are deferred under [ADR 0010](../adr/0010-feature-stable-mvp-before-hosted-reliability-baseline.md), not waived. They remain mandatory before production and may restart when route/query/contract changes invalidate comparability.

## Phase 1A-B controls implemented

- Candidate document metadata is split into a stable preparation/type aggregate and
  append-only version rows. PostgreSQL rejects version updates; privacy and retention
  remain able to delete rows explicitly.
- Composite foreign keys enforce the same owner across preparation, document, version,
  and file asset. Unique constraints prevent one released asset from being attached to
  multiple product versions.
- The attach boundary accepts only an active owner, draft owned preparation, exact
  owner-matched released asset, compatible candidate-document purpose/category,
  unexpired retention, complete release metadata, and matching current delete-only
  privacy decision.
- The metadata read API requires `preparation:read`, applies exact owner predicates, uses
  opaque 404 responses, and excludes object keys, KMS metadata, internal privacy record
  IDs, document bytes, filenames, and extracted text.
- Audit/outbox evidence excludes candidate text, document digest, and object keys.
  Telemetry continues to use only bounded route templates and operational enums.
- File deletion releases the document reference in the same transaction before deleting
  the asset row. Account erasure removes document lineage before preparation context,
  while durable object deletion must finish before final account deletion.
- At the Phase 1A-B boundary there was no public upload/paste mutation. Phase 1A-C adds
  that boundary only; parser, extracted text, prompt, model output, answer, score, audio,
  and video remain later gates.

## Phase 1A-C controls implemented

- Upload and paste require authenticated `preparation:write`, exact owner matching, an
  active account, a draft preparation, current purpose authorization, and delete-only
  privacy/retention. Status reads require `preparation:read` and exact owner/preparation
  predicates.
- Raw bodies are bounded by both declared length and streamed accumulation. Content
  encoding and unsupported types are rejected. Upload accepts only the existing
  PDF/DOCX/UTF-8 allowlist; paste additionally requires plain UTF-8. No filename or
  multipart metadata is accepted.
- Raw idempotency keys are never stored. Their owner-scoped SHA-256 and a request digest
  binding preparation/type/source/media/content digest make exact replay deterministic
  and conflicting reuse fail closed.
- A durable processing lease/token and reserved UUIDv7 asset close process-crash and
  database/object-store gaps. Active retry cannot run the same claim concurrently;
  expired claims can recover. Resumption validates owner, policy, purpose, type, length,
  digest, parser-release policy, retention, and deletion state before reusing an asset.
- Storage failure rotates only a reservation already placed on durable cleanup. Scanner
  failure preserves the quarantined asset. Failures after clean release or immutable
  attachment reuse the same asset/version, preventing orphan growth and duplicate
  lineage.
- Infected or otherwise unsafe content is never released or attached. Parser access is
  still impossible from the intake API; extraction remains behind the Phase 1A-D exact
  adapter/version/isolation gate.
- Intake responses, exports, audit, outbox, logs, and telemetry exclude bytes, filenames,
  object keys, KMS data, raw idempotency key, request/content digest, processing token,
  and internal policy IDs. Cache control is `no-store`.
- Account erasure deletes intake metadata before document/preparation records. File
  deletion releases both intake and version references transactionally; rejected
  status-only rows are covered by due retention.
- Rate limiting, distributed concurrency budgets, load/abuse evidence, live staging
  objectives, alerting, provider IaC, and the final production gate remain mandatory
  Phase 0D work. The current conservative per-owner lock is not a substitute for that
  evidence.

This threat model must be updated before each phase gate and whenever a new data type, vendor, trust boundary, or external audience is introduced.
