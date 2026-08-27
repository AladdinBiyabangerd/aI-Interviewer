# PostgreSQL Backup and Restore Runbook

## Safety rules

1. Never test a restore over an active database.
2. Use a dedicated recovery database or isolated cluster.
3. Encrypt backup artifacts in transit and at rest; restrict access to operators with a documented need.
4. Do not put DSNs, passwords, CV/JD text, interview answers, or dump contents in logs or tickets.
5. Record the source environment, database version, Alembic revision, backup time, checksum, encryption key reference, and retention expiry.
6. A production downgrade that drops or rewrites data requires an approved backup and restoration plan. Normal releases roll forward.
7. A restored database must not receive application traffic until the external deletion manifest has been replayed and verified.

## Pre-production baseline

- Daily encrypted logical backup, retained for 30 days
- Weekly automated restore rehearsal into an isolated database
- Initial recovery point objective: 24 hours
- Initial recovery time objective: 4 hours
- Quarterly access and retention review

These baselines must be replaced by measured business requirements before a public SLA.

## Create a logical backup

Use the same PostgreSQL major version as the source. This local example writes the archive inside the project container and then copies it out:

```powershell
$backupName = "ai_interviewer_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump"
docker compose exec -T postgres pg_dump --username ai_interviewer --dbname ai_interviewer --format custom --no-owner --no-acl --file "/tmp/$backupName"
docker compose cp "postgres:/tmp/$backupName" "./$backupName"
Get-FileHash -Algorithm SHA256 -LiteralPath "./$backupName"
```

Move the archive to approved encrypted storage, verify its checksum, and remove temporary copies according to policy.

## Restore rehearsal

For the project database, the checked rehearsal automates isolated restore, schema and row-count validation, audit immutability, application readiness, and cleanup:

```powershell
./scripts/rehearse-database-restore.ps1
```

It fails without modifying anything if its dedicated recovery database name already exists. For a managed environment, use an approved isolated target and adapt the following manual procedure.

Create a new empty database; never reuse the source database name:

```powershell
$recoveryDatabase = "ai_interviewer_recovery_$(Get-Date -Format 'yyyyMMddHHmmss')"
docker compose exec -T postgres createdb --username ai_interviewer $recoveryDatabase
docker compose cp "./ai_interviewer_backup.dump" "postgres:/tmp/ai_interviewer_backup.dump"
docker compose exec -T postgres pg_restore --username ai_interviewer --dbname $recoveryDatabase --no-owner --no-acl --exit-on-error "/tmp/ai_interviewer_backup.dump"
```

Validate before declaring the rehearsal successful:

- `alembic_version` equals the expected release revision;
- required tables, indexes, constraints, and audit immutability triggers exist;
- expected row counts and sampled checksums match the source record;
- the application readiness check succeeds against the restored database;
- audit events remain immutable;
- all deletion markers created after the restored backup are loaded from the separately protected control-plane ledger and replayed;
- replayed markers erase matching pre-cutoff accounts and do not erase a verified post-cutoff re-registration;
- elapsed restore time satisfies the RTO.

## Backup-aware deletion gate

`backup_deletion_markers` contain an old account UUID, cutoff, backup-expiry time, policy/request references, and a keyed subject fingerprint. They do not contain the raw OIDC issuer or subject. The transactional `privacy.backup_deletion.manifested` outbox event must be consumed into a separately protected control-plane ledger that is not rolled back with an application-database restore.

Before making a restored database ready:

1. Export every unexpired marker newer than the restored backup from the control-plane ledger.
2. Load the canonical Phase 0C-C signed manifest, verify its environment/source authorization, schema version, HMAC signature, and manifest/subject key IDs before replay. Never import an unsigned compatibility manifest in production.
3. Invoke signed-manifest replay against the isolated recovery database.
4. Run the file-deletion worker until every replay-created file task is completed. Escalated tasks block recovery readiness and require an operator-approved requeue after the object-store/KMS fault is fixed.
5. Replay the same signed manifest again so accounts held in `deletion_pending` can be finalized after external object acknowledgement. Repeat only while progress occurs; any remaining pending state fails the restore gate.
6. Confirm every matching account created at or before its cutoff was erased, every exact object-key version/delete-marker was removed, and all outbox/task owner links were cleared.
7. Confirm a deliberately created post-cutoff identity is not erased.
8. Record signature verification, marker/file-task counts, object-deletion evidence, and elapsed time, then run database, object-store, and scanner readiness checks.

Existing backup archives are not rewritten. They remain sensitive until encrypted backup retention expires. The control-plane ledger must retain each referenced subject/manifest verification key through the maximum backup and manifest replay horizon. Key removal before that horizon is a recovery-blocking event.

After evidence is recorded, disconnect all clients and remove only the specifically named recovery database:

```powershell
docker compose exec -T postgres dropdb --force --username ai_interviewer $recoveryDatabase
```

## Point-in-time recovery

Logical dumps do not provide point-in-time recovery. Before production launch, the managed PostgreSQL service must have continuous WAL/PITR configured, retention aligned to the approved RPO, and a separate PITR rehearsal recorded. Provider snapshots alone are not accepted without a successful restore test.
