from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from tests.integration.test_candidate_documents import _delete_test_assets
from tests.integration.test_candidate_source_texts import _attached_document_version
from tests.integration.test_file_security import _application_keyring
from tests.test_candidate_profiles import _result

from ai_interviewer.candidate_inputs.source_texts import CandidateSourceTextService
from ai_interviewer.model_gateway import ModelGatewayResult, PromptReleaseIdentity
from ai_interviewer.persistence.database import Database
from ai_interviewer.persistence.models import AuditEvent, OutboxEvent
from ai_interviewer.privacy.lifecycle import PrivacyLifecycleService
from ai_interviewer.privacy.policy import build_default_jurisdiction_registry
from ai_interviewer.profiling import (
    CandidateProfileConflictError,
    CandidateProfileNotFoundError,
    CandidateProfileOutput,
    CandidateProfilePreconditionError,
    CandidateProfileService,
    CvProfileOutput,
    CvSkillClaim,
    JobDescriptionProfileOutput,
    JobRequirementClaim,
    SourceSpan,
)
from ai_interviewer.profiling.models import CandidateProfile, CandidateProfileVersion

pytestmark = pytest.mark.integration


async def _source_revision(
    database: Database,
    suffix: str,
    *,
    content: str = "Python backend engineer",
) -> tuple[UUID, UUID, object, object, CandidateSourceTextService, object]:
    (
        account_id,
        preparation_id,
        _,
        files,
        asset,
        attached,
        parser,
    ) = await _attached_document_version(database, suffix)
    source_texts = CandidateSourceTextService(database, _application_keyring())
    stored = await source_texts.store_parser_extraction(
        account_id,
        attached.attached_version.version_id,
        content,
        parser,
        f"profile-source-{suffix}",
    )
    return account_id, preparation_id, files, asset, source_texts, stored


def _changed_result(statement: str) -> ModelGatewayResult[CandidateProfileOutput]:
    profile = CvProfileOutput(
        document_type="cv",
        languages=("en",),
        skills=(
            CvSkillClaim(
                claim_id="skill_python",
                statement=statement,
                assertion_kind="explicit",
                evidence=(SourceSpan(start=0, end=6, quote="Python"),),
                name="Python",
                category="programming_language",
            ),
        ),
    )
    return _result(profile)


@pytest.mark.asyncio
async def test_model_profile_is_encrypted_immutable_idempotent_and_owner_scoped(
    database: Database,
) -> None:
    account_id, preparation_id, files, asset, _, stored_source = await _source_revision(
        database,
        "encrypted-profile",
    )
    document_version_id = stored_source.source_text.document_version_id
    source_version_id = stored_source.source_text.versions[0].text_version_id
    profiles = CandidateProfileService(database, _application_keyring())
    result = _changed_result("Python backend expertise")

    first = await profiles.store_model_profile(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        result,
        "profile-store",
    )
    repeated = await profiles.store_model_profile(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        result,
        "profile-store-retry",
    )
    fetched = await profiles.get_profile(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.candidate_profile == first.candidate_profile == fetched
    assert fetched.profile_id.version == 7
    assert fetched.aggregate_version == 1
    assert fetched.latest_version_number == 1
    assert fetched.document_type == "cv"
    version = fetched.versions[0]
    assert version.profile_version_id.version == 7
    assert version.profile == result.output
    assert version.claim_count == 1
    assert version.evidence_span_count == 1
    assert version.evidence_character_count == 6
    assert version.model_provider == "test-provider"
    assert version.schema_id == "cv-profile"

    with pytest.raises(CandidateProfileNotFoundError):
        await profiles.get_profile(
            uuid4(),
            preparation_id,
            document_version_id,
            source_version_id,
        )
    with pytest.raises(CandidateProfileNotFoundError):
        await profiles.get_profile(
            account_id,
            uuid4(),
            document_version_id,
            source_version_id,
        )
    with pytest.raises(CandidateProfileConflictError, match="different profile"):
        await profiles.store_model_profile(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            _changed_result("A conflicting derived statement"),
            "profile-conflict",
        )

    async with database.transaction() as session:
        stored_version = await session.get(CandidateProfileVersion, version.profile_version_id)
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == version.profile_version_id,
                AuditEvent.action == "candidate_profile.model_generation_stored",
            )
        )
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == fetched.profile_id,
                OutboxEvent.event_type == "candidate_profile.model_generation_stored",
            )
        )
    assert stored_version is not None and audit is not None and event is not None
    sensitive = b"Python backend expertise"
    assert sensitive not in stored_version.profile_ciphertext
    assert sensitive.decode() not in f"{audit.details} {event.payload}"
    assert stored_version.profile_digest not in f"{audit.details} {event.payload}"

    with pytest.raises(DBAPIError, match="versions are immutable"):
        async with database.transaction() as session:
            await session.execute(
                update(CandidateProfileVersion)
                .where(CandidateProfileVersion.id == version.profile_version_id)
                .values(claim_count=2)
            )
    with pytest.raises(DBAPIError, match="identity is immutable"):
        async with database.transaction() as session:
            await session.execute(
                update(CandidateProfile)
                .where(CandidateProfile.id == fetched.profile_id)
                .values(document_version_id=uuid4())
            )

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="candidate-profile-cleanup",
    )
    async with database.transaction() as session:
        assert await session.get(CandidateProfile, fetched.profile_id) is None
        assert await session.get(CandidateProfileVersion, version.profile_version_id) is None


@pytest.mark.asyncio
async def test_owner_correction_is_encrypted_immutable_optimistic_and_idempotent(
    database: Database,
) -> None:
    account_id, preparation_id, files, asset, _, stored_source = await _source_revision(
        database,
        "profile-correction",
    )
    document_version_id = stored_source.source_text.document_version_id
    source_version_id = stored_source.source_text.versions[0].text_version_id
    profiles = CandidateProfileService(database, _application_keyring())
    generated = await profiles.store_model_profile(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        _changed_result("Generated Python expertise"),
        "profile-correction-generated",
    )
    corrected_output = _changed_result("Owner-corrected Python expertise").output

    corrected = await profiles.append_correction(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        corrected_output,
        1,
        "profile-correction-first",
    )
    repeated = await profiles.append_correction(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        corrected_output,
        1,
        "profile-correction-retry",
    )

    assert repeated == corrected
    assert corrected.profile_id == generated.candidate_profile.profile_id
    assert corrected.aggregate_version == 2
    assert corrected.latest_version_number == 2
    assert len(corrected.versions) == 2
    original, correction = corrected.versions
    assert original.origin == "model_generation"
    assert correction.origin == "user_correction"
    assert correction.previous_version_id == original.profile_version_id
    assert correction.profile == corrected_output
    assert correction.model_provider is None
    assert correction.prompt_id is None
    assert correction.instructions_sha256 is None

    with pytest.raises(CandidateProfilePreconditionError):
        await profiles.append_correction(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            corrected_output,
            0,
            "profile-correction-invalid-version",
        )
    wrong_type = JobDescriptionProfileOutput(
        document_type="job_description",
        languages=("en",),
        must_have=(
            JobRequirementClaim(
                claim_id="requirement_python",
                statement="Python is required",
                assertion_kind="explicit",
                evidence=(SourceSpan(start=0, end=6, quote="Python"),),
                category="skill",
            ),
        ),
    )
    with pytest.raises(CandidateProfileConflictError, match="document type"):
        await profiles.append_correction(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            wrong_type,
            2,
            "profile-correction-wrong-type",
        )

    with pytest.raises(CandidateProfilePreconditionError):
        await profiles.append_correction(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            _changed_result("A different owner correction").output,
            1,
            "profile-correction-stale",
        )
    with pytest.raises(CandidateProfileNotFoundError):
        await profiles.append_correction(
            account_id,
            uuid4(),
            document_version_id,
            source_version_id,
            corrected_output,
            2,
            "profile-correction-wrong-preparation",
        )

    async with database.transaction() as session:
        stored_correction = await session.get(
            CandidateProfileVersion,
            correction.profile_version_id,
        )
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == correction.profile_version_id,
                AuditEvent.action == "candidate_profile.correction_appended",
            )
        )
        event = await session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == corrected.profile_id,
                OutboxEvent.event_type == "candidate_profile.correction_appended",
            )
        )
    assert stored_correction is not None and audit is not None and event is not None
    sensitive = "Owner-corrected Python expertise"
    assert sensitive.encode() not in stored_correction.profile_ciphertext
    assert sensitive not in f"{audit.details} {event.payload}"
    assert audit.actor_id == account_id

    replayed_model = await profiles.store_model_profile(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        _changed_result("Generated Python expertise"),
        "profile-correction-model-retry",
    )
    assert replayed_model.created is False
    assert replayed_model.candidate_profile == corrected

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="candidate-profile-correction-cleanup",
    )


@pytest.mark.asyncio
async def test_profile_rechecks_evidence_release_and_latest_source_revision(
    database: Database,
) -> None:
    account_id, preparation_id, files, asset, source_texts, stored_source = await _source_revision(
        database, "profile-evidence"
    )
    document_version_id = stored_source.source_text.document_version_id
    source_version_id = stored_source.source_text.versions[0].text_version_id
    profiles = CandidateProfileService(database, _application_keyring())

    with pytest.raises(CandidateProfileNotFoundError):
        await profiles.append_correction(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            _changed_result("Owner correction before generation").output,
            1,
            "profile-correction-before-generation",
        )

    invalid_evidence = CvProfileOutput(
        document_type="cv",
        languages=("en",),
        skills=(
            CvSkillClaim(
                claim_id="skill_python",
                statement="Python",
                assertion_kind="explicit",
                evidence=(SourceSpan(start=0, end=6, quote="Pyth0n"),),
                name="Python",
                category="programming_language",
            ),
        ),
    )
    with pytest.raises(ValueError, match="quote_mismatch"):
        await profiles.store_model_profile(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            _result(invalid_evidence),
            "invalid-profile-evidence",
        )

    wrong_release = _result()
    wrong_release = ModelGatewayResult(
        output=wrong_release.output,
        model_release=wrong_release.model_release,
        prompt_release=PromptReleaseIdentity(
            prompt_id=wrong_release.prompt_release.prompt_id,
            prompt_version=wrong_release.prompt_release.prompt_version,
            schema_id="job-description-profile",
            schema_version=wrong_release.prompt_release.schema_version,
        ),
        instructions_sha256=wrong_release.instructions_sha256,
        output_schema_sha256=wrong_release.output_schema_sha256,
        attempts=wrong_release.attempts,
    )
    with pytest.raises(CandidateProfileConflictError, match="profile release"):
        await profiles.store_model_profile(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            wrong_release,
            "wrong-profile-release",
        )

    corrected = await source_texts.append_correction(
        account_id,
        preparation_id,
        document_version_id,
        "Python backend engineer with corrected details",
        1,
        "profile-source-correction",
    )
    assert corrected.latest_version_number == 2
    with pytest.raises(CandidateProfileConflictError, match="latest source revision"):
        await profiles.store_model_profile(
            account_id,
            preparation_id,
            document_version_id,
            source_version_id,
            _result(),
            "stale-profile-source",
        )

    async with database.transaction() as session:
        assert (
            await session.scalar(
                select(CandidateProfile).where(CandidateProfile.owner_id == account_id)
            )
            is None
        )
    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="candidate-profile-evidence-cleanup",
    )


@pytest.mark.asyncio
async def test_privacy_export_includes_decrypted_profile_with_release_metadata(
    database: Database,
) -> None:
    account_id, preparation_id, files, asset, _, stored_source = await _source_revision(
        database,
        "profile-export",
    )
    document_version_id = stored_source.source_text.document_version_id
    source_version_id = stored_source.source_text.versions[0].text_version_id
    profiles = CandidateProfileService(database, _application_keyring())
    stored = await profiles.store_model_profile(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        _changed_result("Exported Python evidence"),
        "profile-export-store",
    )
    corrected_output = _changed_result("Owner-corrected exported Python evidence").output
    corrected = await profiles.append_correction(
        account_id,
        preparation_id,
        document_version_id,
        source_version_id,
        corrected_output,
        1,
        "profile-export-correction",
    )

    privacy = PrivacyLifecycleService(
        database=database,
        registry=build_default_jurisdiction_registry(),
        subject_hmac_key=b"candidate-profile-export-hmac-key" * 2,
        candidate_profile_lifecycle=profiles,
    )
    exported = await privacy.create_request(
        account_id,
        "export",
        "candidate-profile-export-key",
        "candidate-profile-export",
    )
    assert exported.data is not None
    assert exported.data["schema_version"] == "phase-1b-c2"
    entries = exported.data["candidate_profiles"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["profile_id"] == str(stored.candidate_profile.profile_id)
    assert entry["source_text_version_id"] == str(source_version_id)
    assert entry["document_type"] == "cv"
    exported_version = entry["versions"][0]
    assert exported_version["model_provider"] == "test-provider"
    assert exported_version["schema_id"] == "cv-profile"
    assert exported_version["profile"]["skills"][0]["statement"] == ("Exported Python evidence")
    assert len(entry["versions"]) == 2
    assert entry["versions"][1]["origin"] == "user_correction"
    assert entry["versions"][1]["profile"]["skills"][0]["statement"] == (
        "Owner-corrected exported Python evidence"
    )
    assert corrected.latest_version_number == 2

    await _delete_test_assets(
        database,
        files,
        {asset.id},
        worker_id="candidate-profile-export-cleanup",
    )
