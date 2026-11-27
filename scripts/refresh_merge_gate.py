"""Observe a data-refresh PR, merging only the exact commit the refresh created."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

# The three checks required on main register after the CI workflow's decide job.
# GitHub can return a nonempty, incomplete list during this interval.
REQUIRED = {"Backend (lint + pytest)", "Frontend (typecheck + build)", "E2E (Playwright)"}
PR_FIELDS = "state,baseRefName,baseRefOid,headRefOid,mergeStateStatus,mergeCommit"
MERGED, FAILED, REPLAY = 0, 1, 2


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=45)


def read_json(*args: str):
    result = gh(*args)
    # gh pr checks can return a nonzero exit code alongside valid check data.
    return json.loads(result.stdout)


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def wait_for_merge(pr: str, head: str, base: str, *, clock=time.monotonic, sleep=time.sleep) -> int:
    deadline = clock() + 75 * 60
    registration_end = clock() + 10 * 60
    current = head
    revised = False
    attempts = 0
    while clock() < deadline:
        try:
            state = read_json("pr", "view", pr, "--json", PR_FIELDS)
            if state["baseRefName"] != "main" or state["state"] == "CLOSED":
                log("The refresh PR was closed or retargeted. Its data has not reached main.")
                return FAILED
            if state["state"] == "MERGED":
                merge = (state.get("mergeCommit") or {}).get("oid")
                if merge:
                    # A squash has a different commit ID from the branch head.
                    comparison = read_json("api", f"repos/{{owner}}/{{repo}}/compare/{merge}...main?per_page=1", "--jq", "{status}")
                    if comparison["status"] in {"ahead", "identical"}:
                        return MERGED
                sleep(15)
                continue
            if state["state"] != "OPEN":
                raise ValueError("Unexpected pull request state")
            if state["headRefOid"] != current:
                current = state["headRefOid"]
                revised = True
                registration_end = clock() + 10 * 60
                log("The refresh PR has a revised head. Waiting for its reviewed merge on main.")
            result = gh("pr", "checks", pr, "--required", "--json", "name,bucket")
            checks = json.loads(result.stdout) if result.stdout.strip() else []
            if not isinstance(checks, list):
                raise ValueError("No required check list")
            # Check registration/cancellation can race a newer push or an actual
            # merge. Read the same PR again before using these check results.
            after = read_json("pr", "view", pr, "--json", PR_FIELDS)
            if after != state:
                sleep(5)
                continue
            bad = [row["name"] for row in checks if row["bucket"] in {"fail", "cancel", "skipping"}]
            if bad:
                log("Required checks did not pass: " + ", ".join(bad))
                return FAILED
            if not REQUIRED <= {row["name"] for row in checks}:
                if clock() >= registration_end:
                    log("The full set of required checks did not register on the current head.")
                    return FAILED
                sleep(15)
                continue
            if any(row["bucket"] != "pass" for row in checks) or revised:
                sleep(30)
                continue
            if attempts >= 6:
                if state["baseRefOid"] != base or state["mergeStateStatus"] in {"BEHIND", "DIRTY"}:
                    # GitHub has no compare-and-close operation. Keep the PR
                    # and its branch available if another reviewer is editing it.
                    log("Main moved. Retaining this data PR while replaying the scrape on the new base.")
                    return REPLAY
                log("GitHub refused the protected merge. The original data PR remains available.")
                return FAILED
            attempts += 1
            result = gh("pr", "merge", pr, "--squash", "--match-head-commit", head)
            if result.returncode == 0:
                # The server may have queued the operation. Confirm what
                # actually reached main before a heartbeat can be recorded.
                revised = True
            sleep(10)
        except (ValueError, KeyError, subprocess.SubprocessError) as exc:
            log(f"Could not read GitHub check state ({type(exc).__name__}). Reading again.")
            sleep(15)
    log("The data PR did not reach main before the observation window ended.")
    return FAILED


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr", help="URL returned by gh pr create")
    parser.add_argument("head", help="commit generated from the scrape")
    parser.add_argument("base", help="main commit used to generate the scrape")
    args = parser.parse_args()
    raise SystemExit(wait_for_merge(args.pr, args.head, args.base))
