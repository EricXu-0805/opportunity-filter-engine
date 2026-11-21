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

The data PR and the operator alert name what a run publishes from the same
verdict: ``--label`` is the PR title's shard part and ``--notes`` lists the
publishable and the withheld shards, each withheld one with the verdict's
reasons. The title used to name the requested shard, withheld schools
included, and a withheld school sent no mail.

``--unread`` lists what a shard published without: a school department or a
national source that read nothing this run and keeps the rows it had. Each
withheld its whole shard until 2026-11-16, so it reached the operator as a
withheld shard; now that the shard publishes, this is what still says so.
It also names an internship list that came back under half the size of what
the corpus holds open: such a read retires nothing and still publishes.

Usage:
    python3 scripts/publishable_shards.py --authorized "uw,wisc,national"
    python3 scripts/publishable_shards.py --authorized "uw,wisc" --label --shard "uw,wisc"
    python3 scripts/publishable_shards.py --authorized "uw,wisc" --notes
    python3 scripts/publishable_shards.py --authorized "uiuc,national" --unread
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


def _reasons(value) -> list[str]:
    """A verdict's reasons on one line each, each once: the verdict can repeat a
    reason (ucb's, five times, on 2026-09-05), and error text can span lines."""

    texts = [" ".join(text.split()) for text in value if isinstance(text, str)] if isinstance(value, list) else []
    return list(dict.fromkeys(text for text in texts if text))


def withheld(authorized: list[str], status: dict | None) -> list[tuple[str, list[str]]]:
    """The authorized shards the verdict did not earn, each with its reasons."""

    earned = set(publishable(authorized, status))
    release = status.get("release") if isinstance(status, dict) else None
    release = release if isinstance(release, dict) else {}
    by_unit = release.get("by_unit") if isinstance(release.get("by_unit"), dict) else {}
    structural = _reasons(release.get("structural_reasons"))
    held = []
    for slug in authorized:
        if slug in earned:
            continue
        verdict = by_unit.get(slug)
        reasons = _reasons(verdict.get("reasons") if isinstance(verdict, dict) else None)
        held.append((slug, reasons or structural or ["the release verdict records no reason"]))
    return held


def _named(published: list[str], status: dict | None) -> list[str]:
    """Published shards as the title and the notes name them.

    A school day that read some sources of the national shard (its request
    lists them) publishes those and leaves the rest as committed, so the
    shard is named by them: a bare "national" read as all of it.
    """

    request = status.get("request") if isinstance(status, dict) else None
    sources = request.get("national_sources") if isinstance(request, dict) else None
    if not isinstance(sources, list) or not sources:
        return published
    return [",".join(sources) if slug == "national" else slug for slug in published]


def title_label(shard: str, authorized: list[str], status: dict | None) -> str:
    """The data PR title's shard part: the requested shard when all of it publishes."""

    held = [slug for slug, _ in withheld(authorized, status)]
    if not held:
        return f"shard: {shard or 'full'}"
    published = _named(publishable(authorized, status), status)
    # A full refresh authorizes every shard; its title would not fit them.
    shown = ",".join(published) if shard else f"{len(published)} of {len(authorized)} shards"
    return f"published: {shown}; withheld: {','.join(held)}"


def notes(authorized: list[str], status: dict | None) -> str:
    """What a run may publish and withholds, for the PR body and the alert; empty when it withholds nothing."""

    held = withheld(authorized, status)
    if not held:
        return ""
    published = _named(publishable(authorized, status), status)
    lines = [
        f"Publishable ({len(published)}): {', '.join(published) or 'none'}",
        f"Withheld ({len(held)}), each keeping the data last committed for it:",
    ]
    lines += [f"- {slug}: {'; '.join(reasons)}" for slug, reasons in held]
    return "\n".join(lines)


def _published_degradations(authorized: list[str], status: dict | None) -> list[tuple[str, dict]]:
    """The verdict's degradations of the shards this run publishes: (shard, degradation)."""

    release = status.get("release") if isinstance(status, dict) else None
    release = release if isinstance(release, dict) else {}
    policies = release.get("policies") if isinstance(release.get("policies"), list) else []
    shard_of = {
        policy["summary_key"]: policy.get("school") or "national"
        for policy in policies
        if isinstance(policy, dict) and isinstance(policy.get("summary_key"), str)
    }
    earned = set(publishable(authorized, status))
    degradations = release.get("degradations") if isinstance(release.get("degradations"), list) else []
    return [
        (shard_of[item["source"]], item)
        for item in degradations
        if isinstance(item, dict) and isinstance(item.get("source"), str)
        and shard_of.get(item["source"]) in earned
    ]


def unread(authorized: list[str], status: dict | None) -> list[tuple[str, str]]:
    """What each published shard went without this run: (shard, source and detail).

    Two of the verdict's degradations: a department of a school's faculty
    source that read empty (``empty_department``), and a source of the
    national shard that read zero rows while the corpus holds rows for it
    (``suspicious_zero``). A school shard's own zero-row sources are not
    listed: they have published without mail since they stopped withholding
    their school, and the operator queue tracks them. Nor is a degradation
    of a withheld shard, which is reported by its reasons.
    """

    found = []
    for shard, item in _published_degradations(authorized, status):
        kind = item.get("kind")
        if not (kind == "empty_department" or (kind == "suspicious_zero" and shard == "national")):
            continue
        detail = " ".join(str(item.get("detail") or "").split())
        found.append((shard, f"{item['source']}: {detail}" if detail else item["source"]))
    return list(dict.fromkeys(found))


def collapsed_lists(authorized: list[str], status: dict | None) -> list[tuple[str, str]]:
    """A published shard's lists that came back under half their size: (shard, source and counts).

    refresh_all merges such a list's rows and retires nothing, and marks the
    source ``collapsed_list_baseline``: the internships the corpus held open.
    The verdict records it as a ``partial_failure`` like any other, so
    without this the PR and the alert said nothing of it.
    """

    sources = status.get("sources") if isinstance(status, dict) else None
    sources = sources if isinstance(sources, dict) else {}
    found = []
    for shard, item in _published_degradations(authorized, status):
        info = sources.get(item["source"])
        baseline = info.get("collapsed_list_baseline") if isinstance(info, dict) else None
        if item.get("kind") == "partial_failure" and isinstance(baseline, int):
            found.append((shard, f"{item['source']}: {info.get('fetched')} listed, {baseline} held open"))
    return list(dict.fromkeys(found))


def unread_notes(authorized: list[str], status: dict | None) -> str:
    """What published shards went without, for the PR body and the alert; empty when nothing."""

    blocks = []
    gaps = unread(authorized, status)
    if gaps:
        lines = [f"Published without a fresh read ({len(gaps)}), each keeping the rows it had:"]
        blocks.append("\n".join(lines + [f"- {shard}: {text}" for shard, text in gaps]))
    collapsed = collapsed_lists(authorized, status)
    if collapsed:
        lines = [f"Published from a list under half the size of what is held open ({len(collapsed)}); "
                 "nothing was retired and the rows it listed were updated:"]
        blocks.append("\n".join(lines + [f"- {shard}: {text}" for shard, text in collapsed]))
    return "\n\n".join(blocks)


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
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--label",
        action="store_true",
        help="print the data PR title's shard part instead (needs --shard)",
    )
    output.add_argument(
        "--notes",
        action="store_true",
        help="print the publishable and withheld shards with reasons instead; empty when none is withheld",
    )
    output.add_argument(
        "--unread",
        action="store_true",
        help="print what the published shards went without instead; empty when nothing",
    )
    parser.add_argument("--shard", help="the run's requested shard; empty for a full refresh")
    args = parser.parse_args()

    authorized = [slug for slug in args.authorized.split(",") if slug]
    if not authorized:
        parser.error("--authorized must name at least one shard")

    status = _read_status(Path(args.status_file))
    if args.label:
        if args.shard is None:
            parser.error("--label needs --shard")
        print(title_label(args.shard, authorized, status))
        return 0
    if args.notes or args.unread:
        text = notes(authorized, status) if args.notes else unread_notes(authorized, status)
        if text:
            print(text)
        return 0

    allowed = publishable(authorized, status)
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
