"""Offline command for validating and summarizing aggregated staging evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from ai_interviewer.reliability.baseline import (
    BaselineEvidence,
    evaluate_baseline,
    load_baseline_evidence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-interviewer-baseline")
    subcommands = parser.add_subparsers(dest="command", required=True)
    evaluate = subcommands.add_parser("evaluate", help="validate and summarize evidence")
    evaluate.add_argument("evidence", type=Path)
    subcommands.add_parser("schema", help="print the strict JSON input schema")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "schema":
        print(json.dumps(BaselineEvidence.model_json_schema(), sort_keys=True))
        return 0
    try:
        evidence = load_baseline_evidence(args.evidence)
        summary = evaluate_baseline(evidence)
    except (OSError, ValueError, ValidationError) as exc:
        print(
            json.dumps({"error_type": type(exc).__name__, "status": "invalid"}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary.model_dump(mode="json"), sort_keys=True))
    return 0 if summary.status == "eligible_for_review" else 3


if __name__ == "__main__":  # pragma: no cover - console entry point owns process exit
    raise SystemExit(main())
