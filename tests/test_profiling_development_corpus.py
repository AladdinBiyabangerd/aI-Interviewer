import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from ai_interviewer.profiling.development_corpus import (
    DEVELOPMENT_CORPUS_DATASET_ID,
    ONET_RELEASE,
    ONET_RIGHTS_REFERENCE,
    build_development_profile_corpus,
    development_corpus_source_coordinates,
)
from ai_interviewer.profiling.quality_cli import main
from ai_interviewer.profiling.quality_run import (
    ProfileQualityCorpusCount,
    load_profile_quality_corpus,
    summarize_profile_quality_corpus,
)


def _counts(values: Sequence[ProfileQualityCorpusCount]) -> dict[str, int]:
    return {item.name: item.count for item in values}


def test_development_corpus_meets_every_pre_run_structural_minimum() -> None:
    corpus = build_development_profile_corpus()
    summary = summarize_profile_quality_corpus(corpus)

    assert ONET_RELEASE == "31.0"
    assert corpus.dataset_id == DEVELOPMENT_CORPUS_DATASET_ID
    assert summary.status == "structurally_ready"
    assert summary.reasons == ()
    assert summary.fixture_count == 40
    assert _counts(summary.language_document_slices) == {
        "az:cv": 10,
        "az:job_description": 10,
        "en:cv": 10,
        "en:job_description": 10,
    }
    assert _counts(summary.risk_slices) == {
        "prompt_injection": 16,
        "unsupported_claim": 16,
    }
    assert all(item.count >= 4 for item in summary.field_gold_claims)
    assert _counts(summary.source_kinds) == {"synthetic": 40}
    assert summary.repository_safe_fixture_count == 40
    assert all(
        fixture.provenance.rights_reference == ONET_RIGHTS_REFERENCE for fixture in corpus.fixtures
    )
    assert all(fixture.provenance.repository_safe for fixture in corpus.fixtures)
    assert all("@" not in fixture.source_text for fixture in corpus.fixtures)


def test_development_corpus_has_unique_reviewable_onet_coordinates() -> None:
    coordinates = development_corpus_source_coordinates()

    assert len(coordinates) == 10
    assert len(coordinates) == len(set(coordinates))
    assert all(code.startswith("15-") for code, _ in coordinates)
    assert all(task_id > 0 for _, task_id in coordinates)


def test_checked_in_development_corpus_is_the_canonical_builder_output() -> None:
    fixture_path = (
        Path(__file__).parents[1]
        / "docs"
        / "quality"
        / "fixtures"
        / "phase-1b-d2-development-corpus.json"
    )

    assert load_profile_quality_corpus(fixture_path) == build_development_profile_corpus()


def test_corpus_cli_builds_validates_and_never_overwrites(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "development-corpus.json"

    assert main(["build-development-corpus", str(output)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["status"] == "development_corpus_created"
    assert created["structural_status"] == "structurally_ready"
    assert created["fixture_count"] == 40
    assert created["source_coordinate_count"] == 10
    assert len(created["artifact_sha256"]) == 64

    loaded = load_profile_quality_corpus(output)
    assert loaded == build_development_profile_corpus()
    assert main(["validate-corpus", str(output)]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["status"] == "structurally_ready"
    assert "source_text" not in validated

    assert main(["build-development-corpus", str(output)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error == {"error_type": "FileExistsError", "status": "invalid"}


def test_corpus_readiness_blocks_small_and_prompt_drifted_inputs() -> None:
    corpus = build_development_profile_corpus()
    blocked = corpus.model_copy(
        update={
            "fixtures": corpus.fixtures[:1],
            "prompt_contract_sha256": "0" * 64,
        }
    )

    summary = summarize_profile_quality_corpus(blocked)

    assert summary.status == "blocked"
    assert summary.reasons == (
        "fixture_count_below_minimum",
        "language_document_slice_below_minimum",
        "risk_slice_below_minimum",
        "field_support_below_minimum",
        "prompt_contract_mismatch",
    )
