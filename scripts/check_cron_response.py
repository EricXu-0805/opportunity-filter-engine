#!/usr/bin/env python3
"""Fail a cron workflow step when the response body reports silent failures.

W15. The reminder and saved-search crons return HTTP 200 even when work
failed inside the batch: `curl -sf` only inspects the status line, so the
W14 bookkeeping counters (a silently-failed `remind_at` clear re-sends the
same reminder every single day) and the digest's `status: "partial"` were
reachable only in Render's stdout. The workflow went green and the
`if: failure()` operator alert never fired.

Reads the JSON body on stdin. Exit 1 — failing the step, which triggers the
existing operator-alert job — when any failure signal is present.

Usage:  curl ... | python3 scripts/check_cron_response.py
"""
from __future__ import annotations

import json
import sys

# Counters whose non-zero value means work was lost, will be duplicated, or
# never became visible. `incident_errors` (W15) counts failures the cron could
# not record into the operator queue — the same class of silence this checker
# exists to break, so it fails the step too.
_FAILURE_COUNTERS = ("bookkeeping_failed", "row_errors", "failed", "incident_errors")
_MAX_ERRORS_SHOWN = 5


def check(payload: dict) -> list[str]:
    """Human-readable failure signals found in a cron response body."""
    problems: list[str] = []
    for key in _FAILURE_COUNTERS:
        value = payload.get(key)
        if isinstance(value, int) and value > 0:
            problems.append(f"{key}={value}")
    if payload.get("status") == "partial":
        problems.append("status=partial")
    errors = payload.get("errors")
    if isinstance(errors, list):
        problems.extend(str(e)[:200] for e in errors[:_MAX_ERRORS_SHOWN])
    return problems


def main() -> int:
    raw = sys.stdin.read().strip()
    if not raw:
        print("::warning::empty cron response body — cannot check for silent failures")
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("::warning::cron response was not JSON — cannot check for silent failures")
        return 0
    if not isinstance(payload, dict):
        return 0

    # A skipped run (missing env) is not a failure.
    if payload.get("status") == "skipped":
        print(f"cron skipped: {payload.get('reason', 'unspecified')}")
        return 0

    problems = check(payload)
    if problems:
        print("::error::cron reported failures: " + "; ".join(problems))
        return 1
    print("cron response clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
