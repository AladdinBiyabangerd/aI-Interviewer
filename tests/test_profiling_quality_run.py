import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_interviewer.model_gateway import (
    DisabledModelGateway,
    ModelGatewayPolicy,
    ModelGatewayRequest,
    ModelGatewayResult,
    ModelProviderError,
    ModelProviderRequest,
    ModelProviderResponse,
    ModelReleaseIdentity,
    StructuredModelGateway,
)
from ai_interviewer.profiling.contracts import CvProfileOutput, CvSkillClaim, SourceSpan
from ai_interviewer.profiling.quality import (
    ClaimAdjudication,
    ProfileQualityEvidence,
    QualityProvenance,
    profile_quality_prompt_contract_sha256,
)
from ai_interviewer.profiling.quality_cli import main
from ai_interviewer.profiling.quality_run import (
    ProfileQualityCorpus,
    ProfileQualityCorpusFixture,
    ProfileQualityPredictionRecord,
    ProfileQualityPredictionRun,
    ProfileQualityRunAuthorization,
    finalize_profile_quality_review,
    generate_profile_quality_predictions,
    load_profile_quality_corpus,
    load_profile_quality_review_draft,
    preflight_profile_quality_run,
    prepare_profile_quality_review_draft,
    profile_quality_corpus_sha256,
    profile_quality_run_authorization_sha256,
    write_private_quality_artifact,
)

_NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
_MODEL_RELEASE = ModelReleaseIdentity(
    provider="openai",
    model_id="gpt-5.1",
    model_version="2026-08-31",
)
_SOURCE = "Python project."


def _profile(source: str = _SOURCE, quote: str = "Python") -> CvProfileOutput:
    start = source.index(quote)
    return CvProfileOutput(
        document_type="cv",
        languages=("en",),
        skills=(
            CvSkillClaim(
                claim_id="skill_python",
                statement="Python skill",
                assertion_kind="explicit",
                evidence=(SourceSpan(start=start, end=start + len(quote), quote=quote),),
                name="Python",
                category="programming_language",
            ),
        ),
    )


def _corpus(*, prompt_digest: str | None = None) -> ProfileQualityCorpus:
    return ProfileQualityCorpus(
        schema_version=1,
        contract_version="1b-d-v1",
        policy_version="1.0.0",
        dataset_id="rights-cleared-corpus",
        dataset_version="1.0.0",
        prompt_contract_sha256=(prompt_digest or profile_quality_prompt_contract_sha256()),
        fixtures=(
            ProfileQualityCorpusFixture(
                fixture_id="fixture-1",
                language_slice="en",
                document_type="cv",
                risk_slices=("standard",),
                provenance=QualityProvenance(
                    source_kind="licensed",
                    rights_reference="license-review-1",
                    repository_safe=False,
                ),
                source_text=_SOURCE,
                expected_profile=_profile(),
            ),
        ),
    )


def _authorization(
    corpus: ProfileQualityCorpus,
    *,
    corpus_digest: str | None = None,
    model_release: ModelReleaseIdentity = _MODEL_RELEASE,
    approved_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> ProfileQualityRunAuthorization:
    return ProfileQualityRunAuthorization(
        schema_version=1,
        contract_version="1b-d-v1",
        purpose="profile_quality_evaluation",
        decision="approved",
        dataset_id=corpus.dataset_id,
        dataset_version=corpus.dataset_version,
        corpus_sha256=corpus_digest or profile_quality_corpus_sha256(corpus),
        prompt_contract_sha256=corpus.prompt_contract_sha256,
        model_release=model_release,
        processor_activity_reference="processor-approval-1",
        data_controls_reference="provider-controls-1",
        approver_id="privacy-owner",
        approved_at=approved_at or _NOW - timedelta(hours=1),
        expires_at=expires_at or _NOW + timedelta(hours=1),
    )


@dataclass
class RecordingProvider:
    outcomes: list[ModelProviderResponse | Exception]
    requests: list[ModelProviderRequest] = field(default_factory=list)

    async def generate(self, request: ModelProviderRequest) -> ModelProviderResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(profile: CvProfileOutput | None = None) -> ModelProviderResponse:
    return ModelProviderResponse(
        output_json=(profile or _profile()).model_dump_json(),
        model_release=_MODEL_RELEASE,
        finish_reason="stop",
    )


def _gateway(provider: RecordingProvider) -> StructuredModelGateway:
    return StructuredModelGateway(
        provider,
        _MODEL_RELEASE,
        ModelGatewayPolicy(
            attempt_timeout_seconds=1,
            max_attempts=1,
            retry_base_seconds=0,
            max_input_characters=10_000,
            max_output_characters=10_000,
        ),
    )


@pytest.mark.asyncio
async def test_authorized_prediction_run_is_reproducible_and_payload_safe() -> None:
    corpus = _corpus()
    authorization = _authorization(corpus)
    first_provider = RecordingProvider([_response()])
    second_provider = RecordingProvider([_response()])

    first = await generate_profile_quality_predictions(
        corpus,
        authorization,
        _gateway(first_provider),
        now=_NOW,
    )
    second = await generate_profile_quality_predictions(
        corpus,
        authorization,
        _gateway(second_provider),
        now=_NOW,
    )

    assert first == second
    assert first.status == "completed"
    assert first.fixtures[0].prediction.result_type == "profile"
    assert first_provider.requests[0].input_text == _SOURCE
    assert first_provider.requests[0].request_id == first.fixtures[0].request_id
    assert _SOURCE not in repr(corpus)
    assert _SOURCE not in repr(first)


def test_quality_run_preflight_is_provider_free_and_payload_safe() -> None:
    corpus = _corpus()
    authorization = _authorization(corpus)

    result = preflight_profile_quality_run(corpus, authorization, now=_NOW)

    assert result.status == "authorized"
    assert result.corpus_sha256 == profile_quality_corpus_sha256(corpus)
    assert result.authorization_sha256 == profile_quality_run_authorization_sha256(authorization)
    assert result.prompt_contract_sha256 == profile_quality_prompt_contract_sha256()
    assert result.model_release == authorization.model_release
    assert result.fixture_count == 1
    assert _SOURCE not in repr(result)
    assert authorization.approver_id not in result.model_dump_json()


@pytest.mark.asyncio
async def test_gateway_failure_becomes_a_bounded_prediction_record() -> None:
    corpus = _corpus()
    provider = RecordingProvider([ModelProviderError("provider_rejected")])

    run = await generate_profile_quality_predictions(
        corpus,
        _authorization(corpus),
        _gateway(provider),
        now=_NOW,
    )

    prediction = run.fixtures[0].prediction
    assert prediction.result_type == "failure"
    assert prediction.failure_code == "provider_rejected"
    assert prediction.attempts == 1


@pytest.mark.asyncio
async def test_evidence_mismatch_becomes_invalid_output() -> None:
    corpus = _corpus()
    ungrounded_profile = _profile("Go project.", "Go")

    run = await generate_profile_quality_predictions(
        corpus,
        _authorization(corpus),
        _gateway(RecordingProvider([_response(ungrounded_profile)])),
        now=_NOW,
    )

    prediction = run.fixtures[0].prediction
    assert prediction.result_type == "failure"
    assert prediction.failure_code == "invalid_output"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization_or_clock",
    (
        "corpus_mismatch",
        "corpus_prompt_drift",
        "authorization_prompt_drift",
        "expired",
        "future_approval",
        "naive_clock",
    ),
)
async def test_prediction_run_rejects_inactive_or_mismatched_authorization(
    authorization_or_clock: str,
) -> None:
    corpus = _corpus()
    authorization = _authorization(corpus)
    clock = _NOW
    if authorization_or_clock == "corpus_mismatch":
        authorization = _authorization(corpus, corpus_digest="0" * 64)
    elif authorization_or_clock == "corpus_prompt_drift":
        corpus = _corpus(prompt_digest="0" * 64)
        authorization = _authorization(corpus)
    elif authorization_or_clock == "authorization_prompt_drift":
        authorization = authorization.model_copy(update={"prompt_contract_sha256": "0" * 64})
    elif authorization_or_clock == "expired":
        authorization = _authorization(
            corpus,
            approved_at=_NOW - timedelta(hours=2),
            expires_at=_NOW - timedelta(hours=1),
        )
    elif authorization_or_clock == "future_approval":
        authorization = _authorization(
            corpus,
            approved_at=_NOW + timedelta(hours=1),
            expires_at=_NOW + timedelta(hours=2),
        )
    else:
        clock = _NOW.replace(tzinfo=None)
    provider = RecordingProvider([_response()])

    with pytest.raises(ValueError):
        await generate_profile_quality_predictions(
            corpus,
            authorization,
            _gateway(provider),
            now=clock,
        )

    assert provider.requests == []


@pytest.mark.asyncio
async def test_prediction_run_rejects_disabled_or_wrong_release_gateway() -> None:
    corpus = _corpus()
    authorization = _authorization(corpus)

    with pytest.raises(ValueError):
        await generate_profile_quality_predictions(
            corpus,
            authorization,
            DisabledModelGateway(),
            now=_NOW,
        )

    provider = RecordingProvider([_response()])
    wrong_gateway = StructuredModelGateway(
        provider,
        ModelReleaseIdentity(
            provider="openai",
            model_id="different-model",
            model_version="2026-08-31",
        ),
        ModelGatewayPolicy(max_attempts=1, retry_base_seconds=0),
    )
    with pytest.raises(ValueError):
        await generate_profile_quality_predictions(
            corpus,
            authorization,
            wrong_gateway,
            now=_NOW,
        )
    assert provider.requests == []


def test_corpus_rejects_duplicate_fixtures_and_bad_expected_evidence() -> None:
    corpus = _corpus()
    with pytest.raises(ValidationError):
        ProfileQualityCorpus(
            schema_version=1,
            contract_version="1b-d-v1",
            policy_version="1.0.0",
            dataset_id=corpus.dataset_id,
            dataset_version=corpus.dataset_version,
            prompt_contract_sha256=corpus.prompt_contract_sha256,
            fixtures=(corpus.fixtures[0], corpus.fixtures[0]),
        )

    with pytest.raises(ValidationError):
        ProfileQualityCorpusFixture(
            fixture_id="bad-evidence",
            language_slice="en",
            document_type="cv",
            risk_slices=("standard",),
            provenance=corpus.fixtures[0].provenance,
            source_text=_SOURCE,
            expected_profile=_profile("Go project.", "Go"),
        )


@pytest.mark.parametrize("invalid_shape", ("risk", "language", "document"))
def test_corpus_fixture_rejects_shape_mismatch(invalid_shape: str) -> None:
    corpus = _corpus()
    values: dict[str, object] = {
        "fixture_id": "bad-shape",
        "language_slice": "en",
        "document_type": "cv",
        "risk_slices": ("standard",),
        "provenance": corpus.fixtures[0].provenance,
        "source_text": _SOURCE,
        "expected_profile": _profile(),
    }
    if invalid_shape == "risk":
        values["risk_slices"] = ("standard", "standard")
    elif invalid_shape == "language":
        values["language_slice"] = "az"
    else:
        values["document_type"] = "job_description"

    with pytest.raises(ValidationError):
        ProfileQualityCorpusFixture(**values)  # type: ignore[arg-type]


def test_authorization_requires_openai_and_an_ordered_window() -> None:
    corpus = _corpus()
    with pytest.raises(ValidationError):
        _authorization(
            corpus,
            model_release=ModelReleaseIdentity(
                provider="another-provider",
                model_id="profile-model",
                model_version="2026-08-31",
            ),
        )
    with pytest.raises(ValidationError):
        _authorization(corpus, approved_at=_NOW, expires_at=_NOW)


@pytest.mark.asyncio
async def test_prediction_run_rejects_duplicate_fixture_and_request_ids() -> None:
    corpus = _corpus()
    run = await generate_profile_quality_predictions(
        corpus,
        _authorization(corpus),
        _gateway(RecordingProvider([_response()])),
        now=_NOW,
    )
    record = run.fixtures[0]
    run_values = run.model_dump(exclude={"fixtures"})

    with pytest.raises(ValidationError):
        ProfileQualityPredictionRun(**run_values, fixtures=(record, record))

    second_record = ProfileQualityPredictionRecord(
        fixture_id="fixture-2",
        document_type=record.document_type,
        request_id=record.request_id,
        prediction=record.prediction,
    )
    with pytest.raises(ValidationError):
        ProfileQualityPredictionRun(
            **run_values,
            fixtures=(record, second_record),
        )


@pytest.mark.asyncio
async def test_prediction_result_contract_drift_aborts_the_run() -> None:
    corpus = _corpus()

    class ContractDriftGateway:
        enabled = True

        @property
        def model_release(self) -> ModelReleaseIdentity:
            return _MODEL_RELEASE

        async def generate(
            self,
            request: ModelGatewayRequest,
            output_type: object,
        ) -> ModelGatewayResult[CvProfileOutput]:
            del output_type
            return ModelGatewayResult(
                output=_profile(),
                model_release=_MODEL_RELEASE,
                prompt_release=request.prompt_release,
                instructions_sha256="0" * 64,
                output_schema_sha256="0" * 64,
                attempts=1,
            )

    with pytest.raises(ValueError):
        await generate_profile_quality_predictions(
            corpus,
            _authorization(corpus),
            ContractDriftGateway(),  # type: ignore[arg-type]
            now=_NOW,
        )


@pytest.mark.asyncio
async def test_review_draft_requires_human_adjudication_before_evaluation() -> None:
    corpus = _corpus()
    run = await generate_profile_quality_predictions(
        corpus,
        _authorization(corpus),
        _gateway(RecordingProvider([_response()])),
        now=_NOW,
    )

    draft = prepare_profile_quality_review_draft(corpus, run)

    assert draft.fixtures[0].adjudications == ()
    assert draft.fixtures[0].owner_review_outcome == "not_reviewed"
    with pytest.raises(ValidationError):
        ProfileQualityEvidence.model_validate(draft.model_dump(), strict=True)


@pytest.mark.asyncio
async def test_completed_review_is_bound_to_exact_corpus_and_predictions() -> None:
    corpus = _corpus()
    run = await generate_profile_quality_predictions(
        corpus,
        _authorization(corpus),
        _gateway(RecordingProvider([_response()])),
        now=_NOW,
    )
    draft = prepare_profile_quality_review_draft(corpus, run)
    reviewed_fixture = draft.fixtures[0].model_copy(
        update={
            "adjudications": (
                ClaimAdjudication(
                    field="cv_skills",
                    expected_claim_id="skill_python",
                    predicted_claim_id="skill_python",
                ),
            ),
            "owner_review_outcome": "accepted",
        }
    )
    completed_review = draft.model_copy(update={"fixtures": (reviewed_fixture,)})

    evidence = finalize_profile_quality_review(corpus, run, completed_review)

    assert evidence.fixtures[0].adjudications == reviewed_fixture.adjudications
    assert evidence.fixtures[0].owner_review_outcome == "accepted"
    assert evidence.fixtures[0].prediction == run.fixtures[0].prediction
    assert _SOURCE not in repr(evidence)


@pytest.mark.asyncio
async def test_review_finalization_rejects_incomplete_or_mutated_review() -> None:
    corpus = _corpus()
    run = await generate_profile_quality_predictions(
        corpus,
        _authorization(corpus),
        _gateway(RecordingProvider([_response()])),
        now=_NOW,
    )
    draft = prepare_profile_quality_review_draft(corpus, run)

    with pytest.raises(ValueError, match="every owner outcome"):
        finalize_profile_quality_review(corpus, run, draft)

    changed_fixture = draft.fixtures[0].model_copy(update={"source_text": "Changed source."})
    changed_review = draft.model_copy(update={"fixtures": (changed_fixture,)})
    with pytest.raises(ValueError, match="immutable fixture content"):
        finalize_profile_quality_review(corpus, run, changed_review)

    mismatched_review = draft.model_copy(update={"dataset_version": "different-version"})
    with pytest.raises(ValueError, match="does not match corpus"):
        finalize_profile_quality_review(corpus, run, mismatched_review)

    incomplete_fixture = draft.fixtures[0].model_copy(update={"owner_review_outcome": "accepted"})
    incomplete_review = draft.model_copy(update={"fixtures": (incomplete_fixture,)})
    with pytest.raises(ValidationError, match="at least 1 item"):
        finalize_profile_quality_review(corpus, run, incomplete_review)


@pytest.mark.asyncio
async def test_review_draft_rejects_run_binding_and_record_drift() -> None:
    corpus = _corpus()
    run = await generate_profile_quality_predictions(
        corpus,
        _authorization(corpus),
        _gateway(RecordingProvider([_response()])),
        now=_NOW,
    )

    with pytest.raises(ValueError):
        prepare_profile_quality_review_draft(
            corpus,
            run.model_copy(update={"corpus_sha256": "0" * 64}),
        )
    with pytest.raises(ValueError):
        prepare_profile_quality_review_draft(
            corpus,
            run.model_copy(
                update={
                    "fixtures": (
                        run.fixtures[0].model_copy(update={"fixture_id": "other-fixture"}),
                    )
                }
            ),
        )
    with pytest.raises(ValueError):
        prepare_profile_quality_review_draft(
            corpus,
            run.model_copy(
                update={
                    "fixtures": (
                        run.fixtures[0].model_copy(update={"document_type": "job_description"}),
                    )
                }
            ),
        )


def test_private_artifact_writer_is_exclusive_and_load_is_strict(tmp_path: Path) -> None:
    corpus = _corpus()
    output = tmp_path / "corpus.json"

    digest = write_private_quality_artifact(output, corpus)

    assert len(digest) == 64
    assert load_profile_quality_corpus(output) == corpus
    with pytest.raises(FileExistsError):
        write_private_quality_artifact(output, corpus)
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"unexpected":true}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_profile_quality_corpus(invalid)


def test_private_artifact_writer_removes_its_partial_file_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "partial.json"

    def fail_fsync(descriptor: int) -> None:
        del descriptor
        raise OSError("simulated sync failure")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(OSError):
        write_private_quality_artifact(output, _corpus())
    assert not output.exists()


def test_generate_cli_requires_explicit_external_processing_confirmation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = _corpus()
    authorization = _authorization(corpus)
    corpus_path = tmp_path / "corpus.json"
    authorization_path = tmp_path / "authorization.json"
    output_path = tmp_path / "predictions.json"
    write_private_quality_artifact(corpus_path, corpus)
    write_private_quality_artifact(authorization_path, authorization)
    provider = RecordingProvider([_response()])

    status = main(
        ("generate", str(corpus_path), str(authorization_path), str(output_path)),
        gateway=_gateway(provider),
        now=_NOW,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert json.loads(captured.err) == {"error_type": "ValueError", "status": "invalid"}
    assert captured.out == ""
    assert provider.requests == []
    assert not output_path.exists()


def test_preflight_cli_needs_no_gateway_and_prints_only_safe_coordinates(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = _corpus()
    authorization = _authorization(corpus)
    corpus_path = tmp_path / "private-corpus.json"
    authorization_path = tmp_path / "private-authorization.json"
    write_private_quality_artifact(corpus_path, corpus)
    write_private_quality_artifact(authorization_path, authorization)

    status = main(
        ("preflight", str(corpus_path), str(authorization_path)),
        gateway=DisabledModelGateway(),
        now=_NOW,
    )

    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert status == 0
    assert captured.err == ""
    assert summary["status"] == "authorized"
    assert summary["fixture_count"] == 1
    assert summary["corpus_sha256"] == profile_quality_corpus_sha256(corpus)
    assert summary["model_release"] == authorization.model_release.model_dump(mode="json")
    assert _SOURCE not in captured.out
    assert authorization.approver_id not in captured.out
    assert str(corpus_path) not in captured.out
    assert str(authorization_path) not in captured.out


def test_preflight_cli_rejects_inactive_authorization_with_opaque_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = _corpus()
    authorization = _authorization(
        corpus,
        approved_at=_NOW - timedelta(hours=2),
        expires_at=_NOW - timedelta(hours=1),
    )
    corpus_path = tmp_path / "secret-corpus-name.json"
    authorization_path = tmp_path / "secret-authorization-name.json"
    write_private_quality_artifact(corpus_path, corpus)
    write_private_quality_artifact(authorization_path, authorization)

    status = main(("preflight", str(corpus_path), str(authorization_path)), now=_NOW)

    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {"error_type": "ValueError", "status": "invalid"}
    assert _SOURCE not in captured.err
    assert str(corpus_path) not in captured.err


def test_generate_cli_rejects_existing_output_before_provider_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = _corpus()
    authorization = _authorization(corpus)
    corpus_path = tmp_path / "corpus.json"
    authorization_path = tmp_path / "authorization.json"
    output_path = tmp_path / "existing.json"
    write_private_quality_artifact(corpus_path, corpus)
    write_private_quality_artifact(authorization_path, authorization)
    output_path.write_text("do not overwrite", encoding="utf-8")
    provider = RecordingProvider([_response()])

    status = main(
        (
            "generate",
            str(corpus_path),
            str(authorization_path),
            str(output_path),
            "--confirm-external-processing",
        ),
        gateway=_gateway(provider),
        now=_NOW,
    )

    captured = capsys.readouterr()
    assert status == 2
    assert json.loads(captured.err) == {
        "error_type": "FileExistsError",
        "status": "invalid",
    }
    assert provider.requests == []
    assert output_path.read_text(encoding="utf-8") == "do not overwrite"


def test_generate_and_prepare_review_cli_write_only_safe_summaries(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    corpus = _corpus()
    authorization = _authorization(corpus)
    corpus_path = tmp_path / "private-corpus.json"
    authorization_path = tmp_path / "private-authorization.json"
    predictions_path = tmp_path / "private-predictions.json"
    review_path = tmp_path / "private-review.json"
    completed_review_path = tmp_path / "private-completed-review.json"
    evidence_path = tmp_path / "private-evidence.json"
    write_private_quality_artifact(corpus_path, corpus)
    write_private_quality_artifact(authorization_path, authorization)

    generate_status = main(
        (
            "generate",
            str(corpus_path),
            str(authorization_path),
            str(predictions_path),
            "--confirm-external-processing",
        ),
        gateway=_gateway(RecordingProvider([_response()])),
        now=_NOW,
    )
    generate_output = capsys.readouterr()

    assert generate_status == 0
    summary = json.loads(generate_output.out)
    assert summary["status"] == "completed"
    assert summary["fixture_count"] == 1
    assert summary["failure_count"] == 0
    assert _SOURCE not in generate_output.out
    assert str(predictions_path) not in generate_output.out
    run = ProfileQualityPredictionRun.model_validate_json(
        predictions_path.read_text(encoding="utf-8"),
        strict=True,
    )
    assert run.fixtures[0].prediction.result_type == "profile"

    review_status = main(
        (
            "prepare-review",
            str(corpus_path),
            str(predictions_path),
            str(review_path),
        )
    )
    review_output = capsys.readouterr()

    assert review_status == 0
    assert json.loads(review_output.out)["status"] == "awaiting_human_adjudication"
    assert _SOURCE not in review_output.out
    assert str(review_path) not in review_output.out

    draft = load_profile_quality_review_draft(review_path)
    completed_fixture = draft.fixtures[0].model_copy(
        update={
            "adjudications": (
                ClaimAdjudication(
                    field="cv_skills",
                    expected_claim_id="skill_python",
                    predicted_claim_id="skill_python",
                ),
            ),
            "owner_review_outcome": "accepted",
        }
    )
    completed_review = draft.model_copy(update={"fixtures": (completed_fixture,)})
    write_private_quality_artifact(completed_review_path, completed_review)

    finalize_status = main(
        (
            "finalize-review",
            str(corpus_path),
            str(predictions_path),
            str(completed_review_path),
            str(evidence_path),
        )
    )
    finalize_output = capsys.readouterr()

    assert finalize_status == 0
    finalize_summary = json.loads(finalize_output.out)
    assert finalize_summary["status"] == "ready_for_evaluation"
    assert finalize_summary["fixture_count"] == 1
    assert finalize_summary["artifact_sha256"] == finalize_summary["evidence_sha256"]
    assert _SOURCE not in finalize_output.out
    assert str(evidence_path) not in finalize_output.out
    assert (
        ProfileQualityEvidence.model_validate_json(
            evidence_path.read_text(encoding="utf-8"),
            strict=True,
        )
        .fixtures[0]
        .owner_review_outcome
        == "accepted"
    )


@pytest.mark.parametrize(
    "kind",
    ("corpus", "authorization", "predictions", "review-draft", "evidence", "approval"),
)
def test_cli_prints_each_strict_artifact_schema(
    kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(("schema", kind)) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["additionalProperties"] is False
