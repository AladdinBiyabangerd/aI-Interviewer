# ADR 0006: File and secret security boundary

- **Status:** Accepted for Phase 0C-C
- **Date:** 2026-08-24
- **Scope:** internal storage, quarantine, release, deletion, and application-secret contracts; not a user-facing upload or document-parser implementation

## Context

Phase 1A will receive CV/JD documents containing direct and inferred personal data. Before an HTTP upload route or parser exists, the platform needs a fail-closed boundary for secret delivery, byte validation, encrypted storage, malware quarantine, parser release, retention, export, deletion, and backup restore.

Database rows and object bytes cannot be committed atomically. S3 versioning also means an ordinary delete creates a delete marker while older versions remain retrievable. The design therefore requires explicit durable states and compensating deletion work rather than pretending storage and PostgreSQL share one transaction.

## Decision

### Startup secrets and application cryptography

- Production receives the database URL and privacy keyring from absolute orchestrator-mounted files. Files are read once during settings construction, bounded to 65,536 bytes, required to be regular UTF-8 files, and checked for unsafe POSIX access bits. Errors are opaque and secret values are never logged.
- Network secret lookups do not occur on request paths. The deployment platform may source the mounts from its approved secret manager and rotate them through a controlled restart.
- The privacy keyring is a versioned JSON document with distinct 256-bit keys for `subject_hmac`, `field_encryption`, and `manifest_hmac`. Each purpose has one active key ID; older keys may remain for decryption or restore verification.
- Processor locators use AES-256-GCM. Additional authenticated data binds ciphertext to the account and processor IDs. A keyed locator digest preserves idempotency without plaintext comparison. Production rejects the legacy raw HMAC setting.
- Deletion manifests use canonical JSON and an HMAC key/version. Subject fingerprints also store their key ID so restore replay remains possible across rotation.

### Object-storage contract

- The production adapter uses an S3-compatible private bucket and workload identity. Readiness requires enabled versioning, all four public-access blocks, and default SSE-KMS.
- Every quarantine upload independently requests SSE-KMS with the configured key, supplies a SHA-256 checksum, records only stage/hash metadata, and requires a returned version ID. Download rechecks byte length, SSE-KMS, and the application SHA-256 before returning bytes.
- Clean promotion is an explicit version-pinned server-side copy from an opaque `quarantine/` key to an opaque `released/` key, again with SSE-KMS and checksum calculation requested. Parsers never receive the quarantine key.
- Deletion enumerates exact-key versions and delete markers across every page, deletes each version explicitly, and fails on partial provider errors. This follows the documented S3 versioning model and avoids treating a delete marker as erasure: [S3 versioning workflow](https://docs.aws.amazon.com/AmazonS3/latest/userguide/versioning-workflows.html).
- The adapter follows the provider checksum and per-request encryption contracts: [S3 object integrity](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html) and [PutObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html).

### Validation, quarantine, and scan

- The internal staging service first authorizes owner/purpose/category processing, resolves retention, and requires exactly one active scan-required parser-release policy.
- Allowed bytes are bounded PDF, DOCX, or UTF-8 text. Validation does not trust filenames or request headers. DOCX inspection bounds entry count and expanded size and rejects path traversal, duplicates, encrypted members, extreme compression, executable/script content, missing required parts, bad CRC, and invalid ZIP structure.
- Objects remain parser-inaccessible in quarantine until clamd returns an exact clean verdict over its bounded `INSTREAM` protocol. Engine/signature version and signature timestamp are recorded; signatures outside the configured freshness window fail closed. The protocol implementation follows the ClamAV command contract: [clamd protocol](https://docs.clamav.net/manual/Usage/ClamdProtocol.html).
- Production permits only an absolute local Unix socket to an isolated clamd sidecar. Development may use TCP. Timeouts, maximum stream bytes, bounded responses, malformed output, transport failure, and stale signatures all prevent release.
- Malware names are not persisted. Only a SHA-256 digest of a bounded signature string is retained as evidence.

### Parser release and lifecycle state

- `parser_release_policies` bind privacy policy, category, purpose, media type, maximum bytes, scan requirement, exact parser adapter/version, isolation profile, approval time, and lifecycle status.
- `file_assets` is the authoritative saga state: `upload_pending`, `quarantined`, `scan_failed`, `clean`, `released`, or `deletion_pending`. PostgreSQL constraints require version identity for uploaded/released states.
- A parser read rechecks ownership, released key/version/hash, policy status/approval time, and exact adapter/version/isolation profile. Phase 1A must implement the named parser in a no-network, read-only, resource-bounded runtime; this phase supplies the release gate, not the parser.
- `file_scan_attempts` records bounded evidence. `file_deletion_tasks` supplies lease/retry/escalation/manual-requeue semantics for both quarantine cleanup and full asset erasure.
- Failed storage upload, infected content, retention expiry, privacy deletion, and restore replay schedule durable deletion. Privacy completion waits for all file tasks. A restore with pending external object erasure remains unavailable until workers finish and the signed manifest is replayed again.

## Consequences

- Public deployment requires an operator-provisioned bucket/KMS policy, workload identity, current clamd signatures, mounted secret files, an approved parser-release record, and workers consuming the durable outbox/deletion tasks.
- Bucket lifecycle expiration is useful defense in depth but is not proof of deletion; authoritative completion comes only after exact-key version enumeration reports success.
- Keeping old key material has risk. Rotation retains only key IDs still referenced by encrypted locators, deletion manifests, unexpired backup markers, or backups inside the approved recovery horizon.
- This phase deliberately has no candidate upload API, filename storage, document parsing, extracted text, model call, or browser UI. Phase 1A may expose the internal contract only after Phase 0D deployment/observability gates are complete.

## Rejected alternatives

- Application-level whole-file encryption in addition to SSE-KMS was not added without a key-custody requirement; it would add streaming/range/rotation complexity while the approved KMS boundary already provides envelope encryption. It can be reconsidered for a measured regulatory or tenant-key need.
- A database `bytea` document column was rejected because it couples large sensitive payloads to relational backups and transaction load.
- Filename/header-only validation, scanning after parser execution, unversioned object keys, blind `DELETE`, and an LLM-based malware/content classifier were rejected as unsafe boundaries.
- Calling a remote secret manager for every request was rejected because it couples availability and secret exposure to the request path. Orchestrator-mounted startup delivery is the current production contract.

## Explicitly deferred

- Phase 0D owns deployment wiring, metrics/alerts/SLOs, production provider credentials, and exercised on-call procedures.
- Phase 1A owns authenticated upload/paste routes, immutable candidate document versions, parser workers/sandbox enforcement, recoverable user errors, and corrected extracted text.
- Password-protected Office document support is not implemented; encrypted archives fail closed.

