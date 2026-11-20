#!/usr/bin/env python3
"""Decide whether a push to main may skip the CI suite (ci.yml, job `decide`).

A commit reaches main through a pull request whose CI has already run. When
that run tested the very tree the commit carries, running Backend, Frontend,
Migrations and E2E again on main proves nothing new and holds the backend
deploy back for as long as the suite takes.

The answer is skip only when every fact below is read and agrees. Anything
missing, ambiguous or unreadable is a refusal, and a refusal runs the suite.

A pull_request run does not test the head commit. It tests GitHub's merge of
the head into main as main stood when the run was triggered. So equal trees
are not enough: the commit main was on when the pull request merged must also
be an ancestor of the head. Then the merge the run tested added nothing to
the head, and the run tested the head's tree. This assumes main only moves
forward, so that commit covers every earlier state of main; branch protection
refuses force pushes to main (read 2026-11-16), though not from an
administrator.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable

MAIN_REF = "refs/heads/main"
WORKFLOW_FILE = "ci.yml"
WORKFLOW_PATH = f".github/workflows/{WORKFLOW_FILE}"
# The `name:` of the four test jobs in ci.yml, as the jobs API reports them.
REQUIRED_JOBS = (
    "Backend (lint + pytest)",
    "Frontend (typecheck + build)",
    "Migrations (Flow B merge + CLI replay)",
    "E2E (Playwright)",
)
_SHA = re.compile(r"[0-9a-f]{40}")
# GitHub lists the pull request of a squash merge some seconds after the push:
# the data refresh's #1207 had none 4 seconds after it merged (2026-11-20), so
# the suite ran on main and the deploy waited 40 minutes for it. An empty list
# is asked for again this many times, this many seconds apart.
PULLS_RETRIES = 3
PULLS_WAIT_SECONDS = 5

# Returns one fact (parsed JSON) by name; the path is where the GitHub API
# serves it. Raises Refusal when the fact cannot be had.
Fact = Callable[[str, str], object]


class Refusal(Exception):
    """A reason the suite has to run."""


def _at(value: object, *keys: str) -> object:
    """``value[k1][k2]...``, or None as soon as a level is not a dict."""
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def _is_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _listed(answer: object, key: str, what: str) -> list:
    """The whole list under ``key``; a truncated page is not the whole list."""
    rows = _at(answer, key)
    if not isinstance(rows, list) or _at(answer, "total_count") != len(rows):
        raise Refusal(f"the list of {what} is unreadable or incomplete")
    return rows


def _prove(event: str, ref: str, repo: str, sha: str, fact: Fact) -> str:
    """The proof, in one line, that this tree already passed. Raises Refusal."""
    if event != "push":
        raise Refusal(f"the event is {event!r}, not a push")
    if ref != MAIN_REF:
        raise Refusal(f"the ref is {ref!r}, not {MAIN_REF}")
    if not repo or not _is_sha(sha):
        raise Refusal("the repository or the pushed commit is not named")

    pulls = fact("pulls", f"repos/{repo}/commits/{sha}/pulls?per_page=100")
    if not isinstance(pulls, list):
        raise Refusal("the pull requests of the pushed commit are unreadable")
    if len(pulls) != 1:
        raise Refusal(f"{len(pulls)} pull requests are associated with {sha[:8]}, not exactly one")
    pull = pulls[0]
    number = _at(pull, "number")
    if not _is_number(number):
        raise Refusal("the pull request of the pushed commit has no number")
    if _at(pull, "state") != "closed" or not _at(pull, "merged_at"):
        raise Refusal(f"pull request #{number} is not merged")
    if _at(pull, "merge_commit_sha") != sha:
        raise Refusal(f"pull request #{number} was not merged as {sha[:8]}")
    if _at(pull, "base", "ref") != "main" or _at(pull, "base", "repo", "full_name") != repo:
        raise Refusal(f"pull request #{number} was not merged into main of {repo}")
    if _at(pull, "head", "repo", "full_name") != repo:
        raise Refusal(f"the head of pull request #{number} is not in {repo} (a fork)")
    head = _at(pull, "head", "sha")
    if not _is_sha(head):
        raise Refusal(f"pull request #{number} names no head commit")

    commit = fact("commit", f"repos/{repo}/git/commits/{sha}")
    tree = _at(commit, "tree", "sha")
    parents = _at(commit, "parents")
    if _at(commit, "sha") != sha or not _is_sha(tree) or not isinstance(parents, list):
        raise Refusal(f"the commit {sha[:8]} is unreadable")
    parents = [_at(parent, "sha") for parent in parents]
    # A merge commit of the head, or a squash: one parent, the head's tree.
    if not (parents and _is_sha(parents[0])
            and (len(parents) == 1 or (len(parents) == 2 and parents[1] == head))):
        raise Refusal(f"{sha[:8]} is neither a merge of #{number}'s head {head[:8]} nor a single-parent commit")
    was_main = parents[0]

    head_commit = fact("head_commit", f"repos/{repo}/git/commits/{head}")
    head_tree = _at(head_commit, "tree", "sha")
    if _at(head_commit, "sha") != head or not _is_sha(head_tree):
        raise Refusal(f"the head commit {head[:8]} of #{number} is unreadable")
    if head_tree != tree:
        raise Refusal(f"the tree of {sha[:8]} differs from the tree of #{number}'s head {head[:8]}")

    compare = fact("compare", f"repos/{repo}/compare/{was_main}...{head}?per_page=1")
    if (not str(_at(compare, "url")).endswith(f"/compare/{was_main}...{head}")
            or _at(compare, "base_commit", "sha") != was_main):
        raise Refusal(f"the comparison of main {was_main[:8]} with #{number}'s head is unreadable")
    if _at(compare, "merge_base_commit", "sha") != was_main or _at(compare, "behind_by") != 0:
        raise Refusal(f"#{number}'s head {head[:8]} does not contain {was_main[:8]}, the commit main was on")

    runs = _listed(
        fact("runs", f"repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?head_sha={head}&event=pull_request&per_page=100"),
        "workflow_runs", "CI runs")
    if not runs:
        raise Refusal(f"no pull_request CI run exists for #{number}'s head {head[:8]}")
    for run in runs:
        if (_at(run, "head_sha") != head or _at(run, "event") != "pull_request"
                or _at(run, "path") != WORKFLOW_PATH
                or not _is_number(_at(run, "id")) or not _is_number(_at(run, "run_number"))):
            raise Refusal(f"the list of CI runs for {head[:8]} holds an entry that is not one of its runs")
    if len({run["run_number"] for run in runs}) != len(runs):
        raise Refusal(f"two CI runs for {head[:8]} share a run number")
    run = max(runs, key=lambda candidate: candidate["run_number"])
    run_id = run["id"]
    if _at(run, "status") != "completed" or _at(run, "conclusion") != "success":
        raise Refusal(f"the newest pull_request CI run {run_id} for {head[:8]} is "
                      f"{_at(run, 'status')}/{_at(run, 'conclusion')}, not completed/success")
    if _at(run, "head_repository", "full_name") != repo:
        raise Refusal(f"CI run {run_id} ran for a head outside {repo}")

    jobs = _listed(
        fact("jobs", f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"),
        "jobs", f"jobs of CI run {run_id}")
    for name in REQUIRED_JOBS:
        named = [job for job in jobs if _at(job, "name") == name]
        if len(named) != 1:
            raise Refusal(f"CI run {run_id} lists {len(named)} jobs named {name!r}, not exactly one")
        (job,) = named
        if _at(job, "run_id") != run_id or _at(job, "head_sha") != head:
            raise Refusal(f"the job {name!r} listed for CI run {run_id} belongs to another run")
        if _at(job, "status") != "completed" or _at(job, "conclusion") != "success":
            raise Refusal(f"{name!r} is {_at(job, 'status')}/{_at(job, 'conclusion')} "
                          f"in CI run {run_id}, not completed/success")

    return (f"{sha[:8]} has the tree of pull request #{number}'s head {head[:8]}, "
            f"and all four jobs passed on it in CI run {run_id}")


def _decide(event: str, ref: str, repo: str, sha: str, fact: Fact) -> tuple[bool, str]:
    try:
        return True, _prove(event, ref, repo, sha, fact)
    except Refusal as refusal:
        return False, str(refusal)
    except Exception as exc:  # whatever else goes wrong, the suite runs
        return False, f"the facts could not be read ({type(exc).__name__})"


def decide(*, event: str, ref: str, repo: str, sha: str,
           pulls: object = None, commit: object = None, head_commit: object = None,
           compare: object = None, runs: object = None, jobs: object = None,
           ) -> tuple[bool, str]:
    """(skip, one-line reason) from facts already in hand.

    ``pulls``: GET /repos/{repo}/commits/{sha}/pulls. ``commit`` and
    ``head_commit``: GET /repos/{repo}/git/commits/{sha} for the pushed commit
    and for the pull request's head. ``compare``: GET
    /repos/{repo}/compare/{first parent}...{head}. ``runs``: GET
    /repos/{repo}/actions/workflows/ci.yml/runs for that head and the
    pull_request event. ``jobs``: GET /repos/{repo}/actions/runs/{id}/jobs for
    the newest of those runs. A fact left as None is a refusal.
    """
    facts = {"pulls": pulls, "commit": commit, "head_commit": head_commit,
             "compare": compare, "runs": runs, "jobs": jobs}

    def fact(name: str, _path: str) -> object:
        if facts[name] is None:
            raise Refusal(f"the fact {name!r} is missing")
        return facts[name]

    return _decide(event, ref, repo, sha, fact)


def _from_github(name: str, path: str) -> object:
    try:
        # Six calls and PULLS_RETRIES more, at 30 seconds each, with the waits
        # between them, stay inside the job's five minutes.
        done = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal(f"the fact {name!r} could not be fetched ({type(exc).__name__})") from exc
    if done.returncode != 0:
        raise Refusal(f"the fact {name!r} could not be fetched (gh exit {done.returncode})")
    try:
        return json.loads(done.stdout)
    except ValueError as exc:
        raise Refusal(f"the fact {name!r} is not JSON") from exc


def _from_github_once_listed(name: str, path: str) -> object:
    """``_from_github``, asking again for a list of pull requests that came
    back empty. A commit pushed straight to main has none either, so it waits
    the same seconds before its suite runs."""
    answer = _from_github(name, path)
    for _ in range(PULLS_RETRIES if name == "pulls" else 0):
        if answer != []:
            break
        time.sleep(PULLS_WAIT_SECONDS)
        answer = _from_github(name, path)
    return answer


def main() -> int:
    env = os.environ
    event, ref = env.get("GITHUB_EVENT_NAME", ""), env.get("GITHUB_REF", "")
    skip, reason = _decide(event, ref, env.get("GITHUB_REPOSITORY", ""),
                           env.get("GITHUB_SHA", ""), _from_github_once_listed)
    reason = " ".join(reason.split())
    answer = "true" if skip else "false"
    # On main the answer decides whether the suite runs at all, so it goes on
    # the run page; on a pull request it is always "run" and stays in the log.
    notice = "::notice::" if event == "push" and ref == MAIN_REF else ""
    print(f"{notice}skip={answer}: {reason}")
    output = env.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"skip={answer}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
