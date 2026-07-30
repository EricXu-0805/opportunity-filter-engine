#!/usr/bin/env python3
"""Verify that a refresh PR is bound to the reviewed commits and CI checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

REQUIRED_CHECKS = (
    "Backend (lint + pytest)",
    "Frontend (typecheck + build)",
    "Migrations (Flow B merge + CLI replay)",
    "E2E (Playwright)",
)
_SHA_RE = re.compile(r"[0-9a-f]{40}")


def verify_snapshot(
    snapshot: object,
    *,
    expected_head: str,
    expected_base: str,
    require_success: bool = True,
) -> dict[str, str]:
    """Validate one ``gh pr view --json`` snapshot.

    A green check for an older head or base is not evidence for the candidate
    being merged. Each required check must appear exactly once; when
    success is required by default. ``require_success=False`` is reserved for
    an explicit registration-only wait that must never authorize a merge.
    """

    if not isinstance(snapshot, dict):
        raise ValueError("PR snapshot must be an object")
    for label, value in (("head", expected_head), ("base", expected_base)):
        if _SHA_RE.fullmatch(value) is None:
            raise ValueError(f"expected {label} SHA is invalid")
    if snapshot.get("headRefOid") != expected_head:
        raise ValueError("PR head SHA does not match the pushed candidate")
    if snapshot.get("baseRefOid") != expected_base:
        raise ValueError("PR base SHA moved or does not match the reviewed base")

    rollup = snapshot.get("statusCheckRollup")
    if not isinstance(rollup, list):
        raise ValueError("PR check rollup is missing")
    named = [
        check
        for check in rollup
        if isinstance(check, dict) and isinstance(check.get("name"), str)
    ]
    counts = Counter(check["name"] for check in named)
    missing = [name for name in REQUIRED_CHECKS if counts[name] == 0]
    duplicate = [name for name in REQUIRED_CHECKS if counts[name] > 1]
    if missing or duplicate:
        raise ValueError(
            f"required check registration mismatch; "
            f"missing={missing}, duplicate={duplicate}"
        )

    conclusions: dict[str, str] = {}
    for name in REQUIRED_CHECKS:
        check = next(candidate for candidate in named if candidate["name"] == name)
        status = str(check.get("status") or "").upper()
        conclusion = str(check.get("conclusion") or "").upper()
        conclusions[name] = conclusion or status
        if require_success and (
            status != "COMPLETED" or conclusion != "SUCCESS"
        ):
            raise ValueError(
                f"required check is not a completed success: "
                f"{name} status={status!r} conclusion={conclusion!r}"
            )
    return conclusions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument(
        "--registration-only",
        action="store_true",
        help="verify check registration only; never use this result to merge",
    )
    args = parser.parse_args(argv)
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        conclusions = verify_snapshot(
            snapshot,
            expected_head=args.head,
            expected_base=args.base,
            require_success=not args.registration_only,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    for name, conclusion in conclusions.items():
        print(f"{name}: {conclusion or 'registered'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
