import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from ai_interviewer.core.config import Settings
from ai_interviewer.model_gateway import ModelReleaseIdentity, PromptReleaseIdentity
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.profiling import (
    MAX_PROFILING_ATTEMPTS,
    PROFILING_LEASE_SECONDS,
    RETRYABLE_PROFILING_FAILURES,
    CandidateProfilingJobConflictError,
    CandidateProfilingJobService,
    CandidateProfilingJobUnavailableError,
    CandidateProfilingReleaseSnapshot,
    FailClosedCandidateProfilingJobService,
    ProfilingFailureCode,
    build_candidate_profiling_jobs,
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


def _release(**overrides: object) -> CandidateProfilingReleaseSnapshot:
    values: dict[str, object] = {
        "model_release": ModelReleaseIdentity(
            provider="test-provider",
            model_id="profile-model",
            model_version="2026-09-01",
        ),
        "prompt_release": PromptReleaseIdentity(
            prompt_id="cv-profile-prompt",
            prompt_version="1.0.0",
            schema_id="cv-profile",
            schema_version="1.0.0",
        ),
        "processor_activity_id": uuid4(),
        "instructions_sha256": "a" * 64,
        "output_schema_sha256": "b" * 64,
        "max_output_tokens": 4_096,
    }
    values.update(overrides)
    return CandidateProfilingReleaseSnapshot(**values)  # type: ignore[arg-type]


def test_profiling_job_policy_and_release_snapshot_are_bounded() -> None:
    assert PROFILING_LEASE_SECONDS == 300
    assert MAX_PROFILING_ATTEMPTS == 5
    assert "provider_timeout" in RETRYABLE_PROFILING_FAILURES
    assert "invalid_output" not in RETRYABLE_PROFILING_FAILURES
    assert CandidateProfilingJobService._retry_delay(1) == timedelta(seconds=60)
    assert CandidateProfilingJobService._retry_delay(5) == timedelta(seconds=960)
    assert CandidateProfilingJobService._retry_delay(99) == timedelta(hours=1)
    assert _release().max_output_tokens == 4_096

    with pytest.raises(ValueError, match="instructions_sha256"):
        _release(instructions_sha256="not-a-digest")
    with pytest.raises(ValueError, match="output_schema_sha256"):
        _release(output_schema_sha256="A" * 64)
    with pytest.raises(ValueError, match="max_output_tokens"):
        _release(max_output_tokens=0)
    with pytest.raises(TypeError, match="model_release"):
        _release(model_release="unsafe")
    with pytest.raises(TypeError, match="processor_activity_id"):
        _release(processor_activity_id="unsafe")


def _processable_lineage() -> tuple[
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
]:
    now = datetime.now(UTC)
    document_version_id = uuid4()
    privacy_policy_id = uuid4()
    preparation = SimpleNamespace(
        status="draft",
        retain_until=now + timedelta(days=1),
        retention_action="delete",
        privacy_policy_version_id=privacy_policy_id,
        jurisdiction_code="AZERBAIJAN",
    )
    document = SimpleNamespace(latest_version_number=1, document_type="cv")
    document_version = SimpleNamespace(
        id=document_version_id,
        version_number=1,
        retain_until=now + timedelta(days=1),
        privacy_policy_version_id=privacy_policy_id,
        jurisdiction_code="AZERBAIJAN",
    )
    source_text = SimpleNamespace(
        document_version_id=document_version_id,
        latest_version_number=2,
    )
    source_version = SimpleNamespace(version_number=2)
    return preparation, document, document_version, source_text, source_version


@pytest.mark.parametrize(
    ("target", "attribute", "value", "message"),
    [
        ("preparation", "status", "archived", "archived"),
        (
            "preparation",
            "retain_until",
            datetime.min.replace(tzinfo=UTC),
            "privacy snapshot",
        ),
        ("document", "latest_version_number", 2, "latest document version"),
        (
            "document_version",
            "retain_until",
            datetime.min.replace(tzinfo=UTC),
            "retention deadline",
        ),
        ("source_text", "latest_version_number", 1, "latest source revision"),
    ],
)
def test_processable_lineage_rejects_stale_or_unsafe_input(
    target: str,
    attribute: str,
    value: object,
    message: str,
) -> None:
    preparation, document, document_version, source_text, source_version = _processable_lineage()
    objects = {
        "preparation": preparation,
        "document": document,
        "document_version": document_version,
        "source_text": source_text,
    }
    setattr(objects[target], attribute, value)
    with pytest.raises(CandidateProfilingJobConflictError, match=message):
        CandidateProfilingJobService._require_processable_lineage(
            preparation,
            document,
            document_version,
            source_text,
            source_version,
            datetime.now(UTC),
        )


def test_release_schema_must_match_document_type() -> None:
    CandidateProfilingJobService._require_release_matches_document(_release(), "cv")
    with pytest.raises(CandidateProfilingJobConflictError, match="document type"):
        CandidateProfilingJobService._require_release_matches_document(
            _release(
                prompt_release=PromptReleaseIdentity(
                    prompt_id="jd-profile-prompt",
                    prompt_version="1.0.0",
                    schema_id="job-description-profile",
                    schema_version="1.0.0",
                )
            ),
            "cv",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_id", ["", " worker ", "x" * 129])
async def test_claim_rejects_invalid_worker_before_database_access(worker_id: str) -> None:
    service = CandidateProfilingJobService(cast(DatabaseRuntime, ReadyDatabase()))
    with pytest.raises(ValueError, match="worker_id"):
        await service.claim_jobs(worker_id, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 101])
async def test_claim_rejects_invalid_limit_before_database_access(limit: int) -> None:
    service = CandidateProfilingJobService(cast(DatabaseRuntime, ReadyDatabase()))
    with pytest.raises(ValueError, match="limit"):
        await service.claim_jobs("profiling-worker", limit)


@pytest.mark.asyncio
async def test_failure_code_is_bounded_before_database_access() -> None:
    service = CandidateProfilingJobService(cast(DatabaseRuntime, ReadyDatabase()))
    with pytest.raises(ValueError, match="error_code"):
        await service.mark_failed(
            uuid4(),
            "profiling-worker",
            uuid4(),
            cast(ProfilingFailureCode, "unbounded"),
        )


@pytest.mark.asyncio
async def test_builder_and_disabled_runtime_fail_closed() -> None:
    disabled = build_candidate_profiling_jobs(
        Settings(_env_file=None, environment="test"),
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(disabled, FailClosedCandidateProfilingJobService)
    with pytest.raises(CandidateProfilingJobUnavailableError):
        await disabled.schedule_profiling(uuid4(), uuid4(), uuid4(), uuid4(), _release(), None)
    with pytest.raises(CandidateProfilingJobUnavailableError):
        await disabled.claim_jobs("profiling-worker", 1)
    with pytest.raises(CandidateProfilingJobUnavailableError):
        await disabled.get_profiling_job(uuid4(), uuid4(), uuid4(), uuid4())
    with pytest.raises(CandidateProfilingJobUnavailableError):
        await disabled.mark_succeeded(uuid4(), "profiling-worker", uuid4(), uuid4())
    with pytest.raises(CandidateProfilingJobUnavailableError):
        await disabled.mark_failed(uuid4(), "profiling-worker", uuid4(), "provider_rejected")
    assert (
        await disabled.export_account_profiling_job_metadata(
            cast(AsyncSession, object()),
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
    enabled = build_candidate_profiling_jobs(
        enabled_settings,
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(enabled, CandidateProfilingJobService)
