# Release and rollback runbook

## Safety boundary

This runbook defines the provider-neutral sequence. The selected deployment platform must implement it with an auditable one-off migration job, separate application and migration identities, an immutable image digest, and environment-scoped secret mounts. Never place a database URL or secret value in command output, CI variables printed to logs, image layers, tickets, or release annotations.

Do not route a release when any of these checks fail. Do not use `alembic downgrade` on a data-bearing environment. A failed schema change is handled by a reviewed forward fix; restoration is a separately approved recovery operation.

## Preconditions

- CI is green for the exact source SHA, including the real-PostgreSQL suite and both image vulnerability scans.
- The retained CycloneDX SBOM belongs to that SHA and has passed review policy.
- The image is addressed by registry digest and its OCI revision label equals the source SHA.
- The release notes classify the schema change as additive, expand, migrate, contract, or no-schema-change and state compatibility with the currently serving release.
- Backups/PITR, the deletion-manifest ledger, and the recovery contact are healthy for any migration that changes stored data.
- Staging and production have separate mounted database secret files. The migration role has reviewed DDL access; the API role does not.

## Build and artifact verification

CI supplies UTC creation time, a unique release version, and the full source SHA:

```powershell
docker build `
  --build-arg BUILD_VERSION=0.1.0-release.42 `
  --build-arg BUILD_REVISION=<40-character-source-sha> `
  --build-arg BUILD_CREATED=<utc-rfc3339-time> `
  --tag ai-interviewer-platform:release-candidate `
  .
./scripts/verify-release-image.ps1 `
  -Image ai-interviewer-platform:release-candidate `
  -ExpectedVersion 0.1.0-release.42 `
  -ExpectedRevision <40-character-source-sha>
```

Push once, record the resulting digest, and promote that digest without rebuilding it.

## Environment rollout

Perform every step in staging first, then repeat with an independent approval in production:

1. Confirm no other release workflow is active.
2. Run `ai-interviewer-migrate check-artifact` from the selected image digest without database credentials. Record its schema revision.
3. Start a one-off `ai-interviewer-migrate upgrade` job from the same digest. Mount the database URL as an absolute read-only file and set `AI_INTERVIEWER_ENVIRONMENT`, `AI_INTERVIEWER_RELEASE_ID`, `AI_INTERVIEWER_RELEASE_REVISION`, `AI_INTERVIEWER_DATABASE_URL_FILE`, TLS mode, timeouts, and no unrelated application secrets.
4. Require exit code zero and the `database_migration_completed` JSON event with the exact release ID, SHA, and schema revision. A lock timeout or any other failure stops the rollout.
5. Roll out API instances from that digest with the complete hosted configuration. Keep them out of service until `/api/v1/health/ready` returns `200`.
6. Confirm startup logs carry the expected release ID/SHA and no secret or candidate payload.
7. Exercise liveness, readiness, authentication denial, and one approved synthetic transaction. Confirm the previous release is still available until the new instances are healthy.
8. Record image digest, source SHA, schema revision, migration job identity/times/result, approver, readiness result, and links to CI/SBOM evidence.

## Failure decisions

| Observation | Action |
|---|---|
| Artifact check fails | Quarantine the image; rebuild only from a reviewed source change. |
| Advisory lock times out | Stop. Find the owning release session; never change the lock key or bypass serialization. |
| Migration fails | Keep prior traffic serving, preserve error-type/job evidence, diagnose privately, and ship a forward fix. |
| Migration succeeds but schema verification fails | Block all API rollout; investigate the database and migration graph as a release-integrity incident. |
| New API readiness fails before schema change | Stop new instances and retain the healthy prior release. |
| New API readiness fails after schema change | Do not blindly deploy the old image. Verify schema compatibility; normally issue a forward application fix. |
| Data integrity is suspected | Freeze writes and follow the database recovery and deletion-ledger procedure with incident approval. |

## Rollback compatibility rule

An application rollback is safe only when the target image's compiled expected schema equals the database `alembic_version` and its release notes approve the current data contract. Because readiness checks exact equality, an incompatible rollback remains out of service. Schema evolution must use expand/migrate/contract releases so the old application is retired before contract cleanup.

Use [PostgreSQL Backup and Restore](database-backup-restore.md) only for an approved recovery into an isolated target. Restore success also requires signed deletion-manifest replay and all external file deletions before readiness.
