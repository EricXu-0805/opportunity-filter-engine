"""Check the real data PR and source checkout, after normal publication. Read-only."""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("run", type=int)
p.add_argument("data_pr", type=int)
p.add_argument("release_sha")
p.add_argument("day")
p.add_argument("out", type=Path)
args = p.parse_args()
receipt = json.loads((Path(__file__).resolve().parent.parent / "arizona-nursing-20261127.json").read_bytes())
case = {
    "observed_entity_ids": receipt["baseline_replay_observed_ids"],
    "new_ids": receipt["released_data_scope"]["nursing_additions_after_full_collector_replay"],
    "originals": {
        id: {"active": active} for id, active in receipt["replay"][1]["active_originals"].items() if active is not None
    },
}
target = set(case["observed_entity_ids"])
repo = "EricXu-0805/opportunity-filter-engine"
fix = receipt["source_commit"]


def cmd(*args):
    return subprocess.check_output(args, text=True)


def gh(*args):
    return json.loads(cmd("gh", *args, "--repo", repo))


def is_ancestor(first, last):
    return subprocess.run(["git", "merge-base", "--is-ancestor", first, last], check=False).returncode == 0


def data(sha, path):
    return json.loads(cmd("git", "show", sha + ":" + path))


run = gh("run", "view", str(args.run), "--json", "url,event,headSha,status,conclusion,workflowName,jobs")
pr = gh("pr", "view", str(args.data_pr), "--json", "url,state,baseRefName,headRefName,mergeCommit,mergedAt")
record = {
    "run": run["url"],
    "overall_workflow_outcome": run["conclusion"],
    "data_pr": pr["url"],
    "public_release": args.release_sha,
    "gates": {},
}
checks = record["gates"]


def save(state):
    record["state"] = state
    args.out.write_text(json.dumps(record, indent=2) + "\n")


if run["status"] != "completed" or pr["state"] != "MERGED":
    save("pending_publication")
    sys.exit(2)
merge = pr["mergeCommit"]["oid"]
checks["natural_schedule"] = run["event"] == "schedule" and run["workflowName"] == "Refresh Opportunity Data"
checks["data_pr_of_run"] = pr["baseRefName"] == "main" and pr["headRefName"] == "auto/refresh-data-" + str(args.run)
checks["data_merge_in_public_release"] = is_ancestor(merge, args.release_sha)
job = next((j for j in run["jobs"] if j["name"].lower() == "refresh"), None)
if not job:
    job = next(
        j
        for j in run["jobs"]
        if any("refresh" in step["name"].lower() and "data" in step["name"].lower() for step in j["steps"])
    )
log = cmd("gh", "api", f"repos/{repo}/actions/jobs/{job['databaseId']}/logs")
match = re.search(r"git log -1 --format=%H\s*\n[^\n]*?\b([a-f0-9]{40})\b", log)
checkout = match[1] if match else ""
checks["real_checkout_includes_fix"] = bool(checkout and is_ancestor(fix, checkout))
checks["arizona_ran"] = bool(re.search(r"arizona_faculty: \d+ fetched", log))
record["collector_checkout"] = checkout
status = data(merge, "data/processed/collector_status.json")
ledger = status["sources"]["arizona_faculty"]["stale_unit_ledger"]["nurs"]
checks["requested_deep_school"] = "arizona" in status["request"]["schools"] and status["request"]["deep"]
checks["real_day"] = ledger["started_at"].startswith(args.day)
seen = set(ledger["observed_entity_ids"])
baseline = data("e4edf829", "data/processed/shards/arizona.json")
rows = {r["id"]: r for r in data(merge, "data/processed/shards/arizona.json")}
checks["original_arizona_ids_preserved"] = set(r["id"] for r in baseline) <= rows.keys()
checks["fully_read_unit"] = (
    ledger["fetch_status"] == ledger["parse_status"] == "ok"
    and ledger["completeness_status"] == "complete"
    and ledger["retirement_authorized"]
    and not ledger["missed_present_identities"]
)
record["seen_nursing_ids"] = len(seen)
record["reported_nursing_live_roster"] = ledger["live_roster_count"]
record["nursing_observed_emissions"] = ledger["observed_count"]
record["observed_start"] = ledger["started_at"]
record["observed_end"] = ledger["completed_at"]
record["newly_seen_since_replay"] = sorted(seen - target)
record["absent_since_replay"] = sorted(target - seen)
checks["november_roster_accounted"] = target <= seen
record["rows"] = []
start = datetime.fromisoformat(ledger["started_at"]).replace(tzinfo=None)
end = datetime.fromisoformat(ledger["completed_at"]).replace(tzinfo=None)
for id in sorted(set(case["new_ids"]) | set(case["originals"]) | {"faculty-arizona-nurs-77b21e8a"}):
    row = rows.get(id) or {}
    m = row.get("metadata", {})
    t = m.get("last_seen_at")
    expected_fresh = id in (
        set(case["new_ids"])
        | {"faculty-arizona-nurs-726ce682", "faculty-arizona-nurs-df22308d", "faculty-arizona-nurs-20b8c26b"}
    )
    fresh = bool(t and start <= datetime.fromisoformat(t).replace(tzinfo=None) <= end)
    prior = case["originals"].get(id, {})
    ok = (
        bool(id in seen and fresh and m.get("is_active") is True)
        if expected_fresh
        else bool(
            id not in rows and id in seen
            if id == "faculty-arizona-nurs-77b21e8a"
            else bool(row)
            and m.get("is_active") == prior.get("active")
            and (
                not m.get("deactivation_reason")
                if prior.get("active")
                else m.get("deactivation_reason") == "absent_from_directory_rescrape"
            )
        )
    )
    record["rows"].append(
        {
            "id": id,
            "listed_here": id in seen,
            "snapshot_name": row.get("pi_name"),
            "active": m.get("is_active"),
            "seen_during_nursing_fetch": fresh,
            "matched": ok,
        }
    )
checks["target_identities_and_true_observation_times"] = all(r["matched"] for r in record["rows"])
save("pass" if all(checks.values()) else "review")
print(record["state"], record["gates"], args.out)
sys.exit(0 if record["state"] == "pass" else 1)
