#!/usr/bin/env python3
"""Emit a one-shot ApplicationKeyring JSON document for hosted deploys."""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys


def _material() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print a single-line JSON document (Railway/Vercel env paste).",
    )
    args = parser.parse_args(argv)
    document = {
        "version": 1,
        "active": {
            "subject_hmac": "subject-v1",
            "field_encryption": "field-v1",
            "manifest_hmac": "manifest-v1",
        },
        "keys": [
            {"id": "subject-v1", "purpose": "subject_hmac", "material": _material()},
            {"id": "field-v1", "purpose": "field_encryption", "material": _material()},
            {"id": "manifest-v1", "purpose": "manifest_hmac", "material": _material()},
        ],
    }
    if args.compact:
        sys.stdout.write(json.dumps(document, separators=(",", ":")))
    else:
        json.dump(document, sys.stdout, indent=2)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
