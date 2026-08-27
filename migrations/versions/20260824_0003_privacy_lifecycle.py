"""Create the jurisdiction-aware privacy lifecycle.

Revision ID: 20260824_0003
Revises: 20260823_0002
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0003"
down_revision: str | None = "20260823_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid_pk() -> sa.Column[object]:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        nullable=False,
    )


def _created_at() -> sa.Column[object]:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _updated_at() -> sa.Column[object]:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _version() -> sa.Column[object]:
    return sa.Column("version", sa.BigInteger(), server_default=sa.text("1"), nullable=False)


def upgrade() -> None:
    op.drop_constraint(op.f("ck_accounts_status_allowed"), "accounts", type_="check")
    op.create_check_constraint(
        "status_allowed",
        "accounts",
        "status IN ('active', 'disabled', 'deletion_pending')",
    )

    op.execute("DROP TRIGGER audit_events_reject_truncate ON audit_events")
    op.execute("DROP TRIGGER audit_events_reject_update_delete ON audit_events")
    op.execute("DROP FUNCTION reject_audit_event_mutation()")
    op.add_column("audit_events", sa.Column("evidence_category", sa.String(100), nullable=True))
    op.add_column(
        "audit_events", sa.Column("retain_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "retention_pair",
        "audit_events",
        "(evidence_category IS NULL AND retain_until IS NULL) OR "
        "(evidence_category IS NOT NULL AND retain_until IS NOT NULL)",
    )
    op.create_index(
        "ix_audit_events_retention",
        "audit_events",
        ["retain_until"],
        postgresql_where=sa.text("retain_until IS NOT NULL"),
    )
    op.execute(
        """
        CREATE FUNCTION reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'DELETE'
               AND OLD.retain_until IS NOT NULL
               AND OLD.retain_until <= now() THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_reject_update_delete
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_reject_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )

    op.create_table(
        "privacy_policy_versions",
        sa.Column("policy_key", sa.String(100), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("jurisdiction_code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("legal_review_status", sa.String(16), nullable=False),
        sa.Column("minimum_age", sa.Integer(), nullable=False),
        sa.Column("request_deadline_days", sa.Integer(), nullable=False),
        sa.Column("notice_uri", sa.String(2048), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _uuid_pk(),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name=op.f("ck_privacy_policy_versions_status_allowed"),
        ),
        sa.CheckConstraint(
            "legal_review_status IN ('pending', 'approved', 'superseded')",
            name=op.f("ck_privacy_policy_versions_legal_review_status_allowed"),
        ),
        sa.CheckConstraint(
            "status <> 'active' OR legal_review_status = 'approved'",
            name=op.f("ck_privacy_policy_versions_active_requires_legal_approval"),
        ),
        sa.CheckConstraint(
            "minimum_age >= 18 AND minimum_age <= 120",
            name=op.f("ck_privacy_policy_versions_minimum_age_valid"),
        ),
        sa.CheckConstraint(
            "request_deadline_days >= 1 AND request_deadline_days <= 365",
            name=op.f("ck_privacy_policy_versions_request_deadline_valid"),
        ),
        sa.CheckConstraint(
            "char_length(content_sha256) = 64",
            name=op.f("ck_privacy_policy_versions_content_digest_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_policy_versions")),
        sa.UniqueConstraint(
            "policy_key",
            "policy_version",
            name=op.f("uq_policy_key_version"),
        ),
    )
    op.create_index(
        "ix_privacy_policy_jurisdiction_status",
        "privacy_policy_versions",
        ["jurisdiction_code", "status"],
    )

    op.create_table(
        "privacy_profiles",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("residence_country_code", sa.String(2), nullable=False),
        sa.Column("residence_subdivision_code", sa.String(16), nullable=True),
        sa.Column("jurisdiction_codes", postgresql.JSONB(), nullable=False),
        sa.Column("jurisdiction_versions", postgresql.JSONB(), nullable=False),
        sa.Column("storage_region", sa.String(64), nullable=False),
        sa.Column("adult_attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "privacy_policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        _created_at(),
        _updated_at(),
        _version(),
        sa.CheckConstraint(
            "char_length(residence_country_code) = 2",
            name=op.f("ck_privacy_profiles_country_code_length"),
        ),
        sa.CheckConstraint(
            "jsonb_array_length(jurisdiction_codes) >= 1",
            name=op.f("ck_privacy_profiles_jurisdictions_nonempty"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_privacy_profiles_version_positive")),
        sa.PrimaryKeyConstraint("account_id", name=op.f("pk_privacy_profiles")),
    )

    op.create_table(
        "consent_notices",
        sa.Column(
            "privacy_policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("notice_key", sa.String(100), nullable=False),
        sa.Column("notice_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("data_category", sa.String(100), nullable=False),
        sa.Column("document_uri", sa.String(2048), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        _uuid_pk(),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'retired')",
            name=op.f("ck_consent_notices_status_allowed"),
        ),
        sa.CheckConstraint(
            "char_length(content_sha256) = 64",
            name=op.f("ck_consent_notices_content_digest_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_notices")),
        sa.UniqueConstraint(
            "privacy_policy_version_id",
            "notice_key",
            "notice_version",
            name=op.f("uq_consent_notice_policy_key_version"),
        ),
    )
    op.create_index(
        "ix_consent_notices_lookup",
        "consent_notices",
        ["notice_key", "status", "effective_at"],
    )

    op.create_table(
        "processing_rules",
        sa.Column(
            "privacy_policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("jurisdiction_code", sa.String(64), nullable=False),
        sa.Column("data_category", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("legal_basis", sa.String(100), nullable=False),
        sa.Column(
            "consent_notice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("consent_notices.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        _created_at(),
        _uuid_pk(),
        sa.CheckConstraint(
            "btrim(legal_basis) <> ''",
            name=op.f("ck_processing_rules_legal_basis_nonempty"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_rules")),
        sa.UniqueConstraint(
            "privacy_policy_version_id",
            "jurisdiction_code",
            "data_category",
            "purpose",
            name=op.f("uq_processing_rule_context"),
        ),
    )
    op.create_index(
        "ix_processing_rules_resolution",
        "processing_rules",
        ["privacy_policy_version_id", "jurisdiction_code"],
    )

    op.create_table(
        "retention_rules",
        sa.Column(
            "privacy_policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("jurisdiction_code", sa.String(64), nullable=False),
        sa.Column("data_category", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        _created_at(),
        _uuid_pk(),
        sa.CheckConstraint(
            "retention_days >= 1 AND retention_days <= 36500",
            name=op.f("ck_retention_rules_days_valid"),
        ),
        sa.CheckConstraint(
            "action IN ('delete', 'anonymize')",
            name=op.f("ck_retention_rules_action_allowed"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retention_rules")),
        sa.UniqueConstraint(
            "privacy_policy_version_id",
            "jurisdiction_code",
            "data_category",
            "purpose",
            name=op.f("uq_retention_rule_context"),
        ),
    )
    op.create_index(
        "ix_retention_rules_resolution",
        "retention_rules",
        ["privacy_policy_version_id", "jurisdiction_code"],
    )

    op.create_table(
        "privacy_requests",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "privacy_policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("jurisdiction_code", sa.String(64), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_action", sa.String(16), nullable=False),
        sa.Column("attempts", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        _created_at(),
        _updated_at(),
        _version(),
        _uuid_pk(),
        sa.CheckConstraint(
            "request_type IN ('access', 'export', 'deletion')",
            name=op.f("ck_privacy_requests_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('received', 'verified', 'processing', 'completed', 'failed', 'cancelled')",
            name=op.f("ck_privacy_requests_status_allowed"),
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key_hash) = 64",
            name=op.f("ck_privacy_requests_idempotency_digest_length"),
        ),
        sa.CheckConstraint(
            "due_at >= requested_at", name=op.f("ck_privacy_requests_due_after_request")
        ),
        sa.CheckConstraint(
            "retain_until > requested_at",
            name=op.f("ck_privacy_requests_retention_after_request"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_privacy_requests_attempts_nonnegative")),
        sa.CheckConstraint("version > 0", name=op.f("ck_privacy_requests_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_privacy_requests")),
        sa.UniqueConstraint(
            "account_id",
            "idempotency_key_hash",
            name=op.f("uq_privacy_request_idempotency"),
        ),
    )
    op.create_index(
        "ix_privacy_requests_account_created",
        "privacy_requests",
        ["account_id", "created_at"],
    )
    op.create_index("ix_privacy_requests_status_due", "privacy_requests", ["status", "due_at"])
    op.create_index("ix_privacy_requests_retention", "privacy_requests", ["retain_until"])

    op.create_table(
        "processors",
        sa.Column("processor_key", sa.String(100), nullable=False),
        sa.Column("inventory_version", sa.String(64), nullable=False),
        sa.Column("legal_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("privacy_uri", sa.String(2048), nullable=False),
        sa.Column("contract_reference", sa.String(255), nullable=False),
        sa.Column("operating_countries", postgresql.JSONB(), nullable=False),
        sa.Column(
            "subprocessors",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _created_at(),
        _updated_at(),
        _version(),
        _uuid_pk(),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'retired')",
            name=op.f("ck_processors_status_allowed"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_processors_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processors")),
        sa.UniqueConstraint(
            "processor_key",
            "inventory_version",
            name=op.f("uq_processor_key_version"),
        ),
    )

    op.create_table(
        "processor_activities",
        sa.Column(
            "processor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "privacy_policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("privacy_policy_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("data_category", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("origin_region", sa.String(64), nullable=False),
        sa.Column("processing_region", sa.String(64), nullable=False),
        sa.Column("storage_region", sa.String(64), nullable=False),
        sa.Column("cross_border", sa.Boolean(), nullable=False),
        sa.Column("transfer_mechanism", sa.String(255), nullable=True),
        sa.Column("deletion_mechanism", sa.String(100), nullable=False),
        sa.Column("deletion_sla_days", sa.Integer(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        _uuid_pk(),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'retired')",
            name=op.f("ck_processor_activities_status_allowed"),
        ),
        sa.CheckConstraint(
            "NOT cross_border OR btrim(transfer_mechanism) <> ''",
            name=op.f("ck_processor_activities_cross_border_requires_mechanism"),
        ),
        sa.CheckConstraint(
            "deletion_sla_days >= 1 AND deletion_sla_days <= 365",
            name=op.f("ck_processor_activities_deletion_sla_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processor_activities")),
    )
    op.create_index(
        "ix_processor_activities_policy",
        "processor_activities",
        ["privacy_policy_version_id", "status"],
    )

    op.create_table(
        "consent_records",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "consent_notice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("consent_notices.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_action", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=True),
        _created_at(),
        _updated_at(),
        _version(),
        _uuid_pk(),
        sa.CheckConstraint(
            "withdrawn_at IS NULL OR withdrawn_at >= granted_at",
            name=op.f("ck_consent_records_withdrawal_order"),
        ),
        sa.CheckConstraint(
            "retain_until > granted_at",
            name=op.f("ck_consent_records_retention_after_grant"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_consent_records_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consent_records")),
    )
    op.create_index(
        "uq_consent_records_active_notice",
        "consent_records",
        ["account_id", "consent_notice_id"],
        unique=True,
        postgresql_where=sa.text("withdrawn_at IS NULL"),
    )
    op.create_index(
        "ix_consent_records_account_created",
        "consent_records",
        ["account_id", "created_at"],
    )
    op.create_index("ix_consent_records_retention", "consent_records", ["retain_until"])

    op.create_table(
        "processor_usages",
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "processor_activity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processor_activities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("processor_subject_reference", sa.String(255), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        _uuid_pk(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processor_usages")),
        sa.UniqueConstraint(
            "account_id",
            "processor_activity_id",
            "processor_subject_reference",
            name=op.f("uq_processor_usage_locator"),
        ),
    )
    op.create_index("ix_processor_usages_account", "processor_usages", ["account_id"])

    op.create_table(
        "processor_deletion_tasks",
        sa.Column(
            "privacy_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("privacy_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "processor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "processor_usage_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processor_usages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("processor_subject_reference", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(128), nullable=True),
        sa.Column("last_error_code", sa.String(100), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retain_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_action", sa.String(16), nullable=False),
        _uuid_pk(),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'retry', 'escalated')",
            name=op.f("ck_processor_deletion_tasks_status_allowed"),
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name=op.f("ck_processor_deletion_tasks_attempts_nonnegative"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('pending', 'processing', 'retry') OR "
            "processor_subject_reference IS NOT NULL",
            name=op.f("ck_processor_deletion_tasks_active_task_requires_locator"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processor_deletion_tasks")),
        sa.UniqueConstraint(
            "privacy_request_id",
            "processor_usage_id",
            name=op.f("uq_deletion_task_usage"),
        ),
    )
    op.create_index(
        "ix_processor_deletion_tasks_available",
        "processor_deletion_tasks",
        ["status", "available_at"],
    )

    op.create_table(
        "backup_deletion_markers",
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_fingerprint", sa.String(64), nullable=False),
        sa.Column("privacy_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("privacy_policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("backups_expire_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        _uuid_pk(),
        sa.CheckConstraint(
            "char_length(subject_fingerprint) = 64",
            name=op.f("ck_backup_deletion_markers_subject_digest_length"),
        ),
        sa.CheckConstraint(
            "backups_expire_at > cutoff_at",
            name=op.f("ck_backup_deletion_markers_backup_expiry_after_cutoff"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_deletion_markers")),
        sa.UniqueConstraint(
            "account_id",
            "cutoff_at",
            name=op.f("uq_backup_marker_account_cutoff"),
        ),
    )
    op.create_index(
        "ix_backup_deletion_markers_expiry",
        "backup_deletion_markers",
        ["backups_expire_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_backup_deletion_markers_expiry", table_name="backup_deletion_markers")
    op.drop_table("backup_deletion_markers")
    op.drop_index("ix_processor_deletion_tasks_available", table_name="processor_deletion_tasks")
    op.drop_table("processor_deletion_tasks")
    op.drop_index("ix_processor_usages_account", table_name="processor_usages")
    op.drop_table("processor_usages")
    op.drop_index("ix_consent_records_retention", table_name="consent_records")
    op.drop_index("ix_consent_records_account_created", table_name="consent_records")
    op.drop_index(
        "uq_consent_records_active_notice",
        table_name="consent_records",
        postgresql_where=sa.text("withdrawn_at IS NULL"),
    )
    op.drop_table("consent_records")
    op.drop_index("ix_processor_activities_policy", table_name="processor_activities")
    op.drop_table("processor_activities")
    op.drop_table("processors")
    op.drop_index("ix_privacy_requests_retention", table_name="privacy_requests")
    op.drop_index("ix_privacy_requests_status_due", table_name="privacy_requests")
    op.drop_index("ix_privacy_requests_account_created", table_name="privacy_requests")
    op.drop_table("privacy_requests")
    op.drop_index("ix_retention_rules_resolution", table_name="retention_rules")
    op.drop_table("retention_rules")
    op.drop_index("ix_processing_rules_resolution", table_name="processing_rules")
    op.drop_table("processing_rules")
    op.drop_index("ix_consent_notices_lookup", table_name="consent_notices")
    op.drop_table("consent_notices")
    op.drop_table("privacy_profiles")
    op.drop_index("ix_privacy_policy_jurisdiction_status", table_name="privacy_policy_versions")
    op.drop_table("privacy_policy_versions")

    op.execute("DROP TRIGGER audit_events_reject_truncate ON audit_events")
    op.execute("DROP TRIGGER audit_events_reject_update_delete ON audit_events")
    op.execute("DROP FUNCTION reject_audit_event_mutation()")
    op.drop_index(
        "ix_audit_events_retention",
        table_name="audit_events",
        postgresql_where=sa.text("retain_until IS NOT NULL"),
    )
    op.drop_constraint(op.f("ck_audit_events_retention_pair"), "audit_events", type_="check")
    op.drop_column("audit_events", "retain_until")
    op.drop_column("audit_events", "evidence_category")
    op.execute(
        """
        CREATE FUNCTION reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = '55000';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_reject_update_delete
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_reject_truncate
        BEFORE TRUNCATE ON audit_events
        FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_event_mutation()
        """
    )

    op.drop_constraint(op.f("ck_accounts_status_allowed"), "accounts", type_="check")
    op.create_check_constraint("status_allowed", "accounts", "status IN ('active', 'disabled')")
