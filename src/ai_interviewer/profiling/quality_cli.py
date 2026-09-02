"""Offline CLI for the labeled profile quality and approval gates."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ai_interviewer.core.config import Settings
from ai_interviewer.model_gateway import ModelGatewayRuntime, build_model_gateway
from ai_interviewer.profiling.development_corpus import (
    build_development_profile_corpus,
    development_corpus_source_coordinates,
)
from ai_interviewer.profiling.quality import (
    ProfileQualityApproval,
    ProfileQualityEvidence,
    evaluate_profile_quality,
    evaluate_profile_quality_gate,
    load_profile_quality_approval,
    load_profile_quality_evidence,
    profile_quality_evidence_sha256,
    profile_quality_prompt_contract_sha256,
)
from ai_interviewer.profiling.quality_run import (
    ProfileQualityCorpus,
    ProfileQualityPredictionRun,
    ProfileQualityReviewDraft,
    ProfileQualityRunAuthorization,
    finalize_profile_quality_review,
    generate_profile_quality_predictions,
    load_profile_quality_corpus,
    load_profile_quality_prediction_run,
    load_profile_quality_review_draft,
    load_profile_quality_run_authorization,
    preflight_profile_quality_run,
    prepare_profile_quality_review_draft,
    profile_quality_prediction_run_sha256,
    summarize_profile_quality_corpus,
    write_private_quality_artifact,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-interviewer-profile-quality")
    subcommands = parser.add_subparsers(dest="command", required=True)
    evaluate = subcommands.add_parser("evaluate", help="evaluate labeled profile evidence")
    evaluate.add_argument("evidence", type=Path)
    gate = subcommands.add_parser("gate", help="verify evidence and named approvals")
    gate.add_argument("evidence", type=Path)
    gate.add_argument("approval", type=Path)
    schema = subcommands.add_parser("schema", help="print a strict JSON schema")
    schema.add_argument(
        "kind",
        choices=(
            "corpus",
            "authorization",
            "predictions",
            "review-draft",
            "evidence",
            "approval",
        ),
    )
    generate = subcommands.add_parser(
        "generate",
        help="generate predictions from an explicitly authorized private corpus",
    )
    generate.add_argument("corpus", type=Path)
    generate.add_argument("authorization", type=Path)
    generate.add_argument("output", type=Path)
    generate.add_argument(
        "--confirm-external-processing",
        action="store_true",
        help="confirm that this exact approved corpus may be sent to the provider",
    )
    preflight = subcommands.add_parser(
        "preflight",
        help="validate an exact corpus authorization without contacting the provider",
    )
    preflight.add_argument("corpus", type=Path)
    preflight.add_argument("authorization", type=Path)
    validate_corpus = subcommands.add_parser(
        "validate-corpus",
        help="report payload-free corpus structural readiness without granting approval",
    )
    validate_corpus.add_argument("corpus", type=Path)
    development_corpus = subcommands.add_parser(
        "build-development-corpus",
        help="create the repository-safe O*NET-derived development corpus",
    )
    development_corpus.add_argument("output", type=Path)
    review = subcommands.add_parser(
        "prepare-review",
        help="join corpus and predictions into an unadjudicated private draft",
    )
    review.add_argument("corpus", type=Path)
    review.add_argument("predictions", type=Path)
    review.add_argument("output", type=Path)
    finalize = subcommands.add_parser(
        "finalize-review",
        help="bind a completed human review to the exact corpus and predictions",
    )
    finalize.add_argument("corpus", type=Path)
    finalize.add_argument("predictions", type=Path)
    finalize.add_argument("review", type=Path)
    finalize.add_argument("output", type=Path)
    subcommands.add_parser("prompt-digest", help="print the current prompt contract digest")
    return parser


def _schema_type(kind: str) -> type[BaseModel]:
    model_types: dict[str, type[BaseModel]] = {
        "corpus": ProfileQualityCorpus,
        "authorization": ProfileQualityRunAuthorization,
        "predictions": ProfileQualityPredictionRun,
        "review-draft": ProfileQualityReviewDraft,
        "evidence": ProfileQualityEvidence,
        "approval": ProfileQualityApproval,
    }
    return model_types[kind]


def _require_new_output_path(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError("quality artifact output path already exists")


def main(
    argv: Sequence[str] | None = None,
    *,
    gateway: ModelGatewayRuntime | None = None,
    now: datetime | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "schema":
        model_type = _schema_type(args.kind)
        print(json.dumps(model_type.model_json_schema(), sort_keys=True))
        return 0
    if args.command == "prompt-digest":
        print(profile_quality_prompt_contract_sha256())
        return 0
    try:
        if args.command == "build-development-corpus":
            _require_new_output_path(args.output)
            corpus = build_development_profile_corpus()
            artifact_digest = write_private_quality_artifact(args.output, corpus)
            corpus_summary = summarize_profile_quality_corpus(corpus)
            print(
                json.dumps(
                    {
                        "artifact_sha256": artifact_digest,
                        "fixture_count": corpus_summary.fixture_count,
                        "source_coordinate_count": len(development_corpus_source_coordinates()),
                        "status": "development_corpus_created",
                        "structural_status": corpus_summary.status,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "validate-corpus":
            corpus = load_profile_quality_corpus(args.corpus)
            corpus_summary = summarize_profile_quality_corpus(corpus)
            print(json.dumps(corpus_summary.model_dump(mode="json"), sort_keys=True))
            return 0 if corpus_summary.status == "structurally_ready" else 3
        if args.command == "preflight":
            corpus = load_profile_quality_corpus(args.corpus)
            authorization = load_profile_quality_run_authorization(args.authorization)
            result = preflight_profile_quality_run(
                corpus,
                authorization,
                now=now or datetime.now(UTC),
            )
            print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
            return 0
        if args.command == "generate":
            if not args.confirm_external_processing:
                raise ValueError("external processing confirmation is required")
            _require_new_output_path(args.output)
            corpus = load_profile_quality_corpus(args.corpus)
            authorization = load_profile_quality_run_authorization(args.authorization)
            runtime = gateway if gateway is not None else build_model_gateway(Settings())
            run = asyncio.run(
                generate_profile_quality_predictions(
                    corpus,
                    authorization,
                    runtime,
                    now=now or datetime.now(UTC),
                )
            )
            artifact_digest = write_private_quality_artifact(args.output, run)
            failure_count = sum(
                record.prediction.result_type == "failure" for record in run.fixtures
            )
            print(
                json.dumps(
                    {
                        "artifact_sha256": artifact_digest,
                        "failure_count": failure_count,
                        "fixture_count": len(run.fixtures),
                        "run_sha256": profile_quality_prediction_run_sha256(run),
                        "status": run.status,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "prepare-review":
            _require_new_output_path(args.output)
            corpus = load_profile_quality_corpus(args.corpus)
            run = load_profile_quality_prediction_run(args.predictions)
            draft = prepare_profile_quality_review_draft(corpus, run)
            artifact_digest = write_private_quality_artifact(args.output, draft)
            print(
                json.dumps(
                    {
                        "artifact_sha256": artifact_digest,
                        "fixture_count": len(draft.fixtures),
                        "status": "awaiting_human_adjudication",
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "finalize-review":
            _require_new_output_path(args.output)
            corpus = load_profile_quality_corpus(args.corpus)
            run = load_profile_quality_prediction_run(args.predictions)
            review = load_profile_quality_review_draft(args.review)
            evidence = finalize_profile_quality_review(corpus, run, review)
            artifact_digest = write_private_quality_artifact(args.output, evidence)
            print(
                json.dumps(
                    {
                        "artifact_sha256": artifact_digest,
                        "evidence_sha256": profile_quality_evidence_sha256(evidence),
                        "fixture_count": len(evidence.fixtures),
                        "status": "ready_for_evaluation",
                    },
                    sort_keys=True,
                )
            )
            return 0
        evidence = load_profile_quality_evidence(args.evidence)
        if args.command == "evaluate":
            summary = evaluate_profile_quality(evidence)
            print(json.dumps(summary.model_dump(mode="json"), sort_keys=True))
            return 0 if summary.status == "eligible_for_approval" else 3
        approval = load_profile_quality_approval(args.approval)
        decision = evaluate_profile_quality_gate(evidence, approval)
        print(json.dumps(decision.model_dump(mode="json"), sort_keys=True))
        return 0 if decision.status == "approved" else 4
    except (OSError, RuntimeError, ValueError, ValidationError) as exc:
        print(
            json.dumps({"error_type": type(exc).__name__, "status": "invalid"}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":  # pragma: no cover - console entry point owns process exit
    raise SystemExit(main())
