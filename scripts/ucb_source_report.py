"""Reporting + output for the UC Berkeley campus opportunity graph.

Produces the three artifacts the product surfaces:

  1. Structured opportunity list (JSON)  — the campus records, schema-normalized.
  2. Ranked feed for users               — rank_all over those records for a
                                            neutral Berkeley undergraduate profile.
  3. Source breakdown                    — what each source/level contributed.

Stdlib + the in-repo matcher only (no network). Reads the live corpus when
present, else regenerates the seed records on the fly.

Usage:
    python -m scripts.ucb_source_report                 # print all three
    python -m scripts.ucb_source_report --write         # also write JSON artifacts
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.collectors import ucb_campus

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
OUT_DIR = PROJECT_ROOT / "data" / "processed"

CAMPUS_SOURCES = set(ucb_campus.EMIT_TO_SCHOOL_AUDIENCE[k][0]
                     for k in ucb_campus.EMIT_TO_SCHOOL_AUDIENCE)

# A neutral Berkeley undergraduate so the ranked feed is meaningful without a
# real user. home_school='ucb' so the campus-audience records are in scope.
NEUTRAL_PROFILE = {
    "year": "junior",
    "major": "Computer Science",
    "home_school": "ucb",
    "secondary_interests": ["Data Science"],
    "seeking_type": ["research", "summer_program"],
    "research_interests_text": "machine learning and data science research",
    "hard_skills": [{"name": "Python", "level": "experienced"}],
    "international_student": False,
    "exploring": False,
    "preferences": {},
}


def _load_campus_records() -> list[dict]:
    if PROCESSED_FILE.exists():
        with PROCESSED_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        campus = [o for o in data if o.get("source") in CAMPUS_SOURCES]
        if campus:
            return campus
    # Fall back to a fresh seed generation (offline).
    return ucb_campus.fetch_and_normalize(deep=False)


def build_report(write: bool = False) -> dict:
    records = _load_campus_records()
    breakdown = ucb_campus.source_breakdown(records)

    # Ranked feed (lazy import keeps the matcher off the import path unless used).
    from src.matcher.ranker import rank_all
    ranked = rank_all(NEUTRAL_PROFILE, records)
    by_id = {o["id"]: o for o in records}
    feed = [
        {
            "rank": i + 1,
            "id": r.opportunity_id,
            "title": by_id.get(r.opportunity_id, {}).get("title", ""),
            "ucb_source_type": by_id.get(r.opportunity_id, {}).get("ucb_source_type", ""),
            "opportunity_type": by_id.get(r.opportunity_id, {}).get("opportunity_type", ""),
            "score": r.final_score,
            "bucket": r.bucket,
            "url": by_id.get(r.opportunity_id, {}).get("url", ""),
            "top_reason": (r.reasons_fit[0] if r.reasons_fit else ""),
        }
        for i, r in enumerate(ranked)
    ]

    report = {"breakdown": breakdown, "feed": feed, "count": len(records)}

    if write:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / "ucb_campus_records.json").write_text(
            json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        (OUT_DIR / "ucb_campus_feed.json").write_text(
            json.dumps(feed, indent=2, ensure_ascii=False), encoding="utf-8")
        (OUT_DIR / "ucb_source_breakdown.json").write_text(
            json.dumps(breakdown, indent=2, ensure_ascii=False), encoding="utf-8")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write JSON artifacts to data/processed/")
    args = parser.parse_args()

    report = build_report(write=args.write)
    ucb_campus._print_report(_load_campus_records())

    print("\nTOP 15 RANKED FEED (neutral Berkeley CS junior):")
    print("-" * 60)
    for row in report["feed"][:15]:
        print(f"  {row['rank']:2d}. [{row['bucket']:<13}] {row['score']:5.1f}  "
              f"{row['title'][:60]}")
    if args.write:
        print(f"\nWrote artifacts to {OUT_DIR}/ucb_campus_records.json, "
              f"ucb_campus_feed.json, ucb_source_breakdown.json")


if __name__ == "__main__":
    main()
