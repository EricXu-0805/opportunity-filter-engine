"""Auto-deactivate opportunities whose deadline has passed.

Runs after every refresh. Idempotent: opps already marked inactive stay inactive,
opps newly past-deadline get `metadata.is_active = False`, opps with rolling
deadlines or no deadline are left alone.

Also records `metadata.deactivated_at` (UTC ISO date) the first time we mark
something inactive, so the admin dashboard can surface freshly-expired entries.

Usage:
    python3 -m src.normalizers.deactivate_past --dry-run
    python3 -m src.normalizers.deactivate_past --save
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .deadlines import parse_to_date as _parse_deadline

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "opportunities.json"


def deactivate_past(opps: list[dict], today: date | None = None) -> dict:
    """Mark opportunities past their deadline as inactive (in place).

    Skip rolling deadlines, no-deadline entries, and unparseable formats.
    Returns counts dict: {newly_deactivated, already_inactive, kept_active,
                           skipped_rolling, skipped_no_deadline, skipped_invalid}.
    """
    today = today or date.today()
    counts = {
        "newly_deactivated": 0,
        "already_inactive": 0,
        "kept_active": 0,
        "skipped_rolling": 0,
        "skipped_no_deadline": 0,
        "skipped_invalid": 0,
    }

    for opp in opps:
        meta = opp.setdefault("metadata", {})

        if opp.get("is_rolling"):
            counts["skipped_rolling"] += 1
            continue

        raw_deadline = opp.get("deadline")
        if not raw_deadline:
            counts["skipped_no_deadline"] += 1
            continue

        parsed = _parse_deadline(raw_deadline)
        if parsed is None:
            counts["skipped_invalid"] += 1
            continue

        if parsed < today:
            if meta.get("is_active") is False:
                counts["already_inactive"] += 1
            else:
                meta["is_active"] = False
                meta.setdefault("deactivated_at", today.isoformat())
                meta["deactivation_reason"] = "deadline_passed"
                counts["newly_deactivated"] += 1
        else:
            counts["kept_active"] += 1

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--save", action="store_true", help="Write changes back to file")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without writing")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        return 1

    with args.path.open("r", encoding="utf-8") as f:
        opps = json.load(f)

    counts = deactivate_past(opps)

    print(f"Loaded {len(opps)} opportunities from {args.path}")
    for key in (
        "newly_deactivated",
        "already_inactive",
        "kept_active",
        "skipped_rolling",
        "skipped_no_deadline",
        "skipped_invalid",
    ):
        print(f"  {key:<22s} {counts[key]:>6d}")

    if args.save and not args.dry_run:
        with args.path.open("w", encoding="utf-8") as f:
            json.dump(opps, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nSaved to {args.path}")
    else:
        print("\n(dry-run — pass --save to persist)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
