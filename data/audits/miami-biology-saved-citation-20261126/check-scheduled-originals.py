"""Check a real scheduled Miami run and its generated PR against known original IDs and the current department.

Usage: python check-scheduled-originals.py RUN_ID REFRESH_PR > receipt.json
Output distinguishes the observed data commit, its PR state, and the public-release check.
"""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys

from bs4 import BeautifulSoup
import requests

root = Path(__file__).parent
baseline = json.loads((root / "biology-37-originals.json").read_text())
source = baseline["candidate_release"]
run_id, pr_num = map(int, sys.argv[1:3])
repo = "EricXu-0805/opportunity-filter-engine"
subject = "faculty-miami-bio-4dfe1b88"
receipt = {"at": datetime.now(timezone.utc).isoformat(), "stage": "scheduled collection and its generated data",
           "run_id": run_id, "refresh_pr": pr_num, "expected_source": source, "outcome": "blocked",
           "school_reads": 0, "snapshot_reads": 0, "originals": []}


def github(endpoint, *, raw=False):
    args = ["gh", "api", f"repos/{repo}/{endpoint}"]
    if raw:
        args += ["-H", "Accept: application/vnd.github.raw+json"]
    data = subprocess.check_output(args, timeout=60)
    return data if raw else json.loads(data)


def contains(older, newer):
    return github(f"compare/{older}...{newer}?per_page=1")["status"] in ("ahead", "identical")


def cleaned(value):
    return " ".join((value or "").replace("\u200c", "").split())


def check():
    run = github(f"actions/runs/{run_id}")
    receipt["action"] = {"url": run["html_url"], "event": run["event"], "status": run["status"],
                         "conclusion": run["conclusion"], "source": run["head_sha"], "started_at": run["run_started_at"]}
    if not (run["event"] == "schedule" and run["path"] == ".github/workflows/refresh-data.yml"
            and run["conclusion"] == "success" and contains(source, run["head_sha"])):
        receipt["blocker"] = "A successful natural refresh beginning with the reviewed source is required."
        return
    pr = github(f"pulls/{pr_num}")
    generated = pr["head"]["sha"]
    receipt["generated"] = {"sha": generated, "pr": pr["html_url"], "state": pr["state"], "merged_at": pr["merged_at"]}
    if pr["head"]["ref"] != f"auto/refresh-data-{run_id}" or not contains(run["head_sha"], generated):
        receipt["blocker"] = "This PR cannot be attributed to the selected scheduled run."
        return
    jobs = github(f"actions/runs/{run_id}/jobs?per_page=100")["jobs"]
    summaries = []
    for job in jobs:
        if job["name"] != "refresh":
            continue
        log = github(f"actions/jobs/{job['id']}/logs", raw=True).decode(errors="replace")
        for line in log.splitlines():
            match = re.search(r"INFO: miami_faculty: (\d+) fetched, (\d+) new, (\d+) updated", line)
            if match:
                summaries.append({"fetched":int(match[1]),"new":int(match[2]),"updated":int(match[3]),
                                  "observed_at":line.split()[0],"job":job["html_url"]})
    if len(summaries) != 1:
        receipt["blocker"] = "The jobs did not yield exactly one Miami source summary."
        return
    receipt["school_job"] = summaries[0]
    receipt["snapshot_reads"] += 1
    data = github(f"contents/data/processed/shards/miami.json?ref={generated}", raw=True)
    records = {r["id"]:r for r in json.loads(data)}
    receipt["school_reads"] += 1
    official = requests.get(baseline["official"], timeout=40)
    receipt["official"] = {"url":official.url,"http":official.status_code}
    official.raise_for_status()
    page = BeautifulSoup(official.content, "html.parser")
    cards = Counter(cleaned(n.get_text(" ",strip=True)) for n in page.select(".people-profile .profile-name span"))
    expected = Counter(row["name"] for row in baseline["originals"])
    receipt["official"].update(named_cards=sum(cards.values()),missing_old_names=list((expected-cards).elements()),
                               additional_names=list((cards-expected).elements()))
    day = summaries[0]["observed_at"][:10]
    for row in baseline["originals"]:
        rec = records.get(row["published_id"]) or {}
        meta = rec.get("metadata") or {}
        checks = {"published_id":rec.get("id")==row["published_id"],"same_name":cleaned(rec.get("pi_name"))==row["name"],
                  "named_by_university":cards[row["name"]]==1,"job_date":str(meta.get("last_seen_at","")).startswith(day),
                  "directory_or_profile_sighting":meta.get("verification_scope") in ("directory","profile"),
                  "active":meta.get("is_active") is True}
        if row["published_id"]==subject:
            checks.update(citation=rec.get("source_url")==baseline["official"]+"#:~:text=DeAngelis",
                          name_accessible=rec.get("pi_name")=="Don DeAngelis",
                          academic_rank=meta.get("faculty_title")=="Research Professor")
        receipt["originals"].append({"saved_id":row["published_id"],"name":row["name"],"unit_only_id":row["normalized_unit_id"],
                                     "published_department":rec.get("department"),"last_observed_at":meta.get("last_seen_at"),"checks":checks})
    outcomes = [v for row in receipt["originals"] for v in row["checks"].values()]
    receipt["outcome"] = "passed" if all(outcomes) and cards==expected else "review_changes"


try:
    check()
except (KeyError, OSError, ValueError, subprocess.SubprocessError, requests.RequestException) as exc:
    receipt["blocker"] = type(exc).__name__
print(json.dumps(receipt,indent=2))
sys.exit({"passed":0,"review_changes":1,"blocked":2}[receipt["outcome"]])
