"""Auto-deactivate opportunities whose deadline has passed.

Runs after every refresh. Idempotent: opps already marked inactive stay inactive,
opps newly past-deadline get `metadata.is_active = False`, opps with rolling
deadlines or no deadline are left alone.

Also records `metadata.deactivated_at` (UTC ISO date) the first time we mark
something inactive, so the admin dashboard can surface freshly-expired entries.

Two targets, because the corpus has two representations. The work file is what
the pipeline reads; the per-school shards are what git stores. A run only
publishes the shards it was authorized to replace, so the work-file pass alone
leaves retirements stranded in every other shard — see
:func:`deactivate_past_in_shards`.

Usage:
    python3 -m src.normalizers.deactivate_past --dry-run
    python3 -m src.normalizers.deactivate_past --save
    python3 -m src.normalizers.deactivate_past --shards --save
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from src.collectors.atomic_json import atomic_write_json

from .deadlines import parse_to_date as _parse_deadline

_PROCESSED = Path(__file__).resolve().parents[2] / "data" / "processed"
DEFAULT_PATH = _PROCESSED / "opportunities.json"
DEFAULT_SHARDS_DIR = _PROCESSED / "shards"


def deactivate_past(opps: list[dict], today: date | None = None) -> dict:
    """Mark opportunities past their deadline as inactive (in place).

    Skip rolling deadlines, no-deadline entries, and unparseable formats.
    Returns counts dict: {newly_deactivated, already_inactive, kept_active,
                           skipped_rolling, skipped_no_deadline, skipped_invalid}.
    """
    today = today or date.today()
    counts = {
        "newly_deactivated": 0,
        "already_inactive": 0,
        "kept_active": 0,
        "skipped_rolling": 0,
        "skipped_no_deadline": 0,
        "skipped_estimate": 0,
        "skipped_invalid": 0,
    }

    for opp in opps:
        meta = opp.setdefault("metadata", {})

        if opp.get("is_rolling"):
            counts["skipped_rolling"] += 1
            continue

        raw_deadline = opp.get("deadline")
        if not raw_deadline:
            counts["skipped_no_deadline"] += 1
            continue

        # An ESTIMATED deadline (nsf_reu derives one from the award start
        # date) is a labeled guess — the hard is_active flip must not fire on
        # it (truthfulness W11); the UI still shows the estimate as such.
        if opp.get("deadline_is_estimate"):
            counts["skipped_estimate"] += 1
            continue

        parsed = _parse_deadline(raw_deadline)
        if parsed is None:
            counts["skipped_invalid"] += 1
            continue

        if parsed < today:
            if meta.get("is_active") is False:
                counts["already_inactive"] += 1
            else:
                meta["is_active"] = False
                meta.setdefault("deactivated_at", today.isoformat())
                meta["deactivation_reason"] = "deadline_passed"
                counts["newly_deactivated"] += 1
        else:
            counts["kept_active"] += 1

    return counts


def deactivate_past_in_shards(
    shards_dir: Path | None = None,
    today: date | None = None,
    *,
    save: bool = False,
) -> dict:
    """Apply the same rule to every committed shard file.

    This exists because the corpus has two representations and only one of them
    is committed. ``deactivate_past`` runs corpus-wide over the work file, but
    the publication split writes back only the shards the run was authorized to
    replace (#722, so a partial scrape can't revert a school it never
    touched). A record that crosses its deadline while its shard is not in that
    day's rotation therefore has its retirement computed and then thrown away:
    CI reassembles the corpus from shards and the record is active again. That
    is not hypothetical — ``handshake-56d6cdae`` (uiuc, deadline 2026-08-06)
    failed the zero-tolerance gate on 2026-08-13, a day-4 run that does not
    include uiuc, and killed the whole refresh.

    Running over shards this run never scraped is safe: the decision is a pure
    function of ``(deadline, today)``, it only ever retires (never revives), and
    it writes only ``metadata.is_active`` / ``deactivated_at`` /
    ``deactivation_reason`` on records it retires. A change that landed on main
    during the scrape survives, because the shard is read from disk here rather
    than rewritten from the run's in-memory corpus.

    Returns ``{shard: counts}`` for shards that had something to retire.
    """
    shards_dir = shards_dir or DEFAULT_SHARDS_DIR
    changed: dict[str, dict] = {}
    for path in sorted(shards_dir.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            records = json.load(f)
        counts = deactivate_past(records, today)
        if not counts["newly_deactivated"]:
            continue
        changed[path.stem] = counts
        if save:
            # Shards are committed minified (scripts/shard_corpus.py split);
            # pretty-printing here would rewrite every line of the file.
            atomic_write_json(path, records, indent=None, separators=(",", ":"))
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--save", action="store_true", help="Write changes back to file")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without writing")
    parser.add_argument(
        "--shards",
        action="store_true",
        help="Operate on the committed per-school shards instead of the work file",
    )
    args = parser.parse_args()

    if args.shards:
        changed = deactivate_past_in_shards(
            save=args.save and not args.dry_run,
        )
        total = sum(c["newly_deactivated"] for c in changed.values())
        print(f"Shard pass: {total} record(s) retired across {len(changed)} shard(s)")
        for shard, counts in sorted(changed.items()):
            print(f"  {shard:<20s} {counts['newly_deactivated']:>4d}")
        if not (args.save and not args.dry_run):
            print("\n(dry-run — pass --save to persist)")
        return 0

    if not args.path.exists():
        print(f"ERROR: file not found: {args.path}", file=sys.stderr)
        return 1

    with args.path.open("r", encoding="utf-8") as f:
        opps = json.load(f)

    counts = deactivate_past(opps)

    print(f"Loaded {len(opps)} opportunities from {args.path}")
    for key in (
        "newly_deactivated",
        "already_inactive",
        "kept_active",
        "skipped_rolling",
        "skipped_no_deadline",
        "skipped_invalid",
    ):
        print(f"  {key:<22s} {counts[key]:>6d}")

    if args.save and not args.dry_run:
        with args.path.open("w", encoding="utf-8") as f:
            json.dump(opps, f, indent=2, ensure_ascii=False, default=str)
        print(f"\nSaved to {args.path}")
    else:
        print("\n(dry-run — pass --save to persist)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
