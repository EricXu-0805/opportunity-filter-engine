"""Read an actual post-B20 main and its proposed B21 merge, preserving later data and reporting same-field edits."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = "data/processed/"
SHARDS = ROOT + "shards/"
THURSDAY = "31984a4cf65992e448a0d8838c15f8cf2c184915"
CLEAN = "cca25d15d7878e94eee857bb185fe14cdae4b099"
PITT = "970cc272acc72aa45fae1c7b445cf6edf5013d8c"
CHANGES = [
    (1468, THURSDAY, CLEAN),
    (1469, CLEAN, "ee4f3bb9ec74cbaa7831b4b1f6e9553c1200eb1d"),
    (1470, CLEAN, PITT),
    (1471, CLEAN, "6bf06d3657cafd2ab1fa89ccb980e7cd909a8c61"),
    (1472, PITT, "57b86bcb555166852f6f7e0e70096d894343f93c"),
]
EXPECTED = {"miami": 444, "duke": 90, "pitt": 29, "fsu": 2, "usc": 2, "ucsd": 1}
MISSING = object()


def git(*args):
    return subprocess.check_output(["git", *args])


def shards_tree(sha):
    lines = git("ls-tree", "-r", sha, "--", ROOT).decode().splitlines()
    return {line.split("\t")[1]: line.split("\t")[0].split()[-1] for line in lines}


def read_rows(sha, path):
    rows = json.loads(git("show", f"{sha}:{path}"))
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError(f"Duplicate original ID in {sha}:{path}")
    return by_id


def apply_delta(before, after, live, path, conflicts):
    if before == after:
        return live
    if live == before or live == after:
        return after
    if all(isinstance(value, dict) for value in (before, after, live)):
        merged = dict(live)
        for key in sorted(before.keys() | after.keys()):
            value = apply_delta(before.get(key, MISSING), after.get(key, MISSING), live.get(key, MISSING),
                                (*path, key), conflicts)
            if value is MISSING:
                merged.pop(key, None)
            else:
                merged[key] = value
        return merged
    conflicts.append(".".join(path))
    return live


def reviewed_net(path):
    baseline = read_rows(THURSDAY, path)
    combined = dict(baseline)
    for number, base, head in CHANGES:
        if not git("diff", "--name-only", base, head, "--", path):
            continue
        before, after = read_rows(base, path), read_rows(head, path)
        assert list(before) == list(after) == list(baseline), f"Original IDs changed in #{number}:{path}"
        for oid in before:
            if before[oid] != after[oid]:
                conflicts = []
                combined[oid] = apply_delta(before[oid], after[oid], combined[oid], (oid,), conflicts)
                assert not conflicts, f"Source disagreement in #{number}:{conflicts}"
    reviewed = {oid: (baseline[oid], row) for oid, row in combined.items() if row != baseline[oid]}
    assert len(reviewed) == EXPECTED[Path(path).stem]
    return reviewed


def review_code_scope(published, candidate):
    def files(ref):
        raw = git("ls-tree", "-r", "-z", ref)
        entries = (line.split(b"\t", 1) for line in raw.split(b"\0") if line)
        return {path.decode(): mode_and_blob.decode() for mode_and_blob, path in entries
                if not path.startswith(ROOT.encode()) and path != b"frontend/src/lib/school-stats.json"}

    base = files("33616280a6a8eac8ea7eecf22ad080641b0c3601")
    original = files("4e712e765834817ff6559fc0b6c69ed476cc8f7d")
    live = files(published)
    merged = files(candidate)
    reviewed = {path for path in base.keys() | original.keys() if base.get(path) != original.get(path)}
    outside = sorted(path for path in live.keys() | merged.keys()
                     if live.get(path) != merged.get(path) and path not in reviewed)
    concurrent, missing = [], []
    for path in sorted(reviewed):
        if live.get(path) not in {base.get(path), original.get(path)}:
            concurrent.append(path)
        elif merged.get(path) != original.get(path):
            missing.append(path)
    return {"reviewed_files": sorted(reviewed), "changes_outside_reviewed_files": outside,
            "individually_review_concurrent_changes_in": concurrent, "missing_reviewed_code": missing,
            "passed": not (outside or concurrent or missing)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--published", required=True, help="Exact real main after B20 and any newer published data")
    parser.add_argument("--candidate", required=True, help="Exact integration commit proposed for that main")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--full-scope", action="store_true", help="Also check the 19 source and test paths and all other tracked files before merging on actual main")
    args = parser.parse_args()
    live_tree, candidate_tree = shards_tree(args.published), shards_tree(args.candidate)
    paths_changed = sorted(live_tree.keys() ^ candidate_tree.keys())
    unexpected = []
    common = live_tree.keys() & candidate_tree.keys()
    checked = {}
    for path in sorted(common):
        school = Path(path).stem
        if not path.startswith(SHARDS) or school not in EXPECTED:
            if live_tree[path] != candidate_tree[path]:
                unexpected.append(path)
            continue
        net = reviewed_net(path)
        live, candidate = read_rows(args.published, path), read_rows(args.candidate, path)
        dropped_or_unexpected = sorted(live.keys() ^ candidate.keys())
        missing_reviewed = sorted(net.keys() - live.keys())
        differs, same_field = [], []
        for oid in live.keys() & candidate.keys():
            expected = live[oid]
            if oid in net:
                expected = apply_delta(*net[oid], expected, (oid,), same_field)
            if candidate[oid] != expected:
                differs.append(oid)
        checked[school] = {"current_ids": len(live), "reviewed_unique_original_ids": sorted(net),
                           "same_order": list(live) == list(candidate),
                           "original_ids_dropped_or_unexpected": dropped_or_unexpected,
                           "reviewed_ids_missing_on_current_main": missing_reviewed,
                           "concurrent_field_changes_requiring_review": sorted(same_field),
                           "rows_differing_from_live_plus_reviewed_delta": sorted(differs)}
    passed = not paths_changed and not unexpected and checked.keys() == EXPECTED.keys() and all(
        val["same_order"] and not any(val[k] for k in ("original_ids_dropped_or_unexpected","reviewed_ids_missing_on_current_main",
                       "concurrent_field_changes_requiring_review","rows_differing_from_live_plus_reviewed_delta"))
        for val in checked.values())
    report = {"published": args.published, "candidate": args.candidate, "scope": "All committed data/processed paths. Run the official 115-school generator separately on the exact candidate.",
              "reviewed_sources": [1467, *[n for n, _, _ in CHANGES]], "shards": checked,
              "unknown_added_or_removed_data_paths": paths_changed,"unexpected_changed_data_paths": unexpected,"passed":passed}
    if args.full_scope:
        report["code_and_other_files"] = review_code_scope(args.published, args.candidate)
        passed = passed and report["code_and_other_files"]["passed"]
        report["passed"] = passed
    args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("current main protected:", passed, "shards:", sum(p.startswith(SHARDS) for p in common))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
