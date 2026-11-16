"""When a push to main may skip the CI suite, and when it may not.

ci.yml's `decide` job runs scripts/ci_skip_decision.py. Its answer is skip only
when a pull request's CI run is shown to have passed on the tree the pushed
commit carries; everything else runs the suite. A wrong skip deploys a tree
nothing tested, so each fact the proof reads has a refusal here, and the two
shapes that do skip (a merge commit, a squash) are pinned beside them.

The workflow half is here too: which jobs wait for the answer, and what a
failed first job does. The deploy job's own condition is in
tests/test_render_deploy.py.
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.ci_skip_decision import REQUIRED_JOBS, WORKFLOW_PATH, _decide, decide

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "ci_skip_decision.py"

REPO = "example-owner/example-repo"
MAIN_WAS = "a" * 40   # the commit main was on when the pull request merged
HEAD = "b" * 40       # the pull request's head
MERGED = "c" * 40     # the commit that landed on main
TREE = "d" * 40
OTHER = "e" * 40
RUN_ID = 7001


def _pull(**changes) -> dict:
    return {
        "number": 41,
        "state": "closed",
        "merged_at": "2026-11-16T10:00:00Z",
        "merge_commit_sha": MERGED,
        "base": {"ref": "main", "repo": {"full_name": REPO}},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
        **changes,
    }


def _commit(sha: str, tree: str, *parents: str) -> dict:
    return {"sha": sha, "tree": {"sha": tree}, "parents": [{"sha": p} for p in parents]}


def _compare(base: str = MAIN_WAS, head: str = HEAD, **changes) -> dict:
    return {
        "url": f"https://api.github.com/repos/{REPO}/compare/{base}...{head}",
        "base_commit": {"sha": base},
        "merge_base_commit": {"sha": base},
        "behind_by": 0,
        **changes,
    }


def _run(run_id: int = RUN_ID, run_number: int = 120, **changes) -> dict:
    return {
        "id": run_id,
        "run_number": run_number,
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "head_sha": HEAD,
        "path": ".github/workflows/ci.yml",
        "head_repository": {"full_name": REPO},
        **changes,
    }


def _runs(*runs: dict) -> dict:
    return {"total_count": len(runs), "workflow_runs": list(runs)}


def _job(name: str, **changes) -> dict:
    return {"name": name, "run_id": RUN_ID, "head_sha": HEAD,
            "status": "completed", "conclusion": "success", **changes}


def _jobs(changed: dict[str, dict] | None = None, extra: tuple[dict, ...] = ()) -> dict:
    jobs = [_job(name, **(changed or {}).get(name, {})) for name in REQUIRED_JOBS]
    jobs += extra
    return {"total_count": len(jobs), "jobs": jobs}


# What a pull_request run of ci.yml also lists: its first job, and the deploy
# job, which a pull request always skips.
_OTHER_JOBS = (_job("Decide (run or skip the suite)"),
               _job("Deploy backend (Render hook)", conclusion="skipped"))


def _facts(**changes) -> dict:
    return {
        "event": "push",
        "ref": "refs/heads/main",
        "repo": REPO,
        "sha": MERGED,
        "pulls": [_pull()],
        "commit": _commit(MERGED, TREE, MAIN_WAS, HEAD),
        "head_commit": {"sha": HEAD, "tree": {"sha": TREE}},
        "compare": _compare(),
        "runs": _runs(_run()),
        "jobs": _jobs(extra=_OTHER_JOBS),
        **changes,
    }


_FACT_NAMES = ("pulls", "commit", "head_commit", "compare", "runs", "jobs")


# ------------------------------------------------------ the two skip shapes

def test_a_merge_commit_of_a_tested_head_skips():
    """A batch pull request: `gh pr merge --merge`, second parent the head."""
    skip, reason = decide(**_facts())
    assert skip is True, reason
    assert "#41" in reason and str(RUN_ID) in reason
    assert MERGED[:8] in reason and HEAD[:8] in reason
    assert "\n" not in reason


def test_a_squash_of_a_tested_head_skips():
    """A data-refresh pull request: one parent, the head's tree."""
    skip, reason = decide(**_facts(commit=_commit(MERGED, TREE, MAIN_WAS)))
    assert skip is True, reason


def test_a_run_that_failed_and_was_re_run_counts_by_its_last_attempt():
    """The jobs API lists the last attempt only, so the facts are those of a
    run that passed; the attempt number is not part of the proof."""
    skip, reason = decide(**_facts(runs=_runs(_run(run_attempt=2)),
                                   jobs=_jobs({name: {"run_attempt": 2} for name in REQUIRED_JOBS})))
    assert skip is True, reason


def test_of_several_runs_for_one_head_only_the_newest_counts():
    """A pull request closed and reopened, or two pull requests on one head
    sha, give that head several pull_request runs."""
    older_red = _run(run_id=6000, run_number=118, conclusion="failure")
    skip, reason = decide(**_facts(runs=_runs(older_red, _run())))
    assert skip is True, reason

    newer_red = _run(run_id=8000, run_number=121, conclusion="failure")
    for runs in (_runs(_run(), newer_red), _runs(newer_red, _run())):
        skip, reason = decide(**_facts(runs=runs))
        assert skip is False
        assert "8000" in reason and "failure" in reason


# ------------------------------------------------------------- the refusals

_REFUSALS = {
    # The event and the ref. A manual dispatch is how the suite is run on
    # main by hand, so it must never skip.
    "a manual dispatch": ({"event": "workflow_dispatch"}, "not a push"),
    "a pull request": ({"event": "pull_request", "ref": "refs/pull/41/merge"}, "not a push"),
    "a schedule": ({"event": "schedule"}, "not a push"),
    "a push to another branch": ({"ref": "refs/heads/batch/example"}, "not refs/heads/main"),
    "a tag": ({"ref": "refs/tags/v1"}, "not refs/heads/main"),
    "no repository": ({"repo": ""}, "not named"),
    "a short sha": ({"sha": MERGED[:12]}, "not named"),
    # The pull request.
    "a commit pushed straight to main (a revert)": ({"pulls": []}, "0 pull requests"),
    "two pull requests on the commit": ({"pulls": [_pull(), _pull(number=42)]}, "2 pull requests"),
    "an answer that is not a list": ({"pulls": {"message": "Not Found"}}, "unreadable"),
    "a pull request without a number": ({"pulls": [_pull(number=None)]}, "no number"),
    "a pull request whose number is not one": ({"pulls": [_pull(number=True)]}, "no number"),
    "an open pull request": ({"pulls": [_pull(state="open", merged_at=None)]}, "is not merged"),
    "a closed, unmerged pull request": ({"pulls": [_pull(merged_at=None)]}, "is not merged"),
    "a pull request merged as another commit": (
        {"pulls": [_pull(merge_commit_sha=OTHER)]}, "was not merged as"),
    "a pull request into another branch": (
        {"pulls": [_pull(base={"ref": "release", "repo": {"full_name": REPO}})]}, "not merged into main"),
    "a pull request into another repository": (
        {"pulls": [_pull(base={"ref": "main", "repo": {"full_name": "someone-else/example-repo"}})]},
        "not merged into main"),
    "a pull request from a fork": (
        {"pulls": [_pull(head={"sha": HEAD, "repo": {"full_name": "a-fork/example-repo"}})]}, "a fork"),
    "a pull request from a deleted fork": (
        {"pulls": [_pull(head={"sha": HEAD, "repo": None})]}, "a fork"),
    "a pull request with no head sha": (
        {"pulls": [_pull(head={"sha": None, "repo": {"full_name": REPO}})]}, "names no head"),
    # The pushed commit.
    "an answer for another commit": ({"commit": _commit(OTHER, TREE, MAIN_WAS, HEAD)}, "is unreadable"),
    "a commit without a tree": ({"commit": {"sha": MERGED, "parents": [{"sha": MAIN_WAS}]}}, "is unreadable"),
    "a merge of something other than the head": (
        {"commit": _commit(MERGED, TREE, MAIN_WAS, OTHER)}, "neither a merge"),
    "a commit with three parents": ({"commit": _commit(MERGED, TREE, MAIN_WAS, HEAD, OTHER)}, "neither a merge"),
    "a commit with no parent": ({"commit": _commit(MERGED, TREE)}, "neither a merge"),
    "a commit whose parents are not a list": (
        {"commit": {"sha": MERGED, "tree": {"sha": TREE}, "parents": None}}, "is unreadable"),
    "a commit whose first parent has no sha": (
        {"commit": {"sha": MERGED, "tree": {"sha": TREE}, "parents": [{}, {"sha": HEAD}]}}, "neither a merge"),
    # The head and the two trees.
    "a head answer for another commit": (
        {"head_commit": {"sha": OTHER, "tree": {"sha": TREE}}}, "is unreadable"),
    "a head answer without a tree": ({"head_commit": {"sha": HEAD}}, "is unreadable"),
    # --admin while behind main: GitHub's merge added main's changes.
    "a merge commit whose tree is not the head's": (
        {"head_commit": {"sha": HEAD, "tree": {"sha": OTHER}}}, "differs from the tree"),
    "a squash whose tree is not the head's": (
        {"commit": _commit(MERGED, TREE, MAIN_WAS), "head_commit": {"sha": HEAD, "tree": {"sha": OTHER}}},
        "differs from the tree"),
    # Main as it was must be inside the head, or the run tested another tree
    # (main gains a change, the run tests head plus it, main reverts it).
    "a comparison of other commits": ({"compare": _compare(base=OTHER)}, "comparison"),
    "a comparison with another head": ({"compare": _compare(head=OTHER)}, "comparison"),
    "a head that had diverged from main": (
        {"compare": _compare(merge_base_commit={"sha": OTHER}, behind_by=2)}, "the commit main was on"),
    "a head behind main by the count alone": ({"compare": _compare(behind_by=1)}, "the commit main was on"),
    # The pull request's CI run.
    "a head with no CI run": ({"runs": _runs()}, "no pull_request CI run"),
    "a truncated list of runs": ({"runs": {"total_count": 2, "workflow_runs": [_run()]}}, "incomplete"),
    "a list holding a run for another head": ({"runs": _runs(_run(head_sha=OTHER))}, "not one of its runs"),
    "a list holding a push run": ({"runs": _runs(_run(event="push"))}, "not one of its runs"),
    "a list holding another workflow's run": (
        {"runs": _runs(_run(path=".github/workflows/security-advisory.yml"))}, "not one of its runs"),
    "runs that are not a list": (
        {"runs": {"total_count": 1, "workflow_runs": {"0": _run()}}}, "incomplete"),
    "a run whose id is not a number": ({"runs": _runs(_run(run_id=str(RUN_ID)))}, "not one of its runs"),
    # Text would put run "9" after run "10".
    "a run whose run number is not a number": ({"runs": _runs(_run(run_number="120"))}, "not one of its runs"),
    "a run with no run number": ({"runs": _runs(_run(run_number=None))}, "not one of its runs"),
    "a run whose run number is a yes": ({"runs": _runs(_run(run_number=True))}, "not one of its runs"),
    "two runs with one run number": ({"runs": _runs(_run(), _run(run_id=7002))}, "share a run number"),
    "a run that failed": ({"runs": _runs(_run(conclusion="failure"))}, "not completed/success"),
    "a run that was cancelled": ({"runs": _runs(_run(conclusion="cancelled"))}, "not completed/success"),
    "a run still going": ({"runs": _runs(_run(status="in_progress", conclusion=None))}, "not completed/success"),
    "a run for a fork's head": (
        {"runs": _runs(_run(head_repository={"full_name": "a-fork/example-repo"}))}, "outside"),
    # Its jobs.
    "a truncated list of jobs": (
        {"jobs": {"total_count": 9, "jobs": [_job(name) for name in REQUIRED_JOBS]}}, "incomplete"),
    "a job listed twice": ({"jobs": _jobs(extra=(_job(REQUIRED_JOBS[0]),))}, "lists 2 jobs"),
    "a job of another run": ({"jobs": _jobs({REQUIRED_JOBS[3]: {"run_id": 9}})}, "another run"),
    "a job for another head": ({"jobs": _jobs({REQUIRED_JOBS[0]: {"head_sha": OTHER}})}, "another run"),
}


@pytest.mark.parametrize("case", sorted(_REFUSALS))
def test_it_refuses(case):
    changes, fragment = _REFUSALS[case]
    skip, reason = decide(**_facts(**changes))
    assert skip is False, f"{case}: skipped with {reason!r}"
    assert fragment in reason, reason
    assert "\n" not in reason


@pytest.mark.parametrize("name", REQUIRED_JOBS)
@pytest.mark.parametrize("state", [
    {"conclusion": "failure"},
    {"conclusion": "cancelled"},
    {"conclusion": "timed_out"},
    # Neither of these is a pass here, whatever branch protection makes of them.
    {"conclusion": "skipped"},
    {"conclusion": "neutral"},
    {"status": "in_progress", "conclusion": None},
])
def test_each_of_the_four_jobs_has_to_have_succeeded(name, state):
    """Migrations too. Branch protection does not require it, so a pull
    request can merge with it red, and that tree must not deploy untested.
    The run's own conclusion is left green here on purpose: the job list is
    read as well, not instead."""
    skip, reason = decide(**_facts(jobs=_jobs({name: state}, extra=_OTHER_JOBS)))
    assert skip is False
    assert name in reason and "not completed/success" in reason


@pytest.mark.parametrize("name", REQUIRED_JOBS)
def test_each_of_the_four_jobs_has_to_be_listed(name):
    listed = [_job(other) for other in REQUIRED_JOBS if other != name]
    skip, reason = decide(**_facts(jobs={"total_count": len(listed), "jobs": listed}))
    assert skip is False
    assert "lists 0 jobs" in reason and name in reason


@pytest.mark.parametrize("name", _FACT_NAMES)
def test_a_fact_that_was_not_fetched_refuses(name):
    skip, reason = decide(**_facts(**{name: None}))
    assert skip is False
    assert name in reason and "missing" in reason


def _without_each_field(value, path=()):
    """(path, copy of ``value`` lacking one leaf field), for every leaf."""
    if isinstance(value, dict):
        for key, inner in value.items():
            if isinstance(inner, dict | list):
                for where, changed in _without_each_field(inner, (*path, key)):
                    yield where, {**value, key: changed}
            else:
                yield (*path, key), {k: v for k, v in value.items() if k != key}
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            for where, changed in _without_each_field(inner, (*path, index)):
                yield where, [*value[:index], changed, *value[index + 1:]]


def test_no_field_of_the_proof_is_optional():
    """Each fact above holds only the fields the proof reads. Take any one of
    them away, from either skip shape, and the answer has to be no: a field
    GitHub stops sending must not turn into a pass."""
    shapes = {
        "merge": _facts(jobs=_jobs()),
        "squash": _facts(jobs=_jobs(), commit=_commit(MERGED, TREE, MAIN_WAS)),
    }
    tried = 0
    for shape, facts in shapes.items():
        assert decide(**facts)[0] is True
        for name in _FACT_NAMES:
            for where, changed in _without_each_field(facts[name]):
                skip, reason = decide(**{**facts, name: changed})
                assert skip is False, f"{shape}: skipped without {name}{list(where)} ({reason})"
                tried += 1
    # 8 + 2 + 4 + 9 + 21 fields in each shape, plus the commit's 4 and 3: the
    # count shows the walk reached every fact rather than none.
    assert tried == 95, tried


@pytest.mark.parametrize("name", _FACT_NAMES)
@pytest.mark.parametrize("junk", [
    "text", 7, True, [], {}, [None], [[]], {"total_count": 1},
    {"total_count": 1, "workflow_runs": [None]}, {"total_count": 1, "jobs": [None]},
    {"total_count": 1, "workflow_runs": ["x"]}, {"sha": None, "tree": None, "parents": None},
    {"sha": MERGED, "tree": {"sha": TREE}, "parents": [None]},
])
def test_a_malformed_fact_refuses_and_never_raises(name, junk):
    skip, reason = decide(**_facts(**{name: copy.deepcopy(junk)}))
    assert skip is False
    assert isinstance(reason, str) and reason


def test_an_unexpected_error_while_reading_a_fact_refuses():
    def broken(name, path):
        raise RuntimeError("no network")

    skip, reason = _decide("push", "refs/heads/main", REPO, MERGED, broken)
    assert skip is False
    assert "RuntimeError" in reason


# --------------------------------------------- the script, as the job runs it

_PATHS = {
    "pulls": f"repos/{REPO}/commits/{MERGED}/pulls?per_page=100",
    "commit": f"repos/{REPO}/git/commits/{MERGED}",
    "head_commit": f"repos/{REPO}/git/commits/{HEAD}",
    "compare": f"repos/{REPO}/compare/{MAIN_WAS}...{HEAD}?per_page=1",
    "runs": f"repos/{REPO}/actions/workflows/ci.yml/runs?head_sha={HEAD}&event=pull_request&per_page=100",
    "jobs": f"repos/{REPO}/actions/runs/{RUN_ID}/jobs?filter=latest&per_page=100",
}

# A gh that answers `gh api <path>` from a file of path -> output, and fails
# for any other path or argument.
_FAKE_GH = """#!{python}
import json, os, sys
with open(os.environ["FAKE_GH_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
with open(os.environ["FAKE_GH_ANSWERS"]) as handle:
    answers = json.load(handle)
if len(sys.argv) != 3 or sys.argv[1] != "api" or sys.argv[2] not in answers:
    sys.exit(1)
sys.stdout.write(answers[sys.argv[2]])
"""


def _answers(**replaced: str) -> dict[str, str]:
    """What gh prints for each path; ``replaced`` swaps one fact's raw output,
    and None removes the path, so that call fails."""
    facts = _facts()
    answers = {_PATHS[name]: json.dumps(facts[name]) for name in _FACT_NAMES}
    for name, raw in replaced.items():
        if raw is None:
            del answers[_PATHS[name]]
        else:
            answers[_PATHS[name]] = raw
    return answers


def _run_as_the_job(tmp_path: Path, command: list[str], answers: dict[str, str] | None, *,
                    event: str = "push", ref: str = "refs/heads/main", cwd: Path = _REPO_ROOT,
                    ) -> tuple[subprocess.CompletedProcess, str, list[list[str]]]:
    """Run ``command`` with the job's environment and a fake gh (no gh at all
    when ``answers`` is None). Returns the result, what was written to
    GITHUB_OUTPUT, and gh's argument lists."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log, output = tmp_path / "gh.log", tmp_path / "github_output"
    output.write_text("")
    path = str(bin_dir)
    if answers is not None:
        (bin_dir / "gh").write_text(_FAKE_GH.format(python=sys.executable))
        (bin_dir / "gh").chmod(0o755)
        (tmp_path / "answers.json").write_text(json.dumps(answers))
        path = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, env={
        "PATH": path,
        "FAKE_GH_LOG": str(log),
        "FAKE_GH_ANSWERS": str(tmp_path / "answers.json"),
        "GH_TOKEN": "fake-github-token-0000",
        "GITHUB_EVENT_NAME": event,
        "GITHUB_REF": ref,
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_SHA": MERGED,
        "GITHUB_OUTPUT": str(output),
    })
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, output.read_text(), calls


_PYTHON = [sys.executable, str(_SCRIPT)]


def test_the_script_skips_when_github_gives_every_fact(tmp_path):
    result, output, calls = _run_as_the_job(tmp_path, _PYTHON, _answers())
    assert result.returncode == 0, result.stderr
    assert output == "skip=true\n"
    (line,) = result.stdout.splitlines()
    assert line.startswith("::notice::skip=true: ")
    # Six reads, nothing else: no method, no field, no other subcommand.
    assert calls == [["api", _PATHS[name]] for name in _FACT_NAMES]
    assert "fake-github-token-0000" not in result.stdout + result.stderr


@pytest.mark.parametrize("name", _FACT_NAMES)
def test_a_failed_lookup_runs_the_suite_without_failing_the_job(tmp_path, name):
    result, output, _ = _run_as_the_job(tmp_path, _PYTHON, _answers(**{name: None}))
    assert result.returncode == 0, result.stderr
    assert output == "skip=false\n"
    assert f"skip=false: the fact '{name}' could not be fetched (gh exit 1)" in result.stdout


@pytest.mark.parametrize("name", _FACT_NAMES)
def test_an_answer_that_is_not_json_runs_the_suite(tmp_path, name):
    result, output, _ = _run_as_the_job(tmp_path, _PYTHON, _answers(**{name: "<html>502</html>"}))
    assert result.returncode == 0, result.stderr
    assert output == "skip=false\n"
    assert "is not JSON" in result.stdout


def test_a_runner_without_gh_runs_the_suite(tmp_path):
    result, output, _ = _run_as_the_job(tmp_path, _PYTHON, None)
    assert result.returncode == 0, result.stderr
    assert output == "skip=false\n"
    assert "could not be fetched (FileNotFoundError)" in result.stdout


@pytest.mark.parametrize(("event", "ref"), [
    ("pull_request", "refs/pull/41/merge"),
    ("workflow_dispatch", "refs/heads/main"),
    ("push", "refs/heads/batch/example"),
])
def test_anything_but_a_push_to_main_asks_github_nothing(tmp_path, event, ref):
    result, output, calls = _run_as_the_job(tmp_path, _PYTHON, _answers(), event=event, ref=ref)
    assert result.returncode == 0, result.stderr
    assert output == "skip=false\n"
    assert calls == []
    assert "::notice::" not in result.stdout


# ------------------------------------------------------------- the workflow

_TEST_JOBS = ("backend", "frontend", "migrations", "e2e")


def _ci() -> dict:
    return yaml.safe_load((_REPO_ROOT / WORKFLOW_PATH).read_text(encoding="utf-8"))


def _decide_job() -> dict:
    return _ci()["jobs"]["decide"]


def _decide_step() -> dict:
    (step,) = (s for s in _decide_job()["steps"] if s.get("id") == "decide")
    return step


def _bash(step: dict) -> list[str]:
    return ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]]


def test_the_script_looks_for_the_jobs_and_the_workflow_ci_yml_has():
    """A renamed job would be missing from every run's job list, and the
    suite would silently go back to running twice."""
    jobs = _ci()["jobs"]
    assert REQUIRED_JOBS == tuple(jobs[job_id]["name"] for job_id in _TEST_JOBS)
    assert WORKFLOW_PATH == ".github/workflows/ci.yml"


def test_every_pull_request_run_of_ci_is_against_main():
    """The proof takes any pull_request run of this workflow for the head as
    a run of the head merged into main. That holds while main is the only
    base the workflow runs for."""
    workflow = _ci()
    triggers = workflow.get(True, workflow.get("on"))  # PyYAML reads `on` as True
    assert triggers["pull_request"] == {"branches": ["main"]}
    assert triggers["push"] == {"branches": ["main"]}
    assert "workflow_dispatch" in triggers


def test_the_first_job_runs_for_every_event_and_may_only_read():
    job = _decide_job()
    assert "if" not in job and "needs" not in job
    assert job["permissions"] == {"actions": "read", "contents": "read", "pull-requests": "read"}
    assert not job.get("continue-on-error")


def test_only_a_push_to_main_can_carry_a_skip_out_of_the_first_job():
    """The script already refuses every other event; the output says so once
    more, so that no change to the script can make a manual run or a pull
    request skip the suite."""
    assert _decide_job()["outputs"] == {
        "skip": "${{ github.event_name == 'push' && github.ref == 'refs/heads/main'"
                " && steps.decide.outputs.skip == 'true' }}",
    }


@pytest.mark.parametrize("job_id", _TEST_JOBS)
def test_each_test_job_runs_unless_the_proof_was_given(job_id):
    """`!cancelled()` and not the default success(): under success() a first
    job that failed would skip all four, and branch protection counts a
    skipped required check as passed. With this condition a failed first job
    has an empty output, which is not 'true', so the suite runs."""
    job = _ci()["jobs"][job_id]
    assert job["needs"] == "decide"
    assert " ".join(str(job["if"]).split()) == "${{ !cancelled() && needs.decide.outputs.skip != 'true' }}"


def test_the_step_answers_no_when_the_checkout_left_no_script(tmp_path):
    """The checkout may fail (continue-on-error), and then there is nothing
    to run. The step must still succeed and say skip=false."""
    (checkout,) = (s for s in _decide_job()["steps"] if "actions/checkout" in str(s.get("uses")))
    assert checkout["continue-on-error"] is True
    empty = tmp_path / "workspace"
    empty.mkdir()
    result, output, calls = _run_as_the_job(tmp_path, _bash(_decide_step()), _answers(), cwd=empty)
    assert result.returncode == 0, result.stderr
    assert output == "skip=false\n"
    assert "::warning::" in result.stdout
    assert calls == []


def test_the_step_passes_the_scripts_answer_on(tmp_path):
    step = _decide_step()
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert "${{" not in step["run"]
    result, output, _ = _run_as_the_job(tmp_path, _bash(step), _answers())
    assert result.returncode == 0, result.stderr
    assert output == "skip=true\n"
    assert "::warning::" not in result.stdout
