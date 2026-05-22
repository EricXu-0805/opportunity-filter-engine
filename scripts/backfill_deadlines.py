"""One-shot data backfill: re-normalize every deadline in opportunities.json.

Runs ``src.normalizers.deadlines.reclassify_opportunity`` over each record
and prints a summary grouped by parsed type. Use ``--save`` to persist;
default is dry-run.

This script was created to fix the 278 ``"?Yes"``/``"?No"`` records leaked
by the historical ``td.views-field-nothing`` SRO selector bug (see the
commit that landed the new normalizer for the full root-cause analysis).
It is intentionally idempotent — running it again after a clean refresh
is a no-op.

Usage:
    python3 scripts/backfill_deadlines.py            # dry run
    python3 scripts/backfill_deadlines.py --save     # write changes
    python3 scripts/backfill_deadlines.py --save --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.normalizers.deadlines import reclassify_opportunity  # noqa: E402

DEFAULT_PATH = PROJECT_ROOT / "data" / "processed" / "opportunities.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--save", action="store_true", help="Persist changes to disk")
    parser.add_argument("--verbose", action="store_true", help="Print every changed record")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"ERROR: {args.path} does not exist", file=sys.stderr)
        return 1

    with args.path.open("r", encoding="utf-8") as f:
        opps = json.load(f)

    by_type: Counter[str] = Counter()
    by_source_changed: Counter[str] = Counter()
    changed_examples: list[dict] = []
    changed_count = 0

    for opp in opps:
        report = reclassify_opportunity(opp)
        by_type[report["parsed_type"]] += 1
        if report["changed"]:
            changed_count += 1
            src = opp.get("source", "?")
            by_source_changed[src] += 1
            if args.verbose or len(changed_examples) < 15:
                changed_examples.append({
                    "id": opp.get("id", "?"),
                    "source": src,
                    "raw": report["raw"],
                    "parsed_type": report["parsed_type"],
                    "old_deadline": report["old_deadline"],
                    "new_deadline": report["new_deadline"],
                    "new_is_rolling": report["new_is_rolling"],
                })

    print(f"Loaded {len(opps)} opportunities from {args.path}")
    print()
    print("Parsed type distribution (all records):")
    for t, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t:<14s} {cnt:>5d}")
    print()
    print(f"Records changed: {changed_count}")
    if by_source_changed:
        print("Changes by source:")
        for src, cnt in by_source_changed.most_common():
            print(f"  {src:<25s} {cnt:>5d}")
    print()
    print(f"First {len(changed_examples)} changed records:")
    for ex in changed_examples:
        rolling_note = " (is_rolling=True)" if ex["new_is_rolling"] else ""
        print(
            f"  [{ex['source']}] {ex['id'][:12]:<14s} "
            f"{ex['raw']!r:30s} → {ex['new_deadline']!r}{rolling_note} "
            f"({ex['parsed_type']})"
        )

    if args.save:
        with args.path.open("w", encoding="utf-8") as f:
            json.dump(opps, f, indent=2, ensure_ascii=False, default=str)
        print(f"\n✓ Saved {len(opps)} records to {args.path}")
    else:
        print("\n(dry-run — pass --save to persist)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
