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

## Phase 1A-D1 controls implemented

- Extracted source text has a dedicated owner-bound aggregate tied to one exact immutable
  document version. Composite foreign keys prevent cross-owner lineage, while document
  erasure and file retention cascade through encrypted revisions.
- PostgreSQL stores only AES-256-GCM ciphertext, nonce, explicit rotation key ID, and a
  context-bound HMAC digest/key ID. Authenticated additional data binds identity,
  revision, origin, predecessor, exact parser provenance, counts, digest, and key ID;
  metadata or ciphertext tampering fails decryption.
- Parser-result persistence repeats the active account, draft preparation, current
  purpose authorization, privacy/legal/retention snapshot, latest document version,
  exact released asset, and active parser-release checks. Policy ID alone is
  insufficient: adapter, version, isolation, media, byte limit, scan requirement,
  category, purpose, and privacy policy must match.
- Content is bounded by characters and UTF-8 bytes, requires LF newlines, and rejects
  unsafe Unicode control/format/surrogate characters. Exact valid multilingual text is
  retained without silent normalization.
- Owner-level locking and unique constraints make exact parser retries idempotent. A
  changed result/provenance conflicts and cannot overwrite the original extraction.
- Database triggers reject source identity reassignment and every source-version update;
  a separate trigger validates the reserved sequential correction chain.
- Audit and outbox events contain only opaque identifiers and bounded parser metadata.
  Plaintext, ciphertext, nonce, digest, document hash, counts, and object keys are
  excluded.
- This internal runtime has no parser, worker, HTTP route, correction, or AI connection.
  Export/retention/recovery integration remains a mandatory D4 gate before product
  traffic can create source text.

## Phase 1A-D2.1 controls implemented

- Each exact document version can create only one owner-bound extraction job. The job
  snapshots the released asset, parser policy, privacy decision, retention rule, media,
  byte length, and source digest; a database trigger prevents those identities from
  being changed while status metadata moves.
- Claims use `SKIP LOCKED`, a bounded five-minute lease, a fresh UUID fencing token, and
  a bounded worker identifier. A stale worker cannot complete or fail a lease after it
  has been reclaimed by another worker.
- Attempts are capped at five. Only the explicit safe failure taxonomy is accepted;
  transient parser/source failures use bounded exponential retry and input/policy
  failures terminate without automatic replay. State constraints require a coherent
  lock, result, error, and completion shape.
- Job rows contain no bytes, object keys, filenames, parser exception text, or source
  text. Scheduling and transitions emit only opaque IDs and allowlisted parser/status
  metadata to audit/outbox channels.
- D2.1 defines persistence and fencing only. No parser process, adapter, network access,
  model call, or product route is enabled until the separately gated D2.2 sandbox is
  implemented and verified.

## Phase 1A-D2.2 through D4 controls implemented

- Parser execution runs in a separate no-network child process with bounded time,
  memory, output, file descriptors, and exact versioned PDF/DOCX/text adapters. Only
  bytes obtained through the released-policy read boundary enter that process.
- The worker persists through the encrypted source-text service and fenced job lease;
  parser faults map to a closed error taxonomy and cannot write a partial success.
- Authenticated owner routes can inspect the full immutable source-text lineage and
  append an optimistic, idempotent correction without mutating prior revisions.
- Source-text content and extraction-job metadata participate in privacy export;
  document-version ownership cascades erase both domains. Real supported-format
  fixtures, migration/model parity, logical restore, and release-image checks passed.

## Phase 1B-A controls implemented

- Model execution is disabled by default. Enabling requires exact bounded
  provider/model/version coordinates and an explicitly injected adapter; no concrete
  provider, endpoint, credential, or outbound call exists yet.
- Provider requests separate instructions from source text and include the
  application-owned JSON schema. Provider responses must carry the exact expected model
  release and are validated again by frozen, strict, extra-forbid application models.
- Prompt/schema release coordinates plus canonical instruction/schema SHA-256 digests
  make successful execution identity reproducible. Unknown fields, coercion, malformed
  JSON, truncation, filtering, excessive output, and release drift fail closed.
- Input/output/token/attempt/timeout/retry bounds limit abuse and cost exposure.
  Cancellation propagates. Retryability and terminal errors use closed safe enums.
- Instructions, candidate source text, JSON schema, and raw output are excluded from
  object representations. Provider exception text is discarded and the gateway emits
  no content-bearing log or telemetry signal.
- Prompt-injection defenses remain incomplete until Phase 1B-B/C adds application-owned
  profile schemas, exact source-span verification, adversarial fixtures, policy-gated
  jobs, and a reviewed provider adapter. Product traffic cannot call the gateway yet.

## Phase 1B-B1 controls implemented

- Separate strict CV and JD output contracts reject unknown fields and coercion. Direct
  identity/contact fields are absent; extracted scope is limited to interview-relevant
  claims and requirements.
- Every claim requires bounded exact source evidence. The verifier checks half-open
  Unicode offsets and quote equality against one exact decrypted source-text version;
  invalid grounding cannot produce a verified result.
- Claim IDs, languages, collection sizes, evidence counts/lengths, derived text, skill
  names, project technologies, and cross-priority JD requirements are bounded or
  uniqueness-checked. Unsafe Unicode and implicit whitespace cleanup are rejected.
- Model outputs and verified profiles suppress content in `repr`/`str`. Verification
  failures expose only closed safe codes without source text, quote, or claim content.
- These contracts reduce but do not solve prompt injection or semantic hallucination.
  At the 1B-B1 boundary no prompt/provider existed and no result was persisted. Phase
  1B-B2.1 now adds exact-source encrypted storage; policy-gated jobs, minimised prompts,
  adversarial fixtures, and reviewed processor controls remain required before product
  execution.

## Phase 1B-B2.1 controls implemented

- A profile aggregate is owner-bound to one exact document version, source-text
  aggregate, and latest immutable source-text revision. Composite foreign keys and
  database triggers reject cross-owner reassignment, lineage drift, mutable aggregate
  identity, profile-version updates, and invalid predecessor/version chains.
- Before writing, the service locks and reauthorizes the active account, draft and
  unexpired preparation, latest non-archived document version, latest source revision,
  privacy profile, processing rule, legal basis, and delete-only retention decision.
  It reopens/decrypts the exact source and repeats application-owned document-type,
  bounds, and exact-quote evidence validation inside the transaction.
- Canonical strict profile JSON is encrypted with AES-256-GCM and never stored as
  plaintext. Metadata-bound AAD and a separate keyed HMAC bind owner/profile/version,
  source/document lineage, schema/model/prompt identities, instruction/schema digests,
  evidence counts, privacy/retention snapshots, and key identities. Read/export fails
  closed on decryption, schema, digest, lineage, or count mismatch.
- The first immutable revision records exact provider/model/version,
  prompt/version, schema ID/version, canonical instruction/schema SHA-256, model
  attempts, and content-free evidence counts. An exact replay is idempotent; a changed
  output or release identity conflicts and cannot overwrite the stored result.
- Privacy access/export decrypts only through the narrow owner-scoped profile service
  under schema `phase-1b-b2.1`. Account, document-version, and source-text cascades erase
  profile aggregates and versions; the stored retention action is delete-only.
- Audit/outbox details contain only opaque resource IDs, document type, version, and
  content-free counts. Profile JSON, source quotes, ciphertext, nonce, digest, and model
  text are excluded from audit, logs, telemetry, and object representations.
- No provider adapter, credential, endpoint, outbound model call, profiling worker,
  public profile route, or correction command was added. Durable fenced jobs and
  bounded dead-letter state are now supplied by Phase 1B-B2.2.

## Phase 1B-B2.2 controls implemented

- One idempotent job is bound to the exact owner, preparation, document version,
  source aggregate, immutable source revision, and document type. Scheduling repeats
  are harmless only when every release and policy snapshot is identical; drift
  conflicts instead of silently reusing work.
- Privacy/legal/retention decisions and exact provider/model, prompt, schema,
  instruction/schema digest, and maximum-output-token coordinates are immutable job
  snapshots protected by constraints and database triggers.
- Claims use `SKIP LOCKED`, a five-minute UUID lease token, database time, and fencing
  on every mutation. Expired claims can be recovered; stale or competing workers cannot
  record failure or success.
- Retryable failures use closed safe codes, bounded exponential backoff, and at most
  five claims. Non-retryable and exhausted work enters explicit `dead_letter` state.
  Candidate text, prompts, output, quotes, raw provider errors, ciphertext, nonce, and
  keyed digests are excluded from the job, audit, and outbox payloads.
- A job can succeed only by referencing an encrypted profile for the same owner,
  document/source revision and exact model/prompt/schema release. Database transition
  and result triggers independently enforce terminal state shape and result linkage.
- Privacy export includes content-free owned profiling-job metadata under schema
  `phase-1b-b2.2`; account/document/source cascades erase the jobs. No provider adapter,
  outbound model call, profiling worker, or public route is enabled by this phase.

## Phase 1B-C1 controls implemented

- Separate application-owned CV/JD prompt releases bind exact instructions, strict
  schemas, maximum output tokens, and canonical SHA-256 identities. Instructions treat
  the complete document as untrusted data, ignore embedded commands, exclude direct
  identity/contact fields, and require exact Unicode source spans.
- Every newly scheduled profiling job requires an immutable approved processor activity.
  Scheduling verifies active processor/activity status, exact model-provider key,
  privacy policy, `candidate_document/interview_preparation` purpose, and the owner's
  origin/storage region. Migration refuses to invent authorization for pre-existing jobs.
- The job UUID is the exact provider request/idempotency/deletion reference. Immediately
  before each call, the worker reauthorizes the activity and registers that locator through
  the privacy lifecycle; PostgreSQL stores only AES-GCM ciphertext and a keyed digest.
  Processor suspension or policy drift prevents candidate text from reaching the adapter.
- Worker execution has a distinct disabled-by-default gate and requires model gateway,
  privacy, file-security, and a gateway retry budget that fits within the five-minute
  lease. The OpenAI adapter is constructed only for explicit OpenAI coordinates and a
  server secret; no background loop starts implicitly.
- Before decryption/provider use, the worker matches the job's model/prompt/schema/digest
  snapshots to the configured gateway and code-owned prompt. After strict gateway parsing,
  it repeats exact-source evidence validation and uses only the encrypted profile service.
- Success is committed with the current UUID lease token. Stale workers return a fenced
  outcome without mutating state; retries reuse the same processor request reference and
  idempotent profile lineage. Cancellation propagates without recording a false failure.
- Safe provider failures map to the existing closed retry/dead-letter taxonomy. Unexpected
  failures become `internal_failure`; source text, prompts, output, quotes, ciphertext,
  locator plaintext, and raw exceptions remain absent from operational evidence.
- Privacy export advances to `phase-1b-c1` because safe profiling-job metadata now includes
  the immutable processor activity ID. No credential is bundled, and the default
  configuration still makes no outbound call or starts a continuous supervisor.

## Phase 1B-C2 controls implemented

- Profile/status reads and corrections require bearer authentication plus
  `preparation:read` or `preparation:write`. Queries bind account, preparation, document
  version, and exact source-text version; cross-owner resources remain opaque `404`.
- Owner status responses expose only bounded job state, attempts, safe failure code,
  retryability, and availability/completion timestamps. Worker identity, lease token,
  processor activity/locator, release digests, and raw provider detail are excluded.
- A profile is exposed only when the fenced job is durably `succeeded` and its result ID
  matches the exact encrypted profile. Active work returns no profile even during the
  small interval after profile persistence and before the job success transition.
- Responses use `Cache-Control: no-store`. Completed histories carry a strong aggregate
  ETag; corrections require a quoted positive `If-Match`, return `412` on stale state,
  and treat only an identical immediately repeated append as idempotent.
- Correction payloads pass the strict CV/JD schema, document-type check, current
  privacy/legal/delete-only retention authorization, latest document/source checks, and
  exact evidence-span comparison against decrypted retained source text inside the
  transaction. Invalid or stale content cannot persist.
- Every correction is a new AES-GCM encrypted, HMAC-bound `user_correction` version with
  an immutable predecessor. Generated and earlier corrected history is never updated;
  database triggers continue to reject version mutation and broken chains.
- Correction audit/outbox contains opaque IDs, bounded schema/origin and evidence counts,
  with the owner as actor. Profile JSON, quotes, source text, ciphertext, nonce, digest,
  and request body remain absent from audit, outbox, logs, and telemetry.
- Privacy export advances to `phase-1b-c2` and includes the complete decrypted,
  revalidated profile history. Existing account/document/source cascades erase it. The
  existing schema already reserved and protects correction rows, so no migration was
  needed. C2 added no provider activation or worker supervisor; the later
  disabled-by-default supervisor is covered below and by ADR 0028.

## Phase 1B-D1 controls implemented

- The quality evaluator is an offline, bounded-file command and does not contact the
  API, database, provider, or any external service. Invalid input and summaries exclude
  source text, profile statements, evidence quotes, paths, prompts, and raw output.
- Every evidence bundle binds exact model coordinates and the canonical digest of both
  current CV/JD prompt/schema contracts. Prompt drift blocks eligibility.
- Gold source spans must validate exactly. Predicted span mismatches lower explicit
  coverage, and the fixed policy requires 100%. Human adjudication exhaustively maps
  every gold and predicted claim once, avoiding opaque model-based semantic judging.
- Minimum corpus, AZ/EN x CV/JD, adversarial-risk, and field-support rules prevent a
  copied-gold or field-sparse seed from claiming release quality. Precision, recall,
  strict prediction success, owner-review coverage, and correction rate all gate the
  result.
- Evaluation cannot approve a release. A separate record binds the full evidence digest
  and requires unique product, engineering, Azerbaijani, and English reviewer roles.
- Only explicitly synthetic fixtures may be marked repository-safe. Sensitive or
  rights-restricted corpora remain outside version control under an approved access,
  purpose, retention, and deletion boundary. D1 ships no real corpus or provider call.

## Phase 1B-D2.1 controls implemented

- The concrete adapter has one fixed TLS destination: OpenAI `POST /v1/responses`.
  Redirects, ambient proxy inheritance, configurable base URLs, provider tools, search,
  files, background execution, and server-side continuation are not enabled.
- The adapter sends the configured exact model version, `store=false`, and
  `truncation=disabled`. It returns the response-reported model identity so alias or
  release drift is rejected by the existing gateway before output can persist.
- Provider schema normalization removes defaults and recursively requires every object
  property with `additionalProperties=false`. The application-owned original strict
  schema, exact source-span verifier, and encrypted persistence boundary remain
  independent final authorities.
- The durable job UUID is sent only as `X-Client-Request-Id`. The API key is held as
  `SecretStr`; hosted environments require an absolute startup secret file. Disabled or
  non-OpenAI configurations reject OpenAI credentials.
- HTTP/provider response bodies and exception text are discarded on failures. Status,
  timeout, network, incomplete, refusal, malformed, oversized, and unexpected-state
  outcomes map to closed safe codes. Successful raw responses are bounded before parsing.
- Execution and the worker remain disabled by default. Mock-transport tests make no
  external request. D2.1 adds no credential, corpus prediction, quality approval,
  processor contract, country activation, public scheduler, or continuous supervisor.
- `store=false` reduces API-side response storage but is not treated as a processor,
  residency, retention, or deletion guarantee. Those remain activity-specific legal and
  operational gates before any real candidate or rights-cleared corpus data is sent.

## Phase 1B-D2.2a controls implemented

- The offline prediction command accepts only a strict corpus and a separate `approved`
  authorization bound to its canonical digest, exact dataset/version, current prompt
  digest, exact OpenAI model release, processor activity, data-control review, approver,
  and timezone-aware active window. Drift or expiry blocks before the first request.
- A second `--confirm-external-processing` operator action is mandatory. This is a
  deliberate safety interlock, not a substitute for rights, privacy, transfer, region,
  retention, deletion, budget, or provider-contract approval.
- A provider-free preflight runs the same corpus digest, current prompt, exact release,
  and active-window authorization checks without constructing a gateway or reading a
  credential. Its summary excludes corpus content, paths, approver identity, processor
  and data-control references, and every secret.
- The corpus is bounded to 200 fixtures and runs sequentially. Deterministic request IDs
  contain digests/coordinates rather than candidate text. Strict gateway and exact-source
  validation remain active; expected failures become bounded codes.
- Corpus, authorization, predictions, review draft, and final evidence are private
  artifacts outside version control. Output uses exclusive create semantics and is
  written only after the run completes; stdout and invalid-input errors exclude paths,
  source/profile content, prompts, keys, and raw provider details.
- Review preparation verifies exact corpus/run binding, then deliberately emits empty
  adjudications and `not_reviewed` outcomes. Automation cannot impersonate the human
  reviewers required by D1.
- Tests use an in-memory provider. D2.2a made no external call and includes no credential,
  real corpus, prediction evidence, processor approval, or human quality decision.

## Disabled-by-default worker supervision controls implemented

- Background work is never started by the API lifespan. A separate operator/orchestrator
  command is required in addition to each worker's explicit enablement flag.
- Extraction remains unavailable without the secure file boundary. Profiling retains
  its model, privacy, secure-file, immutable processor-activity, prompt, evidence, and
  live-lease checks; the supervisor cannot bypass them.
- Each sweep is bounded and attempts enabled worker types independently. Runtime failure
  in one queue produces backoff without starving the other queue. Cancellation and
  process termination preserve normal application resource cleanup.
- Lost extraction transitions are fenced rather than retried against an expired lease.
  The durable winner remains authoritative.
- Operational output contains only bounded outcome counts and exception class names.
  Candidate content, identifiers, paths, keys, object coordinates, provider bodies, and
  exception messages remain excluded.
- Both workers remain disabled by default. No process deployment, provider activation,
  credential, corpus, quality approval, or new data category is introduced.

This threat model must be updated before each phase gate and whenever a new data type, vendor, trust boundary, or external audience is introduced.
