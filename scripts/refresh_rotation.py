#!/usr/bin/env python3
"""Canonical weekly refresh rotation and manual-shard validation.

The workflow delegates all shard selection to this module so collector
registration and the weekly schedule cannot silently drift apart. It also
decides whether a refresh run may start beside another one.

The workflow runs ``--overlap`` before it checks the repository out, from a
copy of this file alone, so nothing here imports from the repository at load
time.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
        "lsu", "utdallas", "pomona", "colby", "swarthmore",
        "barnard", "bates", "brynmawr",
    ),
    7: (NATIONAL_SHARD,),
}

# Isolated batches exist for collectors whose runtime and failure profile differ
# materially from the rest of their day's shard; they stay serialized with the
# primary rotation because collector_status is a global CAS input.
#
# Empty since 2026-09-06: UC Davis was the only entry, and it left the
# supported set (src/school_scope.py). Scheduling it would now fail
# validate_rotation() below, which is the intended coupling — a school the
# product does not offer must not be scraped on a timer.
ISOLATED_WEEKLY_SHARDS: dict[int, tuple[str, ...]] = {}


def registered_school_slugs() -> frozenset[str]:
    """Schools the rotation is expected to schedule.

    Excludes the unsupported set, and validate_rotation() below pins the two
    together: dropping a school from the product without dropping it from the
    rotation fails loudly here rather than leaving a shard that scrapes a
    school nobody is served.
    """
    from src.normalizers.school_audience import SOURCE_DEFAULTS
    from src.school_scope import is_supported

    return frozenset(
        school for school, _ in SOURCE_DEFAULTS.values()
        if school and is_supported(school)
    )


def validate_rotation() -> None:
    """Raise when the rotation is not an exact partition of registrations."""

    if set(WEEKLY_ROTATION) != set(range(1, 8)):
        raise ValueError("weekly rotation must define UTC weekdays 1 through 7")
    if WEEKLY_ROTATION[7] != (NATIONAL_SHARD,):
        raise ValueError("UTC day 7 must be the national-only shard")

    primary = [
        slug
        for day in range(1, 7)
        for slug in WEEKLY_ROTATION[day]
    ]
    isolated = [
        slug
        for day in sorted(ISOLATED_WEEKLY_SHARDS)
        for slug in ISOLATED_WEEKLY_SHARDS[day]
    ]
    scheduled = [*primary, *isolated]
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


def scheduled_shard(utc_weekday: int, *, isolated: bool = False) -> str:
    validate_rotation()
    rotation = ISOLATED_WEEKLY_SHARDS if isolated else WEEKLY_ROTATION
    try:
        return ",".join(rotation[utc_weekday])
    except KeyError as exc:
        if isolated:
            raise ValueError(
                "no isolated refresh batch is registered for that UTC weekday"
            ) from exc
        raise ValueError("UTC weekday must be an integer from 1 through 7") from exc


def normalize_requested_shard(raw: str, *, allow_full: bool = False) -> str:
    """Validate an untrusted workflow_dispatch value and return it unchanged."""
    from src.school_scope import is_supported

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
    unsupported = sorted(slug for slug in slugs if not is_supported(slug))
    if unsupported:
        raise ValueError(
            f"school(s) no longer supported by this product: {unsupported} "
            "(see src/school_scope.py)"
        )
    invalid = sorted(slug for slug in slugs if _SLUG_RE.fullmatch(slug) is None)
    unknown = sorted(set(slugs) - registered_school_slugs())
    if invalid or unknown:
        raise ValueError(f"invalid or unknown school slugs: {invalid or unknown}")
    return ",".join(slugs)


def normalize_publication_unit(raw: str) -> str:
    """Validate one canonical unit that automation may publish or replay."""

    normalized = normalize_requested_shard(raw, allow_full=False)
    canonical_units = {
        ",".join(WEEKLY_ROTATION[day])
        for day in range(1, 8)
    } | {
        ",".join(shard)
        for shard in ISOLATED_WEEKLY_SHARDS.values()
    }
    if normalized in canonical_units or "," not in normalized:
        return normalized
    raise ValueError(
        "manual refresh must select national, one school, or one canonical "
        "scheduled shard"
    )


# uiuc drives headless Chromium outside the faculty_graph engine
# (uiuc_js_faculty recovers the 4 ACES departments from Drupal Views AJAX),
# so it cannot be detected by inspecting school configs.
_BROWSER_SCHOOLS_OUTSIDE_ENGINE = frozenset({"uiuc"})


def _config_needs_browser(school: dict) -> bool:
    for dept in school.get("departments", []):
        for block in ("scrape", "api", "ajax", "json_dir", "sitemap"):
            cfg = dept.get(block)
            if not isinstance(cfg, dict):
                continue
            if cfg.get("render"):
                return True
            enrich = cfg.get("profile_enrich")
            if isinstance(enrich, dict) and enrich.get("render"):
                return True
    # campus_graph configs carry `sources`, not `departments`, and a source
    # behind Cloudflare needs Chromium for exactly the same reason a
    # client-rendered roster does. Missing this half would reproduce the
    # hardcoded-alternation bug one file over: the crawl degrades to None,
    # which reads as an unreachable page, and the source still reports ok.
    for source in school.get("sources", []):
        if isinstance(source, dict) and source.get("render"):
            return True
    return False


def browser_schools() -> frozenset[str]:
    """Slugs whose collectors need headless Chromium, derived from the configs.

    The workflow used to carry this as a hardcoded alternation, and 11
    render-mode schools (asu, brown, casewestern, colostate, drexel, indiana,
    lsu, rpi, uky, unl, utdallas) were missing from it. They collected anyway,
    but only by luck: the install is per-RUN, and every shard happened to
    contain at least one listed school. Nothing enforced that. A school moving
    days, or an edit to the shard table, and those departments go quiet with
    no signal — ``_render_soup`` lazy-imports Playwright and degrades to None
    when it is absent, which looks identical to an unreachable directory, and
    the source still reports "ok" on whatever its other departments returned.
    """
    import importlib
    import pkgutil

    import src.collectors.schools as schools_pkg

    needed = set(_BROWSER_SCHOOLS_OUTSIDE_ENGINE)
    for module in pkgutil.iter_modules(schools_pkg.__path__):
        # Both halves of a school: `<slug>_faculty` (faculty_graph departments)
        # and `<slug>` (campus_graph sources). Scanning only the first left
        # every Cloudflare-walled campus source without a Chromium install.
        if module.name.startswith("_"):
            continue
        try:
            loaded = importlib.import_module(
                f"src.collectors.schools.{module.name}"
            )
        except Exception:  # noqa: BLE001 — a broken config must not break scheduling
            continue
        config = getattr(loaded, "SCHOOL", None)
        if isinstance(config, dict) and _config_needs_browser(config):
            slug = config.get("school_slug")
            if slug:
                needed.add(slug)
    return frozenset(needed)


def shard_needs_browser(shard: str) -> bool:
    """True when any school this run will scrape needs headless Chromium."""

    normalized = normalize_requested_shard(shard, allow_full=True)
    if normalized == NATIONAL_SHARD:
        return False
    if normalized == "":
        return True
    return bool(set(normalized.split(",")) & browser_schools())


def target_shards(shard: str) -> tuple[str, ...]:
    """Return the exact committed shard names a run is authorized to replace."""

    normalized = normalize_requested_shard(shard, allow_full=True)
    if normalized == "":
        return tuple(sorted((*registered_school_slugs(), NATIONAL_SHARD)))
    if normalized == NATIONAL_SHARD:
        return (NATIONAL_SHARD,)
    return tuple(normalized.split(","))


# Scheduled and manual refreshes sit in separate concurrency groups (see
# refresh-data.yml), so GitHub does not keep them apart; the workflow's first
# step asks overlap_decision() instead. Production wins: a scheduled run
# cancels a manual one already in progress, and a manual run defers to any.
PRODUCTION_EVENT = "schedule"
_REFRESH_BRANCH = re.compile(r"auto/refresh-data-([0-9]+)(?:-r[0-9]+)?")


@dataclass(frozen=True)
class OverlapDecision:
    action: str  # "proceed", "defer" or "cancel"
    cancel: tuple[int, ...] = ()
    level: str = "info"  # how the workflow reports message: info, warning or error
    message: str = ""


def _runs_in_progress(payload) -> list[tuple[int, str]] | None:
    """(id, event) of each in-progress run in a workflow-runs API response.

    None when the payload is not one: a failed request leaves nothing to read,
    or an error body.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("workflow_runs"), list):
        return None
    runs = set()
    for run in payload["workflow_runs"]:
        if not isinstance(run, dict):
            return None
        run_id, event, status = run.get("id"), run.get("event"), run.get("status")
        if type(run_id) is not int or not isinstance(event, str) or not isinstance(status, str):
            return None
        # A queued run has not started; it asks for itself when it does.
        if status == "in_progress":
            runs.add((run_id, event))
    return sorted(runs)


def overlap_decision(event_name: str, run_id: int, payload) -> OverlapDecision:
    """Whether refresh run ``run_id`` may start beside the runs in ``payload``.

    ``payload`` is the response of the workflow's runs?status=in_progress
    request, or None when that request failed. Two refreshes must not mutate
    the corpus at once, and a scheduled run's daily shard must not wait on a
    manual recovery: a scheduled run cancels every other in-progress run that
    is not scheduled, and a manual run defers to any. A failed request defers a
    manual run and lets a scheduled one through, as a broken API should not
    cost a day of the rotation.
    """
    runs = _runs_in_progress(payload)
    production = event_name == PRODUCTION_EVENT
    if runs is None:
        if production:
            return OverlapDecision(
                "proceed", level="warning",
                message="Could not list the refresh runs in progress; the scheduled "
                        "refresh proceeds without checking for a manual one.",
            )
        return OverlapDecision(
            "defer", level="error",
            message="Could not list the refresh runs in progress, so this manual "
                    "dispatch cannot tell that none is running. Re-dispatch it.",
        )
    others = [(other, event) for other, event in runs if other != run_id]
    if not others:
        return OverlapDecision("proceed", message="No other refresh in progress; proceeding.")
    if not production:
        ids = ", ".join(str(other) for other, _ in others)
        return OverlapDecision(
            "defer", level="error",
            message=f"A refresh run is already in progress ({ids}). This manual dispatch "
                    "is deferring rather than racing the corpus; re-dispatch once it finishes.",
        )
    manual = tuple(other for other, event in others if event != PRODUCTION_EVENT)
    scheduled = ", ".join(str(other) for other, event in others if event == PRODUCTION_EVENT)
    # The schedule's own concurrency group queues scheduled runs, so another
    # one in progress bypassed that group. It is left running.
    beside = (f"Scheduled run(s) {scheduled} are in progress outside their "
              "concurrency group and are left running.") if scheduled else ""
    if manual:
        ids = ", ".join(str(other) for other in manual)
        return OverlapDecision(
            "cancel", cancel=manual, level="warning",
            message=f"Production wins: cancelling manual refresh run(s) {ids} before "
                    f"this scheduled refresh starts. {beside}".rstrip(),
        )
    return OverlapDecision("proceed", level="warning", message=beside)


def superseded_refresh_prs(prs: list, run_id: int) -> list[int]:
    """Open data-refresh PRs that runs older than ``run_id`` left behind.

    ``prs`` is ``gh pr list --json number,headRefName`` output. A refresh
    closes these before opening its own PR. It used to close every open
    auto/refresh-data-* PR, newer runs' included; a branch names the run that
    opened it, and a run's id grows with the time it was created.
    """
    if not isinstance(prs, list):
        raise ValueError("expected a list of pull requests")
    stale = []
    for pr in prs:
        match = _REFRESH_BRANCH.fullmatch(str(pr.get("headRefName", "")))
        if match and int(match.group(1)) < run_id:
            stale.append(int(pr["number"]))
    return sorted(stale)


def _annotate(level: str, message: str) -> None:
    """Print message to stderr, as a workflow annotation when it is one."""
    if level in ("warning", "error"):
        message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        message = f"::{level}::{message}"
    print(message, file=sys.stderr)


def _overlap_cli(event_name: str, run_id: int, runs_path: str) -> int:
    try:
        payload = json.loads(Path(runs_path).read_text())
    except (OSError, ValueError):
        payload = None
    decision = overlap_decision(event_name, run_id, payload)
    if decision.message:
        _annotate(decision.level, decision.message)
    print(" ".join([decision.action, *(str(other) for other in decision.cancel)]))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--day", type=int, help="UTC weekday (1=Monday, 7=Sunday)")
    group.add_argument("--schools", help="Untrusted manual shard input")
    group.add_argument(
        "--overlap",
        action="store_true",
        help="Print proceed, defer or 'cancel <run ids>' for this run (needs --event, --run-id, --runs)",
    )
    group.add_argument(
        "--superseded-prs",
        action="store_true",
        help="Print the open refresh PRs older runs left, from gh pr list JSON on stdin (needs --run-id)",
    )
    parser.add_argument("--event", help="This run's github.event_name")
    parser.add_argument("--run-id", type=int, help="This run's github.run_id")
    parser.add_argument(
        "--runs",
        help="File holding the in-progress workflow-runs API response; empty or unreadable means the request failed",
    )
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
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="Select the isolated batch registered for --day",
    )
    parser.add_argument(
        "--needs-browser",
        action="store_true",
        help="Print true/false: does the selected shard need headless Chromium",
    )
    parser.add_argument(
        "--publication-unit",
        action="store_true",
        help="Require a bounded canonical publication unit for --schools",
    )
    args = parser.parse_args()

    if args.overlap:
        if not args.event or args.run_id is None or args.runs is None:
            parser.error("--overlap needs --event, --run-id and --runs")
        return _overlap_cli(args.event, args.run_id, args.runs)
    if args.superseded_prs:
        if args.run_id is None:
            parser.error("--superseded-prs needs --run-id")
        try:
            stale = superseded_refresh_prs(json.load(sys.stdin), args.run_id)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            parser.error(f"unreadable pull request list: {exc}")
        for number in stale:
            print(number)
        return 0

    try:
        if args.day is not None:
            shard = scheduled_shard(args.day, isolated=args.isolated)
        else:
            if args.isolated:
                raise ValueError("--isolated requires --day")
            if args.publication_unit:
                if args.allow_full:
                    raise ValueError(
                        "--publication-unit cannot be combined with --allow-full"
                    )
                shard = normalize_publication_unit(args.schools or "")
            else:
                shard = normalize_requested_shard(
                    args.schools or "",
                    allow_full=args.allow_full,
                )
        if args.needs_browser:
            print("true" if shard_needs_browser(shard) else "false")
        else:
            print(",".join(target_shards(shard)) if args.targets else shard)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
