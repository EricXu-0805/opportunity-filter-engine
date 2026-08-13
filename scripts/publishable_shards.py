#!/usr/bin/env python3
"""Narrow a run's authorized shards to the ones its verdict actually earned.

``refresh_rotation --targets`` answers which committed shards a run is
*allowed* to replace. This answers which of them it *may*: the release
contract reports a verdict per publication unit, and a school whose source
errored has not earned an overwrite even though the run was authorized to
touch it.

Before this existed the verdict was one boolean for the whole run, so on
2026-08-08 a single broken UCSB sitemap withheld fifteen other schools'
fresh data — 132,736 records collected over 2h42m and none of it published.

An artifact written before ``release.publishable`` existed returns the
authorized set unchanged. Guessing at it would either publish a school the
verdict blocked or, worse, silently publish nothing.

Usage:
    python3 scripts/publishable_shards.py --authorized "uw,wisc,national"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATUS_FILE = PROJECT_ROOT / "data" / "processed" / "collector_status.json"


def publishable(authorized: list[str], status: dict | None) -> list[str]:
    """Intersect, preserving the authorized order, and never inventing a shard."""

    if not isinstance(status, dict):
        return list(authorized)
    release = status.get("release")
    if not isinstance(release, dict):
        return list(authorized)
    earned = release.get("publishable")
    if not isinstance(earned, list):
        return list(authorized)
    allowed = {slug for slug in earned if isinstance(slug, str)}
    return [slug for slug in authorized if slug in allowed]


def _read_status(path: Path) -> dict | None:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--authorized",
        required=True,
        help="comma-separated shard names this run may replace",
    )
    parser.add_argument(
        "--status-file",
        default=str(STATUS_FILE),
        help="collector_status.json to read the verdict from",
    )
    args = parser.parse_args()

    authorized = [slug for slug in args.authorized.split(",") if slug]
    if not authorized:
        parser.error("--authorized must name at least one shard")

    allowed = publishable(authorized, _read_status(Path(args.status_file)))
    if not allowed:
        # main() already exits 2 when nothing is publishable, so reaching here
        # means the two disagree. Say so rather than emit an empty string that
        # shard_corpus would reject with a less useful message.
        parser.error(
            "the release verdict publishes none of this run's authorized "
            f"shards: {', '.join(authorized)}"
        )
    print(",".join(allowed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
