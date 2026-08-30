from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from tests.integration.test_candidate_documents import (
    _delete_test_assets,
    _domain,
    _released_asset,
)
from tests.integration.test_file_security import _application_keyring

from ai_interviewer.candidate_inputs.documents import (
    AttachDocumentVersionResult,
    CandidateDocumentService,
)
from ai_interviewer.candidate_inputs.source_text_models import (
    CandidateSourceText,
    CandidateSourceTextVersion,
)
from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextConflictError,
    CandidateSourceTextNotFoundError,
    CandidateSourceTextPreconditionError,
    CandidateSourceTextService,
    ParserExecutionIdentity,
)
from ai_interviewer.file_security.lifecycle import FileSecurityService
from ai_interviewer.file_security.models import FileAsset, ParserReleasePolicy
from ai_interviewer.persistence.database import Database
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent

pytestmark = pytest.mark.integration


async def _attached_document_version(
    database: Database,
    suffix: str,
) -> tuple[
    UUID,
    UUID,
    CandidateDocumentService,
    FileSecurityService,
    FileAsset,
    AttachDocumentVersionResult,
    ParserExecutionIdentity,
]:
    account_id, preparation_id, documents, files, _ = await _domain(database, suffix)
    asset = await _released_asset(files, account_id=account_id, marker=suffix)
    attached = await documents.attach_released_asset(
        account_id,
        preparation_id,
        "cv",
        asset.id,
        "upload",
        f"source-text-attach-{suffix}",
    )
    async with database.transaction() as session:
        policy = await session.get(ParserReleasePolicy, asset.parser_release_policy_id)
    assert policy is not None
    parser = ParserExecutionIdentity(
        parser_release_policy_id=policy.id,
        parser_adapter=policy.parser_adapter,
        parser_version=policy.parser_version,
        isolation_profile=policy.isolation_profile,
    )
    return account_id, preparation_id, documents, files, asset, attached, parser


@pytest.mark.asyncio
async def test_parser_result_is_encrypted_immutable_idempotent_and_owner_scoped(
    database: Database,
) -> None:
    (
        account_id,
        preparation_id,
        _,
        files,
        asset,
        attached,
        parser,
    ) = await _attached_document_version(database, "encrypted-lineage")
    document_version_id = attached.attached_version.version_id
    source_texts = CandidateSourceTextService(database, _application_keyring())
    content = "Senior Python mühəndisi\nPostgreSQL və təhlükəsizlik təcrübəsi"

    first = await source_texts.store_parser_extraction(
        account_id,
        document_version_id,
        content,
        parser,
        "source-text-store",
    )
    repeated = await source_texts.store_parser_extraction(
        account_id,
        document_version_id,
        content,
        parser,
        "source-text-store-retry",
    )
    fetched = await source_texts.get_source_text(account_id, preparation_id, document_version_id)

    assert first.created is True
    assert repeated.created is False
    assert repeated.source_text == first.source_text == fetched
    assert first.source_text.source_text_id.version == 7
    assert first.source_text.aggregate_version == 1
    assert first.source_text.latest_version_number == 1
    text_version = first.source_text.versions[0]
    assert text_version.text_version_id.version == 7
    assert text_version.content == content
    assert text_version.character_count == len(content)
    assert text_version.utf8_byte_count == len(content.encode())
    assert text_version.line_count == 2
    assert text_version.parser_release_policy_id == parser.parser_release_policy_id

    with pytest.raises(CandidateSourceTextNotFoundError):
        await source_texts.get_source_text(uuid4(), preparation_id, document_version_id)
    with pytest.raises(CandidateSourceTextConflictError, match="different parser result"):
        await source_texts.store_parser_extraction(
            account_id,
            document_version_id,
            f"{content}\nchanged",
            parser,
            "source-text-conflict",
        )

    async with database.transaction() as session:
        stored = await session.scalar(
            select(CandidateSourceTextVersion).where(
                CandidateSourceTextVersion.id == text_version.text_version_id
            )
        )
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == text_version.text_version_id,
                AuditEvent.action == "candidate_source_text.parser_extraction_stored",
            )
        )
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == first.source_text.source_text_id,
                OutboxEvent.event_type == "candidate_source_text.parser_extraction_stored",
            )
        )
    assert stored is not None and audit is not None and event is not None
    assert stored.content_ciphertext != content.encode()
    assert content.encode() not in stored.content_ciphertext
    assert stored.content_digest != attached.attached_version.content_sha256
    operational_metadata = f"{audit.details} {event.payload}"
    assert content not in operational_metadata
    assert stored.content_digest not in operational_metadata

    with pytest.raises(DBAPIError, match="immutable"):
        async with database.transaction() as session:
            await session.execute(
                update(CandidateSourceTextVersion)
                .where(CandidateSourceTextVersion.id == text_version.text_version_id)
                .values(character_count=1)
            )
    with pytest.raises(DBAPIError, match="identity is immutable"):
        async with database.transaction() as session:
            await session.execute(
                update(CandidateSourceText)
                .where(CandidateSourceText.id == first.source_text.source_text_id)
                .values(document_version_id=uuid4())
            )

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="candidate-source-text-cleanup",
    )
    async with database.transaction() as session:
        assert await session.get(CandidateSourceText, first.source_text.source_text_id) is None
        assert await session.get(CandidateSourceTextVersion, text_version.text_version_id) is None


@pytest.mark.asyncio
async def test_parser_provenance_and_latest_document_version_fail_closed(
    database: Database,
) -> None:
    (
        account_id,
        preparation_id,
        documents,
        files,
        first_asset,
        attached,
        parser,
    ) = await _attached_document_version(database, "policy-boundary")
    source_texts = CandidateSourceTextService(database, _application_keyring())
    wrong_parser = ParserExecutionIdentity(
        parser_release_policy_id=parser.parser_release_policy_id,
        parser_adapter=f"{parser.parser_adapter}-unexpected",
        parser_version=parser.parser_version,
        isolation_profile=parser.isolation_profile,
    )
    with pytest.raises(CandidateSourceTextConflictError, match="parser release"):
        await source_texts.store_parser_extraction(
            account_id,
            attached.attached_version.version_id,
            "safe parser output",
            wrong_parser,
            "source-text-wrong-parser",
        )

    second_asset = await _released_asset(
        files,
        account_id=account_id,
        marker="policy-boundary-v2",
    )
    await documents.attach_released_asset(
        account_id,
        preparation_id,
        "cv",
        second_asset.id,
        "upload",
        "source-text-replacement",
    )
    with pytest.raises(CandidateSourceTextConflictError, match="latest document version"):
        await source_texts.store_parser_extraction(
            account_id,
            attached.attached_version.version_id,
            "safe parser output",
            parser,
            "source-text-obsolete-version",
        )

    await _delete_test_assets(
        database,
        files,
        {first_asset.id, second_asset.id},
        worker_id="candidate-source-text-policy-cleanup",
    )


@pytest.mark.asyncio
async def test_correction_append_is_optimistic_idempotent_and_owner_scoped(
    database: Database,
) -> None:
    (
        account_id,
        preparation_id,
        _,
        files,
        asset,
        attached,
        parser,
    ) = await _attached_document_version(database, "correction-lineage")
    document_version_id = attached.attached_version.version_id
    source_texts = CandidateSourceTextService(database, _application_keyring())
    original = "Parsed CV text before any owner correction."
    stored = await source_texts.store_parser_extraction(
        account_id,
        document_version_id,
        original,
        parser,
        "source-text-for-correction",
    )
    assert stored.source_text.aggregate_version == 1

    corrected = "Parsed CV text after the owner fixed a typo."
    first_correction = await source_texts.append_correction(
        account_id,
        preparation_id,
        document_version_id,
        corrected,
        1,
        "correction-first",
    )
    assert first_correction.aggregate_version == 2
    assert first_correction.latest_version_number == 2
    latest = first_correction.versions[-1]
    assert latest.origin == "user_correction"
    assert latest.version_number == 2
    assert latest.previous_version_id == first_correction.versions[0].text_version_id
    assert latest.content == corrected
    assert latest.parser_adapter is None
    assert latest.parser_release_policy_id is None

    repeated_correction = await source_texts.append_correction(
        account_id,
        preparation_id,
        document_version_id,
        corrected,
        1,
        "correction-retry",
    )
    assert repeated_correction == first_correction

    with pytest.raises(CandidateSourceTextPreconditionError):
        await source_texts.append_correction(
            account_id,
            preparation_id,
            document_version_id,
            "a completely different correction",
            1,
            "correction-stale",
        )
    with pytest.raises(CandidateSourceTextPreconditionError):
        await source_texts.append_correction(
            account_id,
            preparation_id,
            document_version_id,
            corrected,
            99,
            "correction-future-version",
        )
    with pytest.raises(CandidateSourceTextNotFoundError):
        await source_texts.append_correction(
            account_id,
            uuid4(),
            document_version_id,
            corrected,
            2,
            "correction-wrong-preparation",
        )
    with pytest.raises(CandidateSourceTextNotFoundError):
        await source_texts.append_correction(
            uuid4(),
            preparation_id,
            document_version_id,
            corrected,
            2,
            "correction-wrong-owner",
        )

    second_correction = await source_texts.append_correction(
        account_id,
        preparation_id,
        document_version_id,
        "Parsed CV text after a second owner correction.",
        2,
        "correction-second",
    )
    assert second_correction.aggregate_version == 3
    assert second_correction.versions[-1].previous_version_id == latest.text_version_id

    async with database.transaction() as session:
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "candidate_source_text.correction_appended",
                AuditEvent.owner_id == account_id,
            )
        )
    assert audit is not None
    assert "Parsed CV text" not in f"{audit.details}"

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="candidate-source-text-correction-cleanup",
    )
