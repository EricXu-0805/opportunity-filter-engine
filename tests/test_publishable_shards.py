"""Which shards a run has actually earned the right to overwrite.

``refresh_rotation --targets`` says what a run is authorized to replace;
this narrows it to what its verdict allows. On 2026-08-08 the two were the
same thing, so one broken UCSB sitemap withheld fifteen other schools'
fresh data.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

from src.collectors.refresh_contract import evaluate_refresh_summary, expected_sources
from tests.test_refresh_contract import _graph_ok, _ok, _summary

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "publishable_shards.py"
_spec = importlib.util.spec_from_file_location("publishable_shards", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

AUTHORIZED = ["ucsb", "umich", "caltech"]


def _status(publishable):
    return {"release": {"publishable": publishable}}


# A partial release as refresh_contract writes it: ucsb's source errored, so
# its shard is withheld while umich and caltech publish.
_UCSB_ERROR = 'source ucsb_faculty reported error: HTTP 500 "Service Unavailable"'
PARTIAL = {"release": {
    "publishable": ["caltech", "umich"],
    "structural_reasons": [],
    "by_unit": {
        "caltech": {"ready": True, "reasons": []},
        "ucsb": {"ready": False, "reasons": [_UCSB_ERROR, "required source missing: ucsb_urca_projects"]},
        "umich": {"ready": True, "reasons": []},
    },
}}


class TestIntersection:
    def test_a_blocked_school_drops_out_and_the_rest_stay(self):
        assert _mod.publishable(
            AUTHORIZED, _status(["caltech", "umich"])
        ) == ["umich", "caltech"]

    def test_authorized_order_is_preserved(self):
        assert _mod.publishable(
            AUTHORIZED, _status(["caltech", "ucsb", "umich"])
        ) == AUTHORIZED

    def test_a_verdict_naming_an_unauthorized_shard_cannot_add_it(self):
        """The verdict narrows; it never widens. Publishing a shard this run
        was not authorized to touch is how a stale work file overwrites a
        school that landed on main mid-scrape."""
        assert _mod.publishable(["umich"], _status(["umich", "yale"])) == ["umich"]

    def test_an_artifact_without_the_field_narrows_nothing(self):
        for status in (None, {}, {"release": {}}, {"release": {"publishable": "all"}}):
            assert _mod.publishable(AUTHORIZED, status) == AUTHORIZED

    def test_a_blocked_run_narrows_to_empty(self):
        assert _mod.publishable(AUTHORIZED, _status([])) == []


class TestWithheld:
    """The data PR and the alert name what the verdict withheld, and why.

    The PR title named the requested shard, so a withheld school read as
    published, and a run that withheld one succeeded without a word.
    """

    def test_each_withheld_shard_carries_the_verdicts_reasons(self):
        assert _mod.withheld(AUTHORIZED, PARTIAL) == [
            ("ucsb", [_UCSB_ERROR, "required source missing: ucsb_urca_projects"]),
        ]

    def test_nothing_is_withheld_when_everything_publishes_or_the_verdict_is_absent(self):
        everything = {"release": {**PARTIAL["release"], "publishable": AUTHORIZED}}
        for status in (everything, None, {}, {"release": {}}):
            assert _mod.withheld(AUTHORIZED, status) == []

    def test_a_withheld_shard_without_its_own_reason_says_so(self):
        status = {"release": {"publishable": ["umich"], "by_unit": {}}}
        assert _mod.withheld(["ucsb", "umich"], status) == [
            ("ucsb", ["the release verdict records no reason"]),
        ]

    def test_a_repeated_reason_is_listed_once_and_on_one_line(self):
        # The 2026-09-05 verdict gave ucb this one reason five times.
        partial = ("required faculty sources were partial: ['ucb_datascience_faculty', 'ucb_econ_faculty', "
                   "'ucb_ling_faculty', 'ucb_scandinavian_faculty', 'ucb_soc_faculty']")
        status = {"release": {"publishable": ["umich"], "by_unit": {"ucb": {"reasons": [
            *[partial] * 5, "source ucb_ling_faculty reported error: HTTP 502\nBad Gateway\r\n",
            "source ucb_ling_faculty reported error: HTTP 502 Bad Gateway", " \n ",
        ]}}}}
        assert _mod.withheld(["ucb", "umich"], status) == [
            ("ucb", [partial, "source ucb_ling_faculty reported error: HTTP 502 Bad Gateway"]),
        ]
        assert _mod.notes(["ucb", "umich"], status).count("\n") == 2

    def test_only_authorized_shards_are_reported(self):
        # A unit outside this run's authorization was never this run's to publish.
        assert _mod.withheld(["umich"], PARTIAL) == []

    def test_the_title_names_only_what_publishes_and_marks_the_withheld(self):
        assert _mod.title_label("ucsb,umich,caltech", AUTHORIZED, PARTIAL) == (
            "published: umich,caltech; withheld: ucsb")

    def test_the_title_is_unchanged_when_nothing_is_withheld(self):
        assert _mod.title_label("ucsb,umich,caltech", AUTHORIZED, _status(AUTHORIZED)) == (
            "shard: ucsb,umich,caltech")
        assert _mod.title_label("", AUTHORIZED, None) == "shard: full"

    def test_a_full_refresh_counts_what_it_publishes(self):
        assert _mod.title_label("", AUTHORIZED, PARTIAL) == "published: 2 of 3 shards; withheld: ucsb"

    def test_the_notes_list_publishable_and_withheld_shards(self):
        assert _mod.notes(AUTHORIZED, PARTIAL) == (
            "Publishable (2): umich, caltech\n"
            "Withheld (1), each keeping the data last committed for it:\n"
            f"- ucsb: {_UCSB_ERROR}; required source missing: ucsb_urca_projects"
        )
        assert _mod.notes(AUTHORIZED, _status(AUTHORIZED)) == ""


def _uiuc_status(**faculty) -> dict:
    """A deep uiuc+uw run's status as refresh_contract writes its verdict:
    uw_faculty read zero rows, and uiuc_faculty is as ``faculty`` says."""
    sources = {key: _ok(1) for key in expected_sources({"uiuc"}, national=False, deep=True)}
    sources["uiuc_faculty"].update(stale_deactivation_authorized=False, **faculty)
    sources["deactivate_stale_faculty"] = {
        "status": "ok", "skipped_partial_scrape": [], "deactivation_not_authorized": ["uiuc_faculty"]}
    sources["campus_graph:uw"] = _graph_ok()
    sources["uw_faculty"] = {"status": "suspicious_zero", "fetched": 0, "suspicious_zero_baseline": 90}
    summary = _summary({"uiuc", "uw"}, sources)
    return {**summary, "release": evaluate_refresh_summary(
        summary, schools={"uiuc", "uw"}, national=False, deep=True)}


_ONE_DEPARTMENT = dict(empty_departments=["Department of Tides"],
                       empty_department_baselines={"Department of Tides": 38})


def _national_status(**sro) -> dict:
    """A deep national run's status with uiuc_sro as ``sro`` says."""
    sources = {key: _graph_ok() for key in expected_sources(None, national=True, deep=True)}
    sources.update(nsf_reu=_ok(128), simplify_internships=_ok(5326), uiuc_sro=sro)
    summary = _summary(None, sources, national=True)
    return {**summary, "release": evaluate_refresh_summary(
        summary, schools=None, national=True, deep=True)}


# uiuc_sro as refresh_all labels a list whose every page failed while the corpus holds its rows.
_UNREAD_LIST = dict(status="suspicious_zero", fetched=0, suspicious_zero_baseline=285,
                    list_pages_attempted=15, list_pages_loaded=0, list_pages_failed=15,
                    list_complete=False, list_errors=[{"reason": "fetch_failed"}])


# simplify_internships as refresh_all labels a list of 2,056 internships read
# while the corpus holds 5,133 open: merged, nothing retired, check incomplete.
_COLLAPSED_LIST = dict(status="partial_failure", fetched=2056, new=11, updated=2045,
                       list_errors=["the list holds 2056 internships and the corpus 5133 open ones; "
                                    "nothing was retired on this read"],
                       collapsed_list_baseline=5133, incomplete_reasons=["list_errors"],
                       error="Source check incomplete: list_errors")
_COLLAPSED_NOTE = ("Published from a list under half the size of what is held open (1); "
                   "nothing was retired and the rows it listed were updated:\n"
                   "- national: simplify_internships: 2056 listed, 5133 held open")


class TestUnread:
    """What a shard published without is named to the PR and the alert.

    An empty UIUC department and an unread national list each withheld their
    shard until 2026-11-16, and a withheld shard is mailed. Their shards
    publish now, which on its own would have ended the mail.
    """

    def test_an_empty_department_of_a_published_school_is_named(self):
        status = _uiuc_status(**_ONE_DEPARTMENT)
        assert status["release"]["publishable"] == ["uiuc", "uw"]
        # uw_faculty's zero rows are not: a school's zero-row source never sent mail.
        assert _mod.unread(["uiuc", "uw"], status) == [
            ("uiuc", "uiuc_faculty: Department of Tides: 0 records, previously 38")]
        assert _mod.unread_notes(["uiuc", "uw"], status) == (
            "Published without a fresh read (1), each keeping the rows it had:\n"
            "- uiuc: uiuc_faculty: Department of Tides: 0 records, previously 38")
        assert _mod.notes(["uiuc", "uw"], status) == ""

    def test_an_unread_source_of_the_published_national_shard_is_named(self):
        status = _national_status(**_UNREAD_LIST)
        assert status["release"]["publishable"] == ["national"]
        assert _mod.unread(["national"], status) == [("national", "uiuc_sro: 0 records, previously 285")]

    def test_nothing_is_named_when_every_source_was_read_or_the_verdict_is_absent(self):
        assert _mod.unread(["uiuc", "uw"], _uiuc_status()) == []
        assert _mod.unread(["national"], _national_status(**_ok(288))) == []
        for status in (None, {}, {"release": {}}, _status(AUTHORIZED), PARTIAL):
            assert _mod.unread(AUTHORIZED, status) == []
            assert _mod.unread_notes(AUTHORIZED, status) == ""

    def test_a_withheld_shard_is_reported_by_its_reasons_alone(self):
        status = _uiuc_status(**_ONE_DEPARTMENT, status="error", error="js: component failed")
        assert status["release"]["publishable"] == ["uw"]
        assert _mod.unread(["uiuc", "uw"], status) == []
        assert _mod.withheld(["uiuc", "uw"], status) == [
            ("uiuc", ["source uiuc_faculty reported error: js: component failed"])]

    def test_only_authorized_shards_are_reported(self):
        assert _mod.unread(["uw"], _uiuc_status(**_ONE_DEPARTMENT)) == []

    def _national_day(self, **sources) -> dict:
        status = _national_status(**_ok(288))
        status["sources"].update(sources)
        status["release"] = evaluate_refresh_summary(status, schools=None, national=True, deep=True)
        return status

    def test_an_internship_list_under_half_its_size_is_named_with_its_counts(self):
        """Such a read merges its rows, retires nothing and publishes. The
        verdict calls it a partial failure, which neither the PR nor the
        alert named: a list cut to 40% published as an ordinary day."""
        status = self._national_day(simplify_internships=dict(_COLLAPSED_LIST))
        assert status["release"]["publishable"] == ["national"]
        assert _mod.collapsed_lists(["national"], status) == [
            ("national", "simplify_internships: 2056 listed, 5133 held open")]
        assert _mod.unread(["national"], status) == []
        assert _mod.unread_notes(["national"], status) == _COLLAPSED_NOTE
        # Beside a source that read nothing, each stands under its own heading.
        status = self._national_day(simplify_internships=dict(_COLLAPSED_LIST), uiuc_sro=dict(_UNREAD_LIST))
        assert _mod.unread_notes(["national"], status) == (
            "Published without a fresh read (1), each keeping the rows it had:\n"
            "- national: uiuc_sro: 0 records, previously 285\n\n" + _COLLAPSED_NOTE)

    def test_no_other_partial_read_and_no_withheld_shard_is_named_as_a_collapsed_list(self):
        # A list that lost one page is a partial failure too, and was never mailed.
        lost_a_page = dict(status="partial_failure", fetched=280, list_pages_attempted=15, list_pages_loaded=14,
                           list_pages_failed=1, list_complete=False, list_errors=[{"reason": "fetch_failed"}])
        status = self._national_day(uiuc_sro=lost_a_page)
        assert {"kind": "partial_failure", "source": "uiuc_sro",
                "detail": "list_pages_failed, list_incomplete, list_errors"} in status["release"]["degradations"]
        assert _mod.unread_notes(["national"], status) == ""
        # A withheld shard is reported by its reasons.
        status = self._national_day(simplify_internships=dict(_COLLAPSED_LIST),
                                    nsf_reu={"status": "error", "error": "HTTP 500"})
        assert status["release"]["publishable"] == []
        assert _mod.unread_notes(["national"], status) == ""


class TestCli:
    def _run(self, authorized, status, tmp_path, *extra):
        path = tmp_path / "collector_status.json"
        if status is not None:
            path.write_text(json.dumps(status), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable, str(_SCRIPT),
                "--authorized", authorized,
                "--status-file", str(path),
                *extra,
            ],
            capture_output=True, text=True,
        )

    def test_prints_the_title_label_and_the_notes(self, tmp_path):
        r = self._run("ucsb,umich,caltech", PARTIAL, tmp_path, "--label", "--shard", "ucsb,umich,caltech")
        assert (r.returncode, r.stdout) == (0, "published: umich,caltech; withheld: ucsb\n"), r.stderr
        r = self._run("ucsb,umich,caltech", PARTIAL, tmp_path, "--notes")
        assert r.returncode == 0, r.stderr
        assert r.stdout.splitlines()[-1] == f"- ucsb: {_UCSB_ERROR}; required source missing: ucsb_urca_projects"
        everything = _status(["uw", "wisc"])
        r = self._run("uw,wisc", everything, tmp_path, "--notes")
        assert (r.returncode, r.stdout) == (0, "")
        r = self._run("uw,wisc", everything, tmp_path, "--label", "--shard", "")
        assert (r.returncode, r.stdout) == (0, "shard: full\n")
        assert self._run("uw,wisc", everything, tmp_path, "--label").returncode != 0

    def test_prints_what_published_shards_went_without(self, tmp_path):
        r = self._run("uiuc,uw", _uiuc_status(**_ONE_DEPARTMENT), tmp_path, "--unread")
        assert (r.returncode, r.stdout) == (0, _mod.unread_notes(
            ["uiuc", "uw"], _uiuc_status(**_ONE_DEPARTMENT)) + "\n"), r.stderr
        r = self._run("uiuc,uw", _uiuc_status(), tmp_path, "--unread")
        assert (r.returncode, r.stdout) == (0, "")

    def test_prints_the_narrowed_list(self, tmp_path):
        r = self._run("ucsb,umich,caltech", _status(["umich", "caltech"]), tmp_path)
        assert r.returncode == 0
        assert r.stdout.strip() == "umich,caltech"

    def test_a_missing_artifact_passes_the_authorized_set_through(self, tmp_path):
        r = self._run("uw,wisc", None, tmp_path)
        assert r.returncode == 0
        assert r.stdout.strip() == "uw,wisc"

    def test_publishing_nothing_fails_loudly_rather_than_printing_empty(
        self, tmp_path
    ):
        r = self._run("uw,wisc", _status([]), tmp_path)
        assert r.returncode != 0
        assert "publishes none" in r.stderr
        assert r.stdout.strip() == ""


class TestWorkflowWiring:
    def test_the_split_step_narrows_targets_by_the_verdict(self):
        """Authorization and entitlement are different questions.

        refresh_rotation --targets says which shards the run may replace;
        without this second call the split writes all of them regardless of
        whether their verdict earned it.
        """
        text = (_REPO / ".github/workflows/refresh-data.yml").read_text()

        assert "publishable_shards.py --authorized" in text
        # The narrowed value, not the raw authorization, is what reaches split.
        narrow = text.index("publishable_shards.py --authorized")
        split = text.index("shard_corpus.py split --only-shards")
        rotation = text.index("refresh_rotation.py \\\n              --schools")
        assert rotation < narrow < split


_PUBLISH_STEP = "merge once required checks pass"


def _publish_step() -> dict:
    workflow = yaml.safe_load((_REPO / ".github/workflows/refresh-data.yml").read_text())
    return next(step for step in workflow["jobs"]["refresh"]["steps"]
                if _PUBLISH_STEP in str(step.get("name", "")))


def _naming_snippet() -> str:
    """The publish step's script from the narrowing to the split."""
    script = str(_publish_step()["run"])
    start = script.index('TARGETS=$(python3 scripts/publishable_shards.py --authorized "$AUTHORIZED")')
    end = script.index("python3 scripts/shard_corpus.py split", start)
    return textwrap.dedent(script[start:end])


def _outputs(text: str) -> dict:
    """A $GITHUB_OUTPUT file read as the runner reads it."""
    values, lines = {}, text.splitlines()
    while lines:
        line = lines.pop(0)
        if "<<" in line:
            name, end = line.split("<<", 1)
            body = lines[:lines.index(end)]
            values[name] = "\n".join(body)
            del lines[:len(body) + 1]
        else:
            name, value = line.split("=", 1)
            values[name] = value
    return values


class TestThePrNamesWhatItPublishes:
    """The publish step's own lines, run under bash against a run's verdict."""

    def _run(self, tmp_path, status, shard="ucsb,umich,caltech", authorized="ucsb,umich,caltech", daily=""):
        (tmp_path / "scripts").mkdir()
        shutil.copy(_SCRIPT, tmp_path / "scripts" / "publishable_shards.py")
        (tmp_path / "data" / "processed").mkdir(parents=True)
        (tmp_path / "data" / "processed" / "collector_status.json").write_text(json.dumps(status))
        output = tmp_path / "github_output"
        output.write_text("")
        result = subprocess.run(
            ["bash", "-c", "set -euo pipefail\n" + _naming_snippet()
             + 'printf %s "$TARGETS" > targets; printf %s "$MSG" > title; printf %s "$BODY" > body\n'],
            cwd=tmp_path, capture_output=True, text=True,
            env={**os.environ, "AUTHORIZED": authorized, "SHARD": shard, "MODE": "deep", "DAILY": daily,
                 "COUNTS": "10 total, 5 emails, 1 inactive, deep mode", "GITHUB_OUTPUT": str(output)},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        read = {name: (tmp_path / name).read_text() for name in ("targets", "title", "body")}
        return read, output.read_text()

    def test_a_partial_release_titles_the_published_and_reports_the_withheld(self, tmp_path):
        read, output = self._run(tmp_path, PARTIAL)
        assert read["targets"] == "umich,caltech"
        assert read["title"] == ("chore: auto-refresh opportunity data (10 total, 5 emails, 1 inactive, "
                                 "deep mode, published: umich,caltech; withheld: ucsb)")
        notes = _mod.notes(AUTHORIZED, PARTIAL)
        assert read["body"] == (
            "Automated deep data refresh (shard: ucsb,umich,caltech). Merges automatically once "
            "Backend + Frontend checks pass.\n\n" + notes)
        # The alert step reads this output.
        assert _outputs(output) == {"withheld": notes}

    def test_the_withheld_output_ends_at_a_marker_no_run_repeats(self, tmp_path):
        # A fixed marker on a line of the verdict's error text would end the value there.
        markers = set()
        for attempt in ("a", "b"):
            (tmp_path / attempt).mkdir()
            _, output = self._run(tmp_path / attempt, PARTIAL)
            markers.add(output.split("\n", 1)[0].split("<<", 1)[1])
        assert len(markers) == 2 and "WITHHELD_EOF" not in markers

    def test_a_full_release_keeps_the_old_title_and_body_and_reports_nothing(self, tmp_path):
        read, output = self._run(tmp_path, _status(AUTHORIZED))
        assert read["title"] == ("chore: auto-refresh opportunity data (10 total, 5 emails, 1 inactive, "
                                 "deep mode, shard: ucsb,umich,caltech)")
        assert read["body"] == ("Automated deep data refresh (shard: ucsb,umich,caltech). Merges "
                                "automatically once Backend + Frontend checks pass.")
        assert output == ""

    def test_a_full_release_that_went_without_a_department_reports_it(self, tmp_path):
        status = _uiuc_status(**_ONE_DEPARTMENT)
        read, output = self._run(tmp_path, status, shard="uiuc,uw", authorized="uiuc,uw")
        unread = _mod.unread_notes(["uiuc", "uw"], status)
        assert read["targets"] == "uiuc,uw"
        assert read["title"].endswith("deep mode, shard: uiuc,uw)")
        assert read["body"] == ("Automated deep data refresh (shard: uiuc,uw). Merges "
                                "automatically once Backend + Frontend checks pass.\n\n" + unread)
        # The alert step reads this output; nothing is withheld, so that one is unset.
        assert _outputs(output) == {"unread": unread}

    def test_a_partial_release_reports_the_withheld_and_what_the_rest_went_without(self, tmp_path):
        status = _uiuc_status(**_ONE_DEPARTMENT)
        status["sources"]["uw_faculty"] = {"status": "error", "error": "HTTP 500"}
        status["release"] = evaluate_refresh_summary(
            status, schools={"uiuc", "uw"}, national=False, deep=True)
        read, output = self._run(tmp_path, status, shard="uiuc,uw", authorized="uiuc,uw")
        notes, unread = _mod.notes(["uiuc", "uw"], status), _mod.unread_notes(["uiuc", "uw"], status)
        assert read["targets"] == "uiuc"
        assert read["body"].endswith("checks pass.\n\n" + notes + "\n\n" + unread)
        assert _outputs(output) == {"withheld": notes, "unread": unread}

    def _day_with_the_internship_list(self, tmp_path, **list_read):
        """The publish step's lines for a uw,wisc day that also read the internship list as ``list_read``."""
        sources = {"campus_graph:uw": _graph_ok(), "campus_graph:wisc": _graph_ok(),
                   "uw_faculty": _ok(100), "wisc_faculty": _ok(100),
                   "simplify_internships": list_read or _ok(5140)}
        status = _summary({"uw", "wisc"}, sources)
        status["request"]["national_sources"] = ["simplify_internships"]
        status["release"] = evaluate_refresh_summary(
            status, schools={"uw", "wisc"}, national=False, deep=True, national_sources={"simplify_internships"})
        read, output = self._run(tmp_path, status, shard="uw,wisc", authorized="uw,wisc,national",
                                 daily="simplify_internships")
        return read, _outputs(output), status

    def test_a_day_that_also_read_the_internship_list_says_so_in_the_title_and_the_body(self, tmp_path):
        read, outputs, _ = self._day_with_the_internship_list(tmp_path)
        assert read["targets"] == "uw,wisc,national"
        assert read["title"] == ("chore: auto-refresh opportunity data (10 total, 5 emails, 1 inactive, "
                                 "deep mode, shard: uw,wisc + simplify_internships)")
        assert read["body"] == ("Automated deep data refresh (shard: uw,wisc + simplify_internships). Merges "
                                "automatically once Backend + Frontend checks pass.")
        assert outputs == {}

    def test_an_internship_list_that_failed_is_named_withheld_and_the_schools_publish(self, tmp_path):
        read, outputs, status = self._day_with_the_internship_list(
            tmp_path, status="error", error="list answered 503")
        assert read["targets"] == "uw,wisc"
        assert read["title"].endswith("deep mode, published: uw,wisc; withheld: national)")
        notes = ("Publishable (2): uw, wisc\nWithheld (1), each keeping the data last committed for it:\n"
                 "- national: source simplify_internships reported error: list answered 503")
        assert read["body"].endswith("(shard: uw,wisc + simplify_internships). Merges automatically once "
                                     "Backend + Frontend checks pass.\n\n" + notes)
        assert outputs == {"withheld": notes}

    def test_an_internship_list_that_read_empty_is_named_unread_and_everything_publishes(self, tmp_path):
        read, outputs, _ = self._day_with_the_internship_list(
            tmp_path, status="suspicious_zero", fetched=0, suspicious_zero_baseline=5133)
        unread = ("Published without a fresh read (1), each keeping the rows it had:\n"
                  "- national: simplify_internships: 0 records, previously 5133")
        assert read["targets"] == "uw,wisc,national"
        assert read["title"].endswith("deep mode, shard: uw,wisc + simplify_internships)")
        assert read["body"].endswith("checks pass.\n\n" + unread)
        assert outputs == {"unread": unread}

    def test_an_internship_list_under_half_its_size_is_reported_and_everything_publishes(self, tmp_path):
        read, outputs, _ = self._day_with_the_internship_list(tmp_path, **_COLLAPSED_LIST)
        assert read["targets"] == "uw,wisc,national"
        assert read["title"].endswith("deep mode, shard: uw,wisc + simplify_internships)")
        assert read["body"].endswith("checks pass.\n\n" + _COLLAPSED_NOTE)
        # The alert step runs on this output and mails it.
        assert outputs == {"unread": _COLLAPSED_NOTE}

    def test_the_commit_and_the_pr_use_what_the_step_built(self):
        step = _publish_step()
        script = str(step["run"])
        assert step["id"] == "publish"
        assert 'git commit -m "$MSG"' in script
        assert 'gh pr create --base main --head "$BRANCH" --title "$MSG" --body "$BODY"' in script
        # Built after the narrowing, so every attempt names its own commit.
        assert script.index("--label") < script.index('git commit -m "$MSG"')
