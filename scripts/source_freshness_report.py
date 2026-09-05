#!/usr/bin/env python3
"""Corpus freshness, per department source and per school.

Two jobs, deliberately in one place so the numbers cannot disagree:

``report``    print the acceptance figures (school counts by state, stale and
              failed shard counts) from data/processed/source_health.json.

``bootstrap`` seed that ledger from the committed shards for sources it has
              never recorded. The ledger only starts filling on the next
              refresh run, and each run touches one day's shard, so without
              this a corpus-wide answer would take a full rotation to exist
              and would report every unvisited school as never-successful.

The bootstrap derives ``last_success_at`` from the newest ``last_seen_at``
among a source's ACTIVE records: the timestamp a real harvest stamped on the
records it saw. That is evidence, not a guess — and it is exactly the
evidence that shows UC Berkeley's linguistics department last worked on
2026-07-21. It never overwrites a row a refresh run already wrote, and it
never invents a success for a source with no records at all.

Usage:
    python3 scripts/source_freshness_report.py report
    python3 scripts/source_freshness_report.py report --json
    python3 scripts/source_freshness_report.py bootstrap [--dry-run]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors import source_health  # noqa: E402
from src.collectors.refresh_contract import (  # noqa: E402
    record_source_aliases,
    shard_of_source,
)

SHARDS_DIR = PROJECT_ROOT / "data" / "processed" / "shards"


def _shard_records() -> dict[str, list[dict]]:
    """{shard slug: records} straight from the committed shards."""
    out: dict[str, list[dict]] = {}
    for path in sorted(glob.glob(str(SHARDS_DIR / "*.json"))):
        slug = os.path.basename(path)[:-5]
        try:
            with open(path, encoding="utf-8") as handle:
                records = json.load(handle)
        except (OSError, ValueError) as exc:
            print(f"warning: {slug}.json unreadable ({exc})", file=sys.stderr)
            continue
        if isinstance(records, list):
            out[slug] = records
    return out


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def observed_sources(shards: dict[str, list[dict]]) -> dict[str, dict]:
    """Per-source evidence from the corpus: active count + newest sighting.

    Keyed by source. ``school`` prefers the source registry (the authority a
    release verdict uses) and falls back to the shard the records live in, so
    a source whose registry entry carries no school is still attributed to the
    shard file it actually publishes into.
    """
    aliases = record_source_aliases()
    observed: dict[str, dict] = {}
    for slug, records in shards.items():
        for record in records:
            source = record.get("source")
            if not isinstance(source, str) or not source:
                continue
            # A campus crawl stamps its records "<slug>_research_programs" but
            # reports to the run summary as "campus_graph:<slug>". The ledger
            # is keyed by the summary name, so seed under that name or the
            # bootstrap and the refresh runs would write two disjoint rows for
            # one producer.
            source = aliases.get(source, source)
            if (record.get("metadata") or {}).get("is_active") is False:
                continue
            row = observed.setdefault(
                source,
                {"active": 0, "newest_seen": None,
                 "school": shard_of_source(source) or slug},
            )
            row["active"] += 1
            seen = _parse((record.get("metadata") or {}).get("last_seen_at"))
            if seen is not None and (
                row["newest_seen"] is None or seen > row["newest_seen"]
            ):
                row["newest_seen"] = seen
    return observed


def bootstrap(ledger: dict, shards: dict[str, list[dict]]) -> list[str]:
    """Seed never-recorded source rows from the corpus. Returns seeded names.

    Only fills gaps: a source already in the ledger keeps whatever a refresh
    run recorded, because a run's own observation always outranks an
    inference from stored records.
    """
    existing = ledger.setdefault("sources", {})
    seeded: list[str] = []
    for source, row in sorted(observed_sources(shards).items()):
        if source in existing:
            continue
        if row["newest_seen"] is None:
            # No record carries a parseable sighting, so there is no evidence
            # of a successful harvest to record. Left absent rather than
            # stamped with now().
            continue
        existing[source] = {
            "school": row["school"],
            "last_attempt_at": row["newest_seen"].isoformat(),
            "last_success_at": row["newest_seen"].isoformat(),
            "status": source_health.SUCCESS_NONZERO,
            "current_count": row["active"],
            "last_good_count": row["active"],
            "baseline_count": row["active"],
            "consecutive_failures": 0,
            "failure_reason": None,
            "bootstrapped_from": "corpus_last_seen_at",
        }
        seeded.append(source)
    return seeded


def _print_report(report: dict, schools: list[dict]) -> None:
    print("corpus source freshness")
    print(f"  generated_at                     {report['generated_at']}")
    print(f"  warn / stale bounds (days)       {report['warn_days']:g} / "
          f"{report['stale_days']:g}")
    print()
    print(f"  school_count                     {report['school_count']}")
    print(f"  fully_fresh_school_count         "
          f"{report['fully_fresh_school_count']}")
    print(f"  partially_degraded_school_count  "
          f"{report['partially_degraded_school_count']}")
    print(f"  fully_stale_school_count         "
          f"{report['fully_stale_school_count']}")
    print(f"  stale_shard_count                {report['stale_shard_count']}")
    print(f"  failed_shard_count               {report['failed_shard_count']}")
    print(f"  degraded_shard_count             "
          f"{report['degraded_shard_count']}")
    print(f"  total_shard_count                {report['total_shard_count']}")
    if report["fully_stale_schools"]:
        print()
        print("  FULLY STALE: " + ", ".join(report["fully_stale_schools"]))
    degraded = [s for s in schools if s["state"] == "partially_degraded"]
    if degraded:
        print()
        print("  partially degraded schools (publishable; one or more sources "
              "stale):")
        for school in degraded:
            age = school["oldest_stale_age_days"]
            print(f"    {school['school']:16} fresh={school['fresh_shard_count']:3} "
                  f"warn={school['warn_shard_count']:3} "
                  f"stale={school['stale_shard_count']:3} "
                  f"failed={school['failed_shard_count']:3} "
                  f"of {school['total_shard_count']:3}"
                  + (f"  oldest_stale={age:.0f}d" if isinstance(age, float) else ""))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    report_parser = sub.add_parser("report")
    report_parser.add_argument("--json", action="store_true")
    report_parser.add_argument(
        "--fail-on-fully-stale",
        action="store_true",
        help="exit 1 when any school is fully stale (production gate)",
    )

    boot_parser = sub.add_parser("bootstrap")
    boot_parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    ledger = source_health.load_ledger()

    if args.command == "bootstrap":
        seeded = bootstrap(ledger, _shard_records())
        if args.dry_run:
            print(f"bootstrap --dry-run: would seed {len(seeded)} source(s)")
        else:
            source_health.save_ledger(ledger)
            print(f"bootstrap: seeded {len(seeded)} source(s) into "
                  f"{source_health.LEDGER_FILE.name}")
        return 0

    now = datetime.now(UTC)
    report = source_health.corpus_report(ledger, now)
    schools = source_health.school_rows(ledger, now)
    if args.json:
        print(json.dumps({"report": report, "schools": schools}, indent=2))
    else:
        _print_report(report, schools)
    if args.fail_on_fully_stale and report["fully_stale_school_count"]:
        print(
            "::error::fully_stale_school_count is "
            f"{report['fully_stale_school_count']} "
            f"({', '.join(report['fully_stale_schools'])})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
