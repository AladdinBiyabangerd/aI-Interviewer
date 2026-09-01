from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ai_interviewer.api.routes.profiles import _raise_http
from ai_interviewer.core.config import Settings
from ai_interviewer.identity.service import Principal
from ai_interviewer.main import create_app
from ai_interviewer.persistence.database import DatabaseRuntime
from ai_interviewer.profiling import (
    CV_PROFILE_SCHEMA_ID,
    PROFILE_SCHEMA_VERSION,
    CandidateProfileNotFoundError,
    CandidateProfilePreconditionError,
    CandidateProfileRecord,
    CandidateProfileRuntime,
    CandidateProfileUnavailableError,
    CandidateProfileVersionRecord,
    CandidateProfilingJobNotFoundError,
    CandidateProfilingJobRecord,
    CandidateProfilingJobRuntime,
    CandidateProfilingJobUnavailableError,
    CvProfileOutput,
    CvSkillClaim,
    SourceSpan,
)
from tests.fakes import ReadyDatabase


class ControlledAuthentication:
    def __init__(self, principal: Principal) -> None:
        self.principal = principal

    async def authenticate(self, access_token: str, request_id: str | None) -> Principal:
        del access_token, request_id
        return self.principal


def _output(statement: str = "Python experience") -> CvProfileOutput:
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


def _profile_record(
    *,
    profile_id: UUID | None = None,
    source_text_version_id: UUID | None = None,
    aggregate_version: int = 1,
    output: CvProfileOutput | None = None,
) -> CandidateProfileRecord:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    resolved_profile_id = profile_id or uuid4()
    resolved_source_version_id = source_text_version_id or uuid4()
    version = CandidateProfileVersionRecord(
        profile_version_id=uuid4(),
        version_number=aggregate_version,
        origin="model_generation" if aggregate_version == 1 else "user_correction",
        previous_version_id=None if aggregate_version == 1 else uuid4(),
        schema_id=CV_PROFILE_SCHEMA_ID,
        schema_version=PROFILE_SCHEMA_VERSION,
        model_provider="test-provider" if aggregate_version == 1 else None,
        model_id="profile-model" if aggregate_version == 1 else None,
        model_version="2026-09-01" if aggregate_version == 1 else None,
        prompt_id="cv-profile-prompt" if aggregate_version == 1 else None,
        prompt_version="1.0.0" if aggregate_version == 1 else None,
        instructions_sha256="a" * 64 if aggregate_version == 1 else None,
        output_schema_sha256="b" * 64 if aggregate_version == 1 else None,
        model_attempts=1 if aggregate_version == 1 else None,
        claim_count=1,
        evidence_span_count=1,
        evidence_character_count=6,
        created_at=now,
        profile=output or _output(),
    )
    return CandidateProfileRecord(
        profile_id=resolved_profile_id,
        source_text_id=uuid4(),
        source_text_version_id=resolved_source_version_id,
        document_version_id=uuid4(),
        document_type="cv",
        latest_version_number=aggregate_version,
        aggregate_version=aggregate_version,
        privacy_policy_version_id=uuid4(),
        retention_rule_id=uuid4(),
        jurisdiction_code="AZERBAIJAN",
        legal_basis="contract",
        retain_until=now + timedelta(days=1),
        retention_action="delete",
        created_at=now,
        updated_at=now,
        versions=(version,),
    )


def _job_record(
    profile: CandidateProfileRecord,
    *,
    account_id: UUID,
    preparation_id: UUID,
    status: str = "succeeded",
) -> CandidateProfilingJobRecord:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    succeeded = status == "succeeded"
    terminal = status in {"succeeded", "dead_letter"}
    return CandidateProfilingJobRecord(
        job_id=uuid4(),
        owner_id=account_id,
        preparation_id=preparation_id,
        document_version_id=profile.document_version_id,
        source_text_id=profile.source_text_id,
        source_text_version_id=profile.source_text_version_id,
        processor_activity_id=uuid4(),
        document_type="cv",
        privacy_policy_version_id=profile.privacy_policy_version_id,
        retention_rule_id=profile.retention_rule_id,
        jurisdiction_code="AZERBAIJAN",
        legal_basis="contract",
        retain_until=profile.retain_until,
        retention_action="delete",
        model_provider="test-provider",
        model_id="profile-model",
        model_version="2026-09-01",
        prompt_id="cv-profile-prompt",
        prompt_version="1.0.0",
        schema_id=CV_PROFILE_SCHEMA_ID,
        schema_version=PROFILE_SCHEMA_VERSION,
        instructions_sha256="a" * 64,
        output_schema_sha256="b" * 64,
        max_output_tokens=4096,
        status=status,
        attempts=1 if status != "pending" else 0,
        available_at=now,
        locked_at=now if status == "processing" else None,
        locked_by="worker" if status == "processing" else None,
        lease_token=uuid4() if status == "processing" else None,
        error_code="invalid_output" if status == "dead_letter" else None,
        profile_id=profile.profile_id if succeeded else None,
        completed_at=now if terminal else None,
        created_at=now,
        updated_at=now,
    )


class ControlledProfiles:
    def __init__(
        self,
        item: CandidateProfileRecord,
        error: Exception | None = None,
    ) -> None:
        self.item = item
        self.error = error
        self.get_calls = 0
        self.correction_calls: list[tuple[UUID, int]] = []

    def _raise(self) -> None:
        if self.error is not None:
            raise self.error

    async def get_profile(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
    ) -> CandidateProfileRecord:
        del account_id, preparation_id
        assert document_version_id == self.item.document_version_id
        assert source_text_version_id == self.item.source_text_version_id
        self.get_calls += 1
        self._raise()
        return self.item

    async def append_correction(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
        corrected_profile: CvProfileOutput,
        expected_version: int,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> CandidateProfileRecord:
        del preparation_id, request_id, now
        assert document_version_id == self.item.document_version_id
        assert source_text_version_id == self.item.source_text_version_id
        self.correction_calls.append((account_id, expected_version))
        self._raise()
        replacement = _profile_record(
            profile_id=self.item.profile_id,
            source_text_version_id=self.item.source_text_version_id,
            aggregate_version=self.item.aggregate_version + 1,
            output=corrected_profile,
        )
        self.item = replace(
            replacement,
            source_text_id=self.item.source_text_id,
            document_version_id=document_version_id,
            privacy_policy_version_id=self.item.privacy_policy_version_id,
            retention_rule_id=self.item.retention_rule_id,
            retain_until=self.item.retain_until,
            created_at=self.item.created_at,
        )
        return self.item


class ControlledJobs:
    def __init__(
        self,
        item: CandidateProfilingJobRecord,
        error: Exception | None = None,
    ) -> None:
        self.item = item
        self.error = error

    async def get_profiling_job(
        self,
        account_id: UUID,
        preparation_id: UUID,
        document_version_id: UUID,
        source_text_version_id: UUID,
    ) -> CandidateProfilingJobRecord:
        assert account_id == self.item.owner_id
        assert preparation_id == self.item.preparation_id
        assert document_version_id == self.item.document_version_id
        assert source_text_version_id == self.item.source_text_version_id
        if self.error is not None:
            raise self.error
        return self.item


def _client(
    scopes: frozenset[str],
    profiles: ControlledProfiles,
    jobs: ControlledJobs,
) -> TestClient:
    return TestClient(
        create_app(
            Settings(_env_file=None, environment="test", allowed_hosts=("testserver",)),
            database=cast(DatabaseRuntime, ReadyDatabase()),
            authentication=ControlledAuthentication(Principal(jobs.item.owner_id, scopes)),
            candidate_profiles=cast(CandidateProfileRuntime, profiles),
            candidate_profiling_jobs=cast(CandidateProfilingJobRuntime, jobs),
        )
    )


def _path(job: CandidateProfilingJobRecord) -> str:
    return (
        f"/api/v1/preparations/{job.preparation_id}"
        f"/document-versions/{job.document_version_id}"
        f"/profiles/{job.source_text_version_id}"
    )


def _services(*, status: str = "succeeded") -> tuple[ControlledProfiles, ControlledJobs]:
    profile = _profile_record()
    account_id = uuid4()
    preparation_id = uuid4()
    return (
        ControlledProfiles(profile),
        ControlledJobs(
            _job_record(
                profile,
                account_id=account_id,
                preparation_id=preparation_id,
                status=status,
            )
        ),
    )


def test_get_profile_returns_safe_status_history_and_etag() -> None:
    profiles, jobs = _services()
    with _client(frozenset({"preparation:read"}), profiles, jobs) as client:
        response = client.get(
            _path(jobs.item),
            headers={"authorization": "Bearer valid"},
        )
    assert response.status_code == 200
    assert response.headers["etag"] == '"1"'
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["retryable"] is False
    assert body["profile"]["versions"][0]["profile"]["skills"][0]["name"] == "Python"
    assert "instructions_sha256" not in response.text


def test_get_pending_status_does_not_expose_uncommitted_profile() -> None:
    profiles, jobs = _services(status="pending")
    with _client(frozenset({"preparation:read"}), profiles, jobs) as client:
        response = client.get(
            _path(jobs.item),
            headers={"authorization": "Bearer valid"},
        )
    assert response.status_code == 200
    assert response.headers["retry-after"] == "5"
    assert "etag" not in response.headers
    assert response.json()["profile"] is None
    assert response.json()["retryable"] is True
    assert profiles.get_calls == 0


def test_get_dead_letter_status_is_terminal_and_content_free() -> None:
    profiles, jobs = _services(status="dead_letter")
    with _client(frozenset({"preparation:read"}), profiles, jobs) as client:
        response = client.get(
            _path(jobs.item),
            headers={"authorization": "Bearer valid"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "dead_letter"
    assert response.json()["error_code"] == "invalid_output"
    assert response.json()["retryable"] is False
    assert response.json()["profile"] is None
    assert "retry-after" not in response.headers


def test_get_profile_requires_scope_and_maps_owner_safe_not_found() -> None:
    profiles, jobs = _services()
    with _client(frozenset(), profiles, jobs) as client:
        forbidden = client.get(
            _path(jobs.item),
            headers={"authorization": "Bearer valid"},
        )
    assert forbidden.status_code == 403

    jobs.error = CandidateProfilingJobNotFoundError("private owner detail")
    with _client(frozenset({"preparation:read"}), profiles, jobs) as client:
        missing = client.get(
            _path(jobs.item),
            headers={"authorization": "Bearer valid"},
        )
    assert missing.status_code == 404
    assert "private" not in missing.text


def test_correction_requires_if_match_and_appends_history() -> None:
    profiles, jobs = _services()
    headers = {"authorization": "Bearer valid"}
    payload = {"profile": _output("Corrected Python experience").model_dump(mode="json")}
    with _client(frozenset({"preparation:write"}), profiles, jobs) as client:
        missing = client.put(_path(jobs.item), json=payload, headers=headers)
        malformed = client.put(
            _path(jobs.item),
            json=payload,
            headers={**headers, "If-Match": "1"},
        )
        applied = client.put(
            _path(jobs.item),
            json=payload,
            headers={**headers, "If-Match": '"1"'},
        )
    assert missing.status_code == 428
    assert malformed.status_code == 400
    assert applied.status_code == 200
    assert applied.headers["etag"] == '"2"'
    assert applied.json()["profile"]["versions"][0]["origin"] == "user_correction"
    assert profiles.correction_calls == [(jobs.item.owner_id, 1)]


def test_correction_requires_completed_job_and_maps_precondition() -> None:
    profiles, jobs = _services(status="processing")
    payload = {"profile": _output().model_dump(mode="json")}
    headers = {"authorization": "Bearer valid", "If-Match": '"1"'}
    with _client(frozenset({"preparation:write"}), profiles, jobs) as client:
        processing = client.put(_path(jobs.item), json=payload, headers=headers)
    assert processing.status_code == 409
    assert profiles.correction_calls == []

    profiles, jobs = _services()
    profiles.error = CandidateProfilePreconditionError("private stale detail")
    with _client(frozenset({"preparation:write"}), profiles, jobs) as client:
        stale = client.put(_path(jobs.item), json=payload, headers=headers)
    assert stale.status_code == 412
    assert "private" not in stale.text


def test_correction_requires_scope_and_strict_profile_body() -> None:
    profiles, jobs = _services()
    headers = {"authorization": "Bearer valid", "If-Match": '"1"'}
    with _client(frozenset({"preparation:read"}), profiles, jobs) as client:
        forbidden = client.put(
            _path(jobs.item),
            json={"profile": _output().model_dump(mode="json")},
            headers=headers,
        )
    assert forbidden.status_code == 403

    with _client(frozenset({"preparation:write"}), profiles, jobs) as client:
        invalid = client.put(
            _path(jobs.item),
            json={"profile": {"document_type": "cv", "languages": ["en"]}},
            headers=headers,
        )
    assert invalid.status_code == 422
    assert profiles.correction_calls == []


def test_succeeded_job_with_missing_profile_is_opaque() -> None:
    profiles, jobs = _services()
    profiles.error = CandidateProfileNotFoundError("private missing profile")
    with _client(frozenset({"preparation:read"}), profiles, jobs) as client:
        response = client.get(
            _path(jobs.item),
            headers={"authorization": "Bearer valid"},
        )
    assert response.status_code == 404
    assert "private" not in response.text


def test_profile_unavailability_and_result_mismatch_fail_closed() -> None:
    profiles, jobs = _services()
    profiles.error = CandidateProfileUnavailableError("private decryption detail")
    with _client(frozenset({"preparation:read"}), profiles, jobs) as client:
        unavailable = client.get(
            _path(jobs.item),
            headers={"authorization": "Bearer valid"},
        )
    assert unavailable.status_code == 503
    assert "private" not in unavailable.text

    profiles, jobs = _services()
    profiles.item = replace(profiles.item, profile_id=uuid4())
    with _client(frozenset({"preparation:read"}), profiles, jobs) as client:
        mismatch = client.get(
            _path(jobs.item),
            headers={"authorization": "Bearer valid"},
        )
    assert mismatch.status_code == 503


def test_job_unavailability_and_unknown_internal_error_mapping() -> None:
    profiles, jobs = _services()
    jobs.error = CandidateProfilingJobUnavailableError("private database detail")
    with _client(frozenset({"preparation:read"}), profiles, jobs) as client:
        unavailable = client.get(
            _path(jobs.item),
            headers={"authorization": "Bearer valid"},
        )
    assert unavailable.status_code == 503
    assert "private" not in unavailable.text

    internal = RuntimeError("internal marker")
    with pytest.raises(RuntimeError, match="internal marker"):
        _raise_http(internal)


def test_correction_rejects_unsupported_document_type_and_result_mismatch() -> None:
    profiles, jobs = _services()
    headers = {"authorization": "Bearer valid", "If-Match": '"1"'}
    with _client(frozenset({"preparation:write"}), profiles, jobs) as client:
        unsupported = client.put(
            _path(jobs.item),
            json={"profile": {"document_type": "resume"}},
            headers=headers,
        )
    assert unsupported.status_code == 422
    assert profiles.correction_calls == []

    profiles, jobs = _services()
    profiles.item = replace(profiles.item, profile_id=uuid4())
    with _client(frozenset({"preparation:write"}), profiles, jobs) as client:
        mismatch = client.put(
            _path(jobs.item),
            json={"profile": _output().model_dump(mode="json")},
            headers=headers,
        )
    assert mismatch.status_code == 503
