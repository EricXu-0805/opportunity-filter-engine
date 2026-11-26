"""Compare the complete B19 proposal with its live first parent and the reviewed sources."""
import argparse
import json
import subprocess
from pathlib import Path

from check_b19_merge_preservation import BASE, REVIEWED, SHARDS, check

SCHOOL_TOTALS = "frontend/src/lib/school-stats.json"
DATA_PATHS = {f"data/processed/shards/{key}.json" for key in SHARDS}


def tree(ref):
    raw = subprocess.check_output(["git", "ls-tree", "-r", "-z", ref])
    result = {}
    for entry in raw.split(b"\0"):
        if entry:
            metadata, path = entry.split(b"\t",1)
            result[path.decode()] = metadata.decode()
    return result


def changed(left, right):
    return {key for key in left.keys() | right.keys() if left.get(key) != right.get(key)}


def compare(published, candidate):
    base, original, live, merged = map(tree, (BASE, REVIEWED, published, candidate))
    reviewed_paths = changed(base, original)
    unexpected = changed(live, merged) - reviewed_paths
    metadata = {}
    concurrent = []
    for path in sorted(reviewed_paths - DATA_PATHS - {SCHOOL_TOTALS}):
        if live.get(path) in {base.get(path), original.get(path)}:
            metadata[path] = merged.get(path) == original.get(path)
        else:
            concurrent.append(path)
    identity = {name:check(name, published, candidate) for name in SHARDS}
    return {
        "published":published,"candidate":candidate,"original_parent":BASE,"original_b19":REVIEWED,
        "unexpected_changes_outside_reviewed_paths":sorted(unexpected),
        "individually_review_concurrent_changes_in":concurrent,
        "code_or_test_matches_original_review":metadata,
        "verified_data":identity,
        "total_tracked_paths_in_candidate":len(merged),
        "published_processed_paths":sum(path.startswith("data/processed/") for path in live),
        "passed":not unexpected and not concurrent and all(metadata.values()) and all(s["passed"] for s in identity.values()),
        "school_stats":"Run the official normal generator from assembled corpus and from a cold shard-only checkout at this exact candidate.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--published",required=True)
    parser.add_argument("--candidate",required=True)
    parser.add_argument("--out",type=Path,required=True)
    args = parser.parse_args()
    result = compare(args.published, args.candidate)
    args.out.write_text(json.dumps(result,indent=2)+"\n")
    print("B19 complete reviewed scope preserved:",result["passed"])
    raise SystemExit(0 if result["passed"] else 1)
