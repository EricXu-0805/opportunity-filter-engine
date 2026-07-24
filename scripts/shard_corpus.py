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
straggler run that produced a fresher work file is never clobbered.

Runtime readers that can't rely on an assemble step (the deployed backend,
frontend prebuild) fall back to reading the shards directory directly.
"""
from __future__ import annotations

import json
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
          prune: bool = False) -> dict[str, int]:
    """Work file -> minified per-school shard files. Returns {shard: count}.

    Upsert-only by default: writes/updates a shard for every school PRESENT in
    the work file and LEAVES every other on-disk shard untouched. This is the
    safe mode for the weekly refresh, whose work file is assembled from its
    run-start checkout and therefore omits any school onboarded to main *after*
    the run began — deleting those "absent" shards is exactly how auto-refresh
    #614/#630 wiped freshly-landed schools (Yale, then the Wave-3 six). A shard
    is removed ONLY when ``prune=True`` (a deliberate full rebuild), never on a
    partial/scheduled run.

    Shrink guard: if a school's new shard would be < ``keep_ratio`` of the
    already-committed shard (and that shard has >= ``guard_floor`` records), the
    new shard is treated as a flaked scrape and the existing shard is LEFT
    untouched, so a bad re-scrape can never clobber good faculty data. Kept
    shards are logged loudly; the returned count reflects what is actually on
    disk (the retained old count), not the discarded shrunken count.
    """
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from minify_corpus import prune_duplicate_raw

    with open(work_file, encoding="utf-8") as f:
        records = json.load(f)
    prune_duplicate_raw(records)
    by_school: dict[str, list] = {}
    for r in records:
        by_school.setdefault(_slug(r), []).append(r)
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
    for slug, recs in sorted(by_school.items()):
        shard_path = shards_dir / f"{slug}.json"
        if shard_path.exists():
            try:
                with open(shard_path, encoding="utf-8") as f:
                    old_n = len(json.load(f))
            except (OSError, ValueError):
                old_n = 0
            if old_n >= guard_floor and len(recs) < keep_ratio * old_n:
                # Leave the committed shard in place; report its real count.
                kept.append((slug, len(recs), old_n))
                counts[slug] = old_n
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
    return counts


def load_shards(shards_dir: Path = SHARDS_DIR) -> list[dict]:
    """Concatenate all shards (sorted by filename for determinism)."""
    records: list[dict] = []
    for shard in sorted(shards_dir.glob("*.json")):
        with open(shard, encoding="utf-8") as f:
            records.extend(json.load(f))
    return records


def assemble(work_file: Path = WORK_FILE, shards_dir: Path = SHARDS_DIR,
             force: bool = False) -> int:
    """Shards -> work file. Skips when the work file already exists (a fresher
    in-flight corpus must never be clobbered by a stale checkout) unless force.
    Returns the record count written (or -1 when skipped)."""
    if work_file.exists() and not force:
        return -1
    records = load_shards(shards_dir)
    atomic_write_json(work_file, records, indent=None, separators=(",", ":"))
    return len(records)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "split":
        prune = "--prune" in sys.argv
        counts = split(prune=prune)
        total = sum(counts.values())
        print(f"split{' --prune' if prune else ''}: {total} records -> {len(counts)} shards "
              f"({', '.join(f'{s}:{n}' for s, n in counts.items())})")
        return 0
    if cmd == "assemble":
        n = assemble(force="--force" in sys.argv)
        print("assemble: work file already present — skipped (use --force to rebuild)"
              if n < 0 else f"assemble: {n} records -> {WORK_FILE.name}")
        return 0
    print(__doc__)
    print("usage: shard_corpus.py {split [--prune]|assemble [--force]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
