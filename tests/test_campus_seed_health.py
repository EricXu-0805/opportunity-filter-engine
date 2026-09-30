"""The seed-rot canary: what it alerts on, and what it deliberately ignores.

Five configured seeds had 404'd undetected by 2026-08 — Bates, Caltech,
Notre Dame, Northwestern and MIT's Wellesley page. Nothing watched for it
because a dead seed only ever showed up as one line among hundreds in a
refresh log.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import requests

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "check_campus_seeds.py"
_spec = importlib.util.spec_from_file_location("check_campus_seeds", _SCRIPT)
_checker = importlib.util.module_from_spec(_spec)
sys.modules["check_campus_seeds"] = _checker
_spec.loader.exec_module(_checker)


def _school(slug, seeds, program_urls):
    """The registry fields the canary reads: seeds and program URLs."""
    return {
        "school_slug": slug,
        "sources": [{
            "source_name": f"{slug}_programs",
            "seeds": list(seeds),
            "programs": [
                {"key": f"program_{i}", "url": url}
                for i, url in enumerate(program_urls)
            ],
        }],
    }


def _run(monkeypatch, capsys, registry, outcomes, *argv):
    """Run the canary over ``registry`` with every request answered locally.

    ``outcomes`` maps a URL to a status code or an exception to raise; any
    other URL answers 200. Returns the exit code, stdout and each request.
    """
    from src.collectors import schools

    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        outcome = outcomes.get(url, 200)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(status_code=outcome)

    monkeypatch.setattr(schools, "SCHOOL_CONFIGS", registry)
    monkeypatch.setattr(requests, "get", get)
    code = _checker.main(list(argv))
    return code, capsys.readouterr().out, calls


class TestClassify:
    def test_a_missing_page_is_the_only_thing_worth_waking_someone_for(self):
        assert _checker.classify(404) == _checker.GONE
        assert _checker.classify(410) == _checker.GONE

    def test_bot_walls_and_rate_limits_are_not_rot(self):
        """Michigan, JHU and ccrf.uchicago answer 403 to every non-browser.

        Alerting on those means alerting every week forever, which is how a
        check stops being read.
        """
        for status in (401, 403, 406, 429, 451):
            assert _checker.classify(status) == _checker.BLOCKED

    def test_any_success_or_redirect_is_ok(self):
        for status in (200, 202, 301, 302, 308):
            assert _checker.classify(status) == _checker.OK

    def test_a_transport_failure_is_neither_ok_nor_rot(self):
        assert _checker.classify("SSLError") == _checker.UNREACHABLE
        assert _checker.classify("ConnectTimeout") == _checker.UNREACHABLE
        assert _checker.classify(None) == _checker.UNREACHABLE

    def test_a_server_error_is_not_a_missing_page(self):
        assert _checker.classify(500) == _checker.UNREACHABLE
        assert _checker.classify(503) == _checker.UNREACHABLE


class TestSeedInventory:
    def test_every_configured_seed_is_enumerated(self):
        from src.collectors.schools import SCHOOL_CONFIGS

        expected = sum(
            len(source.get("seeds", []) or [])
            for config in SCHOOL_CONFIGS
            for source in config.get("sources", [])
        )
        seeds = _checker.configured_seeds()

        assert len(seeds) == expected
        assert expected > 500, "the registry should not have collapsed"
        assert all(url.startswith("http") for _slug, _src, url in seeds)

    def test_the_five_rotted_urls_are_gone_from_the_configs(self):
        """Pin the successors so a revert reintroduces a known-dead page."""
        urls = {url for _slug, _src, url in _checker.configured_seeds()}
        retired = {
            "https://www.bates.edu/academics/student-research/summer-grants-summary/",
            "https://deans.caltech.edu/Grants_Funding/gwhfund",
            "https://kellogg.nd.edu/opportunities/undergraduate-students/",
            "https://www.tgs.northwestern.edu/success/recruitment/summer-research-opportunity-program/",
            "https://urop.mit.edu/urop-for-wellesley-college-students/",
        }

        assert not (urls & retired)

    def test_the_three_seeds_that_rotted_in_august_and_september_are_gone(self):
        """campus-seed-health failed every run from 2026-08-23 on these three.

        A seed and its program record share the URL, so dropping only the seed
        would silence the canary while the record kept sending students to the
        404. Both have to leave together; Climate+ moved and is pinned to its
        successor, the other two have no successor on their own site.
        """
        from src.collectors.schools import SCHOOL_CONFIGS

        dead = {
            "https://bigdata.duke.edu/participate/climate-plus/",
            "https://undergraduateresearch.duke.edu/program-ii-research-funds",
            "https://www.macalester.edu/serie-center/funding/studentresearch/",
        }
        seeds = {url for _slug, _src, url in _checker.configured_seeds()}
        programs = {
            (config["school_slug"], spec["key"]): spec["url"]
            for config in SCHOOL_CONFIGS
            for source in config.get("sources", [])
            for spec in source.get("programs", [])
        }

        assert not (seeds & dead)
        assert not (set(programs.values()) & dead)
        assert programs[("duke", "climate_plus")] == "https://iid.duke.edu/iid/climate/"
        assert programs[("duke", "climate_plus")] in seeds

    def test_duke_lists_data_plus_and_climate_plus_once_each(self):
        """Each program had a second record pointing at a dead page.

        data_plus sent students to bigdata.duke.edu/data-summer-program/,
        which now redirects to a 404 on iid.duke.edu; it was never a seed,
        so the canary never probed it. climate_plus_x sent them to the
        Nicholas Institute's climate-plus page, which answers curl and
        python-requests with a 404 but a browser user agent, the canary's
        included, with a 200 bot challenge, so the canary read the seed as
        ok. Both duplicates go, along with the dead seed.

        data_plus_x stays and moves to iiD's Data+ page. Its old bigdata URL
        301s to /participate/data-plus/, which answers 200 but is only a
        meta refresh to the iiD+ landing page, so curl -L calls it live
        while a student sees no Data+ page at all.
        """
        from src.collectors.schools import SCHOOL_CONFIGS

        dead = {
            "https://bigdata.duke.edu/data-summer-program/",
            "https://nicholasinstitute.duke.edu/climate-plus",
        }
        seeds = {url for _slug, _src, url in _checker.configured_seeds()}
        programs = {
            (config["school_slug"], spec["key"]): spec["url"]
            for config in SCHOOL_CONFIGS
            for source in config.get("sources", [])
            for spec in source.get("programs", [])
        }

        assert not (seeds & dead)
        assert not (set(programs.values()) & dead)
        assert ("duke", "data_plus") not in programs
        assert ("duke", "climate_plus_x") not in programs
        assert programs[("duke", "data_plus_x")] == "https://iid.duke.edu/iid/data/"
        assert programs[("duke", "data_plus_x")] in seeds

    def test_bates_academic_year_grants_point_at_the_student_research_fund(self):
        """The first run that probed program pages found this one gone.

        academic-year/ answers 404 to every client. It used to 301 to the
        Academic Year Research Grant Information index, which the Wayback
        Machine last saw live on 2026-06-16 and which is a 404 now too. The
        grant the record describes, academic-year research expenses in any
        discipline with a faculty endorsement, is the index's Bates Student
        Research Fund, whose page still answers 200 at its old address and is
        in the academics sitemap. The key stays, so the stored row
        bates-1fa68fe1447a moves in place on the next Bates refresh.
        """
        from src.collectors.schools import SCHOOL_CONFIGS

        dead = "https://www.bates.edu/academics/student-research/academic-year/"
        programs = {
            (config["school_slug"], spec["key"]): spec["url"]
            for config in SCHOOL_CONFIGS
            for source in config.get("sources", [])
            for spec in source.get("programs", [])
        }

        assert dead not in set(programs.values())
        assert programs[("bates", "bates_academic_year_grants")] == (
            "https://www.bates.edu/academics/student-research/"
            "academic-year-research-grant-information/bates-student-research-fund/"
        )


class TestProgramPages:
    """A program record's URL is the page a student lands on.

    Duke's data_plus record pointed at a 404. Its URL was never a seed, so
    the canary, which probed only seeds, never asked.
    """

    def test_a_dead_program_page_fails_the_run_like_a_dead_seed(
        self, monkeypatch, capsys
    ):
        seed = "https://example.edu/research/"
        dead = "https://example.edu/old-summer-program/"

        code, out, _calls = _run(
            monkeypatch, capsys, [_school("example", [seed], [dead])], {dead: 404}
        )

        assert code == 1
        [line] = [line for line in out.splitlines() if dead in line]
        assert line.split()[:4] == ["GONE", "example", "program", "404"]

    def test_a_walled_or_unreachable_program_page_does_not_fail_the_run(
        self, monkeypatch, capsys
    ):
        walled = "https://example.edu/walled/"
        flaky = "https://example.edu/flaky/"

        code, out, _calls = _run(
            monkeypatch,
            capsys,
            [_school("example", [], [walled, flaky])],
            {walled: 403, flaky: requests.ConnectTimeout()},
            "--json",
        )

        assert code == 0
        classes = {row["url"]: row["class"] for row in json.loads(out)["results"]}
        assert classes == {walled: _checker.BLOCKED, flaky: _checker.UNREACHABLE}

    def test_each_url_is_requested_once_even_when_programs_share_it(
        self, monkeypatch, capsys
    ):
        """A program page that is already a seed, or that two programs share
        (across schools too), costs the host one request, not one per
        mention."""
        seeded = "https://example.edu/summer/"
        shared = "https://reu.example.org/"
        registry = [
            _school("example", [seeded], [seeded, shared]),
            _school("other", [], [shared]),
        ]

        code, out, calls = _run(monkeypatch, capsys, registry, {}, "--json")

        assert code == 0
        assert sorted(url for url, _kwargs in calls) == sorted([seeded, shared])
        payload = json.loads(out)
        assert payload["probed"] == 2
        assert {row["url"]: row["kind"] for row in payload["results"]} == {
            seeded: "seed",
            shared: "program",
        }

    def test_program_pages_are_probed_as_politely_as_seeds(
        self, monkeypatch, capsys
    ):
        from src.collectors.campus_graph import HEADERS

        seed = "https://example.edu/research/"
        page = "https://example.edu/program/"

        _code, _out, calls = _run(
            monkeypatch, capsys, [_school("example", [seed], [page])], {}
        )

        assert {url for url, _kwargs in calls} == {seed, page}
        for _url, kwargs in calls:
            assert kwargs["timeout"] == 20
            assert kwargs["headers"] is HEADERS

    def test_every_configured_program_page_is_covered_exactly_once(self):
        from src.collectors.schools import SCHOOL_CONFIGS

        seeds = {url for _slug, _src, url in _checker.configured_seeds()}
        pages = [url for _slug, _src, url in _checker.configured_program_urls()]
        configured = {
            spec["url"]
            for config in SCHOOL_CONFIGS
            for source in config.get("sources", [])
            for spec in source.get("programs", [])
        }

        assert len(pages) == len(set(pages))
        assert not (set(pages) & seeds)
        assert configured <= seeds | set(pages)
        assert len(pages) > 100, "most program pages are not seeds"
