import base64
import json
from datetime import timedelta
from typing import cast
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_interviewer.candidate_inputs.extraction_jobs import (
    CandidateExtractionJobService,
    CandidateExtractionJobUnavailableError,
    FailClosedCandidateExtractionJobService,
    build_candidate_extraction_jobs,
)
from ai_interviewer.candidate_inputs.extraction_models import (
    EXTRACTION_LEASE_SECONDS,
    MAX_EXTRACTION_ATTEMPTS,
    RETRYABLE_EXTRACTION_FAILURES,
    ExtractionFailureCode,
)
from ai_interviewer.core.config import Settings
from ai_interviewer.core.crypto import ApplicationKeyring
from ai_interviewer.persistence.database import DatabaseRuntime
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


def test_extraction_job_policy_constants_are_bounded() -> None:
    assert EXTRACTION_LEASE_SECONDS == 300
    assert MAX_EXTRACTION_ATTEMPTS == 5
    assert "parser_timeout" in RETRYABLE_EXTRACTION_FAILURES
    assert "input_corrupt" not in RETRYABLE_EXTRACTION_FAILURES
    assert CandidateExtractionJobService._retry_delay(1) == timedelta(seconds=60)
    assert CandidateExtractionJobService._retry_delay(5) == timedelta(seconds=960)
    assert CandidateExtractionJobService._retry_delay(99) == timedelta(hours=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("worker_id", ["", " worker ", "x" * 129])
async def test_claim_rejects_invalid_worker_before_database_access(worker_id: str) -> None:
    with pytest.raises(ValueError, match="worker_id"):
        await CandidateExtractionJobService(cast(DatabaseRuntime, ReadyDatabase())).claim_jobs(
            worker_id,
            1,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 101])
async def test_claim_rejects_invalid_limit_before_database_access(limit: int) -> None:
    with pytest.raises(ValueError, match="limit"):
        await CandidateExtractionJobService(cast(DatabaseRuntime, ReadyDatabase())).claim_jobs(
            "parser-worker-1",
            limit,
        )


@pytest.mark.asyncio
async def test_failure_code_is_bounded_before_database_access() -> None:
    with pytest.raises(ValueError, match="error_code"):
        await CandidateExtractionJobService(cast(DatabaseRuntime, ReadyDatabase())).mark_failed(
            uuid4(),
            "parser-worker-1",
            uuid4(),
            cast(ExtractionFailureCode, "unbounded"),
        )


@pytest.mark.asyncio
async def test_builder_and_disabled_runtime_fail_closed() -> None:
    disabled = build_candidate_extraction_jobs(
        Settings(_env_file=None, environment="test"),
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(disabled, FailClosedCandidateExtractionJobService)
    with pytest.raises(CandidateExtractionJobUnavailableError):
        await disabled.claim_jobs("parser-worker-1", 1)

    enabled_settings = Settings(_env_file=None, environment="test").model_copy(
        update={
            "privacy_enabled": True,
            "file_security_enabled": True,
            "privacy_keyring": SecretStr(_keyring_document()),
        }
    )
    enabled = build_candidate_extraction_jobs(
        enabled_settings,
        cast(DatabaseRuntime, ReadyDatabase()),
    )
    assert isinstance(enabled, CandidateExtractionJobService)
    # Construction validates the same keyring that the D1 persistence boundary uses.
    ApplicationKeyring.from_secret(enabled_settings.privacy_keyring)  # type: ignore[arg-type]
