"""Which shards a run has actually earned the right to overwrite.

``refresh_rotation --targets`` says what a run is authorized to replace;
this narrows it to what its verdict allows. On 2026-08-08 the two were the
same thing, so one broken UCSB sitemap withheld fifteen other schools'
fresh data.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "publishable_shards.py"
_spec = importlib.util.spec_from_file_location("publishable_shards", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

AUTHORIZED = ["ucsb", "umich", "caltech"]


def _status(publishable):
    return {"release": {"publishable": publishable}}


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


class TestCli:
    def _run(self, authorized, status, tmp_path):
        path = tmp_path / "collector_status.json"
        if status is not None:
            path.write_text(json.dumps(status), encoding="utf-8")
        return subprocess.run(
            [
                sys.executable, str(_SCRIPT),
                "--authorized", authorized,
                "--status-file", str(path),
            ],
            capture_output=True, text=True,
        )

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
