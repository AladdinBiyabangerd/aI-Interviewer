# ADR 0011: Immutable candidate document lineage over released file assets

- Status: Accepted
- Date: 2026-08-27
- Decision owners: application, data, privacy, and security engineering
- Scope: Phase 1A-B only

## Context

The platform needs a stable identity for each CV and job description used by one
interview preparation. A user may later replace either input, but previous versions must
remain distinguishable so extraction, corrections, prompts, evaluations, exports, and
deletion evidence can identify the exact source they used. Phase 0C-C already owns the
original object bytes, quarantine, malware scan, clean promotion, parser-release policy,
and durable object deletion. Duplicating that state in the product domain would create
two authorities for the same sensitive object.

Ownership and erasure are hard invariants. An application-only owner check would not
protect direct database writes, and deleting a referenced file asset without first
removing the product reference would either violate referential integrity or leave a
dangling lineage. At the same time, immutability cannot mean retaining candidate data
against an account-deletion or retention obligation.

## Decision

1. A preparation has at most one logical `cv` and one logical `job_description`
   aggregate. The aggregate has a UUIDv7 identity, owner, latest ordinal, timestamps,
   and optimistic-concurrency version.
2. Every replacement creates a new `candidate_document_versions` row. It never rewrites
   an earlier version. The row references exactly one already released `file_assets` row
   and snapshots its media type, byte length, content digest, parser-release policy, and
   the active privacy, jurisdiction, legal-basis, retention rule/deadline/action decision.
3. A file asset can back only one candidate document version. A document ordinal is
   unique within its aggregate. The service locks account, preparation, asset, and then
   document state before appending, making retries for the same asset idempotent.
4. Composite foreign keys enforce matching owners from preparation to document and from
   document/version to file asset. These checks remain effective if a caller bypasses
   the service layer.
5. PostgreSQL rejects every `UPDATE` to a candidate document version through a database
   trigger. `DELETE` remains permitted only for the privacy/retention lifecycle. The
   mutable logical aggregate may advance its latest ordinal and optimistic version.
6. The file-deletion worker releases a candidate-document reference in the same database
   transaction immediately before deleting the file-asset row. If the removed version
   was the last one, its logical document is removed; otherwise the latest ordinal is
   recomputed from remaining immutable rows.
7. Privacy export includes owned document lineage metadata. Account erasure deletes
   document lineage before preparation context so explicit deletion counts and audit
   evidence are accurate. Object deletion remains a durable prerequisite for final
   account deletion.
8. Phase 1A-B exposes only authenticated, owner-scoped metadata reads. The public upload
   and paste mutation contract belongs to Phase 1A-C. Parser output, extracted text, and
   AI processing belong to later gates.

## Consequences

- Every downstream artifact can reference an exact, non-rewritten source version.
- PostgreSQL stores no original CV/JD bytes and no extracted text in this phase.
- Privacy and file retention can still erase immutable history; immutability prevents
  mutation, not legally required deletion.
- File deletion now depends on a narrow product-reference lifecycle adapter. New modules
  that reference a file asset must join this release-before-delete contract.
- Removing an older version can leave non-contiguous historical ordinals. Ordinals are
  identities, not a count; new versions continue from the aggregate's current maximum.
- Public upload/paste remains unavailable until its independent validation,
  idempotency, error-recovery, and authorization contract is completed in Phase 1A-C.

## Rejected alternatives

- Mutating one CV/JD row in place: loses source provenance and makes downstream results
  irreproducible.
- Copying object keys or bytes into the document aggregate: duplicates sensitive state
  and bypasses the file-security authority.
- Relying only on service owner checks: permits invalid cross-owner relationships through
  migrations, maintenance scripts, or future code paths.
- `ON DELETE CASCADE` from file asset to document version: hides product-data erasure
  inside an infrastructure deletion and prevents explicit lifecycle coordination.
- Blocking all deletes because versions are immutable: conflicts with privacy and
  retention requirements.
