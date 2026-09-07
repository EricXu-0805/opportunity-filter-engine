"""UC Davis left the supported set, and must stay out until someone says so.

The whole risk of a scope decision like this is that it looks identical, from
the outside, to quietly dropping an inconvenient school from a denominator.
The difference is that a scope decision also stops serving the school — so
these tests pin both halves: the records go inactive everywhere that counts,
AND nothing keeps offering the school to a student.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.school_scope import (
    UNSUPPORTED_REASON,
    UNSUPPORTED_SCHOOLS,
    deactivate_unsupported_schools,
    is_supported,
    supported_only,
    unsupported_reason,
)

_REPO = Path(__file__).resolve().parents[1]


def _gate():
    spec = importlib.util.spec_from_file_location(
        "release_gate", _REPO / "scripts" / "release_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestTheDecisionIsDeclaredNotInferred:
    def test_ucd_is_unsupported(self):
        assert "ucd" in UNSUPPORTED_SCHOOLS
        assert is_supported("ucd") is False

    def test_every_entry_carries_a_date_and_a_reason(self):
        """A scope change without a rationale is indistinguishable from a bug."""
        for slug, entry in UNSUPPORTED_SCHOOLS.items():
            decided_on, reason = entry
            assert decided_on.count("-") == 2, slug
            assert len(reason) > 80, f"{slug} needs a real rationale"

    def test_the_reason_is_retrievable(self):
        assert "Cloudflare" in (unsupported_reason("ucd") or "")
        assert unsupported_reason("ucb") is None

    def test_a_supported_school_is_unaffected(self):
        assert is_supported("ucb") is True
        assert supported_only(["ucb", "ucd", "wisc"]) == ["ucb", "wisc"]

    def test_slug_matching_is_not_fooled_by_case_or_padding(self):
        assert is_supported(" UCD ") is False

    def test_a_non_string_is_not_silently_unsupported(self):
        assert is_supported(None) is True
        assert is_supported(42) is True


class TestRecordsGoInactiveNotDeleted:
    def _rows(self):
        return [
            {"school": "ucd", "id": "a", "metadata": {"is_active": True,
                                                      "last_seen_at": "2026-07-21T00:00:00"}},
            {"school": "ucb", "id": "b", "metadata": {"is_active": True}},
        ]

    def test_unsupported_records_are_deactivated(self):
        rows = self._rows()
        result = deactivate_unsupported_schools(rows)
        assert rows[0]["metadata"]["is_active"] is False
        assert rows[0]["metadata"]["deactivation_reason"] == UNSUPPORTED_REASON
        assert result["by_school"] == {"ucd": 1}

    def test_the_records_are_preserved(self):
        """Inactive, not gone — re-enabling must not need a re-onboarding."""
        rows = self._rows()
        deactivate_unsupported_schools(rows)
        assert len(rows) == 2
        assert rows[0]["id"] == "a"

    def test_no_timestamp_is_rewritten(self):
        """The whole point: scope changed, observations did not."""
        rows = self._rows()
        deactivate_unsupported_schools(rows)
        assert rows[0]["metadata"]["last_seen_at"] == "2026-07-21T00:00:00"

    def test_supported_schools_are_untouched(self):
        rows = self._rows()
        deactivate_unsupported_schools(rows)
        assert rows[1]["metadata"]["is_active"] is True
        assert "deactivation_reason" not in rows[1]["metadata"]

    def test_it_is_idempotent(self):
        rows = self._rows()
        deactivate_unsupported_schools(rows)
        again = deactivate_unsupported_schools(rows)
        assert again["deactivated"] == 0

    def test_an_earlier_retirement_keeps_its_own_reason(self):
        """This pass records why we stopped serving, not why we retired."""
        rows = [{"school": "ucd", "metadata": {
            "is_active": False,
            "deactivation_reason": "absent_from_directory_rescrape"}}]
        deactivate_unsupported_schools(rows)
        assert rows[0]["metadata"]["deactivation_reason"] == (
            "absent_from_directory_rescrape")


class TestNothingKeepsOfferingTheSchool:
    def test_it_is_not_a_registered_school(self):
        from src.collectors.refresh_contract import registered_school_slugs
        assert "ucd" not in registered_school_slugs()

    def test_it_is_never_scheduled(self):
        from scripts.refresh_rotation import (
            ISOLATED_WEEKLY_SHARDS,
            WEEKLY_ROTATION,
            validate_rotation,
        )
        scheduled = {s for day in WEEKLY_ROTATION.values() for s in day}
        scheduled |= {s for day in ISOLATED_WEEKLY_SHARDS.values() for s in day}
        assert "ucd" not in scheduled
        # And the rotation still exactly partitions what IS registered, so
        # dropping the school did not leave a hole somewhere else.
        validate_rotation()

    def test_a_manual_dispatch_cannot_name_it(self):
        from scripts.refresh_rotation import normalize_requested_shard
        with pytest.raises(ValueError, match="no longer supported"):
            normalize_requested_shard("ucd")
        with pytest.raises(ValueError, match="no longer supported"):
            normalize_requested_shard("ucb,ucd")

    def test_the_frontend_does_not_offer_it(self):
        index = (_REPO / "frontend/src/lib/catalogs/index.ts").read_text()
        assert "'./ucd'" not in index

    def test_the_static_fallback_does_not_count_it(self):
        stats = json.loads(
            (_REPO / "frontend/src/lib/school-stats.json").read_text())
        schools = stats.get("schools", stats)
        assert "ucd" not in schools

    def test_the_committed_corpus_holds_no_active_ucd_record(self):
        shard = _REPO / "data/processed/shards/ucd.json"
        records = json.loads(shard.read_text())
        assert records, "the records must be preserved, not deleted"
        assert not [
            r for r in records if (r.get("metadata") or {}).get("is_active")
        ]


class TestTheDenominatorFollowsTheDecision:
    def test_ucd_contributes_no_active_records(self):
        report = _gate().corpus_freshness_report()
        assert report["schools"]["ucd"]["active"] == 0
        assert "ucd" not in report["fully_stale_schools"]

    def test_the_scope_travels_with_the_number(self):
        """A reader must not have to leave the ledger to learn why."""
        report = _gate().corpus_freshness_report()
        assert report["unsupported_schools"] == ["ucd"]
        assert "ucd" in report["no_active_record_schools"]

    def test_an_empty_school_that_is_not_declared_unsupported_blocks(self):
        """The failure mode this scope change could otherwise have created.

        A school that silently lost every active record reads exactly like a
        deliberately retired one. Only the declared set is excused.
        """
        gate = _gate()
        real = gate.corpus_freshness_report

        def fake(*a, **k):
            report = real(*a, **k)
            report["no_active_record_schools"] = ["ucd", "somewhere"]
            report["unexplained_empty_schools"] = ["somewhere"]
            return report

        gate.corpus_freshness_report = fake
        got = gate.check_corpus_freshness()
        assert got["status"] == gate.FAIL
        assert got["reason"] == "unexplained_empty_school"
        assert "somewhere" in got["detail"]

    def test_with_ucd_declared_the_gate_passes_on_the_real_corpus(self):
        gate = _gate()
        got = gate.check_corpus_freshness()
        assert got["status"] == gate.PASS, got["detail"]
        assert got["evidence"]["unexplained_empty_schools"] == []


class TestReEnablingIsOneDeliberateEdit:
    def test_removing_the_entry_restores_support(self, monkeypatch):
        import src.school_scope as scope
        monkeypatch.setattr(scope, "UNSUPPORTED_SCHOOLS", {})
        assert scope.is_supported("ucd") is True
        rows = [{"school": "ucd", "metadata": {"is_active": True}}]
        assert scope.deactivate_unsupported_schools(rows)["deactivated"] == 0
        assert rows[0]["metadata"]["is_active"] is True

    def test_the_catalog_file_is_still_there_to_re_enable(self):
        assert (_REPO / "frontend/src/lib/catalogs/ucd.ts").exists()

    def test_the_collector_is_still_there_to_re_enable(self):
        assert (_REPO / "src/collectors/schools/ucd_faculty.py").exists()
