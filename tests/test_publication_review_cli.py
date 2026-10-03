"""scripts/remediate_publications.py run through its real CLI: the dry runs, and
the `review` command that settles the manual-review queue.

The driver's other cases live in tests/test_publication_remediation.py. These
are here because that file is being edited on another branch.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from src.publication_remediation import (
    DISPOSITION_AMBIGUOUS,
    DISPOSITION_NEEDS_REVIEW,
    DISPOSITION_REMOVED,
    DISPOSITION_VERIFIED,
    NEEDS_REVIEW,
    QUEUED,
    REVIEWED,
    VERIFIED_COMPLETE,
    Ledger,
    awaits_review,
    invalidate_record,
    unit_for,
)
from src.publication_trust import (
    CURRENT_WORKS_GATE,
    VERIFIED_AUTHOR_ID,
    record_works_gate,
    verified_recent_works,
    works_are_verified,
)

_spec = importlib.util.spec_from_file_location(
    "remediate_publications_review",
    Path(__file__).resolve().parents[1] / "scripts" / "remediate_publications.py",
)
driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(driver)

_OLD_GATE = CURRENT_WORKS_GATE - 1
_STRANGERS_WORKS = [
    {"title": "SearchAuditor: Auditing Failures in Long-Horizon Search Agents", "year": 2026},
    {"title": "Spectral-Spatial Networks for Geochemical Anomalies", "year": 2026},
]


def faculty(rid="fac-1", *, name="Zhi-Pei Liang", school="uiuc",
            status=VERIFIED_AUTHOR_ID, gate=_OLD_GATE, works=_STRANGERS_WORKS):
    md: dict = {"is_active": True, "inferred_fields": {"keywords": "derived:openalex_topics"}}
    if works is not None:
        md["recent_works"] = [dict(w) for w in works]
    if status is not None:
        md["publication_attribution_status"] = status
    if gate is not None:
        md["works_gate"] = gate
    url = f"https://ece.illinois.edu/about/directory/faculty/{rid}"
    return {
        "id": rid,
        "source_type": "faculty_research",
        "title": f"Research with Prof. {name}",
        "opportunity_type": "research",
        "pi_name": name,
        "school": school,
        "department": "Electrical & Computer Engineering",
        "url": url,
        "source_url": url,
        "keywords": ["magnetic resonance imaging"],
        "eligibility": {},
        "application": {},
        "metadata": md,
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(monkeypatch, shards, *argv):
    """The real CLI over in-memory shards. Returns (rc, the shard sets saved)."""
    written: list[list[str]] = []
    monkeypatch.setattr(driver, "load_shards", lambda: shards)
    monkeypatch.setattr(
        driver, "save_shards",
        lambda _shards, touched: written.append(sorted(touched)) or sorted(touched),
    )
    return driver.main(list(argv)), written


def _seeded_ledger(tmp_path) -> Path:
    """A ledger that already holds one settled unit, as the committed one does."""
    path = tmp_path / "ledger.jsonl"
    record = faculty("already-settled", gate=CURRENT_WORKS_GATE)
    unit = unit_for(record)
    ledger = Ledger(path)
    ledger.claim(unit)
    ledger.settle(unit, record, DISPOSITION_VERIFIED)
    return path


# ---------------------------------------------------------------------------
# Dry runs write nothing — the committed ledger included
# ---------------------------------------------------------------------------

class TestDryRunsLeaveTheLedgerAlone:
    """`invalidate` and `apply` without --save used to append QUEUED, STARTED and
    HARVEST_SUCCEEDED events to data/processed/publication_remediation_ledger.jsonl,
    a committed file, before their dry-run exit. A dry run of apply against a copy
    of the real ledger on 83940c19 added 8 lines for the 4 withdrawn uiuc units."""

    def test_invalidate_without_save_leaves_the_ledger_byte_identical(self, tmp_path, monkeypatch):
        ledger = _seeded_ledger(tmp_path)
        before = _sha256(ledger)

        rc, written = _run(monkeypatch, {"uiuc": [faculty("old-1"), faculty("old-2")]},
                           "--ledger", str(ledger), "invalidate")

        assert rc == 0
        assert written == []
        assert _sha256(ledger) == before

    def test_invalidate_with_save_still_records_the_queue(self, tmp_path, monkeypatch):
        """The control: the same run with --save appends what the dry run held back."""
        ledger = _seeded_ledger(tmp_path)

        rc, written = _run(monkeypatch, {"uiuc": [faculty("old-1"), faculty("old-2")]},
                           "--ledger", str(ledger), "invalidate", "--save")

        assert rc == 0
        assert written == [["uiuc"]]
        queued = [e for e in Ledger(ledger).events() if e["status"] == QUEUED]
        assert [e["professor_id"] for e in queued] == ["old-1", "old-2"]

    def test_a_dry_run_does_not_create_a_missing_ledger(self, tmp_path, monkeypatch):
        ledger = tmp_path / "absent.jsonl"
        rc, _ = _run(monkeypatch, {"uiuc": [faculty("old-1")]},
                     "--ledger", str(ledger), "invalidate")
        assert rc == 0
        assert not ledger.exists()

    @staticmethod
    def _apply_files(tmp_path, record):
        mapping = tmp_path / "works.json"
        mapping.write_text(json.dumps({
            unit_for(record)["person_key"]: {
                "author_id": "A5000",
                "works": [{"title": "Real MRI Paper", "year": 2026}],
            },
        }), encoding="utf-8")
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps({
            "works_gate": CURRENT_WORKS_GATE,
            "schools_requested": ["uiuc"],
            "schools_answered": ["uiuc"],
        }), encoding="utf-8")
        return mapping, manifest

    def test_apply_without_save_leaves_the_ledger_byte_identical(self, tmp_path, monkeypatch, capsys):
        ledger = _seeded_ledger(tmp_path)
        before = _sha256(ledger)
        record = faculty()
        invalidate_record(record)
        mapping, manifest = self._apply_files(tmp_path, record)

        rc, written = _run(monkeypatch, {"uiuc": [record]}, "--ledger", str(ledger),
                           "apply", str(mapping), "--manifest", str(manifest))

        assert rc == 0
        assert written == []
        assert _sha256(ledger) == before
        # It still decided what a real run would, and said so.
        out = capsys.readouterr()
        assert "claimed 1 unit(s)" in out.err
        assert json.loads(out.out[out.out.index("{"):]) == {DISPOSITION_VERIFIED: 1}

    def test_apply_with_save_settles_the_unit(self, tmp_path, monkeypatch):
        ledger = _seeded_ledger(tmp_path)
        record = faculty()
        invalidate_record(record)
        mapping, manifest = self._apply_files(tmp_path, record)

        rc, written = _run(monkeypatch, {"uiuc": [record]}, "--ledger", str(ledger),
                           "apply", str(mapping), "--manifest", str(manifest), "--save")

        assert rc == 0
        assert written == [["uiuc"]]
        assert [w["title"] for w in verified_recent_works(record)] == ["Real MRI Paper"]
        entry = Ledger(ledger).index()[unit_for(record)["idempotency_key"]]
        assert (entry["status"], entry["result"]) == (VERIFIED_COMPLETE, DISPOSITION_VERIFIED)
        assert entry["attempt_count"] == 1

    def test_a_dry_run_does_not_count_as_an_attempt(self, tmp_path, monkeypatch):
        """A dry run's STARTED event used to make the real run that followed it
        read as a retry (attempt_count 2, retry_count 1)."""
        ledger = _seeded_ledger(tmp_path)

        def withdrawn():   # each run reads the shards afresh, as the CLI does
            record = faculty()
            invalidate_record(record)
            return record

        mapping, manifest = self._apply_files(tmp_path, withdrawn())
        args = ("--ledger", str(ledger), "apply", str(mapping), "--manifest", str(manifest))

        _run(monkeypatch, {"uiuc": [withdrawn()]}, *args)
        rc, written = _run(monkeypatch, {"uiuc": [withdrawn()]}, *args, "--save")

        assert rc == 0
        assert written == [["uiuc"]]
        assert Ledger(ledger).report()["retry_count"] == 0

    def test_staged_events_are_visible_to_the_run_that_staged_them(self, tmp_path):
        """A dry run must decide exactly what a real run would, so its own reads
        replay what it held back: a unit it claimed is claimed for the rest of
        the run."""
        path = tmp_path / "ledger.jsonl"
        ledger = Ledger(path, dry_run=True)
        record = faculty()
        unit = unit_for(record)

        assert ledger.claim(unit)
        ledger.settle(unit, record, DISPOSITION_VERIFIED)

        assert ledger.is_complete(unit["idempotency_key"])
        assert not ledger.claim(unit)
        assert not path.exists()
        assert Ledger(path).index() == {}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Nothing in this file may reach OpenAlex. Patched at ``_get`` rather than
    ``requests.get`` because ``_get`` swallows exceptions and retries."""
    from src.collectors import openalex_enrich as oa

    def refuse(*_a, **_k):
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(oa, "_get", refuse)


# ---------------------------------------------------------------------------
# review: settling the manual-review queue
# ---------------------------------------------------------------------------
# On 83940c19 the committed ledger holds 33 units settled `ambiguous` (carleton
# 8, middlebury 8, swarthmore 7, coloradocollege 6, grinnell 4), the ops scan
# files them as one manual_review incident, and no command could record what a
# person decided about any of them: the sticky-terminal rule in Ledger.index()
# ignored every event after `verified_complete`.

class _Disk:
    """The shards as the CLI sees them: every load reads a fresh copy and only
    a save changes what the next run reads, so a dry run cannot leak."""

    def __init__(self, shards: dict[str, list[dict]]):
        self.shards = shards
        self.writes: list[list[str]] = []

    def load(self):
        return copy.deepcopy(self.shards)

    def save(self, shards, touched):
        for slug in touched:
            self.shards[slug] = copy.deepcopy(shards[slug])
        self.writes.append(sorted(touched))
        return sorted(touched)

    def record(self, rid: str) -> dict:
        return next(r for records in self.shards.values() for r in records if r["id"] == rid)


def _cli(monkeypatch, disk: _Disk, *argv) -> int:
    monkeypatch.setattr(driver, "load_shards", disk.load)
    monkeypatch.setattr(driver, "save_shards", disk.save)
    return driver.main(list(argv))


_AUTHOR = "A5000777"
_AUTHOR_RECORD = {
    "id": f"https://openalex.org/{_AUTHOR}",
    "display_name": "Zhi-Pei Liang",
    "works_count": 120,
    "topics": [
        {"display_name": "Magnetic Resonance Imaging", "field": {"display_name": "Medicine"}},
        {"display_name": "Image Reconstruction", "field": {"display_name": "Engineering"}},
    ],
}


def _raw(title, year, field):
    return {"display_name": title, "publication_year": year,
            "primary_topic": {"field": {"display_name": field}}}


_AUTHOR_WORKS = [
    _raw("Subspace Imaging with Learned Priors", 2026, "Medicine"),
    _raw("Introduction", 2026, "Medicine"),                        # front matter
    _raw("Geochemical Anomaly Detection at Scale", 2025, "Earth and Planetary Sciences"),
    _raw("Fast Spectroscopic Imaging", 2024, "Engineering"),
]


@pytest.fixture
def openalex(monkeypatch):
    """OpenAlex as the review command asks it: one author, one works batch.
    ``calls`` records each request; tests change the answers through it."""
    from src.collectors import openalex_enrich as oa

    state = {"author": dict(_AUTHOR_RECORD), "works": {_AUTHOR: list(_AUTHOR_WORKS)}, "calls": []}

    def fake_get(params, url=oa._API, timeout=20):
        state["calls"].append(url)
        aid = url.rsplit("/", 1)[-1]
        author = state["author"]
        if state.get("merged_into"):
            return {**author, "id": f"https://openalex.org/{state['merged_into']}"}
        return dict(author) if author and author["id"].endswith("/" + aid) else {}

    def fake_works(author_ids, **_kwargs):
        state["calls"].append(("works", tuple(author_ids)))
        return {a: list(state["works"].get(a) or []) for a in author_ids if state["works"].get(a)}

    monkeypatch.setattr(oa, "_get", fake_get)
    monkeypatch.setattr(oa, "works_for_authors", fake_works)
    monkeypatch.setattr(oa, "_warned_429", False)
    return state


@pytest.fixture
def queue(tmp_path, monkeypatch):
    """Four withdrawn professors taken through the real invalidate and apply:
    two the roster could not resolve (ambiguous), one whose answer carried no
    author id (needs_review), and one the gate re-verified."""
    records = [
        faculty("amb-1", name="Zhi-Pei Liang"),
        faculty("amb-2", name="Ada Byron"),
        faculty("nr-1", name="Grace Hopper"),
        faculty("ok-1", name="Alan Turing"),
    ]
    disk = _Disk({"uiuc": records})
    ledger = tmp_path / "ledger.jsonl"
    assert _cli(monkeypatch, disk, "--ledger", str(ledger), "invalidate", "--save") == 0

    key = {r["id"]: unit_for(r)["person_key"] for r in disk.shards["uiuc"]}
    mapping = tmp_path / "works.json"
    mapping.write_text(json.dumps({
        key["ok-1"]: {"author_id": "A5000", "works": [{"title": "Real Paper", "year": 2026}]},
        key["nr-1"]: [{"title": "A Name-Matched Paper", "year": 2026}],
    }), encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"works_gate": CURRENT_WORKS_GATE,
                                    "schools_answered": ["uiuc"]}), encoding="utf-8")
    assert _cli(monkeypatch, disk, "--ledger", str(ledger), "apply", str(mapping),
                "--manifest", str(manifest), "--save") == 0
    disk.writes.clear()
    return disk, ledger


def _waiting(ledger: Path) -> list[str]:
    return sorted(row["professor_id"] for row in Ledger(ledger).manual_review_queue())


def _review(monkeypatch, disk, ledger, *argv) -> int:
    return _cli(monkeypatch, disk, "--ledger", str(ledger), "review", *argv)


class TestTheQueueAsThePipelineLeavesIt:
    def test_the_fixture_is_the_state_the_ledger_is_in(self, queue):
        disk, ledger = queue
        index = Ledger(ledger).index()
        results = {e["professor_id"]: (e["status"], e["result"]) for e in index.values()}
        assert results == {
            "amb-1": (VERIFIED_COMPLETE, DISPOSITION_AMBIGUOUS),
            "amb-2": (VERIFIED_COMPLETE, DISPOSITION_AMBIGUOUS),
            "nr-1": (NEEDS_REVIEW, DISPOSITION_NEEDS_REVIEW),
            "ok-1": (VERIFIED_COMPLETE, DISPOSITION_VERIFIED),
        }
        assert _waiting(ledger) == ["amb-1", "amb-2", "nr-1"]
        assert "recent_works" not in disk.record("amb-1")["metadata"]


class TestReviewList:
    def test_lists_every_unit_awaiting_a_verdict_with_its_evidence(self, queue, monkeypatch, capsys):
        disk, ledger = queue
        before = _sha256(ledger)

        assert _review(monkeypatch, disk, ledger) == 0

        listing = json.loads(capsys.readouterr().out)
        assert listing["awaiting_review"] == 3
        rows = {row["professor_id"]: row for row in listing["units"]}
        assert sorted(rows) == ["amb-1", "amb-2", "nr-1"]
        row = rows["amb-1"]
        assert row["unit"] == f"amb-1@gate{CURRENT_WORKS_GATE}"
        assert row["reason"] == DISPOSITION_AMBIGUOUS
        assert (row["pi_name"], row["school"]) == ("Zhi-Pei Liang", "uiuc")
        assert row["department"] == "Electrical & Computer Engineering"
        assert row["url"].endswith("/amb-1")
        # The papers the retired gate had given them: the question is whether
        # those were theirs, so the evidence comes with the unit.
        assert row["candidate_papers"] == [f"{w['title']}|{w['year']}" for w in _STRANGERS_WORKS]
        assert rows["nr-1"]["reason"] == DISPOSITION_NEEDS_REVIEW
        assert _sha256(ledger) == before
        assert disk.writes == []


class TestRemovedVerdict:
    def test_closes_the_unit_and_keeps_the_record_untrusted(self, queue, monkeypatch):
        disk, ledger = queue

        rc = _review(monkeypatch, disk, ledger, "amb-2", "--removed",
                     "--reviewer", "eric", "--note", "two namesakes, neither in ECE", "--save")

        assert rc == 0
        entry = Ledger(ledger).index()[f"amb-2@gate{CURRENT_WORKS_GATE}"]
        assert (entry["status"], entry["result"]) == (REVIEWED, DISPOSITION_REMOVED)
        assert (entry["reviewer"], entry["review_of"]) == ("eric", DISPOSITION_AMBIGUOUS)
        assert entry["note"] == "two namesakes, neither in ECE"
        assert entry["relationships_after"] == 0
        record = disk.record("amb-2")
        md = record["metadata"]
        assert not works_are_verified(record)
        assert "recent_works" not in md
        assert record["keywords"] == []
        block = md["publication_remediation"]
        assert block["disposition"] == DISPOSITION_REMOVED
        # The automated step removed the two candidates; the record still says so.
        assert (block["relationships_removed"], block["keywords_invalidated"]) == (2, True)
        assert block["review"]["reviewer"] == "eric"
        assert block["review"]["review_of"] == DISPOSITION_AMBIGUOUS
        assert disk.writes == [["uiuc"]]
        assert _waiting(ledger) == ["amb-1", "nr-1"]

    def test_a_needs_review_unit_takes_a_verdict_too(self, queue, monkeypatch):
        disk, ledger = queue
        assert _review(monkeypatch, disk, ledger, "nr-1", "--removed",
                       "--reviewer", "eric", "--save") == 0
        entry = Ledger(ledger).index()[f"nr-1@gate{CURRENT_WORKS_GATE}"]
        assert (entry["status"], entry["result"], entry["review_of"]) == (
            REVIEWED, DISPOSITION_REMOVED, DISPOSITION_NEEDS_REVIEW)
        assert _waiting(ledger) == ["amb-1", "amb-2"]


class TestVerifiedVerdict:
    def test_stamps_the_named_authors_works_through_the_current_gate(self, queue, monkeypatch, openalex):
        disk, ledger = queue

        rc = _review(monkeypatch, disk, ledger, "amb-1", "--verified", _AUTHOR,
                     "--reviewer", "eric", "--save")

        assert rc == 0
        record = disk.record("amb-1")
        md = record["metadata"]
        assert works_are_verified(record)
        assert record_works_gate(record) == CURRENT_WORKS_GATE
        assert md["publication_author_id"] == _AUTHOR
        # apply_works and the gate chose these, not the reviewer: the front
        # matter and the paper outside the author's own fields are gone.
        assert [w["title"] for w in verified_recent_works(record)] == [
            "Subspace Imaging with Learned Priors", "Fast Spectroscopic Imaging"]
        # Restored like any verified unit: no remediation block left behind.
        assert "publication_remediation" not in md
        entry = Ledger(ledger).index()[f"amb-1@gate{CURRENT_WORKS_GATE}"]
        assert (entry["status"], entry["result"]) == (REVIEWED, DISPOSITION_VERIFIED)
        assert (entry["reviewed_author_id"], entry["reviewer"]) == (_AUTHOR, "eric")
        assert entry["relationships_after"] == 2
        assert _waiting(ledger) == ["amb-2", "nr-1"]

    def test_accepts_the_author_url_openalex_shows(self, queue, monkeypatch, openalex):
        disk, ledger = queue
        assert _review(monkeypatch, disk, ledger, "amb-1", "--verified",
                       f"https://openalex.org/{_AUTHOR}", "--reviewer", "eric", "--save") == 0
        assert disk.record("amb-1")["metadata"]["publication_author_id"] == _AUTHOR

    @pytest.mark.parametrize("bad", ["5000777", "A5000777x", "https://openalex.org/W123", ""])
    def test_refuses_an_author_id_that_is_not_one(self, queue, monkeypatch, openalex, bad):
        disk, ledger = queue
        before = _sha256(ledger)
        assert _review(monkeypatch, disk, ledger, "amb-1", "--verified", bad,
                       "--reviewer", "eric", "--save") == 2
        assert (_sha256(ledger), disk.writes, openalex["calls"]) == (before, [], [])

    @pytest.mark.parametrize("problem, reason", [
        ("unknown_author", f"OpenAlex answered {_AUTHOR} with no author"),
        ("merged_author", f"OpenAlex answered {_AUTHOR} with A5000999"),
        ("no_works", "kept none of the 0 recent work(s)"),
        ("gate_keeps_none", "kept none of the 1 recent work(s)"),
        ("identity_revoked", "apply_works did not stamp"),
    ])
    def test_refuses_when_nothing_would_be_verified(self, queue, monkeypatch, openalex, capsys,
                                                    problem, reason):
        disk, ledger = queue
        if problem == "unknown_author":
            openalex["author"] = None
        elif problem == "merged_author":
            openalex["merged_into"] = "A5000999"
        elif problem == "no_works":
            openalex["works"] = {}
        elif problem == "gate_keeps_none":
            openalex["works"] = {_AUTHOR: [_raw("Geochemistry Again", 2026, "Chemistry")]}
        else:
            # apply_works never restores an identity a research refresh revoked,
            # and a review lands through apply_works.
            disk.record("amb-1")["metadata"]["research_refresh"] = {"reason": "identity_revoked"}
        before = _sha256(ledger)
        snapshot = copy.deepcopy(disk.shards)

        rc = _review(monkeypatch, disk, ledger, "amb-1", "--verified", _AUTHOR,
                     "--reviewer", "eric", "--save")

        assert rc == 2
        assert reason in capsys.readouterr().err
        assert (_sha256(ledger), disk.writes, disk.shards) == (before, [], snapshot)
        assert _waiting(ledger) == ["amb-1", "amb-2", "nr-1"]

    def test_refuses_an_author_who_cannot_be_this_professor(self, queue, monkeypatch, openalex, capsys):
        """A mistyped id names a stranger, and `verified` is the one verdict
        that restores trust. A surname that does not match stops it unless the
        reviewer says the mismatch is known."""
        disk, ledger = queue
        openalex["author"] = {**_AUTHOR_RECORD, "display_name": "Brazilian Chemist"}
        before = _sha256(ledger)

        rc = _review(monkeypatch, disk, ledger, "amb-1", "--verified", _AUTHOR,
                     "--reviewer", "eric", "--save")

        assert rc == 2
        assert "Brazilian Chemist" in capsys.readouterr().err
        assert (_sha256(ledger), disk.writes) == (before, [])
        rc = _review(monkeypatch, disk, ledger, "amb-1", "--verified", _AUTHOR,
                     "--reviewer", "eric", "--allow-name-mismatch", "--save")
        assert rc == 0
        assert works_are_verified(disk.record("amb-1"))

    def test_refuses_when_landing_it_would_change_another_record(self, queue, monkeypatch, openalex):
        """apply_works sees the whole corpus. Naming an author id another
        professor already holds strips the attribution from both (one id, two
        people), and a record the verdict is not about must not change."""
        disk, ledger = queue
        disk.record("ok-1")["metadata"]["publication_author_id"] = _AUTHOR
        before = _sha256(ledger)
        snapshot = copy.deepcopy(disk.shards)

        rc = _review(monkeypatch, disk, ledger, "amb-1", "--verified", _AUTHOR,
                     "--reviewer", "eric", "--save")

        assert rc == 3
        assert (_sha256(ledger), disk.writes, disk.shards) == (before, [], snapshot)


class TestOneVerdictPerUnit:
    def test_a_second_verdict_is_refused_and_writes_nothing(self, queue, monkeypatch, openalex, capsys):
        disk, ledger = queue
        assert _review(monkeypatch, disk, ledger, "amb-2", "--removed",
                       "--reviewer", "eric", "--save") == 0
        before = _sha256(ledger)
        settled = copy.deepcopy(disk.shards)
        capsys.readouterr()

        for verdict in (["--removed"], ["--verified", _AUTHOR]):
            rc = _review(monkeypatch, disk, ledger, "amb-2", *verdict,
                         "--reviewer", "someone-else", "--save")
            assert rc == 2
            assert "already has a verdict" in capsys.readouterr().err

        assert (_sha256(ledger), disk.shards) == (before, settled)
        assert disk.writes == [["uiuc"]]
        assert openalex["calls"] == []

    @pytest.mark.parametrize("unit, reason", [
        ("ok-1", "is not awaiting review"),
        ("nobody", "the ledger has no unit nobody"),
    ])
    def test_a_unit_that_is_not_awaiting_review_is_refused(self, queue, monkeypatch, capsys,
                                                           unit, reason):
        disk, ledger = queue
        before = _sha256(ledger)
        assert _review(monkeypatch, disk, ledger, unit, "--removed",
                       "--reviewer", "eric", "--save") == 2
        assert reason in capsys.readouterr().err
        assert (_sha256(ledger), disk.writes) == (before, [])

    def test_a_unit_whose_record_left_the_shards_is_refused(self, queue, monkeypatch, capsys):
        disk, ledger = queue
        disk.shards["uiuc"] = [r for r in disk.shards["uiuc"] if r["id"] != "amb-2"]
        before = _sha256(ledger)
        assert _review(monkeypatch, disk, ledger, "amb-2", "--removed",
                       "--reviewer", "eric", "--save") == 2
        assert "is 0 records in the shards" in capsys.readouterr().err
        assert (_sha256(ledger), disk.writes) == (before, [])

    def test_a_record_id_held_twice_in_the_shards_is_refused(self, queue, monkeypatch, capsys):
        disk, ledger = queue
        disk.shards["copy"] = [copy.deepcopy(disk.record("amb-2"))]
        before = _sha256(ledger)
        assert _review(monkeypatch, disk, ledger, "amb-2", "--removed",
                       "--reviewer", "eric", "--save") == 2
        assert "is 2 records in the shards" in capsys.readouterr().err
        assert (_sha256(ledger), disk.writes) == (before, [])

    def test_a_professor_with_two_open_units_is_decided_by_unit_key(self, tmp_path, monkeypatch, capsys):
        """One record, settled ambiguous under two gates: a professor id names
        both, so the verdict has to name the unit."""
        record = faculty("twice")
        invalidate_record(record)
        ledger = Ledger(tmp_path / "ledger.jsonl")
        for gate in (CURRENT_WORKS_GATE, CURRENT_WORKS_GATE + 1):
            unit = unit_for(record, to_gate=gate)
            ledger.claim(unit)
            ledger.settle(unit, record, DISPOSITION_AMBIGUOUS)
        disk = _Disk({"uiuc": [record]})
        key = f"twice@gate{CURRENT_WORKS_GATE}"

        assert _review(monkeypatch, disk, ledger.path, "twice", "--removed",
                       "--reviewer", "eric", "--save") == 2
        assert "names 2 units" in capsys.readouterr().err
        assert disk.writes == []
        assert _review(monkeypatch, disk, ledger.path, key, "--removed",
                       "--reviewer", "eric", "--save") == 0
        assert _waiting(ledger.path) == ["twice"]
        assert Ledger(ledger.path).index()[key]["status"] == REVIEWED

    @pytest.mark.parametrize("argv", [
        ["amb-1", "--removed", "--save"],                                # who decided?
        ["amb-1", "--removed", "--reviewer", "  ", "--save"],
        ["amb-1", "--reviewer", "eric", "--save"],                       # decided what?
        ["amb-1", "--removed", "--verified", _AUTHOR, "--reviewer", "eric", "--save"],
        ["--removed", "--reviewer", "eric", "--save"],                   # about whom?
    ])
    def test_a_verdict_names_one_unit_one_outcome_and_a_reviewer(self, queue, monkeypatch, argv):
        disk, ledger = queue
        before = _sha256(ledger)
        assert _review(monkeypatch, disk, ledger, *argv) == 2
        assert (_sha256(ledger), disk.writes) == (before, [])

    def test_without_save_a_verdict_writes_nothing(self, queue, monkeypatch, openalex, capsys):
        disk, ledger = queue
        before = _sha256(ledger)
        snapshot = copy.deepcopy(disk.shards)

        for verdict in (["amb-1", "--verified", _AUTHOR], ["amb-2", "--removed"]):
            assert _review(monkeypatch, disk, ledger, *verdict, "--reviewer", "eric") == 0

        assert (_sha256(ledger), disk.writes, disk.shards) == (before, [], snapshot)
        assert _waiting(ledger) == ["amb-1", "amb-2", "nr-1"]
        # ...and showed what --save would land.
        out = capsys.readouterr().out
        assert "Subspace Imaging with Learned Priors" in out


class TestAfterTheQueueIsSettled:
    @staticmethod
    def _settle_all(monkeypatch, disk, ledger):
        assert _review(monkeypatch, disk, ledger, "amb-1", "--verified", _AUTHOR,
                       "--reviewer", "eric", "--save") == 0
        for unit in ("amb-2", "nr-1"):
            assert _review(monkeypatch, disk, ledger, unit, "--removed",
                           "--reviewer", "eric", "--save") == 0

    def test_report_passes_and_the_queue_is_empty(self, queue, monkeypatch, openalex, capsys):
        disk, ledger = queue
        self._settle_all(monkeypatch, disk, ledger)
        capsys.readouterr()

        rc = _cli(monkeypatch, disk, "--ledger", str(ledger), "report")

        report = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert report["manual_review_queue_size"] == 0
        assert report["duplicate_logical_remediations"] == 0
        assert report["by_status"] == {VERIFIED_COMPLETE: 1, REVIEWED: 3}
        assert report["completed"] == 4

    def test_the_trust_verifier_finds_no_leak(self, queue, monkeypatch, openalex, tmp_path, capsys):
        disk, ledger = queue
        self._settle_all(monkeypatch, disk, ledger)
        spec = importlib.util.spec_from_file_location(
            "verify_publication_trust_review",
            Path(__file__).resolve().parents[1] / "scripts" / "verify_publication_trust.py",
        )
        vpt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vpt)
        monkeypatch.setattr(vpt, "_load_records",
                            lambda: [r for records in disk.load().values() for r in records])
        monkeypatch.setattr(vpt, "TRACKING_PATH", tmp_path / "no-tracking.json")
        monkeypatch.setattr(vpt, "LEDGER_PATH", ledger)
        capsys.readouterr()

        rc = vpt.main(["--sample", "10"])

        report = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert report["downstream_unverified_leaks"] == 0
        assert report["trusted_records"] == 2
        assert report["ledger"]["by_result"] == {
            DISPOSITION_VERIFIED: 2, DISPOSITION_REMOVED: 2}

    def test_an_empty_queue_lets_the_manual_review_incident_close(self, queue, monkeypatch, openalex):
        from backend.routes import ops as ops_mod

        disk, ledger = queue
        monkeypatch.setattr(ops_mod, "_REMEDIATION_LEDGER_PATH", ledger)
        monkeypatch.setattr(ops_mod, "_pending_publication_professors", lambda: 0)
        review_key = "manual_review:publication_attribution"

        class Recorder:
            def __init__(self):
                self.recorded: list[str] = []
                self.recovered: list[str] = []

            async def record(self, *, dedup_key, **_kwargs):
                self.recorded.append(dedup_key)
                return True

            async def recover(self, dedup_key, **_kwargs):
                self.recovered.append(dedup_key)
                return True

        def scan():
            rec = Recorder()
            summary = {"skipped": [], "scanned": 0, "detectors": {}, "_open_keys": {review_key}}
            asyncio.run(ops_mod._scan_publication_remediation(rec, summary))
            return rec, summary["detectors"]["publication_remediation"]

        rec, detector = scan()
        assert (rec.recorded, rec.recovered, detector["manual_review"]) == ([review_key], [], 3)

        self._settle_all(monkeypatch, disk, ledger)

        rec, detector = scan()
        assert (rec.recorded, rec.recovered, detector["manual_review"]) == ([], [review_key], 0)


# ---------------------------------------------------------------------------
# The ledger rule: a settled unit reopens for a review event and nothing else
# ---------------------------------------------------------------------------

class TestOnlyAReviewReopensASettledUnit:
    @staticmethod
    def _ambiguous(ledger: Ledger) -> dict:
        record = faculty("amb")
        invalidate_record(record)
        unit = unit_for(record)
        ledger.claim(unit)
        ledger.settle(unit, record, DISPOSITION_AMBIGUOUS)
        return ledger.index()[unit["idempotency_key"]]

    def test_a_stray_automated_event_still_changes_nothing(self, tmp_path):
        ledger = Ledger(tmp_path / "ledger.jsonl")
        entry = self._ambiguous(ledger)
        unit = {"professor_id": "amb", "idempotency_key": entry["idempotency_key"]}
        ledger.append(unit, VERIFIED_COMPLETE, result=DISPOSITION_VERIFIED, reviewer="eric")
        after = ledger.index()[entry["idempotency_key"]]
        assert (after["status"], after["result"]) == (VERIFIED_COMPLETE, DISPOSITION_AMBIGUOUS)
        assert awaits_review(after)

    def test_record_review_settles_it_once(self, tmp_path):
        ledger = Ledger(tmp_path / "ledger.jsonl")
        entry = self._ambiguous(ledger)

        event = ledger.record_review(entry, DISPOSITION_REMOVED, reviewer="eric")
        assert event is not None
        assert ledger.record_review(entry, DISPOSITION_VERIFIED, reviewer="eric",
                                    author_id=_AUTHOR) is None

        after = ledger.index()[entry["idempotency_key"]]
        assert (after["status"], after["result"], after["reviewer"]) == (
            REVIEWED, DISPOSITION_REMOVED, "eric")
        assert not awaits_review(after)
        assert ledger.is_complete(entry["idempotency_key"])
        assert ledger.duplicate_count() == 0

    @pytest.mark.parametrize("event", [
        {"result": DISPOSITION_REMOVED},                                   # no reviewer
        {"result": DISPOSITION_AMBIGUOUS, "reviewer": "eric"},             # not a verdict
        {"result": DISPOSITION_VERIFIED, "reviewer": "eric"},              # verified by whom?
    ], ids=["no_reviewer", "not_a_verdict", "verified_without_author"])
    def test_a_malformed_review_event_is_ignored(self, tmp_path, event):
        ledger = Ledger(tmp_path / "ledger.jsonl")
        entry = self._ambiguous(ledger)
        unit = {"professor_id": "amb", "idempotency_key": entry["idempotency_key"]}
        ledger.append(unit, REVIEWED, **event)
        after = ledger.index()[entry["idempotency_key"]]
        assert (after["status"], after["result"]) == (VERIFIED_COMPLETE, DISPOSITION_AMBIGUOUS)
        with pytest.raises(ValueError):
            ledger.record_review(entry, event["result"], reviewer=event.get("reviewer", ""))

    def test_a_review_of_a_unit_nobody_queued_for_review_is_ignored(self, tmp_path):
        ledger = Ledger(tmp_path / "ledger.jsonl")
        record = faculty("fine")
        unit = unit_for(record)
        ledger.claim(unit)
        ledger.settle(unit, record, DISPOSITION_VERIFIED)
        ledger.append(unit, REVIEWED, result=DISPOSITION_REMOVED, reviewer="eric")
        after = ledger.index()[unit["idempotency_key"]]
        assert (after["status"], after["result"]) == (VERIFIED_COMPLETE, DISPOSITION_VERIFIED)
        entry = ledger.index()[unit["idempotency_key"]]
        assert ledger.record_review(entry, DISPOSITION_REMOVED, reviewer="eric") is None

    def test_a_second_review_event_is_ignored_and_counted_as_a_duplicate(self, tmp_path):
        """record_review refuses a second verdict; a second one that reached
        the file anyway (two reviewers, a replayed line) keeps the first and is
        counted, so `report` fails instead of hiding it."""
        ledger = Ledger(tmp_path / "ledger.jsonl")
        entry = self._ambiguous(ledger)
        ledger.record_review(entry, DISPOSITION_REMOVED, reviewer="eric")
        unit = {"professor_id": "amb", "idempotency_key": entry["idempotency_key"]}
        ledger.append(unit, REVIEWED, result=DISPOSITION_VERIFIED, reviewer="other",
                      reviewed_author_id=_AUTHOR, review_of=DISPOSITION_AMBIGUOUS)
        after = ledger.index()[entry["idempotency_key"]]
        assert (after["result"], after["reviewer"]) == (DISPOSITION_REMOVED, "eric")
        assert ledger.duplicate_count() == 1

    def test_record_review_in_a_dry_run_writes_nothing(self, tmp_path):
        path = tmp_path / "ledger.jsonl"
        entry = self._ambiguous(Ledger(path))
        before = _sha256(path)
        dry = Ledger(path, dry_run=True)
        assert dry.record_review(entry, DISPOSITION_REMOVED, reviewer="eric") is not None
        assert dry.index()[entry["idempotency_key"]]["status"] == REVIEWED
        # A dry run refuses a second verdict exactly as a real one would.
        assert dry.record_review(entry, DISPOSITION_REMOVED, reviewer="eric") is None
        assert _sha256(path) == before
