"""Contracts for the canonical scheduled/manual refresh shard selection."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from refresh_rotation import (  # noqa: E402
    ISOLATED_WEEKLY_SHARDS,
    NATIONAL_SHARD,
    WEEKLY_ROTATION,
    alert_decision,
    normalize_publication_unit,
    normalize_requested_shard,
    overlap_decision,
    registered_school_slugs,
    scheduled_shard,
    superseded_refresh_prs,
    target_shards,
    validate_rotation,
)

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "refresh_rotation.py"


def test_weekly_rotation_covers_every_registered_school_exactly_once():
    validate_rotation()
    scheduled = [
        slug
        for day in range(1, 7)
        for slug in WEEKLY_ROTATION[day]
    ]
    isolated = [
        slug
        for shards in ISOLATED_WEEKLY_SHARDS.values()
        for slug in shards
    ]
    combined = [*scheduled, *isolated]
    assert set(combined) == registered_school_slugs()
    assert len(combined) == len(set(combined))
    assert WEEKLY_ROTATION[7] == (NATIONAL_SHARD,)


def test_scheduled_shard_is_deterministic():
    assert scheduled_shard(2).startswith("ucb,mit,usc,umn")
    assert scheduled_shard(7) == NATIONAL_SHARD
    assert "ucd" not in scheduled_shard(6).split(",")
    with pytest.raises(ValueError, match="weekday"):
        scheduled_shard(8)
    # No isolated batch is registered on any day since UC Davis left the
    # supported set (src/school_scope.py) -- it was the only entry.
    for day in range(1, 8):
        with pytest.raises(ValueError, match="no isolated"):
            scheduled_shard(day, isolated=True)


@pytest.mark.parametrize(
    "payload",
    [
        "uw, national",
        "uw,national",
        "UW",
        "uw,uw",
        "uw;echo-pwned",
        "$(touch-pwned)",
        "not-a-real-school",
        "ucd,uw",
    ],
)
def test_manual_shard_rejects_injection_duplicates_and_unknowns(payload):
    with pytest.raises(ValueError):
        normalize_requested_shard(payload, allow_full=True)


def test_manual_shard_normalizes_only_valid_known_values():
    assert normalize_requested_shard("uw,wisc") == "uw,wisc"
    assert normalize_requested_shard("national") == "national"
    assert normalize_requested_shard("", allow_full=True) == ""


def test_publication_unit_accepts_only_bounded_canonical_units():
    monday = scheduled_shard(1)
    assert normalize_publication_unit(monday) == monday
    assert normalize_publication_unit("uw") == "uw"
    assert normalize_publication_unit("national") == "national"

    with pytest.raises(ValueError, match="explicit"):
        normalize_publication_unit("")
    with pytest.raises(ValueError, match="canonical"):
        normalize_publication_unit("uw,wisc")


def test_target_shards_are_bounded_to_the_authorized_selection():
    assert target_shards("uw,wisc") == ("uw", "wisc")
    assert target_shards("national") == ("national",)
    full = target_shards("")
    assert set(full) == {*registered_school_slugs(), NATIONAL_SHARD}
    assert len(full) == len(registered_school_slugs()) + 1


class TestBrowserDetection:
    """The workflow installs Chromium only when the shard needs it. That list
    used to be a hardcoded alternation in refresh-data.yml missing 11
    render-mode schools; they collected anyway only because the install is
    per-RUN and every shard happened to contain a listed school. Nothing
    enforced that coincidence, and the failure it guards is silent:
    _render_soup lazy-imports Playwright and degrades to None, which is
    indistinguishable from an unreachable directory, while the source still
    reports "ok". Derived from the configs, it cannot drift."""

    def test_every_render_config_is_detected(self):
        import importlib
        import pkgutil

        import src.collectors.schools as schools_pkg
        from scripts.refresh_rotation import browser_schools

        detected = browser_schools()
        for module in pkgutil.iter_modules(schools_pkg.__path__):
            if not module.name.endswith("_faculty"):
                continue
            config = getattr(
                importlib.import_module(f"src.collectors.schools.{module.name}"),
                "SCHOOL", None,
            )
            if not isinstance(config, dict):
                continue
            renders = any(
                isinstance(block, dict)
                and (
                    block.get("render")
                    or (isinstance(block.get("profile_enrich"), dict)
                        and block["profile_enrich"].get("render"))
                )
                for dept in config.get("departments", [])
                for block in dept.values()
            )
            if renders:
                assert config["school_slug"] in detected, (
                    f"{config['school_slug']} renders but the workflow would "
                    "not install Chromium for its shard — its render "
                    "departments would silently collect nothing"
                )

    def test_every_campus_render_source_is_detected(self):
        """The campus half of the same guarantee.

        campus_graph configs carry ``sources``, not ``departments``, and live
        in ``<slug>.py`` rather than ``<slug>_faculty.py`` — so the scan above
        never saw them. uva is the case that proves it matters: its faculty
        config needs no browser, so nothing else would have put it in this set,
        and its Cloudflare-walled UGR hub would have crawled with a plain GET
        on every shard day and reported an unreachable page.
        """
        import importlib
        import pkgutil

        import src.collectors.schools as schools_pkg
        from scripts.refresh_rotation import browser_schools

        detected = browser_schools()
        for module in pkgutil.iter_modules(schools_pkg.__path__):
            if module.name.endswith("_faculty") or module.name.startswith("_"):
                continue
            config = getattr(
                importlib.import_module(f"src.collectors.schools.{module.name}"),
                "SCHOOL", None,
            )
            if not isinstance(config, dict):
                continue
            if any(isinstance(source, dict) and source.get("render")
                   for source in config.get("sources", [])):
                assert config["school_slug"] in detected, (
                    f"{config['school_slug']} has a render campus source but "
                    "the workflow would not install Chromium for its shard — "
                    "the crawl would degrade to None and read as unreachable"
                )

    def test_uva_needs_the_browser_for_its_campus_source_alone(self):
        # Named rather than left to the sweep above: uva is the school whose
        # ONLY render config is a campus source, so it is the one a regression
        # in the campus branch would drop out of the set.
        from scripts.refresh_rotation import browser_schools

        assert "uva" in browser_schools()

    def test_uiuc_is_detected_despite_having_no_render_config(self):
        # uiuc_js_faculty drives Playwright directly (ACES Drupal Views AJAX),
        # outside the faculty_graph engine, so config inspection cannot see it.
        from scripts.refresh_rotation import browser_schools

        assert "uiuc" in browser_schools()

    def test_national_day_skips_the_browser_install(self):
        from scripts.refresh_rotation import shard_needs_browser

        assert shard_needs_browser("national") is False

    def test_a_render_source_open_to_every_school_needs_the_browser_on_the_national_day(
            self, monkeypatch):
        # refresh_all crawls it on the national shard's run, not on the school's.
        from scripts.refresh_rotation import shard_needs_browser
        from src.collectors.schools.stanford import SCHOOL as STANFORD

        [source] = [s for s in STANFORD["sources"] if s["emit"] == "open"]
        monkeypatch.setitem(source, "render", True)
        assert shard_needs_browser("national") is True

    def test_full_refresh_installs_the_browser(self):
        from scripts.refresh_rotation import shard_needs_browser

        assert shard_needs_browser("") is True

    def test_browserless_single_school_skips_the_install(self):
        from scripts.refresh_rotation import shard_needs_browser

        assert shard_needs_browser("wisc") is False


# --- Overlap between refresh runs -------------------------------------------
#
# Scheduled and manual refreshes sit in separate concurrency groups, so GitHub
# never keeps them apart. Only manual dispatches used to check: a scheduled run
# never looked for a manual one. On 2026-10-02 a cron that fired 5.5 h late ran
# for two hours beside a manual dispatch of the same shard.

MANUAL, SCHEDULED = "workflow_dispatch", "schedule"


def _runs(*runs):
    """A workflow-runs API payload: one (id, event[, status]) per run."""
    rows = [(*run, "in_progress")[:3] for run in runs]
    return {
        "total_count": len(rows),
        "workflow_runs": [
            {"id": run_id, "event": event, "status": status}
            for run_id, event, status in rows
        ],
    }


class TestOverlapDecision:
    def test_a_scheduled_run_cancels_the_manual_run_already_in_progress(self):
        # Manual first, then the schedule fires: production wins.
        decision = overlap_decision(SCHEDULED, 200, _runs((100, MANUAL), (200, SCHEDULED)))
        assert (decision.action, decision.cancel) == ("cancel", (100,))
        assert decision.level == "warning"
        assert "100" in decision.message

    def test_a_manual_run_defers_to_the_scheduled_run_already_in_progress(self):
        decision = overlap_decision(MANUAL, 300, _runs((200, SCHEDULED), (300, MANUAL)))
        assert (decision.action, decision.cancel) == ("defer", ())
        assert decision.level == "error"
        assert "200" in decision.message

    def test_several_runs_in_progress(self):
        scheduled = overlap_decision(
            SCHEDULED, 400, _runs((300, MANUAL), (100, MANUAL), (400, SCHEDULED)))
        assert (scheduled.action, scheduled.cancel) == ("cancel", (100, 300))

        manual = overlap_decision(MANUAL, 500, _runs((400, SCHEDULED), (300, MANUAL), (500, MANUAL)))
        assert (manual.action, manual.cancel) == ("defer", ())
        assert "300" in manual.message and "400" in manual.message

    def test_a_scheduled_run_never_cancels_another_scheduled_run(self):
        # The schedule's own concurrency group queues scheduled runs, so a
        # second one in progress means that group was bypassed. Killing the
        # other day's production run is not this guard's call.
        both = overlap_decision(SCHEDULED, 500, _runs((300, SCHEDULED), (400, MANUAL)))
        assert (both.action, both.cancel) == ("cancel", (400,))
        assert "300" in both.message

        alone = overlap_decision(SCHEDULED, 500, _runs((300, SCHEDULED)))
        assert (alone.action, alone.cancel, alone.level) == ("proceed", (), "warning")
        assert "300" in alone.message

    @pytest.mark.parametrize("payload", [
        pytest.param(None, id="request-failed"),
        pytest.param({"message": "Server Error", "status": "500"}, id="error-body"),
        pytest.param([], id="not-an-object"),
        pytest.param({"workflow_runs": [{"id": "100", "event": MANUAL, "status": "in_progress"}]},
                     id="string-id"),
        pytest.param({"workflow_runs": [{"id": 100, "status": "in_progress"}]}, id="no-event"),
    ])
    def test_a_failed_listing_defers_a_manual_run_and_lets_production_proceed(self, payload):
        manual = overlap_decision(MANUAL, 300, payload)
        assert (manual.action, manual.level) == ("defer", "error")

        scheduled = overlap_decision(SCHEDULED, 300, payload)
        assert (scheduled.action, scheduled.cancel, scheduled.level) == ("proceed", (), "warning")
        assert "could not" in scheduled.message.lower()

    def test_only_other_runs_in_progress_count(self):
        for event in (MANUAL, SCHEDULED):
            alone = overlap_decision(event, 300, _runs((300, event)))
            assert (alone.action, alone.cancel, alone.level) == ("proceed", (), "info")

            # A finished run, or one still waiting for a runner, does not hold
            # the corpus; a queued manual run checks for itself when it starts.
            idle = overlap_decision(
                event, 300, _runs((100, MANUAL, "completed"), (200, MANUAL, "queued"), (300, event)))
            assert (idle.action, idle.cancel) == ("proceed", ())

    def test_an_unknown_event_defers_like_a_manual_run(self):
        decision = overlap_decision("repository_dispatch", 300, _runs((200, SCHEDULED)))
        assert decision.action == "defer"
        assert overlap_decision(SCHEDULED, 300, _runs((200, "repository_dispatch"))).cancel == (200,)


class TestAlertDecision:
    """A run the overlap guard stood aside is not a failed refresh.

    The guard step fails a deferring manual run, and a scheduled run cancels a
    manual one; the alert step runs on failure() || cancelled(), so both sent
    "data refresh FAILED" while the refresh they yielded to was running.
    """

    def test_a_manual_run_that_deferred_to_a_refresh_in_progress_does_not_alert(self):
        decision = alert_decision(MANUAL, 300, "failure", "defer", _runs((200, SCHEDULED), (300, MANUAL)))
        assert decision.send is False
        assert "200" in decision.message

    def test_a_manual_run_a_scheduled_run_cancelled_does_not_alert(self):
        decision = alert_decision(MANUAL, 100, "cancelled", "proceed", _runs((100, MANUAL), (200, SCHEDULED)))
        assert decision.send is False
        assert "200" in decision.message
        # The guard may have been cancelled before it wrote its outcome.
        assert alert_decision(MANUAL, 100, "cancelled", "", _runs((200, SCHEDULED))).send is False

    def test_a_real_failure_of_a_manual_run_alerts(self):
        assert alert_decision(MANUAL, 300, "failure", "proceed", _runs((300, MANUAL))).send is True
        # A scheduled run in progress does not excuse a failure the guard did
        # not cause: only a cancellation is the guard's.
        assert alert_decision(MANUAL, 300, "failure", "proceed", _runs((200, SCHEDULED))).send is True

    def test_a_cancellation_that_is_not_the_guards_alerts(self):
        # timeout-minutes or a person: no scheduled run is there to have done it.
        assert alert_decision(MANUAL, 300, "cancelled", "proceed", _runs((300, MANUAL))).send is True
        assert alert_decision(MANUAL, 300, "cancelled", "proceed", _runs()).send is True

    def test_a_deferral_with_nothing_left_running_alerts(self):
        # The guard deferred blind (it could not list the runs) or the refresh
        # it yielded to has gone: the dispatch did not happen and nothing
        # else is refreshing, so the operator must re-dispatch.
        assert alert_decision(MANUAL, 300, "failure", "defer", _runs((300, MANUAL))).send is True

    def test_a_guard_that_could_not_decide_alerts(self):
        decision = alert_decision(MANUAL, 300, "failure", "undecided", _runs((200, SCHEDULED)))
        assert decision.send is True

    @pytest.mark.parametrize("payload", [None, {"message": "Server Error"}, []])
    def test_an_unanswered_listing_alerts(self, payload):
        assert alert_decision(MANUAL, 300, "failure", "defer", payload).send is True
        assert alert_decision(MANUAL, 300, "cancelled", "proceed", payload).send is True

    def test_a_scheduled_run_always_alerts(self):
        # Production is never deferred or cancelled by the guard.
        for status, outcome in (("failure", "proceed"), ("cancelled", "cancel"),
                                ("failure", "defer"), ("cancelled", "proceed")):
            decision = alert_decision(SCHEDULED, 200, status, outcome,
                                      _runs((100, MANUAL), (200, SCHEDULED), (300, SCHEDULED)))
            assert decision.send is True, (status, outcome)


def _cli(*args, stdin=""):
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args], input=stdin, capture_output=True, text=True, cwd=_REPO,
    )


class TestOverlapCli:
    def test_prints_the_action_and_annotates_the_reason(self, tmp_path):
        runs = tmp_path / "runs.json"
        runs.write_text(json.dumps(_runs((100, MANUAL), (101, MANUAL), (200, SCHEDULED))))

        out = _cli("--overlap", "--event", SCHEDULED, "--run-id", "200", "--runs", str(runs))
        assert out.returncode == 0, out.stderr
        assert out.stdout == "cancel 100 101\n"
        assert out.stderr.startswith("::warning::")

        out = _cli("--overlap", "--event", MANUAL, "--run-id", "300", "--runs", str(runs))
        assert (out.returncode, out.stdout) == (0, "defer\n")
        assert out.stderr.startswith("::error::")

    @pytest.mark.parametrize("contents", ["", "{not json", '{"message": "Bad credentials"}'])
    def test_an_empty_or_unreadable_listing_is_a_failed_request(self, tmp_path, contents):
        runs = tmp_path / "runs.json"
        runs.write_text(contents)
        scheduled = _cli("--overlap", "--event", SCHEDULED, "--run-id", "2", "--runs", str(runs))
        assert (scheduled.returncode, scheduled.stdout) == (0, "proceed\n")
        assert scheduled.stderr.startswith("::warning::")
        manual = _cli("--overlap", "--event", MANUAL, "--run-id", "2", "--runs", str(tmp_path / "absent.json"))
        assert (manual.returncode, manual.stdout) == (0, "defer\n")

    def test_runs_from_a_lone_copy_of_this_file(self, tmp_path):
        # The workflow asks before it checks the repository out: it fetches
        # this one file and runs it with the runner's own python3. Anything
        # this module imports from the repository at load time would crash it
        # there, and a crashed guard lets every scheduled run through.
        lone = tmp_path / "a" / "b" / "refresh_rotation.py"
        lone.parent.mkdir(parents=True)
        shutil.copy(_SCRIPT, lone)
        runs = tmp_path / "runs.json"
        runs.write_text(json.dumps(_runs((100, MANUAL))))
        out = subprocess.run(
            [sys.executable, "-I", str(lone), "--overlap", "--event", SCHEDULED,
             "--run-id", "200", "--runs", str(runs)],
            capture_output=True, text=True, cwd=tmp_path,
        )
        assert (out.returncode, out.stdout) == (0, "cancel 100\n"), out.stderr


class TestAlertCli:
    def test_prints_send_or_skip(self, tmp_path):
        runs = tmp_path / "runs.json"
        runs.write_text(json.dumps(_runs((200, SCHEDULED), (300, MANUAL))))
        args = ("--alert", "--event", MANUAL, "--run-id", "300", "--runs", str(runs))
        out = _cli(*args, "--job-status", "failure", "--guard", "defer")
        assert (out.returncode, out.stdout) == (0, "skip\n"), out.stderr
        assert "200" in out.stderr
        out = _cli(*args, "--job-status", "failure", "--guard", "proceed")
        assert (out.returncode, out.stdout) == (0, "send\n"), out.stderr

    def test_an_empty_or_unreadable_listing_sends(self, tmp_path):
        runs = tmp_path / "runs.json"
        runs.write_text("")
        for path in (runs, tmp_path / "absent.json"):
            out = _cli("--alert", "--event", MANUAL, "--run-id", "300", "--runs", str(path),
                       "--job-status", "failure", "--guard", "defer")
            assert (out.returncode, out.stdout) == (0, "send\n"), out.stderr

    def test_needs_the_job_status(self, tmp_path):
        out = _cli("--alert", "--event", MANUAL, "--run-id", "300", "--runs", str(tmp_path / "r.json"))
        assert out.returncode != 0


class TestSupersededRefreshPrs:
    def test_only_older_runs_prs_are_superseded(self):
        prs = [
            {"number": 11, "headRefName": "auto/refresh-data-100"},
            {"number": 12, "headRefName": "auto/refresh-data-150-r2"},
            {"number": 13, "headRefName": "auto/refresh-data-200"},      # this run
            {"number": 14, "headRefName": "auto/refresh-data-300"},      # a newer run
            {"number": 15, "headRefName": "auto/refresh-data-300-r2"},
            {"number": 16, "headRefName": "auto/refresh-data-backfill"},  # not a run's
            {"number": 17, "headRefName": "auto/refresh-data-99x"},
            {"number": 18, "headRefName": "feature/auto/refresh-data-1"},
            {"number": 19, "headRefName": "fix/refresh-guards"},
        ]
        assert superseded_refresh_prs(prs, 200) == [11, 12]

    def test_cli_reads_gh_pr_list_output(self):
        prs = json.dumps([{"number": 7, "headRefName": "auto/refresh-data-5"},
                          {"number": 8, "headRefName": "auto/refresh-data-9"}])
        out = _cli("--superseded-prs", "--run-id", "6", stdin=prs)
        assert (out.returncode, out.stdout) == (0, "7\n"), out.stderr
        assert _cli("--superseded-prs", "--run-id", "6", stdin="not json").returncode != 0


# --- The workflow steps themselves ------------------------------------------
#
# Each scenario runs the step's own script under bash -e, as the runner does,
# with a stand-in gh that answers from a fixed scenario and logs every call.

_FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
scenario = json.load(open(os.environ["FAKE_GH_SCENARIO"]))
log_path = os.environ["FAKE_GH_LOG"]
with open(log_path) as handle:
    earlier = [json.loads(line) for line in handle if line.strip()]
with open(log_path, "a") as handle:
    handle.write(json.dumps(args) + "\n")
if args[:2] == ["pr", "list"]:
    if scenario.get("pr_list_fails"):
        sys.exit(1)
    if "--jq" in args:
        import subprocess
        jq = subprocess.run(["jq", "-r", args[args.index("--jq") + 1]], input=json.dumps(scenario["prs"]),
                            capture_output=True, text=True)
        sys.stdout.write(jq.stdout)
        sys.exit(jq.returncode)
    json.dump(scenario["prs"], sys.stdout)
    sys.exit(0)
if args[:2] == ["pr", "close"]:
    sys.exit(0)
path = next(arg for arg in args if arg.startswith("repos/"))
if "/contents/scripts/refresh_rotation.py" in path:
    if scenario.get("fetch_fails"):
        print('{"message": "Not Found"}')
        sys.exit(1)
    sys.stdout.write(open(scenario["script"]).read())
elif "/actions/workflows/refresh-data.yml/runs" in path:
    if scenario.get("list_fails"):
        print('{"message": "Server Error"}')
        sys.exit(1)
    json.dump(scenario["runs"], sys.stdout)
elif path.endswith("/cancel"):
    sys.exit(1 if scenario.get("cancel_fails") else 0)
else:
    run_id = path.rsplit("/", 1)[1]
    polls = sum(1 for call in earlier + [args] if call[:1] == ["api"] and call[-3:-2] == [path])
    after = scenario.get("completed_after", {}).get(run_id, 1)
    print("completed" if after is not None and polls >= after else "in_progress")
'''


_FAKE_CURL = f'''#!{sys.executable}
import json, os, sys
with open(os.environ["FAKE_GH_LOG"], "a") as handle:
    handle.write(json.dumps(["curl", *sys.argv[1:]]) + "\\n")
'''


def _workflow_step(name_fragment: str) -> dict:
    workflow = yaml.safe_load((_REPO / ".github/workflows/refresh-data.yml").read_text())
    steps = workflow["jobs"]["refresh"]["steps"]
    return next(step for step in steps if name_fragment in str(step.get("name", "")))


@pytest.fixture
def fake_gh(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {
        "gh": _FAKE_GH,
        "sleep": '#!/bin/sh\necho "[\\"sleep\\", \\"$1\\"]" >> "$FAKE_GH_LOG"\n',
        "python3": f'#!/bin/sh\nexec "{sys.executable}" "$@"\n',
        "curl": _FAKE_CURL,
    }.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    log = tmp_path / "gh.log"
    log.write_text("")

    def run(script, scenario, cwd=tmp_path, **env):
        scenario_path = tmp_path / "scenario.json"
        scenario_path.write_text(json.dumps({"script": str(_SCRIPT), **scenario}))
        result = subprocess.run(
            ["bash", "-e", "-c", script], cwd=cwd, capture_output=True, text=True,
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path),
                 "GITHUB_OUTPUT": str(tmp_path / "github_output"),
                 "FAKE_GH_SCENARIO": str(scenario_path), "FAKE_GH_LOG": str(log),
                 "GH_TOKEN": "not-a-token", "REPO": "o/r", "SHA": "abc123", **env},
        )
        calls = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        return result, calls
    return run


def _cancels(calls):
    return [call[-1].split("/")[-2] for call in calls if call[:3] == ["api", "-X", "POST"]]


class TestOverlapStep:
    def test_the_guard_runs_first_for_every_event(self):
        workflow = yaml.safe_load((_REPO / ".github/workflows/refresh-data.yml").read_text())
        steps = workflow["jobs"]["refresh"]["steps"]
        guard = _workflow_step("Keep refresh runs from overlapping")
        # Before the checkout, so a deferral costs seconds; for both events,
        # so a scheduled run looks for a manual one too.
        assert steps.index(guard) == 0
        assert "if" not in guard
        # Cancelling another run needs the token's actions permission.
        assert workflow["jobs"]["refresh"]["permissions"].get("actions") == "write"

    def test_a_manual_run_defers_to_a_scheduled_one(self, fake_gh):
        result, calls = fake_gh(_workflow_step("overlapping")["run"],
                                {"runs": _runs((200, SCHEDULED), (300, MANUAL))},
                                EVENT=MANUAL, RUN_ID="300")
        assert result.returncode == 1
        assert "::error::" in result.stderr + result.stdout
        assert _cancels(calls) == []

    def test_a_scheduled_run_cancels_a_manual_one_and_waits_for_it_to_stop(self, fake_gh):
        result, calls = fake_gh(_workflow_step("overlapping")["run"],
                                {"runs": _runs((100, MANUAL), (101, MANUAL), (200, SCHEDULED)),
                                 "completed_after": {"100": 3, "101": 1}},
                                EVENT=SCHEDULED, RUN_ID="200")
        assert result.returncode == 0, result.stdout + result.stderr
        assert _cancels(calls) == ["100", "101"]
        polls = [call for call in calls if call[:1] == ["api"] and call[-1] == ".status"]
        # 101 stopped at once, 100 on its third look.
        assert [call[1] for call in polls] == ["repos/o/r/actions/runs/100", "repos/o/r/actions/runs/101",
                                                "repos/o/r/actions/runs/100", "repos/o/r/actions/runs/100"]
        # The step ends on the look that saw the last run stop.
        assert calls[-1] == ["api", "repos/o/r/actions/runs/100", "--jq", ".status"]

    def test_a_scheduled_run_proceeds_when_a_cancelled_run_will_not_stop(self, fake_gh):
        result, calls = fake_gh(_workflow_step("overlapping")["run"],
                                {"runs": _runs((100, MANUAL), (200, SCHEDULED)),
                                 "completed_after": {"100": None}, "cancel_fails": True},
                                EVENT=SCHEDULED, RUN_ID="200")
        assert result.returncode == 0
        assert result.stdout.count("::warning::") == 2
        sleeps = [call for call in calls if call[0] == "sleep"]
        assert len(sleeps) * int(sleeps[0][1]) == 300

    @pytest.mark.parametrize("failure", ["list_fails", "fetch_fails"])
    def test_a_failed_request_lets_production_through_and_defers_a_manual_run(self, fake_gh, failure):
        scenario = {"runs": _runs((100, MANUAL), (200, SCHEDULED)), failure: True}
        scheduled, calls = fake_gh(_workflow_step("overlapping")["run"], scenario,
                                   EVENT=SCHEDULED, RUN_ID="200")
        assert scheduled.returncode == 0
        assert "::warning::" in scheduled.stderr + scheduled.stdout
        assert _cancels(calls) == []

        manual, _ = fake_gh(_workflow_step("overlapping")["run"], scenario, EVENT=MANUAL, RUN_ID="300")
        assert manual.returncode == 1
        assert "::error::" in manual.stderr + manual.stdout

    def test_nothing_else_running_proceeds(self, fake_gh):
        for event in (MANUAL, SCHEDULED):
            result, calls = fake_gh(_workflow_step("overlapping")["run"], {"runs": _runs((200, event))},
                                    EVENT=event, RUN_ID="200")
            assert result.returncode == 0, result.stderr
            assert _cancels(calls) == []

    @pytest.mark.parametrize("event,scenario,outcome", [
        (MANUAL, {"runs": _runs((200, SCHEDULED), (300, MANUAL))}, "defer"),
        (MANUAL, {"runs": _runs((300, MANUAL))}, "proceed"),
        (SCHEDULED, {"runs": _runs((100, MANUAL), (300, SCHEDULED))}, "cancel"),
        (MANUAL, {"runs": _runs((300, MANUAL)), "fetch_fails": True}, "undecided"),
        (SCHEDULED, {"runs": _runs((300, SCHEDULED)), "fetch_fails": True}, "undecided"),
    ])
    def test_the_step_reports_its_outcome_for_the_alert(self, fake_gh, tmp_path, event, scenario, outcome):
        assert _workflow_step("overlapping")["id"] == "guard"
        fake_gh(_workflow_step("overlapping")["run"], scenario, EVENT=event, RUN_ID="300")
        assert (tmp_path / "github_output").read_text() == f"outcome={outcome}\n"


_SENDER = "JoinALab <alerts@example.com>"


def _alert_script(run_id: str) -> str:
    """The alert step's script with the expressions GitHub fills in filled in."""
    script = str(_workflow_step("Alert operator")["run"])
    script = re.sub(r"\$\{\{ vars\.RESEND_FROM_EMAIL \|\| '[^']*' \}\}", _SENDER, script)
    for expression, value in {"github.server_url": "https://github.com", "github.repository": "o/r",
                              "github.run_id": run_id}.items():
        script = script.replace("${{ " + expression + " }}", value)
    assert "${{" not in script
    return script


def _mails(calls):
    return [json.loads(call[call.index("-d") + 1]) for call in calls if call[0] == "curl"]


class TestAlertStep:
    """The alert step itself, as the runner runs it after a failure or a cancel."""

    def _run(self, fake_gh, tmp_path, *, event, run_id, status, guard, runs, guard_copy=True, **scenario):
        if guard_copy:
            shutil.copy(_SCRIPT, tmp_path / "refresh_rotation.py")
        step = _workflow_step("Alert operator")
        env = {"EVENT": event, "RUN_ID": run_id, "JOB_STATUS": status, "GUARD": guard,
               "RESEND_API_KEY": "not-a-key", "OPERATOR_EMAIL": "operator@example.com", "SHARD": "uw"}
        assert set(step["env"]) <= {*env, "GH_TOKEN", "REPO"}
        result, calls = fake_gh(_alert_script(run_id), {"runs": runs, **scenario}, **env)
        assert result.returncode == 0, result.stdout + result.stderr
        return result, _mails(calls)

    def test_still_runs_on_failure_and_on_cancel(self):
        condition = str(_workflow_step("Alert operator")["if"])
        assert "failure()" in condition and "cancelled()" in condition
        env = _workflow_step("Alert operator")["env"]
        assert env["GUARD"] == "${{ steps.guard.outputs.outcome }}"
        assert env["JOB_STATUS"] == "${{ job.status }}"

    def test_a_manual_run_that_deferred_to_a_scheduled_one_sends_no_mail(self, fake_gh, tmp_path):
        result, mails = self._run(fake_gh, tmp_path, event=MANUAL, run_id="300", status="failure",
                                  guard="defer", runs=_runs((200, SCHEDULED), (300, MANUAL)))
        assert mails == []
        assert "200" in result.stdout + result.stderr

    def test_a_manual_run_a_scheduled_run_cancelled_sends_no_mail(self, fake_gh, tmp_path):
        # The scheduled guard waits for this run to complete, so it is still
        # in progress while this step runs.
        _, mails = self._run(fake_gh, tmp_path, event=MANUAL, run_id="100", status="cancelled",
                             guard="proceed", runs=_runs((100, MANUAL), (200, SCHEDULED)))
        assert mails == []

    def test_a_real_failure_still_mails(self, fake_gh, tmp_path):
        _, mails = self._run(fake_gh, tmp_path, event=MANUAL, run_id="300", status="failure",
                             guard="proceed", runs=_runs((300, MANUAL)))
        (mail,) = mails
        assert mail["to"] == ["operator@example.com"] and mail["from"] == _SENDER
        assert "FAILED" in mail["subject"] and "uw" in mail["subject"]
        assert "https://github.com/o/r/actions/runs/300" in mail["text"]

    def test_a_cancel_that_is_not_the_guards_still_mails(self, fake_gh, tmp_path):
        _, mails = self._run(fake_gh, tmp_path, event=MANUAL, run_id="300", status="cancelled",
                             guard="proceed", runs=_runs((300, MANUAL)))
        assert len(mails) == 1

    @pytest.mark.parametrize("status", ["failure", "cancelled"])
    def test_a_scheduled_run_always_mails(self, fake_gh, tmp_path, status):
        _, mails = self._run(fake_gh, tmp_path, event=SCHEDULED, run_id="200", status=status,
                             guard="cancel", runs=_runs((100, MANUAL), (200, SCHEDULED)))
        assert len(mails) == 1

    def test_a_failed_listing_mails(self, fake_gh, tmp_path):
        _, mails = self._run(fake_gh, tmp_path, event=MANUAL, run_id="300", status="failure",
                             guard="defer", runs=_runs((200, SCHEDULED)), list_fails=True)
        assert len(mails) == 1

    def test_without_the_guards_copy_it_mails(self, fake_gh, tmp_path):
        # The guard could not fetch its script, so it decided nothing.
        _, mails = self._run(fake_gh, tmp_path, event=MANUAL, run_id="300", status="failure",
                             guard="undecided", runs=_runs((200, SCHEDULED)), guard_copy=False)
        assert len(mails) == 1


def _stale_close_snippet() -> str:
    script = str(_workflow_step("merge once required checks pass")["run"])
    start = script.index("STALE=$(")
    end = script.index("done\n", start) + len("done\n")
    return script[start:end].replace("${{ github.run_id }}", "200")


class TestSupersededPrStep:
    def test_only_older_runs_prs_are_closed(self, fake_gh):
        prs = [{"number": 11, "headRefName": "auto/refresh-data-100"},
               {"number": 12, "headRefName": "auto/refresh-data-300"},
               {"number": 13, "headRefName": "fix/other"}]
        result, calls = fake_gh(_stale_close_snippet(), {"prs": prs}, cwd=_REPO)
        assert result.returncode == 0, result.stderr
        assert [call[2] for call in calls if call[:2] == ["pr", "close"]] == ["11"]

    def test_a_failed_listing_closes_nothing(self, fake_gh):
        result, calls = fake_gh(_stale_close_snippet(), {"prs": [], "pr_list_fails": True}, cwd=_REPO)
        assert result.returncode == 0, result.stderr
        assert [call for call in calls if call[:2] == ["pr", "close"]] == []
