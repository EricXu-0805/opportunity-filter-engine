#!/usr/bin/env python3
"""Canonical weekly refresh rotation and manual-shard validation.

The workflow delegates all shard selection to this module so collector
registration and the weekly schedule cannot silently drift apart.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.normalizers.school_audience import SOURCE_DEFAULTS  # noqa: E402

NATIONAL_SHARD = "national"
_SLUG_RE = re.compile(r"[a-z0-9-]{1,64}")

# Balanced by the committed per-school record counts as of 2026-07-31. Keep
# this explicit and reviewable; validate_rotation() proves it covers every
# registered school exactly once.
WEEKLY_ROTATION: dict[int, tuple[str, ...]] = {
    1: (
        "uiuc", "rutgers", "ncsu", "asu", "ucr", "uiowa", "iastate",
        "buffalo", "fsu", "bc", "emory", "tufts", "stevens", "middlebury",
        "carleton", "amherst", "grinnell", "hamilton", "davidson",
        "macalester", "cmc",
    ),
    2: (
        "ucb", "mit", "usc", "umn", "tamu", "psu", "msu", "utah", "uconn",
        "usf", "georgetown", "nyu", "uva", "njit", "wpi",
    ),
    3: (
        "uw", "wisc", "purdue", "duke", "dartmouth", "harvard", "rochester",
        "yale", "umd", "bu", "rpi", "indiana", "drexel", "uky", "lehigh",
        "wesleyan", "unc", "colgate", "smith", "wellesley", "vassar",
        "bowdoin", "wlu", "coloradocollege", "kenyon", "haverford",
    ),
    4: (
        "utexas", "ucla", "boulder", "cornell", "brown", "rice",
        "vanderbilt", "nd", "vt", "arizona", "pitt", "houston", "udel",
        "uga", "oregonstate", "syracuse",
    ),
    5: (
        "stanford", "ucsd", "princeton", "jhu", "northwestern", "columbia",
        "uf", "washu", "ucsc", "cmu", "ucf", "miami", "clemson",
        "cincinnati", "unl",
    ),
    6: (
        "gatech", "uchicago", "uci", "ucsb", "umich", "upenn", "caltech",
        "osu", "umass", "neu", "sbu", "casewestern", "colostate", "utk",
        "lsu", "utdallas", "ucd", "pomona", "colby", "swarthmore",
        "barnard", "bates", "brynmawr",
    ),
    7: (NATIONAL_SHARD,),
}


def registered_school_slugs() -> frozenset[str]:
    return frozenset(school for school, _ in SOURCE_DEFAULTS.values() if school)


def validate_rotation() -> None:
    """Raise when the rotation is not an exact partition of registrations."""

    if set(WEEKLY_ROTATION) != set(range(1, 8)):
        raise ValueError("weekly rotation must define UTC weekdays 1 through 7")
    if WEEKLY_ROTATION[7] != (NATIONAL_SHARD,):
        raise ValueError("UTC day 7 must be the national-only shard")

    scheduled = [
        slug
        for day in range(1, 7)
        for slug in WEEKLY_ROTATION[day]
    ]
    duplicates = sorted({slug for slug in scheduled if scheduled.count(slug) > 1})
    if duplicates:
        raise ValueError(f"school slugs scheduled more than once: {duplicates}")

    registered = registered_school_slugs()
    missing = sorted(registered - set(scheduled))
    unknown = sorted(set(scheduled) - registered)
    if missing or unknown:
        raise ValueError(
            f"rotation does not match collector registrations; "
            f"missing={missing}, unknown={unknown}"
        )


def scheduled_shard(utc_weekday: int) -> str:
    validate_rotation()
    try:
        return ",".join(WEEKLY_ROTATION[utc_weekday])
    except KeyError as exc:
        raise ValueError("UTC weekday must be an integer from 1 through 7") from exc


def normalize_requested_shard(raw: str, *, allow_full: bool = False) -> str:
    """Validate an untrusted workflow_dispatch value and return it unchanged."""

    if raw == "":
        if allow_full:
            return ""
        raise ValueError("an explicit school shard or national is required")
    if raw != raw.strip() or not re.fullmatch(
        r"[a-z0-9-]+(?:,[a-z0-9-]+)*", raw
    ):
        raise ValueError(
            "schools must be lowercase comma-separated school slugs, or national"
        )
    if raw == NATIONAL_SHARD:
        return raw

    slugs = raw.split(",")
    if NATIONAL_SHARD in slugs:
        raise ValueError("national cannot be combined with school slugs")
    if len(slugs) != len(set(slugs)):
        raise ValueError("school shard contains duplicate slugs")
    invalid = sorted(slug for slug in slugs if _SLUG_RE.fullmatch(slug) is None)
    unknown = sorted(set(slugs) - registered_school_slugs())
    if invalid or unknown:
        raise ValueError(f"invalid or unknown school slugs: {invalid or unknown}")
    return ",".join(slugs)


def target_shards(shard: str) -> tuple[str, ...]:
    """Return the exact committed shard names a run is authorized to replace."""

    normalized = normalize_requested_shard(shard, allow_full=True)
    if normalized == "":
        return tuple(sorted((*registered_school_slugs(), NATIONAL_SHARD)))
    if normalized == NATIONAL_SHARD:
        return (NATIONAL_SHARD,)
    return tuple(normalized.split(","))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--day", type=int, help="UTC weekday (1=Monday, 7=Sunday)")
    group.add_argument("--schools", help="Untrusted manual shard input")
    parser.add_argument(
        "--allow-full",
        action="store_true",
        help="Allow an empty manual value to mean a full refresh",
    )
    parser.add_argument(
        "--targets",
        action="store_true",
        help="Print the authorized committed shard names",
    )
    args = parser.parse_args()

    try:
        if args.day is not None:
            shard = scheduled_shard(args.day)
        else:
            shard = normalize_requested_shard(
                args.schools or "",
                allow_full=args.allow_full,
            )
        print(",".join(target_shards(shard)) if args.targets else shard)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
