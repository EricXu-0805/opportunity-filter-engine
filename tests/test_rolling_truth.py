"""Tests for src.normalizers.rolling_truth — the deadline/is_rolling
contradiction guard.

Demote-only and conflict-only: a fixed deadline with no source text saying
rolling demotes is_rolling; everything else — R70-A no-deadline defaults,
explicit rolling prose, False/absent values — is untouched. Faculty contact
profiles are neutralized by their own trust boundary before serving.
"""

from __future__ import annotations

from src.normalizers.enricher import enrich_opportunity
from src.normalizers.rolling_truth import (
    has_fixed_deadline,
    reconcile_rolling_with_deadline,
    record_text_marks_rolling,
    text_explicitly_marks_rolling,
)


class TestTextEvidence:
    def test_affirmative_rolling(self):
        assert text_explicitly_marks_rolling("Applications reviewed on a rolling basis")

    def test_negated_rolling_is_not_evidence(self):
        assert not text_explicitly_marks_rolling("This is NOT rolling — apply by March 1")
        assert not text_explicitly_marks_rolling("non-rolling deadline")

    def test_empty_and_non_string(self):
        assert not text_explicitly_marks_rolling("")
        assert not text_explicitly_marks_rolling("   ")
        assert not text_explicitly_marks_rolling(None)
        assert not text_explicitly_marks_rolling(3)

    def test_record_fields_are_allowlisted(self):
        # Source text counts; collector notes / source names do not.
        assert record_text_marks_rolling({"title": "Rolling REU applications"})
        assert record_text_marks_rolling(
            {"eligibility": {"eligibility_text_raw": "rolling admission"}})
        assert not record_text_marks_rolling(
            {"source": "rolling_collector", "metadata": {"notes": "rolling"}})


class TestFixedDeadline:
    def test_iso_date_is_fixed(self):
        assert has_fixed_deadline({"deadline": "2026-10-01"})

    def test_rolling_string_deadline_is_not_fixed(self):
        assert not has_fixed_deadline({"deadline": "Rolling"})

    def test_absent_or_blank(self):
        assert not has_fixed_deadline({})
        assert not has_fixed_deadline({"deadline": None})
        assert not has_fixed_deadline({"deadline": "   "})


class TestReconcile:
    def test_contradiction_demotes(self):
        opp = {"deadline": "2026-10-01", "is_rolling": True,
               "title": "Summer Research Fellowship"}
        assert reconcile_rolling_with_deadline(opp) is True
        assert opp["is_rolling"] is False

    def test_deadline_less_faculty_record_untouched(self):
        opp = {"deadline": None, "is_rolling": True,
               "source_type": "faculty_research"}
        assert reconcile_rolling_with_deadline(opp) is False
        assert opp["is_rolling"] is True

    def test_no_deadline_no_text_untouched(self):
        # The R70-A default shape: safe no-deadline assumption stays True.
        opp = {"is_rolling": True, "opportunity_type": "fellowship",
               "title": "Graduate Fellowship"}
        assert reconcile_rolling_with_deadline(opp) is False
        assert opp["is_rolling"] is True

    def test_explicit_rolling_text_beats_deadline(self):
        # "Rolling until filled, priority March 1" — both claims are sourced;
        # keep the collector's word rather than guess.
        opp = {"deadline": "2026-03-01", "is_rolling": True,
               "description_clean": "Applications accepted on a rolling basis."}
        assert reconcile_rolling_with_deadline(opp) is False
        assert opp["is_rolling"] is True

    def test_never_promotes(self):
        opp = {"deadline": None, "is_rolling": False,
               "description_clean": "rolling admission"}
        assert reconcile_rolling_with_deadline(opp) is False
        assert opp["is_rolling"] is False
        absent = {"deadline": "2026-10-01"}
        assert reconcile_rolling_with_deadline(absent) is False
        assert "is_rolling" not in absent


class TestEnricherWiring:
    def test_enrich_opportunity_demotes_contradiction(self):
        opp = {
            "title": "Chemistry Summer Program",
            "opportunity_type": "summer_program",
            "deadline": "2026-02-15",
            "is_rolling": True,
            "description_raw": "A ten-week summer research program in chemistry "
                               "with housing provided. Apply with a transcript "
                               "and one recommendation letter before the deadline.",
            "keywords": ["chemistry"],
        }
        enrich_opportunity(opp)
        assert opp["is_rolling"] is False

    def test_enrich_opportunity_keeps_faculty_rolling(self):
        opp = {
            "title": "Research with Prof. Ada Lovelace — ECE",
            "source_type": "faculty_research",
            "opportunity_type": "research",
            "deadline": None,
            "is_rolling": True,
            "description_raw": "Research opportunity with Professor Ada Lovelace "
                               "in the Department of Electrical Engineering. "
                               "Contact the professor directly to inquire.",
            "keywords": ["machine learning"],
        }
        enrich_opportunity(opp)
        assert opp["is_rolling"] is True
