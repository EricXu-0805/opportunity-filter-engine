"""Publication trust boundary — fail-closed attribution gating.

Product rule: a publication may influence professor-specific output ONLY when
``metadata.publication_attribution_status == "verified_author_id"``. Anything
else — name_match, absent (legacy), pending, rejected, junk, wrong-typed —
must be excluded from Match reason, Ask AI, Resume personalization, and Cold
Email, plus the served API payloads. These tests exercise the real feature
paths, not just the centralized helper.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime

import pytest

from src.publication_trust import (
    NAME_MATCH,
    PENDING_REMEDIATION,
    VERIFIED_AUTHOR_ID,
    attribution_status,
    can_use_publications_for_personalization,
    verified_recent_works,
    works_are_verified,
)

_WORKS = [
    {"title": "NeuroFlow: Decoding Imagined Speech from ECoG Arrays", "year": 2026},
    {"title": "Cortical Signal Denoising for Implantable BCIs", "year": 2024},
]

# Every way attribution can fail to be explicitly verified. The gate must
# fail CLOSED on all of them — including statuses that do not exist yet.
#
# PENDING_REMEDIATION is in this tuple rather than in a suite of its own on
# purpose: it is the status the historical remediation writes over 6,255
# records whose papers a superseded gate approved, and it has to be excluded by
# every surface below by the SAME rule that excludes name_match, not by a
# second rule someone remembered to add. Listing it here runs it through all
# fourteen downstream assertions — card, rerank, chat, brief, cold email,
# tailor, gaps, batch, similar — for free, and any new surface added to this
# file inherits the coverage.
UNVERIFIED_STATUSES = (
    NAME_MATCH, PENDING_REMEDIATION, None, "", "pending", "rejected", "unknown",
    "definitely_verified", "VERIFIED_AUTHOR_ID", 42, True,
)


def _opp(status="__absent__", works=_WORKS):
    md: dict = {"is_active": True}
    if works is not None:
        md["recent_works"] = [dict(w) for w in works]
    if status != "__absent__":
        md["publication_attribution_status"] = status
    return {
        "id": "fac-1", "title": "Research with Prof. Jane Doe — ECE",
        "opportunity_type": "research", "pi_name": "Jane Doe",
        "lab_or_program": "Prof. Jane Doe's Group",
        "department": "Electrical Engineering",
        "keywords": ["brain-computer interfaces"],
        "description_raw": "Research on neural interfaces.",
        "eligibility": {"skills_required": ["Python"]},
        "application": {},
        "metadata": md,
    }


class TestCentralGate:
    def test_verified_passes(self):
        opp = _opp(VERIFIED_AUTHOR_ID)
        assert works_are_verified(opp)
        assert can_use_publications_for_personalization(opp)
        assert verified_recent_works(opp) == opp["metadata"]["recent_works"]
        assert attribution_status(opp) == VERIFIED_AUTHOR_ID

    def test_everything_else_fails_closed(self):
        for status in UNVERIFIED_STATUSES:
            opp = _opp(status)
            assert not works_are_verified(opp), status
            assert not can_use_publications_for_personalization(opp), status
            assert verified_recent_works(opp) == [], status
        # legacy record: field absent entirely
        legacy = _opp()
        assert not works_are_verified(legacy)
        assert verified_recent_works(legacy) == []
        assert attribution_status(legacy) is None
        # records with no metadata at all
        assert verified_recent_works({"id": "x"}) == []
        assert not works_are_verified({"id": "x", "metadata": None})

    def test_gate_is_equality_not_complement(self):
        # The rule is status == verified, never status != rejected — a brand
        # new status value must fail closed the day it is introduced.
        assert not works_are_verified(_opp("approved_by_reviewer"))

    def test_backend_reexport_is_the_same_authority(self):
        import backend.lib.publication_attribution as ba
        import src.publication_trust as pt

        assert ba.works_are_verified is pt.works_are_verified
        assert ba.verified_recent_works is pt.verified_recent_works
        assert ba.VERIFIED_AUTHOR_ID == pt.VERIFIED_AUTHOR_ID

    def test_pipeline_constants_come_from_the_gate(self):
        from src.collectors import openalex_enrich as oa

        assert oa.ATTRIBUTION_VERIFIED == VERIFIED_AUTHOR_ID
        assert oa.ATTRIBUTION_NAME_MATCH == NAME_MATCH


class TestMatchSurfaces:
    def test_card_excludes_unverified_works(self):
        from backend.routes.matches import _match_card

        card = _match_card(_opp(VERIFIED_AUTHOR_ID))
        assert card["recent_works"]
        assert card["publication_attribution_status"] == VERIFIED_AUTHOR_ID
        for status in (NAME_MATCH, "pending", "junk"):
            card = _match_card(_opp(status))
            assert "recent_works" not in card
            assert "publication_attribution_status" not in card
        card = _match_card(_opp())  # legacy
        assert "recent_works" not in card

    def test_rerank_candidate_text_excludes_unverified_works(self, monkeypatch):
        # Match score + reason: the LLM rerank only ever sees works through
        # the gate, so an unverified paper can move neither the blended score
        # nor the "why you match" line. (The rule-based ranker reads no
        # publication data at all — see src/matcher/ranker.py.)
        from backend.routes import matches

        captured = {}
        monkeypatch.setattr(matches, "_resolve", lambda *a, **k: object())

        def fake_score(query, cand):
            captured["cand"] = dict(cand)
            return {c[0]: {"s": 50.0, "r": ""} for c in cand}

        monkeypatch.setattr(matches, "_llm_score_candidates", fake_score)
        from src.matcher.ranker import MatchResult

        results = [
            MatchResult(opportunity_id=i, eligibility_score=50, readiness_score=50,
                        upside_score=50, final_score=50.0, bucket="good_match",
                        reasons_fit=[], reasons_gap=[], next_steps=[])
            for i in ("ver", "leg")
        ]
        lookup = {"ver": {**_opp(VERIFIED_AUTHOR_ID), "id": "ver"},
                  "leg": {**_opp(NAME_MATCH), "id": "leg"}}
        matches.llm_rerank({"research_interests_text": "trust-boundary-query"},
                           results, lookup)
        assert "NeuroFlow" in captured["cand"]["ver"]
        assert "NeuroFlow" not in captured["cand"]["leg"]
        assert "name-matched" not in captured["cand"]["leg"]

    def test_rerank_prompt_carries_no_unverified_labeling_protocol(self):
        # The system prompt must not teach the model a "name-matched" handling
        # rule — exclusion happens before the prompt, not inside it.
        import inspect

        from backend.routes import matches

        src = inspect.getsource(matches._llm_score_candidates)
        assert "name-matched" not in src
        assert "unverified" not in src


class TestAskAISurface:
    def test_chat_context_gets_only_verified_works(self):
        from backend.routes.opportunities import _build_chat_system_prompt

        system = _build_chat_system_prompt(_opp(VERIFIED_AUTHOR_ID), None)
        assert "NeuroFlow" in system
        for status in (NAME_MATCH, "pending", "junk"):
            system = _build_chat_system_prompt(_opp(status), None)
            assert "NeuroFlow" not in system
            assert "publications" not in system.casefold()
        system = _build_chat_system_prompt(_opp(), None)  # legacy
        assert "NeuroFlow" not in system


class TestColdEmailSurface:
    def test_professor_brief_and_corpus_and_anchors_are_gated(self):
        from backend.routes.cold_email import (
            _build_email_corpus,
            _professor_anchors,
            _render_professor_brief,
        )
        from src.recommender.cold_email import _common_parts

        profile = {"name": "Eric", "year": "freshman", "major": "CompE",
                   "school": "UIUC", "hard_skills": ["Python"],
                   "research_interests_text": "brain-computer interfaces"}

        verified = _opp(VERIFIED_AUTHOR_ID)
        p = _common_parts(profile, verified)
        assert "NeuroFlow" in _render_professor_brief(p, verified)
        assert "neuroflow" in _build_email_corpus(p, verified)
        assert "neuroflow" in _professor_anchors(p, verified)

        for status in (NAME_MATCH, "__absent__", "junk"):
            opp = _opp(status) if status != "__absent__" else _opp()
            p = _common_parts(profile, opp)
            assert "NeuroFlow" not in _render_professor_brief(p, opp), status
            assert "neuroflow" not in _build_email_corpus(p, opp), status
            assert "neuroflow" not in _professor_anchors(p, opp), status

    def test_template_email_never_cites_unverified_paper(self):
        from src.recommender.cold_email import generate_cold_email

        profile = {"name": "Eric", "year": "sophomore", "major": "CompE",
                   "hard_skills": ["Python"], "research_interests_text": "bci"}
        # Even a verified paper is named only when the student chose it (M33);
        # the chosen-paper path is covered in test_email_paper_reading.py.
        for status in (VERIFIED_AUTHOR_ID, NAME_MATCH, "__absent__", "pending"):
            opp = _opp(status) if status != "__absent__" else _opp()
            text = generate_cold_email(profile, opp)
            assert "NeuroFlow" not in text
            assert "caught my attention" not in text


class TestResumeSurface:
    def test_tailor_quotes_only_verified_titles_and_only_as_target_text(self, monkeypatch):
        # A paper title can be target text a rewrite links to (the professor's
        # own words), never evidence of the student's work. Only a verified
        # author id admits it; every other status and legacy records never do.
        from backend.routes import tailor

        captured = {}

        def fake_chat(messages, **kwargs):
            captured["messages"] = messages
            return None  # prompt already captured; parsing is not under test

        monkeypatch.setattr(tailor, "chat_completion", fake_chat)
        profile = {"name": "Eric", "year": "junior", "major": "CompE",
                   "hard_skills": [{"name": "Python", "level": "expert"}],
                   "coursework": ["ECE 385"],
                   "research_interests_text": "brain-computer interfaces"}
        statuses = [(VERIFIED_AUTHOR_ID, True), ("__absent__", False), *((s, False) for s in UNVERIFIED_STATUSES)]
        for status, admitted in statuses:
            opp = _opp(status)
            captured.clear()
            anchors = tailor._snapshot_anchors(opp, opp)
            assert any(anchor.evidence["field"] == "paper_title" for anchor in anchors) is admitted
            tailor._ai_tailor_bullets(profile, opp, ["Built a Python EEG parser"], anchors=anchors)
            system, user = (m["content"] for m in captured["messages"])
            assert ("NeuroFlow" in user) is admitted and "NeuroFlow" not in system
            data = json.loads(user.split("DATA (JSON):\n", 1)[1])
            # The student's only evidence is their own line.
            assert data["units"] == [{"unit_id": "b1", "original": "Built a Python EEG parser"}]

    def test_the_trust_verifier_checks_tailor_by_the_verified_read_and_its_anchors(self):
        """scripts/verify_publication_trust.py exited 1 on this branch: its resume_tailoring scan flagged any
        "recent_works", and tailor.py reads paper titles through verified_recent_works. It now applies the
        rule test_publication_remediation applies to the source, and runs each candidate through the anchors."""
        import importlib.util
        import inspect
        from pathlib import Path

        from backend.routes import tailor

        spec = importlib.util.spec_from_file_location(
            "verify_publication_trust_tailor", Path(__file__).resolve().parents[1] / "scripts" / "verify_publication_trust.py")
        vpt = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vpt)
        source = inspect.getsource(tailor)
        assert "verified_recent_works" in source and vpt.tailor_source_leaks(source) == []
        for mutant in (source + "\nraw = record['metadata']['recent_works']\n",
                       source + "\nstatus = 'publication_attribution_status'\n"):
            assert vpt.tailor_source_leaks(mutant) == ["tailor.py reads publication data outside verified_recent_works"]
        records = [{**_opp(status), "id": f"r-{index}"} for index, status in enumerate(UNVERIFIED_STATUSES)]
        assert vpt.tailor_anchor_leaks(tailor._snapshot_anchors, records) == []
        # A tailor that quoted every recent work would leak each unverified record's titles.
        def every_title(source_record, snapshot):
            titles = [work["title"] for work in (source_record.get("metadata") or {}).get("recent_works") or []]
            return tailor.opportunity_anchors("", [], paper_titles=titles)
        assert vpt.tailor_anchor_leaks(every_title, records) == [record["id"] for record in records]

    def test_gap_analysis_ignores_publication_data(self):
        from src.recommender.resume_advisor import analyze_gaps

        profile = {"hard_skills": [{"name": "Python", "level": "expert"}],
                   "coursework": []}
        with_works = analyze_gaps(profile, _opp(NAME_MATCH))
        without = analyze_gaps(profile, _opp(works=None))
        assert with_works == without


class TestServedPayloads:
    def test_batch_and_similar_share_the_redact_gate(self):
        # /opportunities/{id}, /batch and /similar all serialize through
        # _redact — one gate, no per-endpoint drift.
        import inspect

        from backend.lib.public_opportunity_detail import project_public_detail
        from backend.routes import opportunities as op

        assert "project_public_detail" in inspect.getsource(op._redact)
        assert "works_are_verified" in inspect.getsource(project_public_detail)
        assert "recent_works" in op._UNVERIFIED_PUBLICATION_KEYS
        src_batch = inspect.getsource(op.get_opportunities_batch)
        src_similar = inspect.getsource(op.get_similar_opportunities)
        src_detail = inspect.getsource(op.get_opportunity)
        for s in (src_batch, src_similar, src_detail):
            assert "_redact" in s


_PUBLICATION_KEYS = ("recent_works", "publication_attribution_status", "publication_author_id")


def _aged(*ages):
    """Papers that many calendar years old today, so the fixtures never expire."""
    this_year = datetime.now(UTC).year
    return [{"title": f"Zebrafinch Syrinx Imaging, Part {n}", "year": this_year - age}
            for n, age in enumerate(ages, 1)]


def _verified(works, **fields):
    opp = {**_opp(VERIFIED_AUTHOR_ID, works=works), **fields}
    opp["metadata"]["publication_author_id"] = "https://openalex.org/A123"
    return opp


def _reading(work):
    return {"version": 1, "purpose": "first_contact",
            "paper_reading": {**work, "level": "abstract", "confirmed": True}}


class TestRecentListsOnly:
    """M152: a verified list is served only when its newest paper is at most
    ten calendar years old. The rule reads the dates, never the authorship."""

    def test_newest_paper_eleven_years_old_is_shown_nowhere_and_cannot_be_chosen(self):
        from backend.lib.email_contact_context import email_research_works, validate_paper_reading
        from backend.lib.public_opportunity_detail import project_public_detail
        from backend.routes.matches import _match_card

        opp = _verified(_aged(11, 27))
        assert works_are_verified(opp)
        assert verified_recent_works(opp) == []
        detail = project_public_detail(opp)
        assert not any(key in detail["metadata"] for key in _PUBLICATION_KEYS)
        card = _match_card(opp)
        assert "recent_works" not in card and "publication_attribution_status" not in card
        # The e-mail flow validates against the detail projection; the raw row
        # is refused by the same rule.
        for target in (detail, opp):
            assert email_research_works(target) == []
            for work in opp["metadata"]["recent_works"]:
                with pytest.raises(ValueError):
                    validate_paper_reading(_reading(work), target)

    def test_an_old_list_reaches_no_writing_flow_and_a_recent_one_still_does(self, monkeypatch):
        from backend.routes import matches, tailor
        from backend.routes.cold_email import _build_email_corpus, _professor_anchors, _render_professor_brief
        from backend.routes.opportunities import _build_chat_system_prompt
        from src.matcher.ranker import MatchResult
        from src.recommender.cold_email import _common_parts

        profile = {"name": "Eric", "year": "freshman", "major": "CompE", "school": "UIUC",
                   "hard_skills": ["Python"], "research_interests_text": "brain-computer interfaces"}
        lookup = {"old": {**_verified(_aged(11)), "id": "old"}, "kept": {**_verified(_aged(9, 27)), "id": "kept"}}
        for opp, shown in ((lookup["old"], False), (lookup["kept"], True)):
            parts = _common_parts(profile, opp)
            assert bool(parts["recent_works"]) is shown
            assert ("Zebrafinch" in _build_chat_system_prompt(opp, None)) is shown
            assert ("Zebrafinch" in _render_professor_brief(parts, opp)) is shown
            assert ("zebrafinch" in _build_email_corpus(parts, opp)) is shown
            assert ("zebrafinch" in _professor_anchors(parts, opp)) is shown
            anchors = tailor._snapshot_anchors(opp, opp)
            assert any(anchor.evidence["field"] == "paper_title" for anchor in anchors) is shown

        captured = {}
        monkeypatch.setattr(matches, "_resolve", lambda *a, **k: object())

        def fake_score(query, cand):
            captured["cand"] = dict(cand)
            return {c[0]: {"s": 50.0, "r": ""} for c in cand}

        monkeypatch.setattr(matches, "_llm_score_candidates", fake_score)
        results = [
            MatchResult(opportunity_id=i, eligibility_score=50, readiness_score=50,
                        upside_score=50, final_score=50.0, bucket="good_match",
                        reasons_fit=[], reasons_gap=[], next_steps=[])
            for i in lookup
        ]
        matches.llm_rerank({"research_interests_text": "recent-lists-query"}, results, lookup)
        assert "Zebrafinch" in captured["cand"]["kept"]
        assert "Zebrafinch" not in captured["cand"]["old"]

    def test_newest_paper_nine_years_old_serves_the_whole_list_as_before(self):
        from backend.lib.email_contact_context import validate_paper_reading
        from backend.lib.public_opportunity_detail import project_public_detail
        from backend.routes.matches import _match_card

        opp = _verified(_aged(9, 27))
        works = opp["metadata"]["recent_works"]
        assert verified_recent_works(opp) == works
        detail, card = project_public_detail(opp), _match_card(opp)
        assert detail["metadata"]["recent_works"] == works
        assert detail["metadata"]["publication_attribution_status"] == VERIFIED_AUTHOR_ID
        assert detail["metadata"]["publication_author_id"] == "https://openalex.org/A123"
        assert card["recent_works"] == works and card["publication_attribution_status"] == VERIFIED_AUTHOR_ID
        # The list is shown whole: its 27-year-old paper can still be chosen.
        for work in works:
            validate_paper_reading(_reading(work), detail)

    @pytest.mark.parametrize("works", [[], None])
    def test_a_record_without_papers_is_unchanged(self, works):
        from backend.lib.public_opportunity_detail import project_public_detail
        from backend.routes.matches import _match_card

        opp = _verified(works)
        assert verified_recent_works(opp) == []
        detail, card = project_public_detail(opp), _match_card(opp)
        assert detail["metadata"]["publication_attribution_status"] == VERIFIED_AUTHOR_ID
        assert detail["metadata"]["publication_author_id"] == "https://openalex.org/A123"
        assert detail["metadata"].get("recent_works") == works
        assert "recent_works" not in card and "publication_attribution_status" not in card

    @pytest.mark.parametrize("works", [_aged(9, 27), _aged(0), [], None])
    def test_recent_and_empty_lists_have_the_payloads_they_had_without_the_rule(self, works, monkeypatch):
        import src.publication_trust as trust
        from backend.lib.public_opportunity_detail import project_public_detail
        from backend.routes.matches import _match_card

        opp = _verified(works)
        detail, card = project_public_detail(opp), _match_card(opp)
        monkeypatch.setattr(trust, "RECENT_WORKS_MAX_AGE_YEARS", 10**6)
        assert project_public_detail(opp) == detail and _match_card(opp) == card

    def test_the_boundary_is_the_calendar_year(self):
        from src.publication_trust import newest_work_is_recent

        works = [{"title": "Zebrafinch Syrinx Imaging", "year": 2016}, {"title": "An Older One", "year": 1999}]
        opp = _verified(works)
        # Ten years back is still shown, on the first and the last day of the year.
        for today in (date(2026, 1, 1), date(2026, 12, 31)):
            assert newest_work_is_recent(works, today=today)
            assert verified_recent_works(opp, today=today) == works
        # The next 1 January it is eleven years old.
        assert not newest_work_is_recent(works, today=date(2027, 1, 1))
        assert verified_recent_works(opp, today=date(2027, 1, 1)) == []

    def test_a_list_with_no_readable_year_is_not_served(self):
        for works in ([{"title": "Undated"}], [{"title": "Undated", "year": None}],
                      [{"title": "Year as text", "year": str(datetime.now(UTC).year)}],
                      [{"title": "Year as a flag", "year": True}]):
            assert verified_recent_works(_verified(works)) == [], works
        # One readable recent year is enough, and the undated paper stays on the list.
        mixed = [{"title": "Undated"}, *_aged(3)]
        assert verified_recent_works(_verified(mixed)) == mixed

    @pytest.mark.parametrize("school", ["bc", "emory", "georgetown", "nyu", "tufts", "uga", "unc", "uva"])
    def test_a_school_another_maintainer_built_takes_the_rule(self, school):
        # Until 2026-11-24 these schools' lists were served whatever their age (M159).
        from backend.lib.public_opportunity_detail import project_public_detail

        old = _verified(_aged(11), school=school)
        assert verified_recent_works(old) == []
        assert not any(key in project_public_detail(old)["metadata"] for key in _PUBLICATION_KEYS)
        kept = _verified(_aged(10), school=school)
        assert verified_recent_works(kept) == kept["metadata"]["recent_works"]
        assert project_public_detail(kept)["metadata"]["recent_works"] == kept["metadata"]["recent_works"]


def test_reviewed_namesakes_removed_from_detail_cards_writing_and_legacy_replay():
    from backend.lib.public_opportunity_detail import project_public_detail
    from backend.routes.matches import _match_card
    from src.collectors.openalex_enrich import apply_works

    bad = {"title": "Simulation and experimental study on laser cutting of C/C composite finger seal", "year": 2025}
    other_bad = {"title": "MHD Simulation of Vacuum Arcs Distribution Characteristics under Critical Short Circuit Interrupting Current", "year": 2025}
    old = _verified([bad, other_bad], id="faculty-asu-ece-36055db6")
    assert verified_recent_works(old) == []
    assert "recent_works" not in project_public_detail(old)["metadata"]
    assert "recent_works" not in _match_card(old)
    assert old["metadata"]["recent_works"] == [bad, other_bad]
    assert verified_recent_works({**old, "id": "other-person"}) == [bad, other_bad]
    retained = {"title": "New Insights on Workplace Mistreatment", "year": 2025}
    wrong = {"title": "Day-Ahead Load Forecasting Using MSTL-VMD-Based Multi-Seasonal Decomposition and LSTM-Based Component-Wise Prediction", "year": 2026}
    mixed = _verified([wrong, retained], id="faculty-tamu-mays-2157ba4d", url="https://mays.tamu.edu/directory/sijun-kim/")
    assert verified_recent_works(mixed) == [retained]
    assert project_public_detail(mixed)["metadata"]["recent_works"] == [retained]
    assert _match_card(mixed)["recent_works"] == [retained]
    assert apply_works([mixed], {mixed["url"]: [wrong, retained]}) == 1
    assert mixed["metadata"]["recent_works"] == [retained]
    assert apply_works([mixed], {mixed["url"]: [wrong, retained]}) == 0
