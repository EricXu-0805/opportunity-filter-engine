"""Compare a prospective B19 merge against its actual main parent, without changing either tree."""
import argparse
import json
import subprocess
from pathlib import Path

BASE = "773aaa9a5adc2b531477f0337cac6e88363a627f"
REVIEWED = "5305901ee08b094a27416c8550c1c8b48ff2383b"
SHARDS = {
    "national": {"sro-3ec4ea4e", "sro-44f176cd", "sro-595e912d", "nsf-reu-2447670",
                 "wisc-86cba49b83d7", "sro-3c378261"},
    "utexas": {"faculty-utexas-mpdd-5850399f"},
    "ucsd": {"faculty-ucsd-nano-25a6d469", "faculty-ucsd-nano-dc9e3de3",
             "faculty-ucsd-nano-2aa92754", "faculty-ucsd-nano-04ac1d79", "faculty-ucsd-nano-27240933"},
}
ABSENT = object()


def snapshot(ref_or_directory, school):
    local_dir = Path(ref_or_directory)
    if local_dir.is_dir():
        raw = (local_dir / (school + ".json")).read_bytes()
    else:
        raw = subprocess.check_output(["git", "show", f"{ref_or_directory}:data/processed/shards/{school}.json"])
    rows = json.loads(raw)
    by_id = {r["id"]: r for r in rows}
    if len(rows) != len(by_id):
        raise ValueError(f"{school} has duplicate IDs in {ref_or_directory}")
    return by_id


def extend_review(old, reviewed, current, path, overlaps):
    if old == reviewed:
        return current
    if current == old or current == reviewed:
        return reviewed
    if all(isinstance(o, dict) for o in (old, reviewed, current)):
        result = dict(current)
        for k in sorted(old.keys() | reviewed.keys()):
            changed = extend_review(old.get(k, ABSENT), reviewed.get(k, ABSENT), current.get(k, ABSENT), (*path, k), overlaps)
            if changed is ABSENT:
                result.pop(k, None)
            else:
                result[k] = changed
        return result
    overlaps.append(".".join(path))
    return current


def check(shard, live_ref, merged_ref):
    before, reviewed, live, merged = (snapshot(ref, shard) for ref in (BASE, REVIEWED, live_ref, merged_ref))
    touched = {oid for oid in before if before[oid] != reviewed[oid]}
    if touched != SHARDS[shard] or list(before) != list(reviewed):
        raise ValueError(f"The verified source baseline for {shard} has changed")
    overlaps, different = {}, []
    for oid in live.keys() & merged.keys():
        current = live[oid]
        expected = current
        if oid in touched:
            conflicts = []
            expected = extend_review(before[oid], reviewed[oid], current, (), conflicts)
            if conflicts:
                overlaps[oid] = conflicts
        if expected != merged[oid]:
            different.append(oid)
    missing_reviewed = sorted(touched - live.keys())
    dropped = sorted(live.keys() - merged.keys())
    added = sorted(merged.keys() - live.keys())
    same_order = list(live) == list(merged)
    return {
        "published_rows": len(live), "candidate_rows": len(merged), "original_reviewed_ids": sorted(touched),
        "published_ids_dropped_by_candidate": dropped, "ids_added_by_candidate": added,
        "same_order": same_order, "reviewed_ids_absent_on_published_main": missing_reviewed,
        "overlapping_source_fields_requiring_individual_review": overlaps,
        "rows_different_from_current_fields_plus_reviewed_changes": sorted(different),
        "passed": same_order and not (missing_reviewed or overlaps or different),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--published", required=True, help="Exact then-current main SHA, or a verified directory of its shard blobs")
    p.add_argument("--candidate", required=True, help="Exact proposed integration SHA, or a verified directory of its shard blobs")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    shards = {shard: check(shard, args.published, args.candidate) for shard in SHARDS}
    report = {"reviewed_baseline": BASE, "reviewed_b19": REVIEWED, "published": args.published,
              "candidate": args.candidate, "shards": shards, "passed": all(q["passed"] for q in shards.values())}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(args.candidate, "preserves current data and verified B19 fields:", report["passed"])
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
