#!/usr/bin/env python3
"""Report which configured campus_graph seed and program pages no longer exist.

Every seed in ``schools.SCHOOL_CONFIGS`` is a URL some university controls,
and universities move pages. When one 404s the crawl silently loses whatever
it discovered from that seed, and — before the release contract learned to
degrade instead of veto — a single dead URL could withhold a whole shard's
publication. Five had rotted undetected by 2026-08: Bates' summer-grants
index, Caltech's Grants_Funding section, Notre Dame's Kellogg undergraduate
index, Northwestern's SROP page and MIT's Wellesley UROP page.

A program record's URL is where Match sends a student, and on 2026-09-30
488 of the 1,021 distinct program URLs were not seeds. Duke's data_plus
record pointed at a 404 that nothing probed, because its page was never a
seed. Program pages that are not seeds are now probed too, once per URL,
through the same pool with the same timeout.

A dead page is deterministic and worth waking someone for. A bot challenge,
a timeout or a rate-limit is not: those recur, recover, and would train the
reader to ignore this check. So only ``gone`` fails the run.

Usage:
    python3 scripts/check_campus_seeds.py            # report, exit 1 if any gone
    python3 scripts/check_campus_seeds.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

GONE = "gone"
BLOCKED = "blocked"
UNREACHABLE = "unreachable"
OK = "ok"

# 404/410 are the site saying the page does not exist. 403/406/429 are the
# site saying not to you, not right now — Cloudflare fronts several campuses
# and answers 403 to every non-browser client.
_GONE_STATUSES = frozenset({404, 410})
_BLOCKED_STATUSES = frozenset({401, 403, 406, 429, 451})


def classify(status: object) -> str:
    """Map one probe result to the class that decides whether we alert."""

    if isinstance(status, int) and not isinstance(status, bool):
        if 200 <= status < 400:
            return OK
        if status in _GONE_STATUSES:
            return GONE
        if status in _BLOCKED_STATUSES:
            return BLOCKED
    return UNREACHABLE


def configured_seeds() -> list[tuple[str, str, str]]:
    from src.collectors.schools import SCHOOL_CONFIGS

    seeds: list[tuple[str, str, str]] = []
    for config in SCHOOL_CONFIGS:
        slug = config.get("school_slug", "?")
        for source in config.get("sources", []):
            for url in source.get("seeds", []) or []:
                seeds.append((slug, source["source_name"], url))
    return seeds


def configured_program_urls() -> list[tuple[str, str, str]]:
    """Program record URLs that no seed probe covers, one entry per URL.

    A URL that is also a seed is left to the seed probe; a URL several
    programs share is named after the first of them.
    """
    from src.collectors.schools import SCHOOL_CONFIGS

    covered = {url for _slug, _source, url in configured_seeds()}
    pages: list[tuple[str, str, str]] = []
    for config in SCHOOL_CONFIGS:
        slug = config.get("school_slug", "?")
        for source in config.get("sources", []):
            for spec in source.get("programs", []) or []:
                url = spec["url"]
                if url not in covered:
                    covered.add(url)
                    pages.append((slug, source["source_name"], url))
    return pages


def _probe(item: tuple[str, str, str], kind: str = "seed") -> dict:
    import requests

    from src.collectors.campus_graph import HEADERS
    from src.collectors.ucb_common import _ca_bundle

    slug, source, url = item
    try:
        resp = requests.get(
            url, headers=HEADERS, timeout=20, verify=_ca_bundle()
        )
        status: object = resp.status_code
    except Exception as exc:  # noqa: BLE001 — every failure is data here
        status = type(exc).__name__
    return {
        "school": slug,
        "source": source,
        "kind": kind,
        "url": url,
        "status": status,
        "class": classify(status),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--workers", type=int, default=8, help="concurrent probes"
    )
    args = parser.parse_args(argv)

    seeds = configured_seeds()
    pages = configured_program_urls()
    kinds = ["seed"] * len(seeds) + ["program"] * len(pages)
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(_probe, seeds + pages, kinds))

    gone = [r for r in results if r["class"] == GONE]
    blocked = [r for r in results if r["class"] == BLOCKED]
    unreachable = [r for r in results if r["class"] == UNREACHABLE]

    if args.json:
        print(json.dumps({"probed": len(results), "results": results}, indent=1))
    else:
        print(
            f"probed {len(results)} configured pages ({len(seeds)} seeds, "
            f"{len(pages)} program pages that are not seeds): "
            f"{len(results) - len(gone) - len(blocked) - len(unreachable)} ok, "
            f"{len(gone)} gone, {len(blocked)} blocked, "
            f"{len(unreachable)} unreachable"
        )
        for label, rows in (
            ("GONE", gone),
            ("blocked", blocked),
            ("unreachable", unreachable),
        ):
            for row in sorted(rows, key=lambda r: (r["school"], r["url"])):
                print(
                    f"  {label:11s} {row['school']:14s} {row['kind']:7s} "
                    f"{row['status']}  {row['url']}"
                )

    if gone:
        print(
            f"::error::{len(gone)} configured campus page(s) no longer exist; "
            "a dead seed loses the crawl whatever it linked to, and a dead "
            "program page is where Match sends students"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
