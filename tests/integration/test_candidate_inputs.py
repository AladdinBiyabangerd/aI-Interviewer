from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update
from tests.integration.test_privacy import PrivacyContext, _create_privacy_context

from ai_interviewer.candidate_inputs.models import CandidatePreparation
from ai_interviewer.candidate_inputs.service import (
    CandidateInputService,
    CandidatePreparationConflictError,
    CandidatePreparationNotFoundError,
    CandidatePreparationPreconditionError,
    PreparationInput,
    apply_due_candidate_input_retention,
)
from ai_interviewer.persistence.database import Database
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent
from ai_interviewer.privacy.lifecycle import PrivacyLifecycleService
from ai_interviewer.privacy.models import ProcessingRule, RetentionRule
from ai_interviewer.privacy.policy import build_default_jurisdiction_registry
from ai_interviewer.privacy.rules import PrivacyPolicyUnavailableError

pytestmark = pytest.mark.integration


def _input(**changes: object) -> PreparationInput:
    values: dict[str, object] = {
        "company_name": "Synthetic Company",
        "role_family": "software_engineering",
        "role_family_other": None,
        "role_title": "Backend Engineer",
        "seniority": "senior",
        "seniority_other": None,
        "target_country_code": "AZ",
        "target_office": "Baku",
        "interview_round": "system_design",
        "interview_round_other": None,
        "interview_language": "az",
    }
    values.update(changes)
    return PreparationInput(**values)  # type: ignore[arg-type]


async def _allow_candidate_context(
    database: Database,
    context: PrivacyContext,
    *,
    retention_action: str = "delete",
) -> None:
    async with database.transaction() as session:
        session.add_all(
            [
                ProcessingRule(
                    privacy_policy_version_id=context.policy_id,
                    jurisdiction_code="AZERBAIJAN",
                    data_category="candidate_preparation_context",
                    purpose="interview_preparation",
                    allowed=True,
                    legal_basis="contract",
                ),
                RetentionRule(
                    privacy_policy_version_id=context.policy_id,
                    jurisdiction_code="AZERBAIJAN",
                    data_category="candidate_preparation_context",
                    purpose="interview_preparation",
                    retention_days=30,
                    action=retention_action,
                ),
            ]
        )


@pytest.mark.asyncio
async def test_create_is_idempotent_private_and_audited(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _allow_candidate_context(database, context)
    service = CandidateInputService(database)

    first = await service.create_preparation(
        context.account_id,
        _input(company_name="  Synthetic Company  ", target_country_code="az"),
        "stable-preparation-key",
        "candidate-create",
    )
    repeated = await service.create_preparation(
        context.account_id,
        _input(),
        "stable-preparation-key",
        "candidate-create-retry",
    )

    assert first.created is True
    assert repeated.created is False
    assert first.preparation.id == repeated.preparation.id
    assert first.preparation.id.version == 7
    assert first.preparation.company_name == "Synthetic Company"
    assert first.preparation.target_country_code == "AZ"
    assert first.preparation.retention_action == "delete"
    assert first.preparation.version == 1

    async with database.transaction() as session:
        row_count = await session.scalar(
            select(func.count())
            .select_from(CandidatePreparation)
            .where(CandidatePreparation.owner_id == context.account_id)
        )
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == first.preparation.id,
                AuditEvent.action == "candidate_preparation.created",
            )
        )
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == first.preparation.id,
                OutboxEvent.event_type == "candidate_preparation.created",
            )
        )
    assert row_count == 1
    assert audit is not None and event is not None
    operational_metadata = f"{audit.details} {event.payload}"
    assert "Synthetic Company" not in operational_metadata
    assert "Backend Engineer" not in operational_metadata
    assert event.payload["role_family"] == "software_engineering"

    with pytest.raises(CandidatePreparationConflictError, match="idempotency"):
        await service.create_preparation(
            context.account_id,
            _input(company_name="Different Company"),
            "stable-preparation-key",
            "candidate-create-conflict",
        )


@pytest.mark.asyncio
async def test_owner_pagination_replace_and_archive_are_fail_closed(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _allow_candidate_context(database, context)
    service = CandidateInputService(database)
    first = await service.create_preparation(
        context.account_id, _input(), "preparation-page-one", "page-one"
    )
    second = await service.create_preparation(
        context.account_id,
        _input(company_name="Second Synthetic Company"),
        "preparation-page-two",
        "page-two",
    )

    page_one = await service.list_preparations(context.account_id, limit=1, after=None)
    page_two = await service.list_preparations(
        context.account_id, limit=1, after=page_one.next_after
    )
    assert len(page_one.items) == 1 and page_one.next_after == page_one.items[0].id
    assert len(page_two.items) == 1 and page_two.next_after is None
    assert {page_one.items[0].id, page_two.items[0].id} == {
        first.preparation.id,
        second.preparation.id,
    }

    other_owner = uuid4()
    with pytest.raises(CandidatePreparationNotFoundError):
        await service.get_preparation(other_owner, first.preparation.id)

    updated = await service.replace_preparation(
        context.account_id,
        first.preparation.id,
        _input(company_name="Updated Synthetic Company", interview_language="en"),
        expected_version=1,
        request_id="candidate-update",
    )
    assert updated.version == 2
    assert updated.company_name == "Updated Synthetic Company"
    assert updated.interview_language == "en"
    with pytest.raises(CandidatePreparationPreconditionError):
        await service.replace_preparation(
            context.account_id,
            first.preparation.id,
            _input(),
            expected_version=1,
            request_id="candidate-stale-update",
        )

    archived = await service.archive_preparation(
        context.account_id,
        first.preparation.id,
        expected_version=2,
        request_id="candidate-archive",
    )
    assert archived.status == "archived"
    assert archived.version == 3
    repeated = await service.archive_preparation(
        context.account_id,
        first.preparation.id,
        expected_version=3,
        request_id="candidate-archive-retry",
    )
    assert repeated.version == 3
    with pytest.raises(CandidatePreparationConflictError, match="archived"):
        await service.replace_preparation(
            context.account_id,
            first.preparation.id,
            _input(),
            expected_version=3,
            request_id="candidate-archived-update",
        )


@pytest.mark.asyncio
async def test_processing_and_retention_fail_closed(database: Database) -> None:
    context = await _create_privacy_context(database)
    service = CandidateInputService(database)
    with pytest.raises(PrivacyPolicyUnavailableError):
        await service.create_preparation(
            context.account_id,
            _input(),
            "candidate-policy-missing",
            "candidate-policy-missing",
        )

    await _allow_candidate_context(database, context, retention_action="anonymize")
    with pytest.raises(CandidatePreparationConflictError, match="delete retention"):
        await service.create_preparation(
            context.account_id,
            _input(),
            "candidate-anonymize-unsupported",
            "candidate-anonymize-unsupported",
        )


@pytest.mark.asyncio
async def test_privacy_export_and_deletion_include_candidate_context(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _allow_candidate_context(database, context)
    candidate_service = CandidateInputService(database)
    created = await candidate_service.create_preparation(
        context.account_id,
        _input(),
        "candidate-export-record",
        "candidate-export-record",
    )
    privacy = PrivacyLifecycleService(
        database=database,
        registry=build_default_jurisdiction_registry(),
        subject_hmac_key=b"integration-privacy-hmac-key-value" * 2,
        candidate_data_lifecycle=candidate_service,
    )

    exported = await privacy.create_request(
        context.account_id,
        "export",
        "candidate-context-export-key",
        "candidate-context-export",
    )
    assert exported.data is not None
    assert exported.data["schema_version"] == "phase-1a-c.1"
    assert exported.data["candidate_document_intakes"] == []
    assert exported.data["candidate_preparations"][0]["preparation_id"] == str(
        created.preparation.id
    )
    assert exported.data["candidate_preparations"][0]["company_name"] == "Synthetic Company"
    assert "idempotency_key_hash" not in str(exported.data["candidate_preparations"])

    deletion = await privacy.create_request(
        context.account_id,
        "deletion",
        "candidate-context-delete-key",
        "candidate-context-delete",
    )
    assert deletion.status == "completed"
    async with database.transaction() as session:
        persisted = await session.get(CandidatePreparation, created.preparation.id)
    assert persisted is None


@pytest.mark.asyncio
async def test_due_retention_removes_only_expired_candidate_context(database: Database) -> None:
    context = await _create_privacy_context(database)
    await _allow_candidate_context(database, context)
    service = CandidateInputService(database)
    past = datetime.now(UTC) - timedelta(days=40)
    expired = await service.create_preparation(
        context.account_id,
        _input(company_name="Expired Synthetic Company"),
        "candidate-expired-record",
        "candidate-expired-record",
    )
    current = await service.create_preparation(
        context.account_id,
        _input(),
        "candidate-current-record",
        "candidate-current-record",
    )

    async with database.transaction() as session:
        await session.execute(
            update(CandidatePreparation)
            .where(CandidatePreparation.id == expired.preparation.id)
            .values(
                created_at=past,
                updated_at=past,
                retain_until=past + timedelta(days=30),
            )
        )

    async with database.transaction() as session:
        removed = await apply_due_candidate_input_retention(session)
    assert removed == 1
    async with database.transaction() as session:
        assert await session.get(CandidatePreparation, expired.preparation.id) is None
        assert await session.get(CandidatePreparation, current.preparation.id) is not None
