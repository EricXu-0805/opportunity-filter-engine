"""scripts/remediate_publications.py run through its real CLI: the dry runs, and
the `review` command that settles the manual-review queue.

The driver's other cases live in tests/test_publication_remediation.py. These
are here because that file is being edited on another branch.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from src.publication_remediation import (
    DISPOSITION_VERIFIED,
    QUEUED,
    VERIFIED_COMPLETE,
    Ledger,
    invalidate_record,
    unit_for,
)
from src.publication_trust import (
    CURRENT_WORKS_GATE,
    VERIFIED_AUTHOR_ID,
    verified_recent_works,
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
