import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_interviewer.model_gateway import ModelReleaseIdentity
from ai_interviewer.profiling.contracts import (
    CareerClaim,
    CvProfileOutput,
    CvProjectClaim,
    CvSkillClaim,
    JobDescriptionProfileOutput,
    JobRequirementClaim,
    ResponsibilityClaim,
    SeniorityHint,
    SourceSpan,
)
from ai_interviewer.profiling.quality import (
    MAX_QUALITY_EVIDENCE_BYTES,
    ClaimAdjudication,
    FailedQualityPrediction,
    LabeledProfileFixture,
    ProfileQualityApproval,
    ProfileQualityEvidence,
    QualityApprovalDecision,
    QualityProvenance,
    SuccessfulQualityPrediction,
    evaluate_profile_quality,
    evaluate_profile_quality_gate,
    load_profile_quality_approval,
    load_profile_quality_evidence,
    profile_quality_evidence_sha256,
    profile_quality_prompt_contract_sha256,
)
from ai_interviewer.profiling.quality_cli import main

_MODEL_RELEASE = ModelReleaseIdentity(
    provider="reviewed-provider",
    model_id="profile-model",
    model_version="2026-09-01",
)


def _span(source: str, quote: str) -> SourceSpan:
    start = source.index(quote)
    return SourceSpan(start=start, end=start + len(quote), quote=quote)


def _source(language: str, document_type: str) -> str:
    if document_type == "cv":
        if language == "az":
            return "Python layihəsi. Sistem qurdu. Beş il təcrübə. Senior mühəndis. Docker."
        return "Python project. Built systems. Five years experience. Senior engineer. Docker."
    if language == "az":
        return "Python tələbdir. Docker üstünlükdür. Sistem qurmaq. Senior rol. Remote."
    return "Python required. Docker preferred. Build systems. Senior role. Remote."


def _cv_profile(
    source: str, language: str, *, bad_evidence: bool = False, extra: bool = False
) -> CvProfileOutput:
    python_span = (
        SourceSpan(start=7, end=13, quote="Python") if bad_evidence else _span(source, "Python")
    )
    project_quote = "layihəsi" if language == "az" else "project"
    responsibility_quote = "Sistem qurdu" if language == "az" else "Built systems"
    career_quote = "Beş il təcrübə" if language == "az" else "Five years experience"
    skills = [
        CvSkillClaim(
            claim_id="skill_python",
            statement="Python skill",
            assertion_kind="explicit",
            evidence=(python_span,),
            name="Python",
            category="programming_language",
        )
    ]
    if extra:
        skills.append(
            CvSkillClaim(
                claim_id="skill_docker_extra",
                statement="Docker skill",
                assertion_kind="explicit",
                evidence=(_span(source, "Docker"),),
                name="Docker",
                category="devops_tooling",
            )
        )
    return CvProfileOutput(
        document_type="cv",
        languages=(language,),  # type: ignore[arg-type]
        skills=tuple(skills),
        projects=(
            CvProjectClaim(
                claim_id="project_primary",
                statement="Built a project",
                assertion_kind="explicit",
                evidence=(_span(source, project_quote),),
                name="Primary project",
                technologies=("Python",),
            ),
        ),
        responsibilities=(
            ResponsibilityClaim(
                claim_id="responsibility_systems",
                statement="Built systems",
                assertion_kind="explicit",
                evidence=(_span(source, responsibility_quote),),
            ),
        ),
        claims=(
            CareerClaim(
                claim_id="claim_experience",
                statement="Has five years of experience",
                assertion_kind="explicit",
                evidence=(_span(source, career_quote),),
                claim_type="achievement",
            ),
        ),
        seniority_hints=(
            SeniorityHint(
                claim_id="seniority_senior",
                statement="Senior level",
                assertion_kind="explicit",
                evidence=(_span(source, "Senior"),),
                seniority="senior",
            ),
        ),
    )


def _jd_profile(
    source: str, language: str, *, bad_evidence: bool = False, extra: bool = False
) -> JobDescriptionProfileOutput:
    python_span = (
        SourceSpan(start=7, end=13, quote="Python") if bad_evidence else _span(source, "Python")
    )
    responsibility_quote = "Sistem qurmaq" if language == "az" else "Build systems"
    must_have = [
        JobRequirementClaim(
            claim_id="must_python",
            statement="Python is required",
            assertion_kind="explicit",
            evidence=(python_span,),
            category="skill",
        )
    ]
    if extra:
        must_have.append(
            JobRequirementClaim(
                claim_id="must_remote_extra",
                statement="Remote work is required",
                assertion_kind="explicit",
                evidence=(_span(source, "Remote"),),
                category="location",
            )
        )
    return JobDescriptionProfileOutput(
        document_type="job_description",
        languages=(language,),  # type: ignore[arg-type]
        must_have=tuple(must_have),
        nice_to_have=(
            JobRequirementClaim(
                claim_id="nice_docker",
                statement="Docker is preferred",
                assertion_kind="explicit",
                evidence=(_span(source, "Docker"),),
                category="skill",
            ),
        ),
        responsibilities=(
            ResponsibilityClaim(
                claim_id="responsibility_systems",
                statement="Build systems",
                assertion_kind="explicit",
                evidence=(_span(source, responsibility_quote),),
            ),
        ),
        seniority_hints=(
            SeniorityHint(
                claim_id="seniority_senior",
                statement="Senior level",
                assertion_kind="explicit",
                evidence=(_span(source, "Senior"),),
                seniority="senior",
            ),
        ),
    )


def _fixture(
    index: int,
    language: str,
    document_type: str,
    *,
    prediction_kind: str = "profile",
    bad_evidence: bool = False,
    extra: bool = False,
    review: str = "accepted",
) -> LabeledProfileFixture:
    source = _source(language, document_type)
    if document_type == "cv":
        expected = _cv_profile(source, language)
        predicted = _cv_profile(source, language, bad_evidence=bad_evidence, extra=extra)
        fields = (
            ("cv_skills", "skill_python"),
            ("cv_projects", "project_primary"),
            ("cv_responsibilities", "responsibility_systems"),
            ("cv_claims", "claim_experience"),
            ("cv_seniority_hints", "seniority_senior"),
        )
        extra_field = "cv_skills"
        extra_claim = "skill_docker_extra"
    else:
        expected = _jd_profile(source, language)
        predicted = _jd_profile(source, language, bad_evidence=bad_evidence, extra=extra)
        fields = (
            ("jd_must_have", "must_python"),
            ("jd_nice_to_have", "nice_docker"),
            ("jd_responsibilities", "responsibility_systems"),
            ("jd_seniority_hints", "seniority_senior"),
        )
        extra_field = "jd_must_have"
        extra_claim = "must_remote_extra"
    if prediction_kind == "failure":
        prediction = FailedQualityPrediction(
            result_type="failure",
            attempts=3,
            failure_code="invalid_output",
        )
        adjudications = tuple(
            ClaimAdjudication(field=field, expected_claim_id=claim_id)  # type: ignore[arg-type]
            for field, claim_id in fields
        )
    else:
        prediction = SuccessfulQualityPrediction(
            result_type="profile",
            attempts=1,
            profile=predicted,
        )
        adjudication_list = [
            ClaimAdjudication(
                field=field,  # type: ignore[arg-type]
                expected_claim_id=claim_id,
                predicted_claim_id=claim_id,
            )
            for field, claim_id in fields
        ]
        if extra:
            adjudication_list.append(
                ClaimAdjudication(
                    field=extra_field,  # type: ignore[arg-type]
                    predicted_claim_id=extra_claim,
                )
            )
        adjudications = tuple(adjudication_list)
    return LabeledProfileFixture(
        fixture_id=f"fixture-{index}",
        language_slice=language,  # type: ignore[arg-type]
        document_type=document_type,  # type: ignore[arg-type]
        risk_slices=("standard", "prompt_injection", "unsupported_claim"),
        provenance=QualityProvenance(
            source_kind="synthetic",
            rights_reference="internal.synthetic.v1",
            repository_safe=True,
        ),
        source_text=source,
        expected_profile=expected,
        prediction=prediction,
        adjudications=adjudications,
        owner_review_outcome=review,  # type: ignore[arg-type]
    )


def _evidence(
    *,
    prediction_kind: str = "profile",
    bad_evidence: bool = False,
    extra: bool = False,
    review: str = "accepted",
    prompt_digest: str | None = None,
) -> ProfileQualityEvidence:
    combinations = (
        (language, document_type)
        for language in ("az", "en")
        for document_type in ("cv", "job_description")
        for _ in range(10)
    )
    return ProfileQualityEvidence(
        schema_version=1,
        contract_version="1b-d-v1",
        policy_version="1.0.0",
        dataset_id="synthetic-quality-corpus",
        dataset_version="1.0.0",
        prompt_contract_sha256=prompt_digest or profile_quality_prompt_contract_sha256(),
        model_release=_MODEL_RELEASE,
        fixtures=tuple(
            _fixture(
                index,
                language,
                document_type,
                prediction_kind=prediction_kind,
                bad_evidence=bad_evidence,
                extra=extra,
                review=review,
            )
            for index, (language, document_type) in enumerate(combinations)
        ),
    )


def _approval(evidence: ProfileQualityEvidence) -> ProfileQualityApproval:
    approved_at = datetime(2026, 9, 1, tzinfo=UTC)
    return ProfileQualityApproval(
        schema_version=1,
        contract_version="1b-d-v1",
        policy_version="1.0.0",
        evidence_sha256=profile_quality_evidence_sha256(evidence),
        model_release=evidence.model_release,
        approvals=tuple(
            QualityApprovalDecision(
                role=role,  # type: ignore[arg-type]
                reviewer_id=f"reviewer-{role}",
                approved_at=approved_at,
                decision="approved",
            )
            for role in ("product", "engineering", "language_az", "language_en")
        ),
    )


def test_complete_quality_evidence_is_eligible_but_requires_separate_approval() -> None:
    evidence = _evidence()

    summary = evaluate_profile_quality(evidence)
    decision = evaluate_profile_quality_gate(evidence, _approval(evidence))

    assert summary.status == "eligible_for_approval"
    assert summary.reasons == ()
    assert summary.fixture_count == 40
    assert summary.overall.precision == 1
    assert summary.overall.recall == 1
    assert summary.prediction_success_rate == 1
    assert summary.source_span_coverage == 1
    assert summary.owner_review_coverage == 1
    assert summary.owner_correction_rate == 0
    assert summary.failure_counts == ()
    assert all(metric.fixture_count == 10 for metric in summary.language_document_slices)
    assert all(metric.fixture_count == 40 for metric in summary.risk_slices)
    assert decision.status == "approved"
    assert decision.reasons == ()


def test_failures_and_unreviewed_results_block_recall_coverage_and_success() -> None:
    summary = evaluate_profile_quality(_evidence(prediction_kind="failure", review="not_reviewed"))

    assert summary.status == "blocked"
    assert summary.overall.precision is None
    assert summary.overall.recall == 0
    assert summary.prediction_success_rate == 0
    assert summary.source_span_coverage is None
    assert summary.owner_review_coverage == 0
    assert summary.owner_correction_rate is None
    assert summary.failure_counts[0].failure_code == "invalid_output"
    assert summary.failure_counts[0].count == 40
    assert "overall_precision_below_threshold" in summary.reasons
    assert "overall_recall_below_threshold" in summary.reasons
    assert "field_recall_below_threshold" in summary.reasons
    assert "slice_recall_below_threshold" in summary.reasons
    assert "source_span_coverage_below_threshold" in summary.reasons
    assert "prediction_success_below_threshold" in summary.reasons
    assert "owner_review_incomplete" in summary.reasons
    assert "correction_rate_above_threshold" in summary.reasons


def test_false_positives_bad_spans_corrections_and_prompt_drift_block_gate() -> None:
    false_positive = evaluate_profile_quality(_evidence(extra=True))
    bad_span = evaluate_profile_quality(_evidence(bad_evidence=True))
    corrected = evaluate_profile_quality(_evidence(review="corrected"))
    prompt_drift = evaluate_profile_quality(_evidence(prompt_digest="0" * 64))

    assert "overall_precision_below_threshold" in false_positive.reasons
    assert "field_precision_below_threshold" in false_positive.reasons
    assert "slice_precision_below_threshold" in false_positive.reasons
    assert bad_span.source_span_coverage < 1  # type: ignore[operator]
    assert "source_span_coverage_below_threshold" in bad_span.reasons
    assert corrected.owner_correction_rate == 1
    assert "correction_rate_above_threshold" in corrected.reasons
    assert prompt_drift.reasons == ("prompt_contract_mismatch",)


def test_small_seed_is_valid_evidence_but_cannot_claim_release_quality() -> None:
    full = _evidence()
    seed = ProfileQualityEvidence(
        schema_version=1,
        contract_version="1b-d-v1",
        policy_version="1.0.0",
        dataset_id="seed",
        dataset_version="1",
        prompt_contract_sha256=full.prompt_contract_sha256,
        model_release=full.model_release,
        fixtures=full.fixtures[:1],
    )

    summary = evaluate_profile_quality(seed)

    assert summary.status == "blocked"
    assert "fixture_count_below_minimum" in summary.reasons
    assert "language_document_slice_below_minimum" in summary.reasons
    assert "risk_slice_below_minimum" in summary.reasons
    assert "field_support_below_minimum" in summary.reasons


def test_repository_seed_covers_az_en_cv_jd_without_pretending_to_pass() -> None:
    seed_path = (
        Path(__file__).parents[1] / "docs" / "quality" / "fixtures" / "phase-1b-d1-seed.json"
    )

    seed = load_profile_quality_evidence(seed_path)
    summary = evaluate_profile_quality(seed)

    assert summary.status == "blocked"
    assert summary.fixture_count == 4
    assert {fixture.language_slice for fixture in seed.fixtures} == {"az", "en"}
    assert {fixture.document_type for fixture in seed.fixtures} == {"cv", "job_description"}
    assert {risk for fixture in seed.fixtures for risk in fixture.risk_slices} >= {
        "prompt_injection",
        "unsupported_claim",
    }
    assert summary.source_span_coverage == 1


def test_gate_rejects_ineligible_mismatched_or_incomplete_approval() -> None:
    evidence = _evidence()
    partial = ProfileQualityApproval(
        schema_version=1,
        contract_version="1b-d-v1",
        policy_version="older-policy",
        evidence_sha256="0" * 64,
        model_release=ModelReleaseIdentity(
            provider="other",
            model_id="other",
            model_version="1",
        ),
        approvals=(
            QualityApprovalDecision(
                role="engineering",
                reviewer_id="reviewer-engineering",
                approved_at=datetime(2026, 9, 1, tzinfo=UTC),
                decision="approved",
            ),
        ),
    )

    decision = evaluate_profile_quality_gate(evidence, partial)
    ineligible = evaluate_profile_quality_gate(
        ProfileQualityEvidence(
            schema_version=1,
            contract_version="1b-d-v1",
            policy_version="1.0.0",
            dataset_id="seed",
            dataset_version="1",
            prompt_contract_sha256=evidence.prompt_contract_sha256,
            model_release=evidence.model_release,
            fixtures=evidence.fixtures[:1],
        ),
        _approval(evidence),
    )

    assert decision.status == "blocked"
    assert decision.reasons == (
        "approval_evidence_mismatch",
        "approval_model_mismatch",
        "approval_policy_mismatch",
        "required_approval_missing",
    )
    assert ineligible.reasons[0] == "evaluation_not_eligible"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda payload: payload.update({"risk_slices": ["standard", "standard"]}), "unique"),
        (lambda payload: payload.update({"language_slice": "mixed"}), "language slice"),
        (lambda payload: payload.update({"document_type": "job_description"}), "document type"),
        (
            lambda payload: payload["expected_profile"]["skills"][0]["evidence"][0].update(
                {"start": 7, "end": 13}
            ),
            "expected profile evidence",
        ),
        (
            lambda payload: payload["adjudications"][0].update({"field": "cv_projects"}),
            "expected claim field",
        ),
        (
            lambda payload: payload["adjudications"].append(payload["adjudications"][0]),
            "only once",
        ),
        (
            lambda payload: payload["adjudications"].pop(),
            "every expected claim",
        ),
    ],
)
def test_fixture_relationships_fail_closed(mutate: object, message: str) -> None:
    payload = _fixture(1, "en", "cv").model_dump(mode="json")
    mutate(payload)  # type: ignore[operator]
    with pytest.raises(ValidationError, match=message):
        LabeledProfileFixture.model_validate_json(json.dumps(payload))


def test_adjudication_prediction_and_provenance_relationships_fail_closed() -> None:
    with pytest.raises(ValidationError, match="expected or predicted"):
        ClaimAdjudication(field="cv_skills")
    with pytest.raises(ValidationError, match="synthetic"):
        QualityProvenance(
            source_kind="licensed",
            rights_reference="license-1",
            repository_safe=True,
        )

    payload = _fixture(1, "en", "cv", extra=True).model_dump(mode="json")
    payload["adjudications"].pop()
    with pytest.raises(ValidationError, match="every predicted claim"):
        LabeledProfileFixture.model_validate_json(json.dumps(payload))

    payload = _fixture(1, "en", "cv").model_dump(mode="json")
    payload["adjudications"][0]["field"] = "languages"
    with pytest.raises(ValidationError, match="automatically"):
        LabeledProfileFixture.model_validate_json(json.dumps(payload))

    fixture = _fixture(1, "en", "cv")
    wrong_document_prediction = SuccessfulQualityPrediction(
        result_type="profile",
        attempts=1,
        profile=JobDescriptionProfileOutput(
            document_type="job_description",
            languages=("en",),
            must_have=(
                JobRequirementClaim(
                    claim_id="must_python",
                    statement="Python is required",
                    assertion_kind="explicit",
                    evidence=(_span(fixture.source_text, "Python"),),
                    category="skill",
                ),
            ),
        ),
    )
    with pytest.raises(ValidationError, match="predicted profile document type"):
        LabeledProfileFixture(
            fixture_id="wrong-prediction-document",
            language_slice=fixture.language_slice,
            document_type=fixture.document_type,
            risk_slices=fixture.risk_slices,
            provenance=fixture.provenance,
            source_text=fixture.source_text,
            expected_profile=fixture.expected_profile,
            prediction=wrong_document_prediction,
            adjudications=fixture.adjudications,
            owner_review_outcome="accepted",
        )

    payload = fixture.model_dump(mode="json")
    payload["adjudications"][0]["predicted_claim_id"] = None
    payload["adjudications"].append({"field": "cv_projects", "predicted_claim_id": "skill_python"})
    with pytest.raises(ValidationError, match="predicted claim field"):
        LabeledProfileFixture.model_validate_json(json.dumps(payload))

    payload = fixture.model_dump(mode="json")
    payload["adjudications"].append({"field": "cv_skills", "predicted_claim_id": "skill_python"})
    with pytest.raises(ValidationError, match="predicted claim may be adjudicated only once"):
        LabeledProfileFixture.model_validate_json(json.dumps(payload))


def test_evidence_and_approval_reject_duplicate_identifiers_and_roles() -> None:
    evidence = _evidence()
    with pytest.raises(ValidationError, match="fixture IDs"):
        ProfileQualityEvidence(
            schema_version=1,
            contract_version="1b-d-v1",
            policy_version="1.0.0",
            dataset_id="duplicate",
            dataset_version="1",
            prompt_contract_sha256=evidence.prompt_contract_sha256,
            model_release=evidence.model_release,
            fixtures=(evidence.fixtures[0], evidence.fixtures[0]),
        )

    approval = _approval(evidence)
    with pytest.raises(ValidationError, match="roles must be unique"):
        ProfileQualityApproval(
            schema_version=1,
            contract_version="1b-d-v1",
            policy_version="1.0.0",
            evidence_sha256=approval.evidence_sha256,
            model_release=approval.model_release,
            approvals=(approval.approvals[0], approval.approvals[0]),
        )


def test_bounded_loaders_and_cli_emit_only_safe_summaries(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _evidence()
    approval = _approval(evidence)
    evidence_path = tmp_path / "evidence.json"
    approval_path = tmp_path / "approval.json"
    evidence_path.write_text(evidence.model_dump_json(), encoding="utf-8")
    approval_path.write_text(approval.model_dump_json(), encoding="utf-8")

    assert load_profile_quality_evidence(evidence_path) == evidence
    assert load_profile_quality_approval(approval_path) == approval
    assert main(("evaluate", str(evidence_path))) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "eligible_for_approval"
    assert "Five years experience" not in output
    assert main(("gate", str(evidence_path), str(approval_path))) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "approved"

    assert main(("schema", "evidence")) == 0
    assert json.loads(capsys.readouterr().out)["additionalProperties"] is False
    assert main(("schema", "approval")) == 0
    assert json.loads(capsys.readouterr().out)["additionalProperties"] is False
    assert main(("prompt-digest",)) == 0
    assert capsys.readouterr().out.strip() == profile_quality_prompt_contract_sha256()

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text('{"private":"must-not-leak"}', encoding="utf-8")
    assert main(("evaluate", str(invalid_path))) == 2
    error = capsys.readouterr().err
    assert "must-not-leak" not in error
    assert str(invalid_path) not in error

    with pytest.raises(ValueError, match="regular file"):
        load_profile_quality_evidence(tmp_path / "missing.json")
    monkeypatch.setattr(
        "ai_interviewer.profiling.quality.MAX_QUALITY_EVIDENCE_BYTES",
        1,
    )
    with pytest.raises(ValueError, match="maximum size"):
        load_profile_quality_approval(approval_path)
    assert MAX_QUALITY_EVIDENCE_BYTES == 32 * 1024 * 1024
