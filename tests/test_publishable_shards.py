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

    def _run(self, tmp_path, status, shard="ucsb,umich,caltech"):
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
            env={**os.environ, "AUTHORIZED": "ucsb,umich,caltech", "SHARD": shard, "MODE": "deep",
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

    def test_the_commit_and_the_pr_use_what_the_step_built(self):
        step = _publish_step()
        script = str(step["run"])
        assert step["id"] == "publish"
        assert 'git commit -m "$MSG"' in script
        assert 'gh pr create --base main --head "$BRANCH" --title "$MSG" --body "$BODY"' in script
        # Built after the narrowing, so every attempt names its own commit.
        assert script.index("--label") < script.index('git commit -m "$MSG"')
