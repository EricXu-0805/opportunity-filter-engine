#!/usr/bin/env python3
"""Write the frontend's static school-coverage fallback from the canonical count.

``frontend/src/lib/school-stats.json`` is what the university switcher shows
before the live fetch resolves, and what it keeps showing if that fetch fails.
It is therefore the same claim as the API's, made earlier — so it is generated
by calling the same function the API route calls
(``backend.lib.school_coverage.coverage_payload``) rather than by a second
implementation that counts the corpus its own way.

That second implementation is not hypothetical: this file used to be produced by
a Node script that counted every record with a ``school`` set — no release
scope, no actionability, no listing/faculty split — while the API served
listings only. Same school, same corpus, two numbers that differed by 100x, and
the chip swapped one for the other mid-render. Deriving both from one function
is the only version of "keep them in sync" that stays true without anyone
remembering to.

Python rather than the old Node prebuild hook because the filters that decide
which records count (``target_truth``, release scope) live in Python and are
real business logic. Reimplementing them in JS to serve a build step is how the
two definitions drifted apart the first time. The build now validates this file
instead of recomputing it (``frontend/scripts/gen-school-stats.mjs``), and
``tests/test_school_coverage.py`` fails if it goes stale against the shards.

Usage::

    python scripts/gen_school_stats.py          # write the file
    python scripts/gen_school_stats.py --check   # exit 1 if it is stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from backend.data_loader import load_opportunities  # noqa: E402
from backend.lib.release_scope import release_visible_opportunities  # noqa: E402
from backend.lib.school_coverage import coverage_payload  # noqa: E402
from backend.lib.target_actionability import actionable_opportunities  # noqa: E402

OUT_PATH = REPO_ROOT / "frontend" / "src" / "lib" / "school-stats.json"


def _national_count(opportunities: list[dict]) -> int:
    """Records that belong to no campus — the open pool every school also sees.

    Counted through the same filter stack as the per-school numbers so the
    switcher footer ("every school also sees N national opportunities") and the
    cards describe one universe. Not folded into any school's total: a shared
    pool added to each card would overstate every card and, summed across the
    grid, count itself 116 times.
    """
    records = actionable_opportunities(release_visible_opportunities(opportunities))
    return sum(
        1
        for record in records
        if not isinstance(record.get("school"), str) or not record["school"].strip()
        if (record.get("metadata") or {}).get("is_active") is not False
    )


def build_payload() -> dict:
    opportunities = load_opportunities()
    payload = coverage_payload(opportunities)
    payload["national_count"] = _national_count(opportunities)
    return payload


def render(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if the committed file is stale.",
    )
    args = parser.parse_args()

    rendered = render(build_payload())

    if args.check:
        current = OUT_PATH.read_text() if OUT_PATH.exists() else ""
        if current != rendered:
            print(
                f"school-stats: {OUT_PATH.relative_to(REPO_ROOT)} is stale — "
                "run `python scripts/gen_school_stats.py`.",
                file=sys.stderr,
            )
            return 1
        print("school-stats: committed file matches the corpus.")
        return 0

    OUT_PATH.write_text(rendered)
    payload = json.loads(rendered)
    schools = payload["schools"]
    print(
        f"school-stats: {len(schools)} schools, "
        f"{sum(s['total_count'] for s in schools.values())} campus records "
        f"(listings + faculty contacts), national={payload['national_count']} "
        f"-> {OUT_PATH.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
