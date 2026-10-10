"""How the backend is started and deployed on Render."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[1]


def _web_service() -> dict:
    blueprint = yaml.safe_load((_REPO / "render.yaml").read_text(encoding="utf-8"))
    (service,) = (s for s in blueprint["services"] if s.get("type") == "web")
    return service


def test_the_backend_starts_exactly_one_uvicorn_worker():
    """uvicorn's --workers defaults to $WEB_CONCURRENCY when that is set.

    Each worker loads the whole corpus, about 1.3-1.5 GB, on a 2 GB plan, so
    a WEB_CONCURRENCY of 2 or more appearing in the service environment would
    start more copies than the instance can hold. Naming the count in the
    start command makes the environment irrelevant.
    """
    argv = shlex.split(_web_service()["startCommand"])
    assert argv[0] == "uvicorn", argv
    assert argv.count("--workers") == 1, argv
    assert argv[argv.index("--workers") + 1] == "1", argv
    assert not any(arg.startswith("--workers=") for arg in argv), argv


# --------------------------------------------------- the deploy-hook job

_DEPLOY_JOB = "deploy-backend"
# The checks the deploy waits for: job id -> the check name it reports. Branch
# protection on main requires the first three (read from the GitHub API on
# 2026-10-09); it does not require Migrations, so the deploy waits for that one
# itself rather than letting a commit whose migrations failed go live.
_DEPLOY_CHECKS = {
    "backend": "Backend (lint + pytest)",
    "frontend": "Frontend (typecheck + build)",
    "e2e": "E2E (Playwright)",
    "migrations": "Migrations (Flow B merge + CLI replay)",
}
_SHA = "0123456789abcdef0123456789abcdef01234567"
_HOOK = "https://api.render.com/deploy/srv-fakeservice?key=fake-hook-key-0000"


def _ci() -> dict:
    return yaml.safe_load(
        (_REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


def _deploy_job() -> dict:
    return _ci()["jobs"][_DEPLOY_JOB]


def _deploy_step() -> dict:
    (step,) = _deploy_job()["steps"]
    return step


def test_the_deploy_waits_for_the_required_checks_and_migrations():
    job = _deploy_job()
    assert sorted(job["needs"]) == sorted(_DEPLOY_CHECKS)
    jobs = _ci()["jobs"]
    for job_id, check in _DEPLOY_CHECKS.items():
        assert jobs[job_id]["name"] == check, job_id


def test_only_a_push_to_main_deploys():
    """Never a pull request, a manual dispatch or a schedule.

    No status function either: with none, GitHub applies success(), so a
    needed job that failed, was cancelled or was skipped skips the deploy.
    always() or failure() here would deploy a commit whose checks did not pass.
    """
    condition = " ".join(str(_deploy_job()["if"]).split())
    assert "github.event_name == 'push'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "||" not in condition
    for function in ("always()", "success()", "failure()", "cancelled()"):
        assert function not in condition, function


def test_a_failed_deploy_is_not_hidden():
    job = _deploy_job()
    assert not job.get("continue-on-error")
    assert not any(step.get("continue-on-error") for step in job["steps"])


def test_the_hook_url_reaches_the_script_only_through_its_environment():
    """`${{ secrets.X }}` inside `run` is written into the script file the
    runner executes. Through `env` the script holds only the variable name."""
    step = _deploy_step()
    assert step["env"] == {
        "RENDER_DEPLOY_HOOK_URL": "${{ secrets.RENDER_DEPLOY_HOOK_URL }}",
        "DEPLOY_SHA": "${{ github.sha }}",
        "GH_TOKEN": "${{ github.token }}",
    }
    run = step["run"]
    assert "${{" not in run
    for tracing in ("set -x", "set -o xtrace", "--verbose", "--trace", "curl -v"):
        assert tracing not in run, tracing


def test_the_job_can_read_the_head_of_main_and_nothing_else():
    assert _deploy_job()["permissions"] == {"contents": "read"}


def _fake_tool(bin_dir: Path, name: str) -> None:
    """A stand-in for ``name`` that logs its arguments, prints
    $FAKE_<NAME>_OUT and exits with $FAKE_<NAME>_EXIT."""
    key = name.upper()
    tool = bin_dir / name
    tool.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"with open(os.environ['FAKE_{key}_LOG'], 'a') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"sys.stdout.write(os.environ['FAKE_{key}_OUT'])\n"
        f"sys.exit(int(os.environ['FAKE_{key}_EXIT']))\n"
    )
    tool.chmod(0o755)


def _calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _run_deploy(tmp_path: Path, hook: str, *, status: str = "200", curl_exit: int = 0,
                head: str = _SHA, gh_exit: int = 0,
                ) -> tuple[subprocess.CompletedProcess, list[list[str]], list[list[str]]]:
    """Run the step's script as GitHub runs it, with a gh that reports
    ``head`` as the head of main and a curl that answers with ``status``.
    Returns the result and the argument lists curl and gh were called with."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_tool(bin_dir, "curl")
    _fake_tool(bin_dir, "gh")
    curl_log, gh_log = tmp_path / "curl.log", tmp_path / "gh.log"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CURL_LOG": str(curl_log),
        "FAKE_CURL_OUT": status,
        "FAKE_CURL_EXIT": str(curl_exit),
        "FAKE_GH_LOG": str(gh_log),
        "FAKE_GH_OUT": f"{head}\n" if head else "",
        "FAKE_GH_EXIT": str(gh_exit),
        "GITHUB_REPOSITORY": "example-owner/example-repo",
        "GH_TOKEN": "fake-github-token-0000",
        "RENDER_DEPLOY_HOOK_URL": hook,
        "DEPLOY_SHA": _SHA,
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _deploy_step()["run"]],
        env=env, capture_output=True, text=True,
    )
    return result, _calls(curl_log), _calls(gh_log)


def _printed(result: subprocess.CompletedProcess) -> str:
    return result.stdout + result.stderr


def test_without_the_secret_it_succeeds_and_deploys_nothing(tmp_path):
    """Until the owner sets the secret, Render's checksPass waits on this
    job's check too, so it has to pass."""
    result, calls, gh_calls = _run_deploy(tmp_path, "")
    assert result.returncode == 0, _printed(result)
    assert "::notice::" in result.stdout
    assert calls == []
    assert gh_calls == []


def test_with_the_secret_it_posts_the_hook_once_for_this_commit(tmp_path):
    result, calls, _ = _run_deploy(tmp_path, _HOOK)
    assert result.returncode == 0, _printed(result)
    (argv,) = calls
    assert argv[argv.index("-X") + 1] == "POST"
    assert f"{_HOOK}&ref={_SHA}" in argv
    assert _SHA in result.stdout


def test_a_hook_url_without_a_query_string_still_gets_the_ref(tmp_path):
    bare = "https://api.render.com/deploy/srv-fakeservice"
    _, calls, _ = _run_deploy(tmp_path, bare)
    (argv,) = calls
    assert f"{bare}?ref={_SHA}" in argv


def test_a_non_2xx_answer_fails_the_job_without_printing_the_url(tmp_path):
    for status in ("404", "500", "301"):
        run_dir = tmp_path / status
        run_dir.mkdir()
        result, _, _ = _run_deploy(run_dir, _HOOK, status=status)
        printed = _printed(result)
        assert result.returncode != 0, status
        assert "::error::" in printed and status in printed
        assert "fake-hook-key-0000" not in printed and "srv-fakeservice" not in printed


def test_an_unreachable_hook_fails_the_job_without_printing_the_url(tmp_path):
    result, _, _ = _run_deploy(tmp_path, _HOOK, status="000", curl_exit=7)
    printed = _printed(result)
    assert result.returncode != 0
    assert "::error::" in printed
    assert "fake-hook-key-0000" not in printed and "srv-fakeservice" not in printed


# A re-run of an older main run is still a push to main and still carries
# that commit's own github.sha. Without a head check its deploy would build
# the older commit over a newer one, and the ref-pinned hook call has already
# turned Render's auto-deploy off, so nothing would put the newer one back.
_NEWER = "fedcba9876543210fedcba9876543210fedcba98"


def test_it_asks_github_for_the_head_of_main(tmp_path):
    result, _, gh_calls = _run_deploy(tmp_path, _HOOK)
    assert result.returncode == 0, _printed(result)
    (argv,) = gh_calls
    assert argv[0] == "api"
    assert "repos/example-owner/example-repo/git/ref/heads/main" in argv


def test_an_older_commit_is_not_deployed_once_main_has_moved(tmp_path):
    result, calls, _ = _run_deploy(tmp_path, _HOOK, head=_NEWER)
    assert result.returncode == 0, _printed(result)
    assert calls == [], "curl was called, so the older commit was deployed"
    notice = result.stdout
    assert "::notice::" in notice
    assert _NEWER in notice and _SHA in notice


def test_an_unreadable_head_fails_the_job_without_deploying(tmp_path):
    cases = {
        "gh-failed": {"gh_exit": 1, "head": ""},
        "empty": {"head": ""},
        "not-a-sha": {"head": "main"},
    }
    for label, kwargs in cases.items():
        run_dir = tmp_path / label
        run_dir.mkdir()
        result, calls, _ = _run_deploy(run_dir, _HOOK, **kwargs)
        printed = _printed(result)
        assert result.returncode != 0, label
        assert "::error::" in printed, label
        assert calls == [], label
        assert "fake-hook-key-0000" not in printed, label
        assert "fake-github-token-0000" not in printed, label


def test_no_failure_message_tells_anyone_to_re_run_an_older_run():
    """Re-running an older main run can still cancel a newer run waiting in
    ci.yml's concurrency group, so the advice is the head commit's run only."""
    run = _deploy_step()["run"]
    for line in run.splitlines():
        if "::error::" in line and "e-run" in line:
            assert "head of main" in line, line
