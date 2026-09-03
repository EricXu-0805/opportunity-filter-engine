#!/usr/bin/env python3
"""Per-school corpus sharding — the committed representation of the corpus.

The corpus outgrew GitHub's hard 100 MB blob limit as one file (96 MB minified
at 17 schools; every new school adds ~3-6 MB). What git stores is therefore a
directory of per-school shards, each far below the limit and growing
independently:

    data/processed/shards/<school>.json      (records with school == <school>)
    data/processed/shards/national.json      (records with school == None)

The PIPELINE is unchanged: collectors, normalizers, the backend, and tests all
keep reading/writing the single work file ``data/processed/opportunities.json``
(now gitignored). The two representations meet at exactly two moments:

    assemble  (checkout -> work file)   python scripts/shard_corpus.py assemble
    split     (work file -> commit)     python scripts/shard_corpus.py split

``split`` reuses minify_corpus's lossless pruning (drop description_raw where it
equals description_clean) and writes each shard minified. It is UPSERT-ONLY:
it touches only schools present in the work file and never deletes an absent
school's shard unless run with ``--prune`` (a deliberate full rebuild). The
scheduled refresh omits ``--prune`` so a partial run can't delete a school it
simply didn't scrape — the failure mode that wiped Yale (#614) and the Wave-3
six (#630) off main.
``assemble`` is a no-op when the work file already exists unless --force — so a
straggler run that produced a fresher work file is never clobbered — and it
FAILS rather than writing a near-empty work file (see MIN_ASSEMBLED_RECORDS),
because a silently empty corpus turns the data-quality test gate green.

Runtime readers that can't rely on an assemble step (the deployed backend,
frontend prebuild) fall back to reading the shards directory directly.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.atomic_json import atomic_write_json  # noqa: E402

WORK_FILE = PROJECT_ROOT / "data" / "processed" / "opportunities.json"
SHARDS_DIR = PROJECT_ROOT / "data" / "processed" / "shards"
NATIONAL = "national"


def _slug(record: dict) -> str:
    s = record.get("school")
    return s if isinstance(s, str) and s.strip() else NATIONAL


# A re-scrape that suddenly yields far fewer records for an established school
# is almost always a broken/flaked scrape (Cloudflare/AWS-WAF or a headless
# render failing on CI's datacenter IP, an assemble-skip on a stale work file,
# etc.) rather than real attrition — a 1000-faculty school never loses 30% of
# its roster in one weekly cycle. Keep the prior committed shard instead of
# committing the regression. Guards only established shards (>= floor records);
# small/volatile shards update freely.
SHRINK_KEEP_RATIO = 0.7
SHRINK_GUARD_FLOOR = 100


def split(work_file: Path = WORK_FILE, shards_dir: Path = SHARDS_DIR,
          keep_ratio: float = SHRINK_KEEP_RATIO,
          guard_floor: int = SHRINK_GUARD_FLOOR,
          prune: bool = False,
          only_shards: set[str] | None = None,
          retained_out: set[str] | None = None) -> dict[str, int]:
    """Work file -> minified per-school shard files. Returns {shard: count}.

    Upsert-only by default: writes/updates a shard for every school PRESENT in
    the work file and LEAVES every other on-disk shard untouched. Passing
    ``only_shards`` narrows that further to the exact schools authorized by a
    scheduled refresh. This is the safe publication mode for a long-running
    scrape: its work file contains stale run-start copies of non-target schools,
    so those copies must never be replayed over a newer default branch.

    A shard is removed ONLY when ``prune=True`` (a deliberate full rebuild),
    never on a partial/scheduled run. ``prune`` and ``only_shards`` are mutually
    exclusive because a target-scoped release is never authorized to infer
    global deletion.

    Shrink guard: if a school's new shard would be < ``keep_ratio`` of the
    already-committed shard (and that shard has >= ``guard_floor`` records), the
    new shard is treated as a flaked scrape and the existing shard is LEFT
    untouched, so a bad re-scrape can never clobber good faculty data. Kept
    shards are logged loudly; the returned count reflects what is actually on
    disk (the retained old count), not the discarded shrunken count.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from minify_corpus import prune_duplicate_raw

    if prune and only_shards is not None:
        raise ValueError("prune cannot be combined with target-only shard output")
    if only_shards is not None and not only_shards:
        raise ValueError("only_shards must name at least one target")
    if only_shards is not None:
        invalid = sorted(
            slug
            for slug in only_shards
            if re.fullmatch(r"[a-z0-9-]{1,64}", slug) is None
        )
        if invalid:
            raise ValueError(f"invalid target shard slug(s): {invalid}")

    with open(work_file, encoding="utf-8") as f:
        records = json.load(f)
    prune_duplicate_raw(records)
    by_school: dict[str, list] = {}
    for r in records:
        by_school.setdefault(_slug(r), []).append(r)
    invalid_record_slugs = sorted(
        slug
        for slug in by_school
        if re.fullmatch(r"[a-z0-9-]{1,64}", slug) is None
    )
    if invalid_record_slugs:
        raise ValueError(
            f"work file contains unsafe school slug(s): {invalid_record_slugs}"
        )
    if only_shards is not None:
        missing = sorted(only_shards - set(by_school))
        if missing:
            raise ValueError(
                f"target shard(s) absent from refresh work file: {missing}"
            )
        by_school = {
            slug: by_school[slug]
            for slug in sorted(only_shards)
        }
    shards_dir.mkdir(parents=True, exist_ok=True)
    # Only a deliberate full rebuild (prune=True) removes shards for schools
    # absent from the work file. A partial/scheduled split leaves them alone so
    # it can never delete a school it simply didn't scrape this run.
    if prune:
        for stale in shards_dir.glob("*.json"):
            if stale.stem not in by_school:
                stale.unlink()
                print(f"shard_corpus: pruned absent shard {stale.name}", file=sys.stderr)
    counts: dict[str, int] = {}
    kept: list[tuple[str, int, int]] = []
    old_counts: dict[str, int] = {}
    for slug, recs in sorted(by_school.items()):
        shard_path = shards_dir / f"{slug}.json"
        if shard_path.exists():
            try:
                with open(shard_path, encoding="utf-8") as f:
                    old_n = len(json.load(f))
            except (OSError, ValueError):
                old_n = 0
        else:
            old_n = 0
        old_counts[slug] = old_n
        if old_n >= guard_floor and len(recs) < keep_ratio * old_n:
            kept.append((slug, len(recs), old_n))

    # A shrunken target keeps its prior shard and says so LOUDLY - but only
    # that target. This used to raise before writing anything, so one flaked
    # school discarded every healthy school in the same run: the same
    # one-failure-vetoes-everything shape that #8 removed from the release
    # verdict and that source_health removes from the per-department gate.
    # Retention is reported back to the caller (and printed by main) so
    # "published" never silently means "kept the old one".
    kept_slugs = {slug for slug, _new_n, _old_n in kept}
    for slug, recs in sorted(by_school.items()):
        shard_path = shards_dir / f"{slug}.json"
        if slug in kept_slugs:
            # Retained: the prior shard stays exactly as committed, and
            # its siblings below are written regardless.
            counts[slug] = old_counts[slug]
            continue
        atomic_write_json(shard_path, recs, indent=None, separators=(",", ":"))
        counts[slug] = len(recs)
    if kept:
        for slug, new_n, old_n in kept:
            print(
                f"shard_corpus: SHRINK GUARD kept prior {slug}.json ({old_n} records) "
                f"— this run yielded only {new_n} (< {keep_ratio:.0%}); likely a "
                f"flaked scrape, not committing the regression.",
                file=sys.stderr,
            )
    # Stamp last_publish_at for exactly the shards whose bytes changed. A
    # retained shard is NOT a publish: recording one would let a
    # permanently broken school look freshly published every week.
    if retained_out is not None:
        retained_out.update(kept_slugs)
    written = {slug: n for slug, n in counts.items() if slug not in kept_slugs}
    if written:
        _record_publish(written, shards_dir)
    return counts


def _record_publish(written: dict[str, int], shards_dir: Path) -> None:
    """Stamp the publish moment for the shards just written.

    Best-effort: sharding must not fail because a monitoring ledger could not
    be updated. Per-SHARD only - publishing a school must never be mistaken
    for its departments having succeeded (see source_health.record_publish).
    """
    try:
        from datetime import UTC, datetime

        from src.collectors import source_health

        # Beside the shards being written, so a split into a tmp directory
        # cannot stamp publish times into the committed ledger.
        path = source_health.ledger_path_for(shards_dir.parent)
        ledger = source_health.load_ledger(path)
        source_health.record_publish(ledger, shards=written, now=datetime.now(UTC))
        source_health.save_ledger(ledger, path)
    except Exception as exc:  # noqa: BLE001
        print(f"shard_corpus: could not record publish timestamps: {exc}",
              file=sys.stderr)


def load_shards(shards_dir: Path = SHARDS_DIR) -> list[dict]:
    """Concatenate all shards (sorted by filename for determinism)."""
    records: list[dict] = []
    for shard in sorted(shards_dir.glob("*.json")):
        with open(shard, encoding="utf-8") as f:
            records.extend(json.load(f))
    return records


# An assemble that yields (almost) nothing is never legitimate outside a
# deliberate bootstrap: the committed shards hold ~132k records, and the
# smallest plausible real corpus is orders of magnitude above this floor. It
# used to write `[]` and exit 0 when data/processed/shards/ was empty, absent,
# or simply not checked out — and that silence propagated: 53 data-quality
# tests SKIP when the work file is missing (tests/test_opportunity_data_quality
# .py:48 and friends) and a ~0-record work file skips or trivially passes them
# too, so pytest exits 0 with the data-quality gate vacuously green. The floor
# sits far below the true count on purpose: it catches catastrophe (no shards,
# wrong cwd, a truncated checkout), not attrition — per-school regressions are
# the shrink guard's job, above.
MIN_ASSEMBLED_RECORDS = 1000


def assemble(work_file: Path = WORK_FILE, shards_dir: Path = SHARDS_DIR,
             force: bool = False, allow_empty: bool = False,
             min_records: int = MIN_ASSEMBLED_RECORDS) -> int:
    """Shards -> work file. Skips when the work file already exists (a fresher
    in-flight corpus must never be clobbered by a stale checkout) unless force.
    Returns the record count written (or -1 when skipped).

    Raises ValueError when the shards yield fewer than ``min_records`` records
    and ``allow_empty`` is False — before writing anything, so a broken
    checkout cannot leave a truncated work file behind for later steps to read.
    ``allow_empty`` is the escape hatch for a legitimate bootstrap (first
    school, a scratch corpus built from one shard, a fixture directory).
    """
    if work_file.exists() and not force:
        return -1
    records = load_shards(shards_dir)
    if not allow_empty and len(records) < min_records:
        raise ValueError(
            f"assemble refused: {shards_dir} yielded {len(records)} records, "
            f"below the {min_records}-record floor (the committed corpus is "
            f"~132k). An empty/short assemble silently disables the "
            f"data-quality gate, so this fails instead of writing "
            f"{work_file.name}. Check that the shards directory was checked "
            f"out; pass --allow-empty for a deliberate bootstrap."
        )
    atomic_write_json(work_file, records, indent=None, separators=(",", ":"))
    return len(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    split_parser = subparsers.add_parser("split")
    split_parser.add_argument("--prune", action="store_true")
    split_parser.add_argument(
        "--only-shards",
        help="Comma-separated committed shard slugs authorized for this release",
    )
    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--force", action="store_true")
    assemble_parser.add_argument(
        "--allow-empty",
        action="store_true",
        help=f"skip the {MIN_ASSEMBLED_RECORDS}-record floor (bootstrap only)",
    )
    args = parser.parse_args(argv)

    if args.command == "split":
        only_shards = None
        if args.only_shards is not None:
            values = args.only_shards.split(",")
            if any(not value for value in values) or len(values) != len(set(values)):
                parser.error("--only-shards must contain unique non-empty slugs")
            only_shards = set(values)
        retained: set[str] = set()
        try:
            counts = split(
                prune=args.prune,
                only_shards=only_shards,
                retained_out=retained,
            )
        except ValueError as exc:
            parser.error(str(exc))
        total = sum(counts.values())
        mode = " --prune" if args.prune else (
            " --only-shards" if only_shards is not None else ""
        )
        print(f"split{mode}: {total} records -> {len(counts)} shards "
              f"({', '.join(f'{s}:{n}' for s, n in counts.items())})")
        if retained:
            # Loud, and on the annotation channel so it surfaces in the run
            # log - but NOT fatal: the shards that were written are correct
            # and withholding them would repeat the bug this replaced.
            print(
                "::warning::shard_corpus: retained the previously committed "
                f"shard(s) for {', '.join(sorted(retained))} (shrink guard); "
                f"{len(counts) - len(retained)} shard(s) published normally. "
                "Those schools keep their last-known-good data and are "
                "reported stale until a run re-collects them.",
                file=sys.stderr,
            )
        return 0
    if args.command == "assemble":
        try:
            # Paths passed explicitly (not left to the defaults, which bind at
            # def time) so a test can point the CLI at a fixture directory.
            n = assemble(WORK_FILE, SHARDS_DIR,
                         force=args.force, allow_empty=args.allow_empty)
        except ValueError as exc:
            # Non-zero, so the CI step that runs this actually gates.
            print(f"::error::{exc}", file=sys.stderr)
            return 1
        print("assemble: work file already present — skipped (use --force to rebuild)"
              if n < 0 else f"assemble: {n} records -> {WORK_FILE.name}")
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
