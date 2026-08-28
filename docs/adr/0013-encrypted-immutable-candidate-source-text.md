# ADR 0013: Encrypted immutable candidate source-text lineage

- Status: Accepted
- Date: 2026-08-27
- Decision owners: application, data, privacy, and security engineering
- Scope: Phase 1A-D1 only

## Context

Phase 1A-C can create an immutable candidate document version backed by one clean,
released file asset, but intentionally does not run a parser or retain extracted text.
Phase 1A-D needs user-inspectable text before any AI processing. Parser output is as
sensitive as the original CV or job description and must remain traceable to the exact
source, parser release, privacy decision, and later user corrections.

Plaintext source text in PostgreSQL would broaden database and backup exposure. A mutable
single text column would also make parser retries, user corrections, prompts, exports,
and investigations irreproducible. At the same time, immutable lineage cannot prevent
privacy or retention deletion.

## Decision

1. Each retained `candidate_document_versions` row can own at most one
   `candidate_source_texts` aggregate. Composite foreign keys enforce the same owner,
   and deletion of the exact document version cascades through all encrypted text
   revisions.
2. `candidate_source_text_versions` is append-only. Revision 1 is exactly one
   `parser_extraction`; later revisions are reserved for `user_correction` and must
   point to the immediately preceding revision. Database checks and a chain-validation
   trigger enforce these shapes. A separate trigger rejects every version update.
3. Source content is stored only as AES-256-GCM ciphertext, a 12-byte nonce, and an
   explicit key ID from the application keyring. Authenticated additional data binds
   ciphertext to owner, source/document/version identities, revision/origin, complete
   parser provenance, measured bounds, digest, and encryption-key identity. Moving or
   editing any bound metadata makes decryption fail closed.
4. A keyed HMAC digest with its own rotation-aware key ID provides integrity and safe
   same-document retry comparison without publishing a reusable plaintext SHA-256
   oracle. Plaintext, ciphertext, nonce, and digest never enter audit or outbox payloads.
5. Persisted parser provenance snapshots the exact parser-release policy ID, adapter,
   version, and isolation profile. Storage succeeds only while the owner and draft
   preparation are active, the target is the latest retained document version, the
   exact asset remains released, the policy remains active, and current purpose/privacy
   authorization matches the immutable document snapshot.
6. The source-text contract accepts 1-500,000 Unicode characters and at most 2,000,000
   UTF-8 bytes. It requires LF newlines, allows tab/newline controls only, and rejects
   NUL, carriage return, Unicode format controls, and surrogate code points. The
   original released bytes remain authoritative; this contract protects the later UI
   and model boundary without rewriting extracted content silently.
7. Parser-result storage is owner-serialized and idempotent for the exact content and
   exact parser provenance. A different result for the same document version conflicts;
   it never overwrites or silently appends a second parser extraction.
8. Phase 1A-D1 exposes no HTTP endpoint and executes no parser. The internal service is
   inert until the separately verified worker gate is connected. Inspection/correction
   and complete privacy/export/recovery integration remain later 1A-D gates.

## Consequences

- PostgreSQL and logical backups contain encrypted candidate text, never plaintext.
- Exact document, parser, and later correction lineage can be reproduced and audited.
- Removing a document version for account erasure or file retention also removes all
  encrypted source text without weakening immutability.
- Active and historical field/HMAC keys must remain available for the approved data and
  backup horizons. Missing or unauthentic key material makes reads fail closed.
- There is deliberately no parser library, sandbox execution, correction endpoint, AI
  call, or model-ready profile in this subphase.

## Rejected alternatives

- Plaintext or merely database-provider-encrypted text: exposes content to database
  operators and logical backups beyond the application field-encryption boundary.
- One mutable text field on the document version: loses correction and parser lineage.
- Global unkeyed content hashes: enable equality probing for common job descriptions or
  CV fragments.
- Treating a policy foreign key as complete provenance: policy rows can change lifecycle
  state, while downstream artifacts need the exact executed adapter/version/profile.
- Running PDF/DOCX libraries inside the API process: bypasses the explicit isolated
  worker and bounded-resource gate reserved for Phase 1A-D2.
