"""Reconcile the three reviewed additions with the upstream tree that will actually be published."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

BASE = "1f73bfdba364aa2505cd33840825f4f56008cbcc"
REVIEWED = "76c7071217f07a12cc6125629b451b43d7073f3a"
SHARD = "data/processed/shards/udel.json"
MATTHEW = "faculty-udel-geol-cc0d1c3c"


def check(repo, actual, proposal):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args])

    def paths(start, end):
        return set(git("diff", "--name-only", start, end).decode().splitlines())

    def files(revision):
        return set(git("ls-tree", "-r", "--name-only", revision).decode().splitlines())

    def contents(revision, path, present):
        return git("show", revision + ":" + path) if path in present else b""

    originals, upstream_files, proposal_files, reviewed_files = (files(s) for s in (BASE, actual, proposal, REVIEWED))
    target = paths(BASE, REVIEWED)
    actual_changes = paths(actual, proposal)
    assert len(target) == 16 and SHARD in target
    assert actual_changes <= target, actual_changes - target
    overlay = {}
    with tempfile.TemporaryDirectory() as scratch:
        for name in sorted(target - {SHARD}):
            assert name in proposal_files and name in reviewed_files
            start = contents(BASE, name, originals)
            upstream = contents(actual, name, upstream_files)
            reviewed = contents(REVIEWED, name, reviewed_files)
            if start == upstream:
                desired = reviewed
            elif upstream == reviewed:
                desired = upstream
            else:
                paths_to_merge = [Path(scratch) / part for part in ("published", "old", "reviewed")]
                for path, data in zip(paths_to_merge, (upstream, start, reviewed), strict=True):
                    path.write_bytes(data)
                result = subprocess.run(["git", "merge-file", "-p", *map(str, paths_to_merge)], capture_output=True)
                assert result.returncode == 0, (name, "overlapping source changes require review")
                desired = result.stdout
            assert contents(proposal, name, proposal_files) == desired, name
            overlay[name] = hashlib.sha256(desired).hexdigest()
    upstream = json.loads(contents(actual, SHARD, upstream_files))
    proposal_rows = json.loads(contents(proposal, SHARD, proposal_files))
    original_rows = json.loads(contents(BASE, SHARD, originals))
    reviewed_rows = json.loads(contents(REVIEWED, SHARD, reviewed_files))

    def record(rows):
        matched = [r for r in rows if r["id"] == MATTHEW]
        assert len(matched) == 1 and matched[0]["pi_name"] == "Matthew Oliver"
        return matched[0]

    previous, changed, current = map(record, (original_rows, reviewed_rows, upstream))
    fields = {key for key in previous | changed if previous.get(key) != changed.get(key)}
    assert fields == {"url", "source_url"}
    assert all(
        current[field] in {previous[field], changed[field]} for field in fields
    ), "Different campus URL needs review"
    current.update({field: changed[field] for field in fields})
    assert proposal_rows == upstream, "An existing Delaware row, field, order, or identity changed unexpectedly"
    other_shards = {p for p in upstream_files if p.startswith("data/processed/shards/") and p.endswith(".json")} - {
        SHARD
    }
    assert other_shards <= proposal_files and not other_shards & actual_changes
    return {
        "reviewed_parent": BASE,
        "reviewed": REVIEWED,
        "actual_parent": actual,
        "proposed": proposal,
        "other_shards_unchanged": len(other_shards),
        "delaware_original_count_in_order": len(upstream),
        "delaware_original": MATTHEW,
        "delaware_updated_fields": sorted(fields),
        "independently_reconstructed_source_sha256": overlay,
        "changed_paths": sorted(actual_changes),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--proposal", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.write_text(json.dumps(check(args.repo, args.actual, args.proposal), indent=2) + "\n")
