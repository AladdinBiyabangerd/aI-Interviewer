"""Minimal local identity mapping for external OIDC subjects."""

from typing import Literal

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ai_interviewer.persistence.base import (
    PersistenceBase,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    VersionedRecordMixin,
)

AccountStatus = Literal["active", "disabled", "deletion_pending"]


class Account(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    VersionedRecordMixin,
    PersistenceBase,
):
    """A pseudonymous account keyed by the OIDC issuer/subject pair."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_accounts_issuer_subject"),
        CheckConstraint("btrim(issuer) <> ''", name="issuer_nonempty"),
        CheckConstraint("btrim(subject) <> ''", name="subject_nonempty"),
        CheckConstraint(
            "status IN ('active', 'disabled', 'deletion_pending')",
            name="status_allowed",
        ),
        CheckConstraint("version > 0", name="version_positive"),
    )

    issuer: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        String(32),
        default="active",
        server_default="active",
        nullable=False,
    )
