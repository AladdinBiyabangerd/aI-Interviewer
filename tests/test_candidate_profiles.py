import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring, KeyringError
from ai_interviewer.model_gateway import (
    ModelGatewayResult,
    ModelReleaseIdentity,
    PromptReleaseIdentity,
)
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.profiling import (
    CV_PROFILE_SCHEMA_ID,
    PROFILE_SCHEMA_VERSION,
    CandidateProfileOutput,
    CandidateProfileRecord,
    CandidateProfileService,
    CandidateProfileUnavailableError,
    CvProfileOutput,
    CvSkillClaim,
    FailClosedCandidateProfileService,
    SourceSpan,
    build_candidate_profiles,
)
from tests.fakes import ReadyDatabase


def _keyring_document() -> str:
    def entry(key_id: str, purpose: str, marker: bytes) -> dict[str, str]:
        return {
            "id": key_id,
            "purpose": purpose,
            "material": base64.b64encode(marker * 32).decode(),
        }

    return json.dumps(
        {
            "version": 1,
            "active": {
                "field_encryption": "field-v1",
                "manifest_hmac": "manifest-v1",
                "subject_hmac": "subject-v1",
            },
            "keys": [
                entry("field-v1", "field_encryption", b"f"),
                entry("manifest-v1", "manifest_hmac", b"m"),
                entry("subject-v1", "subject_hmac", b"s"),
            ],
        }
    )


def _profile(statement: str = "Python") -> CvProfileOutput:
    return CvProfileOutput(
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


def _result(
    profile: CandidateProfileOutput | None = None,
    *,
    attempts: int = 1,
    instructions_sha256: str = "a" * 64,
) -> ModelGatewayResult[CandidateProfileOutput]:
    return ModelGatewayResult(
        output=profile or _profile(),
        model_release=ModelReleaseIdentity(
            provider="test-provider",
            model_id="profile-model",
            model_version="2026-08-31",
        ),
        prompt_release=PromptReleaseIdentity(
            prompt_id="cv-profile-prompt",
            prompt_version="1.0.0",
            schema_id=CV_PROFILE_SCHEMA_ID,
            schema_version=PROFILE_SCHEMA_VERSION,
        ),
        instructions_sha256=instructions_sha256,
        output_schema_sha256="b" * 64,
        attempts=attempts,
    )


def _service(keyring: ApplicationKeyring | None = None) -> CandidateProfileService:
    return CandidateProfileService(
        cast(DatabaseRuntime, ReadyDatabase()),
        keyring or ApplicationKeyring.from_secret(SecretStr(_keyring_document())),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "message"),
    [
        (_result(attempts=0), "attempts"),
        (_result(instructions_sha256="A" * 64), "instructions_sha256"),
    ],
)
async def test_invalid_gateway_metadata_fails_before_database_access(
    result: ModelGatewayResult[CandidateProfileOutput],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        await _service().store_model_profile(
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            result,
            None,
        )


@pytest.mark.asyncio
async def test_invalid_correction_type_fails_before_database_access() -> None:
    with pytest.raises(TypeError, match="corrected_profile"):
        await _service().append_correction(
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            cast(CandidateProfileOutput, object()),
            1,
            None,
        )


def test_profile_retry_helpers_fail_closed_for_missing_or_unreadable_lineage() -> None:
    service = _service()
    empty_record = cast(CandidateProfileRecord, SimpleNamespace(versions=()))
    assert service._same_model_result(empty_record, _result()) is False

    canonical = service._canonical_profile_json(_profile())
    profile, version = _stored_profile_version(canonical)
    version.origin = "model_generation"
    assert (
        service._is_repeat_correction(
            profile,
            version,
            "Python",
            _profile(),
            2,
        )
        is False
    )

    version.origin = "user_correction"
    version.version_number = 2
    unreadable = _service(cast(ApplicationKeyring, _FixedKeyring(None, fail=True)))
    assert (
        unreadable._is_repeat_correction(
            profile,
            version,
            "Python",
            _profile(),
            2,
        )
        is False
    )


class _FixedKeyring:
    def __init__(self, plaintext: str | None, *, fail: bool = False) -> None:
        self._plaintext = plaintext
        self._fail = fail

    def decrypt_field(self, _encrypted: object, *, aad: bytes) -> str:
        del aad
        if self._fail:
            raise KeyringError("synthetic failure")
        assert self._plaintext is not None
        return self._plaintext

    def verify_hmac(
        self,
        _purpose: str,
        *,
        key_id: str,
        data: bytes,
        digest: str,
    ) -> bool:
        del key_id, data, digest
        return False


def _stored_profile_version(
    profile_json: str,
) -> tuple[SimpleNamespace, SimpleNamespace]:
    now = datetime.now(UTC)
    profile = SimpleNamespace(
        id=uuid4(),
        owner_id=uuid4(),
        source_text_id=uuid4(),
        source_text_version_id=uuid4(),
        document_version_id=uuid4(),
        document_type="cv",
        privacy_policy_version_id=uuid4(),
        retention_rule_id=uuid4(),
        jurisdiction_code="AZERBAIJAN",
        legal_basis="contract",
        retain_until=now + timedelta(days=1),
        retention_action="delete",
    )
    version = SimpleNamespace(
        id=uuid4(),
        profile_id=profile.id,
        version_number=1,
        origin="model_generation",
        previous_version_id=None,
        schema_id=CV_PROFILE_SCHEMA_ID,
        schema_version=PROFILE_SCHEMA_VERSION,
        model_provider="test-provider",
        model_id="profile-model",
        model_version="2026-08-31",
        prompt_id="cv-profile-prompt",
        prompt_version="1.0.0",
        instructions_sha256="a" * 64,
        output_schema_sha256="b" * 64,
        model_attempts=1,
        claim_count=1,
        evidence_span_count=1,
        evidence_character_count=6,
        profile_json_utf8_bytes=len(profile_json.encode()),
        profile_digest="c" * 64,
        profile_digest_key_id="subject-v1",
        profile_encryption_key_id="field-v1",
        profile_nonce=b"n" * 12,
        profile_ciphertext=b"ciphertext",
        created_at=now,
    )
    return profile, version


@pytest.mark.parametrize(
    ("keyring", "plaintext", "message"),
    [
        (_FixedKeyring(None, fail=True), None, "decryption"),
        (_FixedKeyring("not-json"), "not-json", "schema"),
        (_FixedKeyring("{}"), "{}", "schema"),
    ],
)
def test_profile_decryption_and_schema_fail_closed(
    keyring: _FixedKeyring,
    plaintext: str | None,
    message: str,
) -> None:
    stored_json = plaintext or _service()._canonical_profile_json(_profile())
    profile, version = _stored_profile_version(stored_json)
    service = _service(cast(ApplicationKeyring, keyring))

    with pytest.raises(CandidateProfileUnavailableError, match=message):
        service._version_record(profile, version, "Python")


def test_profile_integrity_failure_is_payload_safe() -> None:
    canonical = _service()._canonical_profile_json(_profile())
    profile, version = _stored_profile_version(canonical)
    service = _service(cast(ApplicationKeyring, _FixedKeyring(canonical)))

    with pytest.raises(CandidateProfileUnavailableError, match="integrity") as exc:
        service._version_record(profile, version, "Python")
    assert "Python" not in repr(exc.value)


def _processable_snapshot() -> tuple[SimpleNamespace, ...]:
    now = datetime.now(UTC)
    policy_id = uuid4()
    preparation = SimpleNamespace(
        status="draft",
        retain_until=now + timedelta(days=1),
        retention_action="delete",
        privacy_policy_version_id=policy_id,
        jurisdiction_code="AZERBAIJAN",
    )
    document = SimpleNamespace(latest_version_number=1)
    document_version = SimpleNamespace(
        id=uuid4(),
        version_number=1,
        retain_until=now + timedelta(days=1),
        privacy_policy_version_id=policy_id,
        jurisdiction_code="AZERBAIJAN",
    )
    source_text = SimpleNamespace(
        document_version_id=document_version.id,
        latest_version_number=2,
    )
    source_version = SimpleNamespace(version_number=2)
    return preparation, document, document_version, source_text, source_version


@pytest.mark.parametrize(
    ("target", "attribute", "value", "message"),
    [
        (0, "status", "archived", "archived"),
        (1, "latest_version_number", 2, "latest document"),
        (2, "retain_until", datetime.min.replace(tzinfo=UTC), "retention deadline"),
        (4, "version_number", 1, "latest source"),
    ],
)
def test_processable_lineage_rejects_stale_or_expired_state(
    target: int,
    attribute: str,
    value: object,
    message: str,
) -> None:
    snapshot = _processable_snapshot()
    setattr(snapshot[target], attribute, value)

    with pytest.raises(RuntimeError, match=message):
        CandidateProfileService._require_processable_lineage(
            *snapshot,
            datetime.now(UTC),
        )


@pytest.mark.asyncio
async def test_profile_builder_and_disabled_runtime_fail_closed() -> None:
    disabled = build_candidate_profiles(
        Settings(_env_file=None, environment="test"),
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(disabled, FailClosedCandidateProfileService)
    with pytest.raises(CandidateProfileUnavailableError):
        await disabled.store_model_profile(uuid4(), uuid4(), uuid4(), uuid4(), _result(), None)
    with pytest.raises(CandidateProfileUnavailableError):
        await disabled.get_profile(uuid4(), uuid4(), uuid4(), uuid4())
    with pytest.raises(CandidateProfileUnavailableError):
        await disabled.append_correction(
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
            _profile(),
            1,
            None,
        )
    assert (
        await disabled.export_account_profile_metadata(
            cast(object, object()),
            account_id=uuid4(),
        )
        == []
    )

    enabled_settings = Settings(_env_file=None, environment="test").model_copy(
        update={
            "privacy_enabled": True,
            "file_security_enabled": True,
            "privacy_keyring": SecretStr(_keyring_document()),
        }
    )
    enabled = build_candidate_profiles(
        enabled_settings,
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(enabled, CandidateProfileService)
