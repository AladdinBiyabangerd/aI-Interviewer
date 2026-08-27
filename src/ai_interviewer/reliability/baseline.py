"""Strict, payload-free evidence and calculations for a staging SLI baseline."""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ai_interviewer.core.reliability import (
    HTTP_DURATION_BUCKETS_SECONDS,
    product_route_contract_digest,
)

BASELINE_WINDOW_DAYS = 28
MAX_EVIDENCE_BYTES = 2 * 1024 * 1024

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ReleaseId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
]
ReleaseRevision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
SafeComponent = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"),
]
IneligibilityReason = Literal[
    "no_eligible_requests",
    "operational_snapshot_incomplete",
    "route_contract_mismatch",
    "sensitive_canary_detected",
    "telemetry_gap",
    "unexpected_metric_attributes",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ReleaseCohort(_StrictModel):
    release_id: ReleaseId
    release_revision: ReleaseRevision


class CollectionEvidence(_StrictModel):
    source_kind: Literal["monitoring-backend-export"]
    backend_type: SafeComponent
    backend_version: SafeComponent
    collector_version: SafeComponent
    metric_temporality: Literal["delta", "cumulative"]
    export_interval_seconds: int = Field(ge=5, le=300)
    monitor_interval_seconds: int = Field(ge=5, le=300)
    query_digest_sha256: Sha256Digest
    export_digest_sha256: Sha256Digest


class HistogramObservation(_StrictModel):
    """Per-bucket counts for the fixed explicit bounds, followed by +Inf."""

    bucket_counts: tuple[int, ...]

    @model_validator(mode="after")
    def validate_bucket_contract(self) -> Self:
        expected = len(HTTP_DURATION_BUCKETS_SECONDS) + 1
        if len(self.bucket_counts) != expected:
            raise ValueError(f"histogram requires exactly {expected} bucket counts")
        if any(count < 0 for count in self.bucket_counts):
            raise ValueError("histogram bucket counts must be non-negative")
        return self

    @property
    def count(self) -> int:
        return sum(self.bucket_counts)


class DailyObservation(_StrictModel):
    day: date
    eligible_requests: int = Field(ge=0)
    server_error_requests: int = Field(ge=0)
    client_error_requests: int = Field(ge=0)
    latency_all: HistogramObservation
    latency_non_5xx: HistogramObservation
    telemetry_gap_seconds: int = Field(ge=0, le=86_400)
    sensitive_canary_matches: int = Field(ge=0)
    unexpected_metric_attributes: int = Field(ge=0)
    operational_snapshot_successes: int = Field(ge=0)
    operational_snapshot_errors: int = Field(ge=0)
    operational_snapshot_max_age_seconds: float | None = Field(default=None, ge=0)
    process_restarts: int = Field(ge=0)
    counter_resets: int = Field(ge=0)
    deployments: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_daily_counts(self) -> Self:
        if self.server_error_requests > self.eligible_requests:
            raise ValueError("server errors cannot exceed eligible requests")
        if self.client_error_requests > self.eligible_requests - self.server_error_requests:
            raise ValueError("client errors cannot exceed non-5xx requests")
        if self.latency_all.count != self.eligible_requests:
            raise ValueError("all-request histogram count must equal eligible requests")
        if self.latency_non_5xx.count != self.eligible_requests - self.server_error_requests:
            raise ValueError("non-5xx histogram count must equal good requests")
        if self.operational_snapshot_successes == 0:
            if self.operational_snapshot_max_age_seconds is not None:
                raise ValueError("snapshot age requires a successful snapshot")
        elif self.operational_snapshot_max_age_seconds is None:
            raise ValueError("successful snapshots require a maximum last-success age")
        return self


class BaselineEvidence(_StrictModel):
    schema_version: Literal[1]
    contract_version: Literal["0d-c-a-v1"]
    service_name: Literal["ai-interviewer-api"]
    environment: Literal["staging"]
    synthetic_only: Literal[True]
    window_start: date
    window_end: date
    route_contract_sha256: Sha256Digest
    collection: CollectionEvidence
    releases: tuple[ReleaseCohort, ...] = Field(min_length=1, max_length=32)
    days: tuple[DailyObservation, ...] = Field(
        min_length=BASELINE_WINDOW_DAYS,
        max_length=BASELINE_WINDOW_DAYS,
    )

    @model_validator(mode="after")
    def validate_window_and_cohorts(self) -> Self:
        if self.window_end - self.window_start != timedelta(days=BASELINE_WINDOW_DAYS):
            raise ValueError("baseline window must contain exactly 28 UTC days")
        expected_days = tuple(
            self.window_start + timedelta(days=offset) for offset in range(BASELINE_WINDOW_DAYS)
        )
        if tuple(observation.day for observation in self.days) != expected_days:
            raise ValueError("baseline observations must be ordered, unique, and contiguous")
        cohort_keys = {(cohort.release_id, cohort.release_revision) for cohort in self.releases}
        if len(cohort_keys) != len(self.releases):
            raise ValueError("release cohorts must be unique")
        return self


class QuantileEstimate(_StrictModel):
    quantile: Literal["p50", "p95", "p99"]
    upper_bound_seconds: float | None
    overflow: bool


class BaselineSummary(_StrictModel):
    schema_version: Literal[1] = 1
    status: Literal["eligible_for_review", "incomplete"]
    contract_version: Literal["0d-c-a-v1"]
    window_start: date
    window_end: date
    eligible_requests: int
    good_requests: int
    server_error_requests: int
    client_error_requests: int
    availability_ratio: float | None
    average_requests_per_day: float
    minimum_daily_requests: int
    maximum_daily_requests: int
    days_without_traffic: int
    latency_all: tuple[QuantileEstimate, ...]
    latency_non_5xx: tuple[QuantileEstimate, ...]
    telemetry_gap_seconds: int
    operational_snapshot_successes: int
    operational_snapshot_errors: int
    maximum_operational_snapshot_age_seconds: float | None
    process_restarts: int
    counter_resets: int
    deployments: int
    reasons: tuple[IneligibilityReason, ...]


def _quantiles(bucket_counts: tuple[int, ...]) -> tuple[QuantileEstimate, ...]:
    total = sum(bucket_counts)
    estimates: list[QuantileEstimate] = []
    quantiles: tuple[tuple[Literal["p50", "p95", "p99"], float], ...] = (
        ("p50", 0.5),
        ("p95", 0.95),
        ("p99", 0.99),
    )
    for name, quantile in quantiles:
        if total == 0:
            estimates.append(
                QuantileEstimate(
                    quantile=name,
                    upper_bound_seconds=None,
                    overflow=False,
                )
            )
            continue
        target = math.ceil(total * quantile)
        cumulative = 0
        selected_index = len(bucket_counts) - 1
        for index, count in enumerate(bucket_counts):
            cumulative += count
            if cumulative >= target:
                selected_index = index
                break
        overflow = selected_index == len(HTTP_DURATION_BUCKETS_SECONDS)
        estimates.append(
            QuantileEstimate(
                quantile=name,
                upper_bound_seconds=(
                    None if overflow else HTTP_DURATION_BUCKETS_SECONDS[selected_index]
                ),
                overflow=overflow,
            )
        )
    return tuple(estimates)


def evaluate_baseline(evidence: BaselineEvidence) -> BaselineSummary:
    totals = [observation.eligible_requests for observation in evidence.days]
    eligible_requests = sum(totals)
    server_errors = sum(observation.server_error_requests for observation in evidence.days)
    good_requests = eligible_requests - server_errors
    all_buckets = tuple(
        sum(observation.latency_all.bucket_counts[index] for observation in evidence.days)
        for index in range(len(HTTP_DURATION_BUCKETS_SECONDS) + 1)
    )
    good_buckets = tuple(
        sum(observation.latency_non_5xx.bucket_counts[index] for observation in evidence.days)
        for index in range(len(HTTP_DURATION_BUCKETS_SECONDS) + 1)
    )
    telemetry_gap_seconds = sum(observation.telemetry_gap_seconds for observation in evidence.days)
    reasons: list[IneligibilityReason] = []
    if eligible_requests == 0:
        reasons.append("no_eligible_requests")
    if any(observation.operational_snapshot_successes == 0 for observation in evidence.days):
        reasons.append("operational_snapshot_incomplete")
    if evidence.route_contract_sha256 != product_route_contract_digest():
        reasons.append("route_contract_mismatch")
    if any(observation.sensitive_canary_matches for observation in evidence.days):
        reasons.append("sensitive_canary_detected")
    if telemetry_gap_seconds:
        reasons.append("telemetry_gap")
    if any(observation.unexpected_metric_attributes for observation in evidence.days):
        reasons.append("unexpected_metric_attributes")

    snapshot_ages = [
        observation.operational_snapshot_max_age_seconds
        for observation in evidence.days
        if observation.operational_snapshot_max_age_seconds is not None
    ]
    return BaselineSummary(
        status="eligible_for_review" if not reasons else "incomplete",
        contract_version=evidence.contract_version,
        window_start=evidence.window_start,
        window_end=evidence.window_end,
        eligible_requests=eligible_requests,
        good_requests=good_requests,
        server_error_requests=server_errors,
        client_error_requests=sum(
            observation.client_error_requests for observation in evidence.days
        ),
        availability_ratio=(good_requests / eligible_requests if eligible_requests else None),
        average_requests_per_day=eligible_requests / BASELINE_WINDOW_DAYS,
        minimum_daily_requests=min(totals),
        maximum_daily_requests=max(totals),
        days_without_traffic=sum(total == 0 for total in totals),
        latency_all=_quantiles(all_buckets),
        latency_non_5xx=_quantiles(good_buckets),
        telemetry_gap_seconds=telemetry_gap_seconds,
        operational_snapshot_successes=sum(
            observation.operational_snapshot_successes for observation in evidence.days
        ),
        operational_snapshot_errors=sum(
            observation.operational_snapshot_errors for observation in evidence.days
        ),
        maximum_operational_snapshot_age_seconds=max(snapshot_ages, default=None),
        process_restarts=sum(observation.process_restarts for observation in evidence.days),
        counter_resets=sum(observation.counter_resets for observation in evidence.days),
        deployments=sum(observation.deployments for observation in evidence.days),
        reasons=tuple(reasons),
    )


def load_baseline_evidence(path: Path) -> BaselineEvidence:
    """Load a bounded local evidence export without logging its path or contents."""
    if not path.is_file():
        raise ValueError("baseline evidence must be a regular file")
    with path.open("rb") as evidence_file:
        payload = evidence_file.read(MAX_EVIDENCE_BYTES + 1)
    if len(payload) > MAX_EVIDENCE_BYTES:
        raise ValueError("baseline evidence exceeds the maximum size")
    return BaselineEvidence.model_validate_json(payload)
