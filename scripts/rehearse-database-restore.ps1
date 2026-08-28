param(
    [ValidatePattern('^ai_interviewer(?:_[a-z0-9_]+)?$')]
    [string]$SourceDatabase = "ai_interviewer",
    [ValidatePattern('^ai_interviewer_restore_[a-z0-9_]+$')]
    [string]$RecoveryDatabase = "ai_interviewer_restore_rehearsal"
)

$ErrorActionPreference = "Stop"

if ($SourceDatabase -eq $RecoveryDatabase) {
    throw "The recovery database must be different from the source database"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

$containerBackup = "/tmp/$RecoveryDatabase.dump"
$createdBackup = $false
$createdRecoveryDatabase = $false
$startedPostgres = $false
$originalDatabaseUrl = $env:AI_INTERVIEWER_DATABASE_URL
$originalEnvironment = $env:AI_INTERVIEWER_ENVIRONMENT
$startedAt = Get-Date

try {
    $runningServices = docker compose ps --status running --services
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the local PostgreSQL service"
    }
    if ($runningServices -notcontains "postgres") {
        Invoke-Checked -Description "PostgreSQL startup" -Command {
            docker compose up --detach --wait --wait-timeout 60 postgres
        }
        $startedPostgres = $true
    }

    $existingDatabase = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname postgres `
        --tuples-only `
        --no-align `
        --command "SELECT datname FROM pg_database WHERE datname = '$RecoveryDatabase'"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect the recovery database name"
    }
    if ($existingDatabase) {
        throw "Recovery database '$RecoveryDatabase' already exists; it was not modified"
    }

    $sourceRevision = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $SourceDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT version_num FROM alembic_version"
    if ($LASTEXITCODE -ne 0 -or -not $sourceRevision.Trim()) {
        throw "The source database does not contain a valid Alembic revision"
    }
    $expectedRevision = uv run python -c "from ai_interviewer.persistence.schema import EXPECTED_SCHEMA_REVISION; print(EXPECTED_SCHEMA_REVISION)"
    if ($LASTEXITCODE -ne 0 -or -not $expectedRevision.Trim()) {
        throw "Could not read the release-owned schema revision"
    }
    if ($sourceRevision.Trim() -ne $expectedRevision.Trim()) {
        throw "The source database schema does not match this release; run the release-owned forward migration before the restore rehearsal"
    }
    $sourceCounts = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $SourceDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT (SELECT count(*) FROM outbox_events) || ':' || (SELECT count(*) FROM audit_events) || ':' || (SELECT count(*) FROM accounts) || ':' || (SELECT count(*) FROM privacy_profiles) || ':' || (SELECT count(*) FROM consent_records) || ':' || (SELECT count(*) FROM privacy_requests) || ':' || (SELECT count(*) FROM processor_usages) || ':' || (SELECT count(*) FROM processor_deletion_tasks) || ':' || (SELECT count(*) FROM backup_deletion_markers) || ':' || (SELECT count(*) FROM parser_release_policies) || ':' || (SELECT count(*) FROM file_assets) || ':' || (SELECT count(*) FROM file_scan_attempts) || ':' || (SELECT count(*) FROM file_deletion_tasks) || ':' || (SELECT count(*) FROM candidate_preparations) || ':' || (SELECT count(*) FROM candidate_documents) || ':' || (SELECT count(*) FROM candidate_document_versions) || ':' || (SELECT count(*) FROM candidate_document_intakes) || ':' || (SELECT count(*) FROM candidate_source_texts) || ':' || (SELECT count(*) FROM candidate_source_text_versions) || ':' || (SELECT count(*) FROM candidate_extraction_jobs)"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read source row counts"
    }

    Invoke-Checked -Description "Logical backup" -Command {
        docker compose exec -T postgres pg_dump `
            --username ai_interviewer `
            --dbname $SourceDatabase `
            --format custom `
            --no-owner `
            --no-acl `
            --file $containerBackup
    }
    $createdBackup = $true
    $backupHash = docker compose exec -T postgres sha256sum $containerBackup
    if ($LASTEXITCODE -ne 0) {
        throw "Could not calculate the backup checksum"
    }

    Invoke-Checked -Description "Recovery database creation" -Command {
        docker compose exec -T postgres createdb `
            --username ai_interviewer `
            $RecoveryDatabase
    }
    $createdRecoveryDatabase = $true
    Invoke-Checked -Description "Logical restore" -Command {
        docker compose exec -T postgres pg_restore `
            --username ai_interviewer `
            --dbname $RecoveryDatabase `
            --no-owner `
            --no-acl `
            --exit-on-error `
            $containerBackup
    }

    $restoredRevision = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT version_num FROM alembic_version"
    $restoredCounts = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT (SELECT count(*) FROM outbox_events) || ':' || (SELECT count(*) FROM audit_events) || ':' || (SELECT count(*) FROM accounts) || ':' || (SELECT count(*) FROM privacy_profiles) || ':' || (SELECT count(*) FROM consent_records) || ':' || (SELECT count(*) FROM privacy_requests) || ':' || (SELECT count(*) FROM processor_usages) || ':' || (SELECT count(*) FROM processor_deletion_tasks) || ':' || (SELECT count(*) FROM backup_deletion_markers) || ':' || (SELECT count(*) FROM parser_release_policies) || ':' || (SELECT count(*) FROM file_assets) || ':' || (SELECT count(*) FROM file_scan_attempts) || ':' || (SELECT count(*) FROM file_deletion_tasks) || ':' || (SELECT count(*) FROM candidate_preparations) || ':' || (SELECT count(*) FROM candidate_documents) || ':' || (SELECT count(*) FROM candidate_document_versions) || ':' || (SELECT count(*) FROM candidate_document_intakes) || ':' || (SELECT count(*) FROM candidate_source_texts) || ':' || (SELECT count(*) FROM candidate_source_text_versions)"
    $requiredTables = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('accounts', 'alembic_version', 'audit_events', 'backup_deletion_markers', 'candidate_document_intakes', 'candidate_document_versions', 'candidate_documents', 'candidate_extraction_jobs', 'candidate_preparations', 'candidate_source_text_versions', 'candidate_source_texts', 'consent_notices', 'consent_records', 'file_assets', 'file_deletion_tasks', 'file_scan_attempts', 'outbox_events', 'parser_release_policies', 'privacy_policy_versions', 'privacy_profiles', 'privacy_requests', 'processing_rules', 'processor_activities', 'processor_deletion_tasks', 'processor_usages', 'processors', 'retention_rules')"
    $requiredIndexes = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND indexname IN ('ix_audit_events_owner_occurred', 'ix_audit_events_resource', 'ix_audit_events_retention', 'ix_backup_deletion_markers_expiry', 'ix_candidate_document_intakes_owner_preparation', 'ix_candidate_document_intakes_retention', 'ix_candidate_document_intakes_status_lease', 'ix_candidate_document_versions_document_created', 'ix_candidate_documents_owner_preparation', 'ix_candidate_extraction_jobs_owner_created', 'ix_candidate_extraction_jobs_status_available', 'ix_candidate_preparations_owner_id', 'ix_candidate_preparations_retention', 'ix_candidate_source_text_versions_source_created', 'ix_candidate_source_texts_owner_document_version', 'ix_file_assets_owner_created', 'ix_file_assets_retention', 'ix_file_assets_status_updated', 'ix_file_deletion_tasks_available', 'ix_file_deletion_tasks_request', 'ix_file_deletion_tasks_retention', 'ix_file_scan_attempts_asset_scanned', 'ix_outbox_events_aggregate', 'ix_outbox_events_pending_available', 'ix_parser_release_policies_resolution', 'ix_privacy_requests_status_due', 'ix_processor_deletion_tasks_available', 'uq_accounts_issuer_subject', 'uq_candidate_extraction_jobs_document_version', 'uq_consent_records_active_notice')"
    $requiredConstraints = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT count(*) FROM pg_constraint WHERE conname IN ('ck_accounts_issuer_nonempty', 'ck_accounts_status_allowed', 'ck_accounts_subject_nonempty', 'ck_accounts_version_positive', 'ck_audit_events_actor_type_allowed', 'ck_audit_events_retention_pair', 'ck_backup_deletion_markers_subject_digest_length', 'ck_candidate_document_intakes_file_asset_reservation_consistent', 'ck_candidate_document_intakes_processing_lease_consistent', 'ck_candidate_document_intakes_retention_action_delete_only', 'ck_candidate_document_intakes_status_allowed', 'ck_candidate_document_versions_content_digest_format', 'ck_candidate_document_versions_retention_action_delete_only', 'ck_candidate_documents_document_type_allowed', 'ck_candidate_extraction_jobs_attempts_bounded', 'ck_candidate_extraction_jobs_content_digest_format', 'ck_candidate_extraction_jobs_content_length_positive', 'ck_candidate_extraction_jobs_failure_code_allowed', 'ck_candidate_extraction_jobs_isolation_profile_nonempty', 'ck_candidate_extraction_jobs_jurisdiction_nonempty', 'ck_candidate_extraction_jobs_legal_basis_nonempty', 'ck_candidate_extraction_jobs_media_type_nonempty', 'ck_candidate_extraction_jobs_parser_adapter_nonempty', 'ck_candidate_extraction_jobs_parser_version_nonempty', 'ck_candidate_extraction_jobs_retention_action_delete_only', 'ck_candidate_extraction_jobs_retention_after_creation', 'ck_candidate_extraction_jobs_state_consistent', 'ck_candidate_extraction_jobs_status_allowed', 'ck_candidate_preparations_retention_action_delete_only', 'ck_candidate_preparations_role_family_fallback_consistent', 'ck_candidate_preparations_target_country_code_format', 'ck_candidate_source_text_versions_character_count_bounded', 'ck_candidate_source_text_versions_content_ciphertext_bounded', 'ck_candidate_source_text_versions_content_digest_format', 'ck_candidate_source_text_versions_digest_key_nonempty', 'ck_candidate_source_text_versions_encryption_key_nonempty', 'ck_candidate_source_text_versions_content_nonce_length', 'ck_candidate_source_text_versions_isolation_profile_nonempty', 'ck_candidate_source_text_versions_line_count_bounded', 'ck_candidate_source_text_versions_origin_allowed', 'ck_candidate_source_text_versions_origin_provenance_consistent', 'ck_candidate_source_text_versions_parser_adapter_nonempty', 'ck_candidate_source_text_versions_parser_version_nonempty', 'ck_candidate_source_text_versions_utf8_byte_count_bounded', 'ck_candidate_source_text_versions_version_number_positive', 'ck_candidate_source_texts_latest_version_number_positive', 'ck_candidate_source_texts_version_positive', 'ck_file_assets_status_allowed', 'ck_file_deletion_tasks_active_task_requires_object_key', 'ck_file_scan_attempts_error_state_consistent', 'ck_outbox_events_attempts_nonnegative', 'ck_privacy_policy_versions_active_requires_legal_approval', 'ck_privacy_profiles_country_code_length', 'ck_privacy_requests_type_allowed', 'ck_processor_activities_cross_border_requires_mechanism', 'ck_processor_deletion_tasks_encrypted_locator_complete', 'ck_processor_usages_locator_representation_complete', 'fk_candidate_document_intakes_preparation_owner', 'fk_candidate_document_versions_document_owner', 'fk_candidate_document_versions_file_asset_owner', 'fk_candidate_documents_preparation_owner', 'fk_candidate_extraction_jobs_document_version_owner', 'fk_candidate_extraction_jobs_file_asset_owner', 'fk_candidate_extraction_jobs_owner_id_accounts', 'fk_candidate_extraction_jobs_parser_policy', 'fk_candidate_extraction_jobs_privacy_policy', 'fk_candidate_extraction_jobs_retention_rule', 'fk_candidate_extraction_jobs_source_text_owner', 'fk_candidate_source_text_versions_owner_id_accounts', 'fk_candidate_source_text_versions_parser_policy', 'fk_candidate_source_text_versions_previous_source', 'fk_candidate_source_text_versions_source_owner', 'fk_candidate_source_texts_document_version_owner', 'fk_candidate_source_texts_owner_id_accounts', 'pk_accounts', 'pk_audit_events', 'pk_candidate_document_intakes', 'pk_candidate_document_versions', 'pk_candidate_documents', 'pk_candidate_extraction_jobs', 'pk_candidate_preparations', 'pk_candidate_source_text_versions', 'pk_candidate_source_texts', 'pk_file_assets', 'pk_file_deletion_tasks', 'pk_file_scan_attempts', 'pk_outbox_events', 'pk_parser_release_policies', 'pk_privacy_policy_versions', 'pk_privacy_requests', 'pk_processor_deletion_tasks', 'uq_accounts_issuer_subject', 'uq_candidate_document_intakes_document_version', 'uq_candidate_document_intakes_file_asset', 'uq_candidate_document_intakes_owner_idempotency', 'uq_candidate_document_intakes_reserved_asset', 'uq_candidate_document_versions_document_number', 'uq_candidate_document_versions_file_asset', 'uq_candidate_document_versions_id_owner', 'uq_candidate_documents_preparation_type', 'uq_candidate_extraction_jobs_document_version', 'uq_candidate_extraction_jobs_id_owner', 'uq_candidate_preparations_id_owner', 'uq_candidate_preparations_owner_idempotency', 'uq_candidate_source_text_versions_id_source', 'uq_candidate_source_text_versions_source_number', 'uq_candidate_source_texts_document_version', 'uq_candidate_source_texts_id_owner', 'uq_file_assets_id_account', 'uq_privacy_request_idempotency')"
    $auditTriggers = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'audit_events'::regclass AND NOT tgisinternal"
    $documentVersionTriggers = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'candidate_document_versions'::regclass AND tgname = 'candidate_document_versions_reject_update' AND NOT tgisinternal"
    $sourceTextTriggers = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT count(*) FROM pg_trigger WHERE tgrelid IN ('candidate_source_texts'::regclass, 'candidate_source_text_versions'::regclass) AND tgname IN ('candidate_source_texts_protect_identity', 'candidate_source_text_versions_reject_update', 'candidate_source_text_versions_validate_chain') AND NOT tgisinternal"
    $extractionJobTriggers = docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --tuples-only `
        --no-align `
        --command "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'candidate_extraction_jobs'::regclass AND tgname IN ('candidate_extraction_jobs_validate_snapshot', 'candidate_extraction_jobs_protect_identity') AND NOT tgisinternal"
    if ($LASTEXITCODE -ne 0) {
        throw "Restored schema validation queries failed"
    }

    if ($restoredRevision.Trim() -ne $sourceRevision.Trim()) {
        throw "The restored Alembic revision does not match the source"
    }
    if ($restoredCounts.Trim() -ne $sourceCounts.Trim()) {
        throw "The restored operational row counts do not match the source"
    }
    if ($requiredTables.Trim() -ne "27") {
        throw "One or more required tables are missing after restore"
    }
    if ($requiredIndexes.Trim() -ne "31") {
        throw "One or more required indexes are missing after restore"
    }
    if ($requiredConstraints.Trim() -ne "110") {
        throw "One or more required constraints are missing after restore"
    }
    if ($auditTriggers.Trim() -ne "2") {
        throw "Audit immutability triggers are missing after restore"
    }
    if ($documentVersionTriggers.Trim() -ne "1") {
        throw "Candidate document-version immutability trigger is missing after restore"
    }
    if ($sourceTextTriggers.Trim() -ne "3") {
        throw "Candidate source-text lineage triggers are missing after restore"
    }
    if ($extractionJobTriggers.Trim() -ne "2") {
        throw "Candidate extraction-job triggers are missing after restore"
    }

    Invoke-Checked -Description "Audit immutability probe creation" -Command {
        docker compose exec -T postgres psql `
            --username ai_interviewer `
            --dbname $RecoveryDatabase `
            --set ON_ERROR_STOP=1 `
            --command "INSERT INTO audit_events (actor_type, action, resource_type, details) VALUES ('system', 'restore.immutability_probe', 'database', '{}'::jsonb)"
    }
    docker compose exec -T postgres psql `
        --username ai_interviewer `
        --dbname $RecoveryDatabase `
        --set ON_ERROR_STOP=1 `
        --command "UPDATE audit_events SET action = 'restore.tamper_test' WHERE action = 'restore.immutability_probe'"
    if ($LASTEXITCODE -eq 0) {
        throw "The restored audit table accepted a mutation"
    }

    $env:AI_INTERVIEWER_ENVIRONMENT = "test"
    $env:AI_INTERVIEWER_DATABASE_URL = "postgresql+psycopg://ai_interviewer:local-only@127.0.0.1:55432/$RecoveryDatabase"
    Invoke-Checked -Description "Restored database readiness" -Command {
        uv run python scripts/check_database_readiness.py
    }

    $duration = [math]::Round(((Get-Date) - $startedAt).TotalSeconds, 2)
    Write-Output "restore_rehearsal=passed"
    Write-Output "source_revision=$($sourceRevision.Trim())"
    Write-Output "source_and_restored_counts=$($sourceCounts.Trim())"
    Write-Output "audit_trigger_count=$($auditTriggers.Trim())"
    Write-Output "document_version_trigger_count=$($documentVersionTriggers.Trim())"
    Write-Output "source_text_trigger_count=$($sourceTextTriggers.Trim())"
    Write-Output "extraction_job_trigger_count=$($extractionJobTriggers.Trim())"
    Write-Output "backup_sha256=$($backupHash.Split(' ')[0])"
    Write-Output "duration_seconds=$duration"
}
finally {
    if ($createdRecoveryDatabase) {
        docker compose exec -T postgres dropdb `
            --force `
            --if-exists `
            --username ai_interviewer `
            $RecoveryDatabase | Out-Null
    }
    if ($createdBackup) {
        docker compose exec -T postgres rm -f $containerBackup | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Could not remove the temporary backup '$containerBackup'"
        }
    }
    if ($null -eq $originalDatabaseUrl) {
        Remove-Item Env:AI_INTERVIEWER_DATABASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:AI_INTERVIEWER_DATABASE_URL = $originalDatabaseUrl
    }
    if ($null -eq $originalEnvironment) {
        Remove-Item Env:AI_INTERVIEWER_ENVIRONMENT -ErrorAction SilentlyContinue
    }
    else {
        $env:AI_INTERVIEWER_ENVIRONMENT = $originalEnvironment
    }
    if ($startedPostgres) {
        docker compose stop --timeout 10 postgres | Out-Null
    }
}
