import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_interviewer.core.reliability import (
    HTTP_DURATION_BUCKETS_SECONDS,
    product_route_contract_digest,
)
from ai_interviewer.reliability import baseline as baseline_module
from ai_interviewer.reliability.baseline import (
    BASELINE_WINDOW_DAYS,
    BaselineEvidence,
    CollectionEvidence,
    DailyObservation,
    HistogramObservation,
    ReleaseCohort,
    evaluate_baseline,
    load_baseline_evidence,
)
from ai_interviewer.reliability.cli import main

_ALL_BUCKETS = (0, 0, 0, 0, 0, 10, 60, 25, 4, 0, 0, 0, 0, 0, 1)
_GOOD_BUCKETS = (0, 0, 0, 0, 0, 10, 60, 25, 4, 0, 0, 0, 0, 0, 0)
_EMPTY_BUCKETS = (0,) * (len(HTTP_DURATION_BUCKETS_SECONDS) + 1)


def _day(day: date, *, requests: int = 100) -> DailyObservation:
    if requests == 0:
        all_buckets = good_buckets = _EMPTY_BUCKETS
        server_errors = client_errors = 0
    else:
        all_buckets = _ALL_BUCKETS
        good_buckets = _GOOD_BUCKETS
        server_errors = 1
        client_errors = 5
    return DailyObservation(
        day=day,
        eligible_requests=requests,
        server_error_requests=server_errors,
        client_error_requests=client_errors,
        latency_all=HistogramObservation(bucket_counts=all_buckets),
        latency_non_5xx=HistogramObservation(bucket_counts=good_buckets),
        telemetry_gap_seconds=0,
        sensitive_canary_matches=0,
        unexpected_metric_attributes=0,
        operational_snapshot_successes=2_880,
        operational_snapshot_errors=0,
        operational_snapshot_max_age_seconds=60.0,
        process_restarts=0,
        counter_resets=0,
        deployments=0,
    )


def _evidence(*, requests: int = 100) -> BaselineEvidence:
    start = date(2026, 7, 1)
    return BaselineEvidence(
        schema_version=1,
        contract_version="0d-c-a-v1",
        service_name="ai-interviewer-api",
        environment="staging",
        synthetic_only=True,
        window_start=start,
        window_end=start + timedelta(days=BASELINE_WINDOW_DAYS),
        route_contract_sha256=product_route_contract_digest(),
        collection=CollectionEvidence(
            source_kind="monitoring-backend-export",
            backend_type="reviewed-backend",
            backend_version="1.2.3",
            collector_version="0.140.0",
            metric_temporality="cumulative",
            export_interval_seconds=30,
            monitor_interval_seconds=30,
            query_digest_sha256="a" * 64,
            export_digest_sha256="b" * 64,
        ),
        releases=(
            ReleaseCohort(
                release_id="2026.07-baseline",
                release_revision="c" * 40,
            ),
        ),
        days=tuple(
            _day(start + timedelta(days=offset), requests=requests)
            for offset in range(BASELINE_WINDOW_DAYS)
        ),
    )


def test_complete_baseline_is_calculated_from_counts_and_fixed_buckets() -> None:
    summary = evaluate_baseline(_evidence())

    assert summary.status == "eligible_for_review"
    assert summary.reasons == ()
    assert summary.eligible_requests == 2_800
    assert summary.good_requests == 2_772
    assert summary.server_error_requests == 28
    assert summary.client_error_requests == 140
    assert summary.availability_ratio == 0.99
    assert summary.average_requests_per_day == 100
    assert summary.minimum_daily_requests == 100
    assert summary.maximum_daily_requests == 100
    assert summary.days_without_traffic == 0
    assert [point.upper_bound_seconds for point in summary.latency_all] == [0.25, 0.5, 0.75]
    assert [point.upper_bound_seconds for point in summary.latency_non_5xx] == [
        0.25,
        0.5,
        0.75,
    ]
    assert all(not point.overflow for point in summary.latency_all)
    assert summary.operational_snapshot_successes == 80_640
    assert summary.maximum_operational_snapshot_age_seconds == 60


def test_incomplete_evidence_reports_fixed_reasons_without_approving_it() -> None:
    evidence = _evidence()
    first = evidence.days[0].model_dump()
    first.update(
        {
            "telemetry_gap_seconds": 30,
            "sensitive_canary_matches": 1,
            "unexpected_metric_attributes": 1,
            "operational_snapshot_successes": 0,
            "operational_snapshot_max_age_seconds": None,
        }
    )
    payload = evidence.model_dump()
    payload["route_contract_sha256"] = "0" * 64
    payload["days"] = (DailyObservation.model_validate(first), *evidence.days[1:])

    summary = evaluate_baseline(BaselineEvidence.model_validate(payload))

    assert summary.status == "incomplete"
    assert summary.reasons == (
        "operational_snapshot_incomplete",
        "route_contract_mismatch",
        "sensitive_canary_detected",
        "telemetry_gap",
        "unexpected_metric_attributes",
    )
    assert summary.telemetry_gap_seconds == 30


def test_no_traffic_is_no_data_and_never_perfect_availability() -> None:
    summary = evaluate_baseline(_evidence(requests=0))

    assert summary.status == "incomplete"
    assert summary.reasons == ("no_eligible_requests",)
    assert summary.availability_ratio is None
    assert summary.days_without_traffic == BASELINE_WINDOW_DAYS
    assert all(point.upper_bound_seconds is None for point in summary.latency_all)
    assert all(not point.overflow for point in summary.latency_all)


def test_schema_rejects_partial_windows_inconsistent_counts_and_payload_fields() -> None:
    evidence = _evidence()
    payload = evidence.model_dump()
    payload["days"] = evidence.days[:-1]
    with pytest.raises(ValidationError, match="at least 28 items"):
        BaselineEvidence.model_validate(payload)

    invalid_day = evidence.days[0].model_dump()
    invalid_day["eligible_requests"] = 99
    with pytest.raises(ValidationError, match="histogram count must equal eligible"):
        DailyObservation.model_validate(invalid_day)

    with pytest.raises(ValidationError, match="exactly 15 bucket counts"):
        HistogramObservation(bucket_counts=(1,))

    with pytest.raises(ValidationError, match="non-negative"):
        HistogramObservation(bucket_counts=(*_EMPTY_BUCKETS[:-1], -1))

    payload = evidence.model_dump()
    payload["candidate_text"] = "must-not-enter-evidence"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        BaselineEvidence.model_validate(payload)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"server_error_requests": 101}, "server errors cannot exceed"),
        ({"client_error_requests": 100}, "client errors cannot exceed"),
        ({"latency_non_5xx": HistogramObservation(bucket_counts=_ALL_BUCKETS)}, "good requests"),
        (
            {
                "operational_snapshot_successes": 0,
                "operational_snapshot_max_age_seconds": 1.0,
            },
            "snapshot age requires",
        ),
        ({"operational_snapshot_max_age_seconds": None}, "successful snapshots require"),
    ],
)
def test_daily_evidence_relationships_fail_closed(updates: dict[str, object], message: str) -> None:
    payload = _evidence().days[0].model_dump()
    payload.update(updates)
    with pytest.raises(ValidationError, match=message):
        DailyObservation.model_validate(payload)


def test_window_order_and_release_cohort_uniqueness_are_enforced() -> None:
    evidence = _evidence()
    wrong_window = evidence.model_dump()
    wrong_window["window_end"] = evidence.window_end + timedelta(days=1)
    with pytest.raises(ValidationError, match="exactly 28 UTC days"):
        BaselineEvidence.model_validate(wrong_window)

    unordered = evidence.model_dump()
    unordered["days"] = (evidence.days[1], evidence.days[0], *evidence.days[2:])
    with pytest.raises(ValidationError, match="ordered, unique, and contiguous"):
        BaselineEvidence.model_validate(unordered)

    duplicate = evidence.model_dump()
    duplicate["releases"] = (*evidence.releases, evidence.releases[0])
    with pytest.raises(ValidationError, match="release cohorts must be unique"):
        BaselineEvidence.model_validate(duplicate)


def test_histogram_overflow_is_explicit_instead_of_inventing_a_latency() -> None:
    evidence = _evidence()
    overflow_all = HistogramObservation(bucket_counts=(*_EMPTY_BUCKETS[:-1], 100))
    overflow_good = HistogramObservation(bucket_counts=(*_EMPTY_BUCKETS[:-1], 99))
    days = []
    for observation in evidence.days:
        payload = observation.model_dump()
        payload["latency_all"] = overflow_all
        payload["latency_non_5xx"] = overflow_good
        days.append(DailyObservation.model_validate(payload))
    evidence_payload = evidence.model_dump()
    evidence_payload["days"] = tuple(days)

    summary = evaluate_baseline(BaselineEvidence.model_validate(evidence_payload))

    assert all(point.overflow for point in summary.latency_all)
    assert all(point.upper_bound_seconds is None for point in summary.latency_all)


def test_loader_is_size_bounded_and_cli_outputs_only_safe_results(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(_evidence().model_dump_json(), encoding="utf-8")
    assert load_baseline_evidence(evidence_path).environment == "staging"
    assert main(("evaluate", str(evidence_path))) == 0
    valid_output = json.loads(capsys.readouterr().out)
    assert valid_output["status"] == "eligible_for_review"
    assert "query_digest_sha256" not in valid_output

    evidence_path.write_text('{"password":"must-not-leak"}', encoding="utf-8")
    assert main(("evaluate", str(evidence_path))) == 2
    captured = capsys.readouterr()
    assert "must-not-leak" not in captured.err
    assert str(evidence_path) not in captured.err
    assert json.loads(captured.err) == {"error_type": "ValidationError", "status": "invalid"}

    missing_path = tmp_path / "missing.json"
    with pytest.raises(ValueError, match="regular file"):
        load_baseline_evidence(missing_path)

    incomplete_path = tmp_path / "incomplete.json"
    incomplete_path.write_text(_evidence(requests=0).model_dump_json(), encoding="utf-8")
    assert main(("evaluate", str(incomplete_path))) == 3
    assert json.loads(capsys.readouterr().out)["status"] == "incomplete"

    monkeypatch.setattr(baseline_module, "MAX_EVIDENCE_BYTES", 1)
    with pytest.raises(ValueError, match="maximum size"):
        load_baseline_evidence(evidence_path)

    assert main(("schema",)) == 0
    schema = json.loads(capsys.readouterr().out)
    assert schema["additionalProperties"] is False
