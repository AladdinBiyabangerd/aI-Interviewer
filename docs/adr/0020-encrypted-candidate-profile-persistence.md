# ADR 0020: Encrypted immutable candidate-profile persistence

- Status: Accepted
- Scope: Phase 1B-B2.1 only
- Date: 2026-09-01
- Depends on: ADR 0013 source-text lineage, ADR 0018 model gateway, and ADR 0019
  evidence-linked profile contracts

## Context

Phase 1B-B1 could validate a strict CV or job-description profile against one exact
corrected source string, but the result existed only in memory. Enabling a provider or
background worker before durable lineage, confidentiality, integrity, privacy, and
erasure boundaries existed would allow a derived profile to become detached from the
source, release coordinates, or legal decision that produced it.

## Decision

1. One `candidate_profiles` aggregate represents the profile for exactly one immutable
   `candidate_source_text_versions` row. It also stores the matching owner, source
   aggregate, candidate-document version and type, and immutable privacy policy,
   jurisdiction, legal-basis, retention-rule, delete-only action, and deadline
   snapshots.
2. `candidate_profile_versions` is append-only. Version one has origin
   `model_generation` and records exact provider/model/version, prompt/version, schema
   ID/version, canonical instruction/schema SHA-256 values, attempt count, and bounded
   content-free claim/evidence counts. The shape reserves a strictly chained
   `user_correction` origin for a later reviewed command, but this phase exposes no such
   command.
3. The strict profile is serialized as deterministic canonical JSON and stored only as
   AES-256-GCM ciphertext. A context-bound HMAC detects substitution without creating a
   global plaintext equality oracle. AAD binds the complete owner/profile/version,
   source/document, schema/release, evidence-count, privacy/retention, digest, and key
   context.
4. The persistence service does not trust a previously verified in-memory object by
   itself. In the write transaction it locks the relevant lineage, reauthorizes the
   active privacy rule, decrypts the exact latest source revision, checks the exact
   document/release identity, and repeats application-owned evidence-span validation.
   Invalid or stale output cannot enter the database.
5. A retry with the same exact source revision, canonical profile, release identities,
   digests, attempts, and counts is idempotent. A changed output or release conflicts;
   existing encrypted history is never overwritten.
6. Composite foreign keys, constraints, and four database triggers protect owner and
   snapshot identity, reject profile-version updates, and validate aggregate/version
   chains independently of application code.
7. Owner privacy export decrypts and validates profile revisions through the narrow
   service and uses bundle schema `phase-1b-b2.1`. Account, document-version, and
   source-text deletion cascades erase profiles. No anonymize fallback is permitted.
8. Runtime construction fails closed unless privacy/file security and the application
   keyring are available. Audit, outbox, logs, and representations contain no profile
   JSON, source quote, ciphertext, nonce, digest, or provider error detail.

## Consequences

The repository now has a durable confidential and reproducible boundary for a verified
CV/JD profile without allowing candidate content to cross an external processor trust
boundary. Reads and exports require historical encryption and digest keys for the
approved data/backup horizon, and key loss or metadata drift intentionally makes the
record unavailable instead of silently accepting it.

This decision does not add a profiling-job table, lease/dead-letter handling, provider
adapter, outbound call, public profile route, or correction workflow. Phase 1B-B2.2
must add fenced durable jobs before Phase 1B-C can enable reviewed model execution.
