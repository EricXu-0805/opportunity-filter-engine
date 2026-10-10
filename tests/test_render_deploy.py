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
# The checks branch protection requires on main (read from the GitHub API on
# 2026-10-09): job id -> the check name it reports.
_REQUIRED_CHECKS = {
    "backend": "Backend (lint + pytest)",
    "frontend": "Frontend (typecheck + build)",
    "e2e": "E2E (Playwright)",
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


def test_the_deploy_waits_for_every_required_check():
    job = _deploy_job()
    assert sorted(job["needs"]) == sorted(_REQUIRED_CHECKS)
    jobs = _ci()["jobs"]
    for job_id, check in _REQUIRED_CHECKS.items():
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
    }
    run = step["run"]
    assert "${{" not in run
    for tracing in ("set -x", "set -o xtrace", "--verbose", "--trace", "curl -v"):
        assert tracing not in run, tracing


def _run_deploy(tmp_path: Path, hook: str, *, status: str = "200",
                curl_exit: int = 0) -> tuple[subprocess.CompletedProcess, list[list[str]]]:
    """Run the step's script as GitHub runs it, with a curl that records its
    arguments and answers with ``status``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "curl.log"
    fake = bin_dir / "curl"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['FAKE_CURL_LOG'], 'a') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if '-w' in sys.argv:\n"
        "    sys.stdout.write(os.environ['FAKE_CURL_STATUS'])\n"
        "sys.exit(int(os.environ['FAKE_CURL_EXIT']))\n"
    )
    fake.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_CURL_LOG": str(log),
        "FAKE_CURL_STATUS": status,
        "FAKE_CURL_EXIT": str(curl_exit),
        "RENDER_DEPLOY_HOOK_URL": hook,
        "DEPLOY_SHA": _SHA,
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", _deploy_step()["run"]],
        env=env, capture_output=True, text=True,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, calls


def _printed(result: subprocess.CompletedProcess) -> str:
    return result.stdout + result.stderr


def test_without_the_secret_it_succeeds_and_deploys_nothing(tmp_path):
    """Until the owner sets the secret, Render's checksPass waits on this
    job's check too, so it has to pass."""
    result, calls = _run_deploy(tmp_path, "")
    assert result.returncode == 0, _printed(result)
    assert "::notice::" in result.stdout
    assert calls == []


def test_with_the_secret_it_posts_the_hook_once_for_this_commit(tmp_path):
    result, calls = _run_deploy(tmp_path, _HOOK)
    assert result.returncode == 0, _printed(result)
    (argv,) = calls
    assert argv[argv.index("-X") + 1] == "POST"
    assert f"{_HOOK}&ref={_SHA}" in argv
    assert _SHA in result.stdout


def test_a_hook_url_without_a_query_string_still_gets_the_ref(tmp_path):
    bare = "https://api.render.com/deploy/srv-fakeservice"
    _, calls = _run_deploy(tmp_path, bare)
    (argv,) = calls
    assert f"{bare}?ref={_SHA}" in argv


def test_a_non_2xx_answer_fails_the_job_without_printing_the_url(tmp_path):
    for status in ("404", "500", "301"):
        run_dir = tmp_path / status
        run_dir.mkdir()
        result, _ = _run_deploy(run_dir, _HOOK, status=status)
        printed = _printed(result)
        assert result.returncode != 0, status
        assert "::error::" in printed and status in printed
        assert "fake-hook-key-0000" not in printed and "srv-fakeservice" not in printed


def test_an_unreachable_hook_fails_the_job_without_printing_the_url(tmp_path):
    result, _ = _run_deploy(tmp_path, _HOOK, status="000", curl_exit=7)
    printed = _printed(result)
    assert result.returncode != 0
    assert "::error::" in printed
    assert "fake-hook-key-0000" not in printed and "srv-fakeservice" not in printed
