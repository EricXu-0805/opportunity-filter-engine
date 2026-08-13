"""A gate that cannot fail is a lie about coverage — pin the shape of ours.

Every defect below shipped as green CI: the audits ran under
`continue-on-error`, so "Dependency audit ✓" in the checks list meant nothing;
`npm run lint --if-present` turned into a pass the moment the script was
deleted; the cron workflows `exit 0`-ed when their secrets were unset, so a
revoked CRON_SECRET was an invisible nightly no-op; and ops-scan — the job that
exists to notice trouble — had no alert step at all, so its own death looked
exactly like "no incidents".

These are workflow *properties*, not code paths, so they are asserted against
the workflow YAML directly (same approach as
tests/test_ops_plumbing.py::TestWorkflowWiring and tests/test_refresh_alerting).
The runtime halves of the same story are unit-tested: the assemble floor in
tests/test_shard_corpus.py, the NO-GO exit code in
tests/test_truthfulness_framework.py, and the response checker in
tests/test_ops_plumbing.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[1]
_WORKFLOWS = _REPO / ".github" / "workflows"
sys.path.insert(0, str(_REPO / "scripts"))

# Branch protection lives on GitHub, not in this repo, so the required set is
# mirrored here on purpose: these are the four checks a PR must pass (Backend,
# Frontend, Migrations, plus E2E — required since 2026-07-28). The security
# audits were moved OUT of them into an advisory job precisely so that no
# required job needs a step whose failure is ignored.
REQUIRED_CI_JOBS = ("backend", "frontend", "migrations", "e2e")
ADVISORY_CI_JOB = "security-advisory"
# The advisory audits live in their own workflow rather than in ci.yml, because
# Render's `autoDeployTrigger: checksPass` waits on EVERY check run of a commit
# and counts only success/neutral/skipped as passing — it has no notion of
# "required". While the advisory job ran on push-to-main, one red audit stopped
# backend deploys entirely (four days on da18e7b).
ADVISORY_WORKFLOW = "security-advisory.yml"
RELEASE_GATE_WORKFLOW = "release-gate.yml"
CI_WORKFLOWS = ("ci.yml", ADVISORY_WORKFLOW)

# Endpoint-calling crons: without these secrets the run does nothing at all, so
# "unset" must fail rather than pass. (RESEND_API_KEY/OPERATOR_EMAIL configure
# the alert itself and stay optional — see test_alert_config_stays_optional.)
ENDPOINT_CRONS = ("daily-reminders.yml", "saved-searches-refresh.yml", "ops-scan.yml")
CRON_REQUIRED_SECRETS = ("BACKEND_URL", "CRON_SECRET")
ALL_CRONS = (*ENDPOINT_CRONS, "refresh-data.yml")


def _workflow(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _jobs(name: str) -> dict:
    return _workflow(name)["jobs"]


def _triggers(name: str) -> dict:
    """A workflow's `on:` block.

    YAML 1.1 resolves the bare key `on` to the boolean True, so PyYAML stores
    the trigger map under True, not "on". Read both so this keeps working if
    the file is ever written as `"on":`.
    """
    wf = _workflow(name)
    block = wf.get(True, wf.get("on"))
    assert isinstance(block, dict), f"{name}: unreadable `on:` block"
    return block


def _steps(workflow_name: str) -> list[dict]:
    """Every step of every job in a workflow."""
    return [s for job in _jobs(workflow_name).values() for s in job["steps"]]


def _named_step(workflow_name: str, fragment: str, job_id: str | None = None) -> dict:
    steps = (_jobs(workflow_name)[job_id]["steps"] if job_id
             else _steps(workflow_name))
    matches = [s for s in steps
               if fragment.lower() in str(s.get("name", "")).lower()]
    assert matches, f"{workflow_name}: no step named like {fragment!r}"
    return matches[0]


def _exit_zero_guards(run: str, secrets: tuple[str, ...]) -> list[str]:
    """Lines that test one of ``secrets`` for emptiness and then exit 0."""
    lines = run.splitlines()
    found: list[str] = []
    for i, line in enumerate(lines):
        if "-z " not in line or not any(s in line for s in secrets):
            continue
        if "exit 0" in " ".join(lines[i:i + 4]):
            found.append(line.strip())
    return found


# --------------------------------------------------------- required CI jobs

def test_the_required_jobs_still_exist_under_these_ids():
    """Guards the premise of every other assertion in this file."""
    jobs = _jobs("ci.yml")
    missing = [j for j in REQUIRED_CI_JOBS if j not in jobs]
    assert not missing, (
        f"required CI job(s) {missing} vanished or were renamed — update "
        "REQUIRED_CI_JOBS here and the branch-protection settings together"
    )


def test_no_required_job_contains_a_step_whose_failure_is_ignored():
    """The core rule: a required check must not carry a decorative step.

    `pip-audit --strict` and `npm audit --audit-level=high` both ran with
    `continue-on-error: true` inside Backend and Frontend. They rendered as
    steps of a *required* job, so the checks list read as though dependency
    advisories gated a merge, while in fact no finding could ever fail
    anything. Either a step gates or it belongs in the advisory job.
    """
    jobs = _jobs("ci.yml")
    offenders: list[str] = []
    for job_id in REQUIRED_CI_JOBS:
        job = jobs[job_id]
        if job.get("continue-on-error"):
            offenders.append(f"{job_id} (job-level continue-on-error)")
        for step in job["steps"]:
            if step.get("continue-on-error"):
                label = step.get("name") or step.get("uses") or step.get("run")
                offenders.append(f"{job_id} -> {str(label)[:60]}")
    assert not offenders, (
        "required CI jobs contain step(s) that pretend to gate: "
        + "; ".join(offenders)
    )


def test_advisory_workflow_never_attaches_a_check_to_a_main_commit():
    """A red audit must not be able to stop a deploy.

    Render waits for every check run on the commit, so an advisory job running
    on push-to-main is a deploy gate no matter what branch protection says.
    That is not theory: three cryptography advisories turned this job red on
    da18e7b and the backend stopped deploying for four days while Vercel — which
    does not wait for checks — shipped the new frontend against it.

    `pull_request` keeps full coverage (every change reaches main through a PR,
    including the daily data-refresh PR) while leaving the squash-merge commit
    with only the four required checks. `schedule` would undo this: a scheduled
    run attaches its check to the newest default-branch commit.
    """
    triggers = _triggers(ADVISORY_WORKFLOW)
    assert "pull_request" in triggers, "the audits must still run on every PR"
    assert "push" not in triggers, (
        "push-to-main puts an advisory check on a main commit, which Render's "
        "checksPass treats as a deploy gate"
    )
    assert "schedule" not in triggers, (
        "a scheduled run attaches its check to the newest main commit — same "
        "failure mode by another route"
    )


def test_the_release_gate_runs_but_can_never_freeze_a_deploy():
    """The gate is wired now, and wired so it cannot repeat #736.

    scripts/release_gate.py went unwired from #733 until 2026-08-14, so the
    committed ledger described a SHA that no longer existed on main. Wiring it
    is worth doing and worth doing carefully: NO-GO is its EXPECTED answer until
    an operator gathers the infrastructure evidence, so a version of this that
    ran automatically would sit permanently red on main and stop Render exactly
    as the advisory audit did.
    """
    triggers = _triggers(RELEASE_GATE_WORKFLOW)
    assert set(triggers) == {"workflow_dispatch"}, (
        "the release gate answers NO-GO by design; any trigger that fires "
        "without a human puts a permanent red check on main, and Render's "
        "checksPass reads that as 'do not deploy'"
    )

    steps = _steps(RELEASE_GATE_WORKFLOW)
    runs = " ".join(str(s.get("run", "")) for s in steps)
    assert "scripts/release_gate.py" in runs, "the gate is not actually invoked"
    # It must surface its own exit code. truthfulness_audit.py used to decide
    # NO-GO and return 0, which is how a verdict stops being a verdict.
    assert any(
        "exit" in str(s.get("run", "")) and "gate" in str(s.get("id", "") or s.get("run", ""))
        for s in steps
    ), "the gate's NO-GO exit code is swallowed instead of failing the job"
    for step in steps:
        assert not step.get("continue-on-error"), step.get("name")


def test_dependency_audits_live_in_a_non_required_advisory_job():
    """Moved, not deleted — and not silenced either.

    An upstream CVE published against a transitive dep must not block an
    unrelated release, which is why these are advisory. But they now fail
    honestly inside a job that is not a required check, instead of being
    swallowed inside one that is.
    """
    jobs = _jobs(ADVISORY_WORKFLOW)
    assert ADVISORY_CI_JOB in jobs, "the advisory audit job is gone"
    assert ADVISORY_CI_JOB not in _jobs("ci.yml"), (
        "the advisory job must not be back in the workflow that runs on main"
    )

    advisory = jobs[ADVISORY_CI_JOB]
    runs = " ".join(str(s.get("run", "")) for s in advisory["steps"])
    assert "pip-audit" in runs, "pip-audit disappeared with the move"
    assert "npm audit" in runs, "npm audit disappeared with the move"
    # The inherited exception must survive relocation, or the move quietly
    # changes which findings are accepted.
    assert "--ignore-vuln GHSA-4xh5-x5gv-qwph" in runs
    assert "--audit-level=high" in runs

    # Advisory means "not required", NOT "cannot fail": a continue-on-error
    # here would recreate the same lie one job over.
    assert not advisory.get("continue-on-error")
    assert not any(s.get("continue-on-error") for s in advisory["steps"])

    # And the audits must not have been left behind in a required job too.
    ci_jobs = _jobs("ci.yml")
    for job_id in REQUIRED_CI_JOBS:
        job_runs = " ".join(str(s.get("run", "")) for s in ci_jobs[job_id]["steps"])
        assert "pip-audit " not in job_runs, job_id
        assert "npm audit " not in job_runs, job_id


def test_frontend_lint_cannot_be_deleted_into_a_pass():
    """`npm run lint --if-present` exits 0 when the script is missing.

    So removing "lint" from package.json — a one-line, plausible-looking
    change — converted the lint gate into a permanent pass with no signal
    anywhere. Without the flag, npm exits non-zero on a missing script.
    """
    lint = _named_step("ci.yml", "Lint", job_id="frontend")
    assert str(lint.get("run", "")).strip() == "npm run lint"
    # Nowhere in CI (comments excluded — the parsed `run` bodies only), so it
    # cannot creep back into another npm invocation either.
    for workflow in CI_WORKFLOWS:
        for job_id, job in _jobs(workflow).items():
            for step in job["steps"]:
                assert "--if-present" not in str(step.get("run", "")), (
                    f"{workflow}:{job_id}: --if-present makes a deleted npm "
                    "script indistinguishable from a pass"
                )


def test_corpus_assemble_is_a_gating_step():
    """pytest's data-quality suite skips when the work file is absent.

    53 tests in tests/test_opportunity_data_quality.py and friends skip on a
    missing work file, so an assemble that writes `[]` and exits 0 (empty or
    unchecked-out shards directory) handed pytest a vacuously green
    data-quality gate. assemble now enforces
    shard_corpus.MIN_ASSEMBLED_RECORDS and exits non-zero below it — which
    only means anything if this step's failure is not swallowed.
    """
    from shard_corpus import MIN_ASSEMBLED_RECORDS

    step = _named_step("ci.yml", "Assemble corpus", job_id="backend")
    run = str(step.get("run", ""))
    assert "shard_corpus.py assemble" in run
    assert not step.get("continue-on-error")
    assert "|| true" not in run
    assert "--allow-empty" not in run, (
        "CI must never bypass the floor — that is the hole this closed"
    )
    # A floor of 0/1 would restore the hole while looking configured.
    assert MIN_ASSEMBLED_RECORDS >= 1000


# ------------------------------------------------------------------- crons

def test_every_cron_alerts_the_operator_when_it_dies():
    """ops-scan had no alert step at all.

    The workflow that turns each refresh's artifacts into collector_failure and
    data_drift incidents emailed nobody when it died — and a scan that never
    ran is indistinguishable from a scan that found nothing, which the admin
    operations queue then renders as an all-clear.
    """
    for name in ALL_CRONS:
        step = _named_step(name, "Alert operator")
        condition = str(step.get("if", ""))
        assert "failure()" in condition, name
        # Exceeding timeout-minutes CANCELS a job rather than failing it, so
        # bare failure() misses exactly the runs that hung (refresh-data lost
        # three five-hour runs that way).
        assert "cancelled()" in condition, name
        run = str(step.get("run", ""))
        assert "api.resend.com/emails" in run, name
        assert "actions/runs/" in run, f"{name}: alert must link the run"


def test_endpoint_crons_fail_on_a_missing_required_secret():
    """`exit 0` on an unset secret made a revoked secret invisible.

    Every cron opened with "secret not set — skipping" + exit 0, so a rotated
    CRON_SECRET or a renamed BACKEND_URL produced a green run every night
    while nothing happened — and because the job succeeded, the
    `if: failure()` operator alert never fired either.
    """
    for name in ENDPOINT_CRONS:
        runs = [str(s.get("run", "")) for s in _steps(name)]

        preflight = [r for r in runs if "exit 1" in r
                     and all(secret in r for secret in CRON_REQUIRED_SECRETS)]
        assert preflight, (
            f"{name}: no step fails the job when a required secret is unset"
        )
        assert "::error::" in preflight[0], (
            f"{name}: the failure must say which secret is missing"
        )

        # ...and no step anywhere may go back to passing on one.
        for run in runs:
            for offender in _exit_zero_guards(run, CRON_REQUIRED_SECRETS):
                raise AssertionError(
                    f"{name}: `exit 0` on a missing required secret: {offender}"
                )


def test_alert_config_stays_optional():
    """No chicken-and-egg: the alert step must not need to alert to report.

    RESEND_API_KEY/OPERATOR_EMAIL configure the notification itself. Making
    them fatal *here* would relocate the silence instead of removing it (and
    would fail a job for lacking the means to report that it failed), so the
    alert step logs and exits 0 when they are unset — the job's own failure is
    already recorded in the Actions run.

    Separately: daily-reminders DOES require RESEND_API_KEY in its preflight,
    because its health-check and digest steps deliver through it. That is about
    the workflow's own work, not about alerting, and the alert step still
    degrades to a log line rather than failing on it.
    """
    for name in ALL_CRONS:
        run = str(_named_step(name, "Alert operator").get("run", ""))
        assert "OPERATOR_EMAIL" in run and "exit 0" in run, name
        # `|| true` on the send: an alerting failure must not overwrite the
        # real failure. The honest cost is that delivery is unverified.
        assert "|| true" in run, name
