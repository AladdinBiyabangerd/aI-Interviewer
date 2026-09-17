#!/usr/bin/env python3
"""Smoke-check a portal-issued access token against GET /api/v1/identity/me.

Usage:
  ACCESS_TOKEN=<at+jwt> \\
  INTERVIEW_API_BASE_URL=http://127.0.0.1:8001 \\
  uv run python scripts/smoke_portal_oidc.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    token = os.environ.get("ACCESS_TOKEN", "").strip()
    base = os.environ.get("INTERVIEW_API_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    if not token:
        print("ACCESS_TOKEN is required", file=sys.stderr)
        return 2

    url = f"{base}/api/v1/identity/me"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            print(body)
            data = json.loads(body)
            if "account_id" not in data:
                print("response missing account_id", file=sys.stderr)
                return 1
            return 0
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"request failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
