"""Publication trust boundary — fail-closed attribution gating.

Product rule: a publication may influence professor-specific output ONLY when
``metadata.publication_attribution_status == "verified_author_id"``. Anything
else — name_match, absent (legacy), pending, rejected, junk, wrong-typed —
must be excluded from Match reason, Ask AI, Resume personalization, and Cold
Email, plus the served API payloads. These tests exercise the real feature
paths, not just the centralized helper.
"""
from __future__ import annotations

from src.publication_trust import (
    NAME_MATCH,
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
UNVERIFIED_STATUSES = (
    NAME_MATCH, None, "", "pending", "rejected", "unknown",
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
        assert "NeuroFlow" in generate_cold_email(profile, _opp(VERIFIED_AUTHOR_ID))
        for status in (NAME_MATCH, "__absent__", "pending"):
            opp = _opp(status) if status != "__absent__" else _opp()
            text = generate_cold_email(profile, opp)
            assert "NeuroFlow" not in text
            assert "caught my attention" not in text


class TestResumeSurface:
    def test_tailor_prompt_never_contains_paper_titles(self, monkeypatch):
        # Resume tailoring reads no publication data by design; pin it so a
        # future prompt change cannot quietly re-introduce paper titles —
        # verified or not, papers are not resume-personalization evidence
        # (they never describe the STUDENT's work).
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
        for opp in (_opp(VERIFIED_AUTHOR_ID), _opp(NAME_MATCH), _opp()):
            captured.clear()
            tailor._ai_tailor_bullets(profile, opp, ["Built a Python EEG parser"])
            joined = " ".join(m["content"] for m in captured["messages"])
            assert "NeuroFlow" not in joined
            assert "Cortical Signal Denoising" not in joined

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

        from backend.routes import opportunities as op

        assert "works_are_verified" in inspect.getsource(op._redact)
        assert "recent_works" in op._UNVERIFIED_PUBLICATION_KEYS
        src_batch = inspect.getsource(op.get_opportunities_batch)
        src_similar = inspect.getsource(op.get_similar_opportunities)
        src_detail = inspect.getsource(op.get_opportunity)
        for s in (src_batch, src_similar, src_detail):
            assert "_redact" in s
