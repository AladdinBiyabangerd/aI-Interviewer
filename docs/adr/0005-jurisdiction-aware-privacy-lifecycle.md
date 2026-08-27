# ADR 0005: Jurisdiction-aware privacy lifecycle

- **Status:** Accepted for Phase 0C-B
- **Date:** 2026-08-24
- **Scope:** privacy-domain primitives; not a certification of legal compliance

Phase 0C-C cryptography, signed-manifest, and file-lifecycle consequences are now implemented by [ADR 0006](0006-file-secret-security.md). The Phase 0C-B exclusions below remain the historical boundary of this decision.

## Context

The platform is intended for a global market, with Azerbaijan as the initial/home market. Residence, processing region, storage region, purpose, data category, legal basis, consent, age, processor, transfer route, retention, and policy version may all affect whether processing is permitted. These decisions cannot be embedded as country-specific conditionals in interview business logic.

At the same time, Phase 0C-B must not become a generic rules engine or encode unreviewed interpretations of every privacy law.

## Decision

### Policy routing and approval

- A small `JurisdictionPolicyRegistry` maps ISO country/subdivision inputs to ordered, versioned policy modules. Specific modules precede broader modules, and a global fail-closed baseline is always last.
- Initial modules represent Azerbaijan, EU/EEA, UK, US federal, Canada, Turkey, Brazil, India, Australia, Singapore, and UAE. They are routing metadata marked as requiring legal review, not legal rules.
- New country or US state/provincial modules can be added through registry configuration without modifying privacy or interview business services.
- Persisted `privacy_policy_versions` must be legally approved and active before selection. No policy record is seeded by migration because publishing policy text, deadlines, legal bases, or retention periods is a legal/product release action.
- A privacy profile stores the exact country/subdivision, ordered jurisdiction codes and module versions, storage region, 18+ attestation time, and approved privacy-policy version used for the decision.

### Purpose limitation and retention

- `processing_rules` are narrow allow/deny records keyed by policy version, jurisdiction, data category, and purpose. They record the reviewed legal basis and exact consent notice when consent is required.
- Missing rules deny processing. Withdrawal immediately makes a consent-based processing decision fail.
- `retention_rules` are separate category/purpose decisions. The resolved duration and action are copied onto lifecycle records when those records are created, so a later policy edit cannot silently rewrite historical retention evidence.
- This is a bounded decision table, not a generic compliance language. Complex exceptions require a reviewed policy module or human privacy-request handling.

### Consent and individual requests

- Consent is tied to immutable notice identity, notice version, policy version, content digest, purpose, category, and disclosure URI. An active grant is unique; withdrawal is explicit and timestamped; a later grant creates new evidence.
- Authenticated self-service requests support access, machine-readable export, and deletion with per-type OAuth scopes and hashed idempotency keys.
- Requests move through received, verified, processing, and terminal states. The current self-service identity is considered verified by the OIDC boundary; delegated/authorized-agent verification remains a later legal/operations workflow.
- Audit evidence records identifiers, actions, policy/purpose metadata, and result codes only. It never records token values, source documents, answers, or raw processor payloads.

### Deletion, processors, and backups

- Deletion first blocks account access, copies required vendor locators into bounded deletion tasks, emits transactional outbox work, removes local consent/usage data, and then removes the identity mapping once all processor tasks acknowledge deletion.
- Vendor tasks use leases, bounded exponential retry, escalation, and an explicit operator requeue path. Successful tasks clear the vendor locator. A request cannot be completed while a processor task remains incomplete.
- The processor inventory separates vendor identity from approved activity. Each activity records category, purpose, policy version, origin/processing/storage regions, cross-border status, reviewed transfer mechanism, deletion method, and deletion SLA. A vendor cannot be registered for account data until the purpose decision also succeeds.
- Deletion creates a keyed-HMAC subject fingerprint and cutoff marker. The marker contains no raw issuer/subject and is emitted for replication to a trusted control-plane store outside ordinary database backup history.
- A restored database must remain isolated until all post-backup deletion manifests are replayed. Replay deletes only an account whose ID, keyed fingerprint, and creation time match the pre-cutoff identity; it does not erase a genuinely newer re-registration.
- Existing backups are not rewritten. They expire under the approved backup horizon, and any restore before expiry must replay the external deletion manifest before readiness.

### Anonymization and audit retention

- Completion removes the account/identity link and direct consent/vendor locators. Privacy requests and processor evidence can be deleted or irreversibly unlinked according to their stored retention action.
- Privacy audit rows are append-only until their declared `retain_until`. Database triggers still reject update, truncate, and premature delete; deletion becomes possible only after the database clock reaches the recorded deadline.
- Historic opaque account UUIDs in audit evidence become unlinkable after the sole account mapping is deleted. Raw external identity values are never copied into audit or outbox details.

## Consequences

- Production must inject a minimum 32-byte HMAC key and enable the privacy lifecycle; key storage/rotation is completed in Phase 0C-C.
- A deployment cannot process user data until legal reviewers publish policy, processing, retention, consent-notice, and processor-activity records for that deployment.
- Actual vendor deletion connectors are added only with a reviewed processor inventory entry; the durable task/outbox contract is ready now.
- The control-plane sink for deletion manifests must be operational, access-controlled, integrity-protected, and included in recovery drills before public launch.
- Residence is self-declared in this phase. Geolocation is neither collected nor treated as a reliable legal-jurisdiction signal.

## Explicitly excluded

- Legal certification for any country, automated resolution of every statutory exception, authorized-agent workflows, regulator portals, legal-hold adjudication, and appeal handling.
- File/object storage, malware scanning, secret-manager integration, and manifest signing; these are Phase 0C-C.
- CV/JD/interview data, Knowledge Base, RAG, crawlers, source ingestion, model calls, voice, and video.
