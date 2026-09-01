import json
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from ai_interviewer.profiling import (
    CV_PROFILE_SCHEMA_ID,
    JOB_DESCRIPTION_PROFILE_SCHEMA_ID,
    PROFILE_SCHEMA_VERSION,
    CareerClaim,
    CvProfileOutput,
    CvProjectClaim,
    CvSkillClaim,
    JobDescriptionProfileOutput,
    JobRequirementClaim,
    ProfileEvidenceError,
    ResponsibilityClaim,
    SeniorityHint,
    SourceSpan,
    profile_output_type,
    validate_profile_evidence,
)


def _span(source: str, quote: str, *, start_at: int = 0) -> SourceSpan:
    start = source.index(quote, start_at)
    return SourceSpan(start=start, end=start + len(quote), quote=quote)


def _cv_profile(source: str) -> CvProfileOutput:
    return CvProfileOutput(
        document_type="cv",
        languages=("en",),
        skills=(
            CvSkillClaim(
                claim_id="skill_python",
                statement="Uses Python professionally",
                assertion_kind="explicit",
                evidence=(_span(source, "Python"),),
                name="Python",
                category="programming_language",
            ),
        ),
        projects=(
            CvProjectClaim(
                claim_id="project_apis",
                statement="Built backend APIs with Python and PostgreSQL",
                assertion_kind="explicit",
                evidence=(_span(source, "Built APIs with Python and PostgreSQL"),),
                name=None,
                technologies=("Python", "PostgreSQL"),
            ),
        ),
        responsibilities=(
            ResponsibilityClaim(
                claim_id="responsibility_migration",
                statement="Led a Kubernetes migration",
                assertion_kind="explicit",
                evidence=(_span(source, "Led migration to Kubernetes"),),
            ),
        ),
        claims=(
            CareerClaim(
                claim_id="claim_services",
                statement="Migration covered three services",
                assertion_kind="explicit",
                evidence=(_span(source, "three services"),),
                claim_type="achievement",
            ),
        ),
        seniority_hints=(
            SeniorityHint(
                claim_id="seniority_senior",
                statement="Source explicitly states senior level",
                assertion_kind="explicit",
                evidence=(_span(source, "Senior backend engineer"),),
                seniority="senior",
            ),
        ),
    )


def _jd_profile(source: str) -> JobDescriptionProfileOutput:
    return JobDescriptionProfileOutput(
        document_type="job_description",
        languages=("az",),
        must_have=(
            JobRequirementClaim(
                claim_id="must_python",
                statement="Python biliyi məcburidir",
                assertion_kind="explicit",
                evidence=(_span(source, "Python bilməlidir"),),
                category="skill",
            ),
        ),
        nice_to_have=(
            JobRequirementClaim(
                claim_id="nice_docker",
                statement="Docker təcrübəsinə üstünlük verilir",
                assertion_kind="explicit",
                evidence=(_span(source, "Docker təcrübəsi üstünlükdür"),),
                category="skill",
            ),
        ),
        responsibilities=(
            ResponsibilityClaim(
                claim_id="responsibility_lead",
                statement="Komandaya rəhbərlik etmək",
                assertion_kind="explicit",
                evidence=(_span(source, "Komandaya rəhbərlik edəcək"),),
            ),
        ),
        seniority_hints=(
            SeniorityHint(
                claim_id="seniority_lead",
                statement="Rəhbərlik məsuliyyəti lead səviyyəsinə işarədir",
                assertion_kind="inferred",
                evidence=(_span(source, "rəhbərlik"),),
                seniority="lead",
            ),
        ),
    )


def test_english_cv_profile_verifies_every_claim_against_exact_source() -> None:
    source = (
        "Senior backend engineer. Built APIs with Python and PostgreSQL. "
        "Led migration to Kubernetes for three services."
    )
    profile = _cv_profile(source)

    verified = validate_profile_evidence(profile, source, "cv")

    assert verified.profile is profile
    assert verified.document_type == "cv"
    assert verified.claim_count == 5
    assert verified.evidence_span_count == 5
    assert 0 < verified.evidence_character_count < len(source)


def test_azerbaijani_jd_profile_preserves_unicode_offsets_and_overlap() -> None:
    source = "Namizəd Python bilməlidir. Docker təcrübəsi üstünlükdür. Komandaya rəhbərlik edəcək."
    profile = _jd_profile(source)

    verified = validate_profile_evidence(profile, source, "job_description")

    spans = [span for claim in profile.evidence_claims() for span in claim.evidence]
    raw_evidence_characters = sum(span.end - span.start for span in spans)
    assert verified.claim_count == 4
    assert verified.evidence_span_count == 4
    assert verified.evidence_character_count < raw_evidence_characters


def test_profile_json_schema_is_closed_and_has_no_direct_contact_fields() -> None:
    cv_schema = CvProfileOutput.model_json_schema(mode="validation")
    jd_schema = JobDescriptionProfileOutput.model_json_schema(mode="validation")

    assert cv_schema["additionalProperties"] is False
    assert jd_schema["additionalProperties"] is False
    assert set(cv_schema["properties"]) == {
        "document_type",
        "languages",
        "skills",
        "projects",
        "responsibilities",
        "claims",
        "seniority_hints",
    }
    serialized = json.dumps((cv_schema, jd_schema), sort_keys=True)
    assert "email" not in serialized
    assert "phone" not in serialized


def test_profile_round_trips_through_strict_json_validation() -> None:
    source = "Python developer"
    profile = CvProfileOutput(
        document_type="cv",
        languages=("en",),
        skills=(
            CvSkillClaim(
                claim_id="skill_python",
                statement="Uses Python",
                assertion_kind="explicit",
                evidence=(_span(source, "Python"),),
                name="Python",
                category="programming_language",
            ),
        ),
    )

    restored = CvProfileOutput.model_validate_json(profile.model_dump_json(), strict=True)

    assert restored == profile


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"email": "candidate@example.com"}),
        lambda payload: payload.update({"document_type": "job_description"}),
        lambda payload: payload.update({"languages": ["tr"]}),
        lambda payload: payload["skills"][0]["evidence"][0].update({"start": "0"}),
        lambda payload: payload["skills"][0].update({"claim_id": "Not Safe"}),
    ],
)
def test_unknown_coerced_or_out_of_contract_profile_fields_fail_closed(
    mutate: Callable[[dict[str, object]], object],
) -> None:
    payload = _cv_profile(
        "Senior backend engineer. Built APIs with Python and PostgreSQL. "
        "Led migration to Kubernetes for three services."
    ).model_dump(mode="json")
    mutate(payload)

    with pytest.raises(ValidationError):
        CvProfileOutput.model_validate(payload)


@pytest.mark.parametrize(
    "build",
    [
        lambda: SourceSpan(start=1, end=1, quote="x"),
        lambda: SourceSpan(start=0, end=2, quote="x"),
        lambda: SourceSpan(start=-1, end=1, quote="xx"),
        lambda: SourceSpan(start=0, end=500_001, quote="x"),
    ],
)
def test_source_span_shape_is_strict_and_bounded(build: Callable[[], object]) -> None:
    with pytest.raises(ValidationError):
        build()


def test_profile_rejects_empty_claim_sets_duplicate_languages_and_duplicate_claim_ids() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        CvProfileOutput(document_type="cv", languages=("en",))

    source = "Python developer"
    skill = CvSkillClaim(
        claim_id="duplicate",
        statement="Uses Python",
        assertion_kind="explicit",
        evidence=(_span(source, "Python"),),
        name="Python",
        category="programming_language",
    )
    with pytest.raises(ValidationError, match="languages must be unique"):
        CvProfileOutput(
            document_type="cv",
            languages=("en", "en"),
            skills=(skill,),
        )
    with pytest.raises(ValidationError, match="claim IDs must be unique"):
        CvProfileOutput(
            document_type="cv",
            languages=("en",),
            skills=(skill,),
            claims=(
                CareerClaim(
                    claim_id="duplicate",
                    statement="Works as a developer",
                    assertion_kind="explicit",
                    evidence=(_span(source, "developer"),),
                    claim_type="employment",
                ),
            ),
        )


def test_claim_rejects_duplicate_evidence_and_project_technology() -> None:
    source = "Python developer"
    span = _span(source, "Python")
    with pytest.raises(ValidationError, match="evidence spans must be unique"):
        ResponsibilityClaim(
            claim_id="responsibility_python",
            statement="Uses Python",
            assertion_kind="explicit",
            evidence=(span, span),
        )

    with pytest.raises(ValidationError, match="technologies must be unique"):
        CvProjectClaim(
            claim_id="project_python",
            statement="Built a Python service",
            assertion_kind="explicit",
            evidence=(span,),
            technologies=("Python", "python"),
        )


@pytest.mark.parametrize(
    "statement",
    [" leading", "trailing ", "unsafe\nline", "unsafe\u2028separator"],
)
def test_derived_profile_text_rejects_implicit_cleanup(statement: str) -> None:
    source = "Python developer"
    with pytest.raises(ValidationError, match="derived profile text"):
        ResponsibilityClaim(
            claim_id="responsibility_python",
            statement=statement,
            assertion_kind="explicit",
            evidence=(_span(source, "Python"),),
        )


@pytest.mark.parametrize(
    ("source", "document_type", "span", "code"),
    [
        ("Java developer", "cv", SourceSpan(start=0, end=6, quote="Python"), "quote_mismatch"),
        ("short", "cv", SourceSpan(start=10, end=16, quote="Python"), "span_out_of_bounds"),
        ("Python developer", "job_description", None, "document_type_mismatch"),
        ("", "cv", None, "source_text_invalid"),
    ],
)
def test_evidence_verifier_returns_only_safe_failure_codes(
    source: str,
    document_type: str,
    span: SourceSpan | None,
    code: str,
) -> None:
    valid_source = "Python developer"
    selected_span = span or _span(valid_source, "Python")
    profile = CvProfileOutput(
        document_type="cv",
        languages=("en",),
        skills=(
            CvSkillClaim(
                claim_id="skill_python",
                statement="Uses Python",
                assertion_kind="explicit",
                evidence=(selected_span,),
                name="Python",
                category="programming_language",
            ),
        ),
    )

    with pytest.raises(ProfileEvidenceError) as raised:
        validate_profile_evidence(profile, source, document_type)  # type: ignore[arg-type]

    assert raised.value.code == code
    if source:
        assert source not in str(raised.value)


def test_evidence_verifier_rejects_invalid_profile_runtime_type() -> None:
    class InvalidProfile:
        document_type = "other"

    with pytest.raises(ProfileEvidenceError) as raised:
        validate_profile_evidence(InvalidProfile(), "source", "cv")  # type: ignore[arg-type]

    assert raised.value.code == "profile_type_invalid"


def test_profile_document_type_selects_one_versioned_schema() -> None:
    assert profile_output_type("cv") is CvProfileOutput
    assert profile_output_type("job_description") is JobDescriptionProfileOutput
    assert CV_PROFILE_SCHEMA_ID == "cv-profile"
    assert JOB_DESCRIPTION_PROFILE_SCHEMA_ID == "job-description-profile"
    assert PROFILE_SCHEMA_VERSION == "1.0.0"

    with pytest.raises(ValueError, match="document type"):
        profile_output_type("other")  # type: ignore[arg-type]


def test_cv_skills_and_jd_requirements_cannot_duplicate_semantic_items() -> None:
    source = "Python is required. Python is preferred."
    first = CvSkillClaim(
        claim_id="skill_python_one",
        statement="Uses Python",
        assertion_kind="explicit",
        evidence=(_span(source, "Python"),),
        name="Python",
        category="programming_language",
    )
    second = CvSkillClaim(
        claim_id="skill_python_two",
        statement="Also uses Python",
        assertion_kind="explicit",
        evidence=(_span(source, "Python", start_at=1),),
        name="python",
        category="programming_language",
    )
    with pytest.raises(ValidationError, match="skill names must be unique"):
        CvProfileOutput(
            document_type="cv",
            languages=("en",),
            skills=(first, second),
        )

    must_have = JobRequirementClaim(
        claim_id="must_python",
        statement="Python experience",
        assertion_kind="explicit",
        evidence=(_span(source, "Python"),),
        category="skill",
    )
    nice_to_have = JobRequirementClaim(
        claim_id="nice_python",
        statement="python experience",
        assertion_kind="inferred",
        evidence=(_span(source, "Python", start_at=1),),
        category="skill",
    )
    with pytest.raises(ValidationError, match="unique across priority groups"):
        JobDescriptionProfileOutput(
            document_type="job_description",
            languages=("en",),
            must_have=(must_have,),
            nice_to_have=(nice_to_have,),
        )


def test_profile_and_verified_result_representations_hide_candidate_content() -> None:
    source = "private-candidate-marker Python"
    profile = CvProfileOutput(
        document_type="cv",
        languages=("en",),
        skills=(
            CvSkillClaim(
                claim_id="skill_private",
                statement="private-candidate-marker",
                assertion_kind="explicit",
                evidence=(_span(source, "private-candidate-marker"),),
                name="Private skill",
                category="other",
            ),
        ),
    )
    verified = validate_profile_evidence(profile, source, "cv")

    assert "private-candidate-marker" not in repr(profile)
    assert "private-candidate-marker" not in str(profile)
    assert "private-candidate-marker" not in repr(verified)
