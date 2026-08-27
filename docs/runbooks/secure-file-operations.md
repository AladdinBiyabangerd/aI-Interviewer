# Secure File and Secret Operations Runbook

## Release gate

Do not enable `AI_INTERVIEWER_FILE_SECURITY_ENABLED` in a production environment until all of the following are evidenced:

1. The bucket is dedicated to the correct environment, versioning is enabled, all public-access blocks are enabled, and default encryption uses the approved customer-managed KMS key.
2. The application workload identity has only the required bucket/key/version/checksum operations and only KMS encrypt/decrypt/data-key permissions for that bucket context. No static AWS access key is stored in the application configuration.
3. Bucket access logging/provider audit events and KMS audit events flow to the approved security account with the approved retention.
4. clamd runs in an isolated sidecar, shares only its Unix socket, has no access to application secrets, cannot serve public traffic, and refreshes signatures on an observed schedule.
5. Database and privacy keyring secrets are mounted as absolute read-only files with no access for other users or group write. The process can read them as its non-root UID.
6. The required privacy processing/retention records and exactly one scan-required parser-release policy are legally/security approved for each category, purpose, and media type.
7. File deletion and outbox workers are running, alarmed, and authorized to delete every version and delete marker. A completed database row without provider deletion success is not accepted as erasure.

## Readiness and safe smoke test

The readiness endpoint checks database connectivity, bucket controls, clamd `PING`, version parsing, and signature freshness. A non-ready result blocks traffic and should be diagnosed from provider/sidecar metrics without logging secrets or file bytes.

In an isolated non-production environment:

1. Publish a synthetic privacy policy, processing rule, retention rules, and parser-release policy.
2. Stage a small synthetic PDF, verify it is stored only under an opaque quarantine key with a version ID, SSE-KMS, checksum, and no public ACL.
3. Scan and release it; confirm the released object is a distinct version-pinned key and parser access succeeds only with the exact approved adapter/version/isolation profile.
4. Run quarantine cleanup and verify all quarantine versions/delete markers are gone.
5. Request account deletion, run file deletion, resume privacy deletion, and verify all released versions/delete markers and owner links are gone.
6. Repeat with the EICAR test fixture only in the isolated approved security environment. It must never obtain a released key.

Never use a real CV/JD for smoke tests or place malware names/file content in logs or tickets.

## Scanner incident

Symptoms include readiness failure, `scan_failed` assets, signature age above the configured maximum, malformed version output, transport timeout, or clamd resource exhaustion.

1. Keep uploads/parsing blocked; do not bypass scanning or manually mark files clean.
2. Check sidecar health, socket ownership/mode, signature-update status/time, engine/signature versions, memory/disk limits, and the configured maximum stream size.
3. Restore signature updates or replace the sidecar with the approved image. Confirm freshness through readiness.
4. Retry `scan_failed` assets through `scan_and_release`; each retry records a new attempt. Never copy quarantine objects directly.
5. If compromise is suspected, suspend affected parser-release policies, preserve metadata-only evidence, rotate/rebuild the scanner, and reassess objects scanned during the affected signature window.

## Object-store or KMS incident

1. Keep readiness closed when bucket controls cannot be verified. Do not fall back to unencrypted/local disk storage.
2. Confirm environment/bucket identity, workload role, KMS key state/policy, region, endpoint TLS, versioning, public blocks, default SSE-KMS, provider health, and request throttling.
3. Failed upload acknowledgements create deletion work when an object key may exist. Run that work after provider recovery.
4. For partial deletion, fix authorization/provider faults and allow bounded retry. Repeated failure escalates the task. Do not clear keys, mark the task complete, or finalize privacy deletion manually.
5. After remediation, an authorized operator may requeue an escalated task. Verify every exact-key version/delete marker is absent before closing the incident.

## Key rotation

### Application keyring

1. Generate a new independent 32-byte value for only the purpose being rotated and a new unique key ID. Never reuse material across purposes or environments.
2. Add the new key while retaining every referenced old key; deploy/restart and verify readiness plus decrypt/manifest tests.
3. Make the new key ID active in a second deployment. New fingerprints, locators, or manifests now use it; old records remain readable/verifiable.
4. Re-encrypt live processor locators through a separately reviewed migration if policy requires rapid retirement. File bytes use KMS and are unaffected by application field-key rotation.
5. Remove an old field key only after no ciphertext references its ID. Remove an old subject/manifest key only after no live record, unexpired deletion marker/manifest, backup, replica, or recovery procedure can reference it.
6. Record key IDs, affected environments, operator/change approval, verification evidence, and earliest permitted retirement. Never record material.

### KMS key

Use provider-native KMS rotation when it preserves decryption. If changing the configured KMS key ID, first validate a controlled copy/re-encryption plan for every live version and verify deletion rights under both keys. Do not disable the old KMS key until the maximum backup/object-version recovery horizon and all deletion work have passed.

### Database secret

Create the new database credential, update the mounted file atomically through the orchestrator, perform a rolling restart, verify new sessions, then revoke the old credential. The service reads secret files only at startup.

## Operational queries and privacy

Operators may inspect IDs, states, attempt counts, bounded error codes, timestamps, scanner/KMS key IDs, media type, lengths, and digests. Access to object bytes or decrypted processor locators requires a separately authorized support/security purpose and must not flow through logs, dashboards, traces, or tickets.

Alerts required before Phase 0D completion include readiness failure, stale signatures, quarantine/scan-failed age, deletion backlog age, escalated deletion tasks, KMS denial/throttling, unexpected bucket-policy changes, public-access-control changes, and object-count/version growth inconsistent with retention.

