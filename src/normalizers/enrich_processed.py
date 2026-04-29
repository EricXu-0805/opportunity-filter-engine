"""
CLI: retroactively enrich data/processed/opportunities.json

Applies enricher to every opportunity that's missing majors/keywords.
Safe to run repeatedly — never overwrites real upstream data.

Usage:
    python3 -m src.normalizers.enrich_processed --dry-run
    python3 -m src.normalizers.enrich_processed --save
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from src.normalizers.enricher import enrich_all

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "opportunities.json"


def _audit(opps: list[dict]) -> dict:
    from src.normalizers.enricher import _is_unsorted  # reuse sentinel logic

    by_source: dict[str, Counter] = {}
    for o in opps:
        src = o.get("source", "?")
        b = by_source.setdefault(src, Counter())
        b["total"] += 1
        if not (o.get("eligibility", {}).get("majors") or []):
            b["empty_majors"] += 1
        if _is_unsorted(o.get("keywords") or []):
            b["empty_kw"] += 1
    return by_source


def _print_audit(title: str, audit: dict) -> None:
    print(f"\n{title}")
    print(f"{'source':<20s} {'total':>6s} {'empty_majors':>14s} {'empty_kw':>10s}")
    for src, c in sorted(audit.items()):
        print(f"{src:<20s} {c['total']:>6d} {c['empty_majors']:>14d} {c['empty_kw']:>10d}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--save", action="store_true", help="Write changes back to file")
    parser.add_argument("--dry-run", action="store_true", help="Show diff without writing")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        return 1

    with args.path.open("r", encoding="utf-8") as f:
        opps = json.load(f)

    print(f"Loaded {len(opps)} opportunities from {args.path}")
    _print_audit("BEFORE:", _audit(opps))

    majors_added, kws_added = enrich_all(opps)

    _print_audit("AFTER:", _audit(opps))
    print(f"\nEnriched: +{majors_added} majors, +{kws_added} keywords (out of {len(opps)} total)")

    if args.save and not args.dry_run:
        with args.path.open("w", encoding="utf-8") as f:
            json.dump(opps, f, indent=2, ensure_ascii=False, default=str)
        print(f"Saved to {args.path}")
    else:
        print("(dry-run — pass --save to persist)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
