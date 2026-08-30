from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from uuid6 import uuid7

from ai_interviewer.candidate_inputs import extraction_worker as worker_module
from ai_interviewer.candidate_inputs.extraction_jobs import (
    CandidateExtractionJobRecord,
    CandidateExtractionJobRuntime,
    ScheduleExtractionResult,
)
from ai_interviewer.candidate_inputs.extraction_models import (
    RETRYABLE_EXTRACTION_FAILURES,
    ExtractionFailureCode,
)
from ai_interviewer.candidate_inputs.extraction_worker import (
    CandidateExtractionWorker,
    FileParserSource,
)
from ai_interviewer.candidate_inputs.source_texts import (
    CandidateSourceTextConflictError,
    CandidateSourceTextRecord,
    CandidateSourceTextRuntime,
    CandidateSourceTextVersionRecord,
    ParserExecutionIdentity,
    StoreParserExtractionResult,
)
from ai_interviewer.extraction_runtime.isolation import IsolationExecutionError
from ai_interviewer.file_security.lifecycle import FileStateConflictError


def _job_record(**overrides: object) -> CandidateExtractionJobRecord:
    now = datetime(2026, 8, 29, tzinfo=UTC)
    defaults: dict[str, object] = {
        "job_id": uuid7(),
        "owner_id": uuid7(),
        "document_version_id": uuid7(),
        "file_asset_id": uuid7(),
        "parser_release_policy_id": uuid7(),
        "privacy_policy_version_id": uuid7(),
        "retention_rule_id": uuid7(),
        "jurisdiction_code": "AZ",
        "legal_basis": "consent",
        "retain_until": datetime(2027, 8, 29, tzinfo=UTC),
        "media_type": "text/plain",
        "content_length": 128,
        "content_sha256": "a" * 64,
        "parser_adapter": "isolated-text-parser",
        "parser_version": "1",
        "isolation_profile": "no-network-readonly-v1",
        "status": "processing",
        "attempts": 1,
        "available_at": now,
        "locked_at": now,
        "locked_by": "worker-1",
        "lease_token": uuid7(),
        "error_code": None,
        "source_text_id": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return CandidateExtractionJobRecord(**defaults)  # type: ignore[arg-type]


@dataclass
class FakeExtractionJobRuntime(CandidateExtractionJobRuntime):
    jobs: list[CandidateExtractionJobRecord]
    succeeded: list[tuple[UUID, str, UUID, UUID]] = field(default_factory=list)
    failed: list[tuple[UUID, str, UUID, str]] = field(default_factory=list)

    async def schedule_extraction(
        self,
        account_id: UUID,
        document_version_id: UUID,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> ScheduleExtractionResult:
        raise NotImplementedError

    async def claim_jobs(
        self,
        worker_id: str,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> tuple[CandidateExtractionJobRecord, ...]:
        return tuple(self.jobs[:limit])

    async def mark_succeeded(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        source_text_id: UUID,
        *,
        now: datetime | None = None,
    ) -> CandidateExtractionJobRecord:
        self.succeeded.append((job_id, worker_id, lease_token, source_text_id))
        return self._update(
            job_id,
            status="succeeded",
            source_text_id=source_text_id,
            error_code=None,
            lease_token=None,
            locked_by=None,
        )

    async def mark_failed(
        self,
        job_id: UUID,
        worker_id: str,
        lease_token: UUID,
        error_code: ExtractionFailureCode,
        *,
        now: datetime | None = None,
    ) -> CandidateExtractionJobRecord:
        self.failed.append((job_id, worker_id, lease_token, error_code))
        retry = error_code in RETRYABLE_EXTRACTION_FAILURES
        return self._update(
            job_id,
            status="retry" if retry else "failed",
            error_code=error_code,
            lease_token=None,
            locked_by=None,
        )

    def _update(self, job_id: UUID, **changes: object) -> CandidateExtractionJobRecord:
        index = next(i for i, job in enumerate(self.jobs) if job.job_id == job_id)
        updated = replace(self.jobs[index], **changes)  # type: ignore[arg-type]
        self.jobs[index] = updated
        return updated


@dataclass
class FakeFileParserSource(FileParserSource):
    content: bytes | None = None
    error: Exception | None = None
    calls: list[tuple[UUID, UUID, str, str, str]] = field(default_factory=list)

    async def read_for_parser(
        self,
        *,
        account_id: UUID,
        file_asset_id: UUID,
        parser_adapter: str,
        parser_version: str,
        isolation_profile: str,
        now: datetime | None = None,
    ) -> bytes:
        self.calls.append(
            (account_id, file_asset_id, parser_adapter, parser_version, isolation_profile)
        )
        if self.error is not None:
            raise self.error
        assert self.content is not None
        return self.content


@dataclass
class FakeSourceTextRuntime(CandidateSourceTextRuntime):
    error: Exception | None = None
    calls: list[tuple[UUID, UUID, str, ParserExecutionIdentity]] = field(default_factory=list)

    async def store_parser_extraction(
        self,
        account_id: UUID,
        document_version_id: UUID,
        content: str,
        parser: ParserExecutionIdentity,
        request_id: str | None,
        *,
        now: datetime | None = None,
    ) -> StoreParserExtractionResult:
        self.calls.append((account_id, document_version_id, content, parser))
        if self.error is not None:
            raise self.error
        created_at = datetime(2026, 8, 29, tzinfo=UTC)
        source_text_id = uuid7()
        version = CandidateSourceTextVersionRecord(
            text_version_id=uuid7(),
            version_number=1,
            origin="parser_extraction",
            previous_version_id=None,
            parser_release_policy_id=parser.parser_release_policy_id,
            parser_adapter=parser.parser_adapter,
            parser_version=parser.parser_version,
            isolation_profile=parser.isolation_profile,
            character_count=len(content),
            utf8_byte_count=len(content.encode()),
            line_count=content.count("\n") + 1,
            created_at=created_at,
            content=content,
        )
        record = CandidateSourceTextRecord(
            source_text_id=source_text_id,
            document_version_id=document_version_id,
            latest_version_number=1,
            aggregate_version=1,
            created_at=created_at,
            updated_at=created_at,
            versions=(version,),
        )
        return StoreParserExtractionResult(source_text=record, created=True)

    async def get_source_text(
        self,
        account_id: UUID,
        document_version_id: UUID,
    ) -> CandidateSourceTextRecord:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_worker_processes_a_claimed_job_to_success(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _job_record()
    jobs = FakeExtractionJobRuntime(jobs=[job])
    files = FakeFileParserSource(content=b"hello world")
    source_texts = FakeSourceTextRuntime()
    monkeypatch.setattr(
        worker_module,
        "run_isolated_extraction",
        lambda adapter, version, content, *, limits: "hello world",
    )
    worker = CandidateExtractionWorker(jobs, files, source_texts, worker_id="worker-1")

    outcomes = await worker.run_once(limit=1)

    assert len(outcomes) == 1
    assert outcomes[0].status == "succeeded"
    assert outcomes[0].error_code is None
    assert len(jobs.succeeded) == 1
    assert jobs.succeeded[0][1] == "worker-1"
    assert files.calls[0][2:] == (job.parser_adapter, job.parser_version, job.isolation_profile)
    assert source_texts.calls[0][2] == "hello world"


@pytest.mark.asyncio
async def test_worker_maps_read_failure_to_source_unavailable() -> None:
    job = _job_record()
    jobs = FakeExtractionJobRuntime(jobs=[job])
    files = FakeFileParserSource(error=FileStateConflictError("file is not released"))
    source_texts = FakeSourceTextRuntime()
    worker = CandidateExtractionWorker(jobs, files, source_texts, worker_id="worker-1")

    outcomes = await worker.run_once(limit=1)

    assert outcomes[0].error_code == "source_unavailable"
    assert outcomes[0].status == "retry"
    assert jobs.failed == [(job.job_id, "worker-1", job.lease_token, "source_unavailable")]
    assert source_texts.calls == []


@pytest.mark.asyncio
async def test_worker_maps_isolation_failure_to_its_closed_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _job_record()
    jobs = FakeExtractionJobRuntime(jobs=[job])
    files = FakeFileParserSource(content=b"not a real pdf")
    source_texts = FakeSourceTextRuntime()

    def _raise(adapter: str, version: str, content: bytes, *, limits: object) -> str:
        raise IsolationExecutionError("input_corrupt")

    monkeypatch.setattr(worker_module, "run_isolated_extraction", _raise)
    worker = CandidateExtractionWorker(jobs, files, source_texts, worker_id="worker-1")

    outcomes = await worker.run_once(limit=1)

    assert outcomes[0].error_code == "input_corrupt"
    assert outcomes[0].status == "failed"
    assert source_texts.calls == []


@pytest.mark.asyncio
async def test_worker_maps_source_text_conflict_to_policy_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _job_record()
    jobs = FakeExtractionJobRuntime(jobs=[job])
    files = FakeFileParserSource(content=b"hello world")
    source_texts = FakeSourceTextRuntime(
        error=CandidateSourceTextConflictError("policy changed"),
    )
    monkeypatch.setattr(
        worker_module,
        "run_isolated_extraction",
        lambda adapter, version, content, *, limits: "hello world",
    )
    worker = CandidateExtractionWorker(jobs, files, source_texts, worker_id="worker-1")

    outcomes = await worker.run_once(limit=1)

    assert outcomes[0].error_code == "policy_unavailable"
    assert outcomes[0].status == "failed"
    assert jobs.succeeded == []


@pytest.mark.asyncio
async def test_worker_processes_multiple_claimed_jobs_in_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _job_record()
    second = _job_record()
    jobs = FakeExtractionJobRuntime(jobs=[first, second])
    files = FakeFileParserSource(content=b"content")
    source_texts = FakeSourceTextRuntime()
    monkeypatch.setattr(
        worker_module,
        "run_isolated_extraction",
        lambda adapter, version, content, *, limits: "content",
    )
    worker = CandidateExtractionWorker(jobs, files, source_texts, worker_id="worker-1")

    outcomes = await worker.run_once(limit=2)

    assert {outcome.job_id for outcome in outcomes} == {first.job_id, second.job_id}
    assert all(outcome.status == "succeeded" for outcome in outcomes)


@pytest.mark.asyncio
async def test_worker_refuses_a_claimed_job_without_a_lease_token() -> None:
    job = _job_record(lease_token=None)
    jobs = FakeExtractionJobRuntime(jobs=[job])
    files = FakeFileParserSource(content=b"content")
    source_texts = FakeSourceTextRuntime()
    worker = CandidateExtractionWorker(jobs, files, source_texts, worker_id="worker-1")

    with pytest.raises(RuntimeError, match="lease token"):
        await worker.run_once(limit=1)
