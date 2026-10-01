"""Evidence-mapped résumé rewrites: anchors, links, the closed vocabulary, the locks and the review.

Provider-free. The routes that use this module are tested in test_tailor_review.py
(Tailor, renovation, re-optimize) and test_target_resume_ai.py (full target).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.lib import evidence_map as em
from backend.lib.blocking import BlockingWorkTimeout
from backend.lib.target_resume_ai_grounding import RESUME_VERB_FORMS
from src.evidence import _faculty_profile_summary

CASES = json.loads((Path(__file__).parent / "fixtures" / "evidence_map_cases.json").read_text())["cases"]
AREAS = ("Image-guided adaptive radiation therapy, Functional image-based tumor response assessment and "
         "predication, Task-based medical imaging quality assessment, Medical imaging and image analysis for "
         "diagnosis and radiation therapy, Deep learning for clinical decision-making, Bioimaging at Multi-Scale")


def faculty(**metadata):
    return {"id": "faculty-x", "source_type": "faculty_research", "pi_name": "Hua Li", "department": "Bioengineering",
            "organization": "University of Illinois Urbana-Champaign", "keywords": ["radiation", "imaging", "tumor"],
            "metadata": metadata}


def anchors_for(texts):
    return {f"t{i}": em.Anchor(f"t{i}", {"field": "description", "requirement_index": None, "start": 0,
                                         "end": len(text), "quote": text})
            for i, text in enumerate(texts, start=1) if text}


class TestAnchors:
    @pytest.mark.parametrize("status", [None, "not_accepting_undergraduates", "research_inactive"])
    def test_a_stated_research_areas_list_is_the_only_quotable_faculty_text(self, status):
        record = faculty(research_areas_raw=AREAS, **({"faculty_availability_status": status} if status else {}))
        description = _faculty_profile_summary(record)
        anchors = em.opportunity_anchors(description, [], research_areas=AREAS)
        assert [anchor.text for anchor in anchors] == [area.strip() for area in AREAS.split(",")]
        for anchor in anchors:
            evidence = anchor.evidence
            assert description[evidence["start"]:evidence["end"]] == evidence["quote"]
            assert "Faculty research profile" not in anchor.text and "Contact this" not in anchor.text
            assert "source profile" not in anchor.text

    @pytest.mark.parametrize("status", [None, "not_accepting_undergraduates", "research_inactive"])
    def test_keywords_printed_as_research_areas_are_never_quotable(self, status):
        # _faculty_profile_summary writes the first 6 keywords when no areas were
        # scraped; some are OpenAlex topics with no inference stamp.
        record = faculty(**({"faculty_availability_status": status} if status else {}))
        description = _faculty_profile_summary(record)
        assert "Research areas: radiation, imaging, tumor" in description
        assert em.opportunity_anchors(description, []) == []
        assert em.opportunity_anchors(description, [], research_areas="radiation, imaging") == []

    def test_a_faculty_template_without_areas_has_no_anchor(self):
        description = _faculty_profile_summary({**faculty(), "keywords": []})
        assert em.opportunity_anchors(description, [], research_areas="") == []

    def test_a_semicolon_list_splits_on_semicolons(self):
        areas = "Soil ecology; nitrogen cycling in prairie soils; microbial community assembly"
        description = _faculty_profile_summary(faculty(research_areas_raw=areas))
        assert [a.text for a in em.opportunity_anchors(description, [], research_areas=areas)] == [
            "Soil ecology", "nitrogen cycling in prairie soils", "microbial community assembly"]

    def test_a_posting_splits_into_sentences_and_requirements(self):
        description = ("The Brooks lab studies photosynthesis and nitrogen metabolism. Duties include growing plants "
                       "and analyzing data. For more information, including how to apply, please see full blog posting.")
        anchors = em.opportunity_anchors(description, ["PCR", "Python"])
        assert [a.text for a in anchors] == [
            "The Brooks lab studies photosynthesis and nitrogen metabolism",
            "Duties include growing plants and analyzing data", "PCR", "Python"]
        assert anchors[2].evidence == {"field": "requirement", "requirement_index": 0, "start": 0, "end": 3,
                                       "quote": "PCR"}
        assert [a.id for a in anchors] == ["t1", "t2", "t3", "t4"]

    def test_urls_and_emails_are_cut_out_of_an_anchor(self):
        description = "Apply via https://lab.example.edu/join or write to pi@example.edu about sleep and memory studies."
        texts = [a.text for a in em.opportunity_anchors(description, [])]
        assert all("http" not in text and "@" not in text for text in texts)
        assert "about sleep and memory studies" in texts

    def test_a_long_sentence_splits_at_commas_and_the_list_is_capped(self):
        long = ", ".join(f"topic number {i} in bioinformatics" for i in range(8)) + "."
        assert all(len(a.text) <= em.MAX_ANCHOR_CHARACTERS for a in em.opportunity_anchors(long, []))
        many = " ".join(f"Topic {i} is studied here." for i in range(80))
        assert len(em.opportunity_anchors(many, [])) == em.MAX_ANCHORS

    def test_verified_paper_titles_are_anchors(self):
        anchors = em.opportunity_anchors("", [], paper_titles=["Deep learning for dose prediction"])
        assert anchors[0].evidence == {"field": "paper_title", "paper_index": 0, "start": 0, "end": 33,
                                       "quote": "Deep learning for dose prediction"}

    def test_full_target_anchors_use_available_research_and_lab_only(self):
        research = {"status": "available", "snapshot": {"works": [{"title": "Sleep and memory in aging"}]}}
        lab = {"status": "available", "snapshot": {"pages": [{"sections": [
            {"heading": "Methods", "text": "We use EEG. We run sleep studies."}]}]}}
        target = {"description": "", "requirements": ["EEG"], "context_version": 4, "research": research, "lab": lab}
        fields = [(a.evidence["field"], a.text) for a in em.target_anchors(target)]
        assert fields == [("requirement", "EEG"), ("paper_title", "Sleep and memory in aging"),
                          ("lab_heading", "Methods"), ("lab_text", "We use EEG"), ("lab_text", "We run sleep studies")]
        stale = {**target, "research": {**research, "status": "stale"}, "lab": {**lab, "status": "stale"}}
        assert [a.text for a in em.target_anchors(stale)] == ["EEG"]


class TestSpans:
    @pytest.mark.parametrize(("anchor", "term", "found"), [
        ("Robotics", "R", False), ("Robotics", "robotics", True),
        ("Age-related Differences", "Age", False), ("Age-related Differences", "age-related differences", True),
        ("Aging in Place", "Aging in", False), ("Aging in Place", "Aging in Place", True),
        ("Pathogens and biofilms in drinking water", "drinking water", True),
        ("饮用水管网中的病原体", "病原体", True),
        ("one two three four five six seven", "one two three four five six seven", False),
    ])
    def test_terms_are_word_bounded_with_no_stopword_edges(self, anchor, term, found):
        assert (em.term_span(anchor, term) is not None) is found

    def test_source_spans_tolerate_case_and_spacing_but_not_paraphrase(self):
        original = "Ran PCR  genotyping on 40 lines"
        assert em.source_span(original, "pcr genotyping") == (4, 19)
        assert em.source_span(original, "PCR genotype") is None
        assert em.source_span(original, "on 40 lines") is None


class TestLemma:
    def test_every_form_of_every_resume_verb_shares_one_lemma(self):
        bases = sorted({base for base, _ in RESUME_VERB_FORMS.values()})
        assert len(bases) >= 150
        for form, (base, _) in RESUME_VERB_FORMS.items():
            assert em.lemma(form) == em.lemma(base), (form, base)

    @pytest.mark.parametrize(("left", "right"), [
        ("writing", "wrote"), ("making", "made"), ("studying", "studied"), ("images", "imaging"),
        ("scripts", "script"), ("analyses", "analyses"),
    ])
    def test_both_sides_normalize_the_same_way(self, left, right):
        assert em.lemma(left) == em.lemma(right)

    def test_quantity_status_and_personal_words_are_visible(self):
        assert {em.lemma(word) for word in ("over", "since", "per")} <= set(
            em.tokens("over 200 samples since 2024, 3 per week"))
        assert {"中", "已"} <= set(em.tokens("撰写中；已投稿；本人负责"))
        assert em.personal_markers("I built it; my part; 本人负责；我们") == 3


class TestEnvelope:
    ROW = {"unit_id": "b1", "links": [], "decision": "keep", "ops": [], "text": None, "keep_reason": "no_link"}

    def test_a_model_that_corrects_itself_is_read_by_its_last_answer(self):
        first = json.dumps({"bullets": [{**self.ROW, "decision": "rewrite", "text": "x", "keep_reason": None}]})
        second = json.dumps({"bullets": [self.ROW]})
        raw = f"{first}\n\nWait, verb_first does not apply here. Let me correct this output.\n\n{second}"
        assert em.parse_rows(raw, {"b1"}, key="bullets") == {"b1": self.ROW}
        assert em.parse_rows(f"{second}\nThat is my answer.", {"b1"}, key="bullets") == {"b1": self.ROW}

    @pytest.mark.parametrize("raw", ["no JSON at all", '{"units": []}', '{"bullets": {}}', '{"bullets": [], "extra": 1}'])
    def test_an_unusable_reply_is_none(self, raw):
        assert em.parse_rows(raw, {"b1"}, key="bullets") is None


class TestLinks:
    def test_only_literal_links_survive_and_same_needs_a_shared_word(self):
        anchors = anchors_for(["Specific techniques include PCR and cloning", "Deep learning for imaging"])
        raw = [
            {"id": "L1", "anchor": "t1", "term": "PCR", "source": "PCR genotyping", "relation": "same"},
            {"id": "L2", "anchor": "t2", "term": "Deep learning", "source": "image classifier", "relation": "same"},
            {"id": "L3", "anchor": "t9", "term": "PCR", "source": "PCR genotyping", "relation": "same"},
            {"id": "L4", "anchor": "t1", "term": "RNA", "source": "PCR genotyping", "relation": "same"},
        ]
        links = em.verify_links(raw, [(None, "Ran PCR genotyping and an image classifier")], anchors)
        assert [(link.id, link.relation) for link in links] == [("L1", "same"), ("L2", "broader")]
        assert links[0].target_evidence["quote"] == "PCR" and links[0].target_evidence["start"] == 28
        assert links[0].source_evidence == {"start": 4, "end": 18, "quote": "PCR genotyping"}

    def test_a_fourth_link_is_ignored(self):
        anchors = anchors_for(["alpha beta gamma delta"])
        raw = [{"id": f"L{i}", "anchor": "t1", "term": term, "source": term, "relation": "same"}
               for i, term in enumerate(["alpha", "beta", "gamma", "delta"], start=1)]
        assert len(em.verify_links(raw, [(None, "alpha beta gamma delta")], anchors)) == 3


class TestContract:
    @pytest.mark.parametrize("case", CASES, ids=lambda case: case["label"])
    def test_declared_maps(self, case):
        anchors = anchors_for(case["anchors"])
        unit = em.Unit("b1", case["original"], case["original"])
        row = {"unit_id": "b1", "links": case["links"], "decision": "rewrite", "ops": case["ops"],
               "text": case["rewrite"], "keep_reason": None}
        outcome = em.check_rewrite(unit, row, anchors,
                                   output_language=case.get("output") or em.language(case["original"]))
        if outcome.status == "pending":
            outcome = em.gate(outcome, unit)
        status, code, detail = case["expected"]
        assert (outcome.status, outcome.code) == (status, code), outcome
        assert detail is None or (outcome.detail or "").startswith(detail), outcome.detail

    def test_the_calibration_disabled_moves_are_refused(self):
        refused = [case for case in CASES if case["expected"][2] in ("relabel_not_same", "unknown_op")]
        assert len(refused) >= 14

    @pytest.mark.parametrize(("decision", "links", "text", "keep_reason"), [
        ("keep", [], "Built it.", "no_link"), ("keep", [], None, "maybe"), ("rewrite", [], None, None),
        ("rewrite", [], "  ", None), ("drop", [], None, None),
    ])
    def test_a_malformed_row_is_invalid(self, decision, links, text, keep_reason):
        unit = em.Unit("b1", "Built a rover.", "Built a rover.")
        row = {"unit_id": "b1", "links": links, "decision": decision, "ops": [], "text": text,
               "keep_reason": keep_reason}
        assert em.check_rewrite(unit, row, {}, output_language="en").status == "invalid"
        assert em.check_rewrite(unit, {**row, "extra": 1}, {}, output_language="en").status == "invalid"

    def test_a_row_may_leave_out_the_fields_its_decision_makes_null(self):
        anchors = anchors_for(["Python"])
        unit = em.Unit("b1", "Wrote parser tests using Python.", "Wrote parser tests using Python.")
        keep = {"unit_id": "b1", "decision": "keep"}
        assert em.check_rewrite(unit, keep, anchors, output_language="en").code == "no_link"
        rewrite = {"unit_id": "b1", "decision": "rewrite", "ops": [{"op": "lead_with", "link": "L1"}],
                   "links": [{"id": "L1", "anchor": "t1", "term": "Python", "source": "Python", "relation": "same"}],
                   "text": "Using Python, wrote parser tests."}
        assert em.check_rewrite(unit, rewrite, anchors, output_language="en").status == "pending"

    def test_an_unchanged_rewrite_is_a_keep(self):
        # A model that "translates" a line already in the output language returns it as written.
        unit = em.Unit("b1", "本人负责浊度和 pH 测定。", "本人负责浊度和 pH 测定。")
        row = {"unit_id": "b1", "links": [], "decision": "rewrite", "ops": [{"op": "translate"}],
               "text": " 本人负责浊度和 pH 测定。", "keep_reason": None}
        outcome = em.check_rewrite(unit, row, {}, output_language="zh")
        assert (outcome.status, outcome.code, outcome.detail) == ("kept", "cosmetic_only", "unchanged_text")

    def test_the_server_names_a_keep(self):
        anchors = anchors_for(["PCR genotyping of mutant lines", "Protein folding"])
        unit = em.Unit("b1", "PCR genotyping of 40 lines; maintained stocks.", "PCR genotyping of 40 lines; maintained stocks.")
        row = {"unit_id": "b1", "decision": "keep", "ops": [], "text": None, "keep_reason": "already_aligned"}
        same = [{"id": "L1", "anchor": "t1", "term": "PCR genotyping", "source": "PCR genotyping", "relation": "same"}]
        assert em.check_rewrite(unit, {**row, "links": []}, anchors, output_language="en").code == "no_link"
        assert em.check_rewrite(unit, {**row, "links": same}, anchors, output_language="en").code == "already_aligned"
        other = [{"id": "L1", "anchor": "t1", "term": "mutant lines", "source": "40 lines", "relation": "same"}]
        assert em.check_rewrite(unit, {**row, "links": other}, anchors, output_language="en").code == "no_safe_change"


class TestGate:
    ROVER = ("Built the drivetrain for the Illini Robotics club rover in 2025 with two teammates; I designed the "
             "motor mount in SolidWorks.")

    def test_a_declared_relabel_is_read_back_for_object_and_quantity_only(self):
        original = "Built a PyTorch image classifier for chest X-ray triage."
        model = "Built a PyTorch computer vision model for chest X-ray triage."
        assert "object_changed" in em.rewrite_findings(model, original, [])
        assert em.rewrite_findings(model, original, [("image classifier", "computer vision model")]) == []
        assert "relabel_not_found" in em.rewrite_findings(model, original, [("image classifier", "vision system")])

    def test_a_denial_and_a_team_result_come_from_the_text_as_written(self):
        original = "I built a Python parser. I did not build the compiler."
        assert "denied_action_asserted" in em.rewrite_findings(
            "I built a compiler. I did not build the compiler.", original, [("Python parser", "compiler")])

    def test_a_hard_finding_keeps_the_original_with_the_findings(self):
        unit = em.Unit("b1", "Cleaned 212 survey responses in R.", "Cleaned 212 survey responses in R.")
        pending = em.Outcome("b1", "pending", text="Cleaned 212 survey responses in Python.", ops=["verb_first"])
        kept = em.gate(pending, unit)
        assert (kept.status, kept.code) == ("kept", "rewrite_rejected") and "python" in kept.findings

    def test_the_alternative_takes_the_posting_term_back_out(self):
        anchors = anchors_for(["Survey data dashboards for public health"])
        original = "Built a dashboard in R for the campus food pantry's survey."
        unit = em.Unit("b1", original, original)
        ops = [{"op": "relabel", "link": "L1", "from": "survey", "to": "survey data"}, {"op": "lead_with", "link": "L1"}]
        row = {"unit_id": "b1", "decision": "rewrite", "ops": ops, "keep_reason": None,
               "links": [{"id": "L1", "anchor": "t1", "term": "survey data", "source": "survey", "relation": "same"}],
               "text": "Survey data: built a dashboard in R for the campus food pantry."}
        outcome = em.check_rewrite(unit, row, anchors, output_language="en")
        assert outcome.status == "kept"  # "survey data" leads, but the pantry's survey is not "survey data"
        row["text"] = "Built a survey data dashboard in R for the campus food pantry."
        row["ops"] = [{"op": "relabel", "link": "L1", "from": "survey", "to": "survey data"}]
        unit = em.Unit("b1", "Built a survey dashboard in R for the campus food pantry.",
                       "Built a survey dashboard in R for the campus food pantry.")
        row["links"][0]["source"] = "survey dashboard"
        outcome = em.gate(em.check_rewrite(unit, row, anchors, output_language="en"), unit)
        assert outcome.status == "pending"
        # Without the term only the student's words remain, unchanged: nothing to offer.
        assert em.without_terms(outcome, unit, row["ops"]) is None


class TestSupport:
    """Lines of the same activity the student confirmed may lend their own clauses, word for word."""
    ORIGINAL = "My team built a Python parser; I wrote parser tests."
    SUPPORT = "I ran 12 parser test cases."

    def check(self, text, support=True, ops=("personal_first",)):
        unit = em.Unit("b1", self.ORIGINAL, self.ORIGINAL, support=(("b2", self.SUPPORT),) if support else ())
        row = {"unit_id": "b1", "links": [], "decision": "rewrite", "ops": [{"op": op} for op in ops],
               "text": text, "keep_reason": None}
        outcome = em.check_rewrite(unit, row, {}, output_language="en")
        return em.gate(outcome, unit) if outcome.status == "pending" else outcome

    def test_a_confirmed_clause_may_join_an_allowed_move_and_counts_toward_the_length(self):
        merged = "I wrote parser tests and ran 12 parser test cases; my team built a Python parser."
        assert len(merged) > 1.25 * len(self.ORIGINAL) + 12
        assert self.check(merged).status == "pending"
        assert self.check(merged, support=False).detail.startswith("added:")

    def test_a_merge_still_needs_an_allowed_move(self):
        merged = "My team built a Python parser; I wrote parser tests. I ran 12 parser test cases."
        assert (self.check(merged, ops=()).code, self.check(merged, ops=()).detail) == (
            "beyond_allowed_edit", "no_substantive_op")

    @pytest.mark.parametrize("text", [
        "I wrote 12 parser tests; my team built a Python parser.",  # the support's number on the unit's action
        "I wrote parser tests and ran 12 parser test cases; I built a Python parser.",  # the team's work as mine
    ])
    def test_a_fact_moved_between_confirmed_lines_is_rejected(self, text):
        assert self.check(text).code in ("rewrite_rejected", "beyond_allowed_edit")
        assert self.check(text).status == "kept"


def _reply(verdicts):
    return json.dumps({"verdicts": verdicts})


def _link(ident="L1"):
    return em.Link(ident, "same", "PCR", "PCR genotyping", {"field": "requirement", "requirement_index": 0,
                                                            "start": 0, "end": 3, "quote": "PCR"},
                   {"start": 4, "end": 18, "quote": "PCR genotyping"})


class TestReview:
    def test_the_payload_carries_links_only_where_there_are_some(self):
        pairs = [em.ReviewPair("a", "b"), em.ReviewPair("c", "d", (_link(),))]
        assert em.review_payload(pairs) == {"pairs": [
            {"index": 1, "original": "a", "rewrite": "b"},
            {"index": 2, "original": "c", "rewrite": "d", "links": [
                {"id": "L1", "source": "PCR genotyping", "target_term": "PCR", "written_as": None}]}]}

    @pytest.mark.parametrize(("verdict", "accepted"), [
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": [{"id": "L1", "entailed": True}]}, True),
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": [{"id": "L1", "entailed": False}]}, False),
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": []}, False),
        ({"index": 1, "changes": "[ok]", "faithful": True}, False),
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": [{"id": "L1", "entailed": True},
                                                                       {"id": "L2", "entailed": True}]}, False),
        ({"index": 1, "changes": "[ok]", "faithful": "true", "links": [{"id": "L1", "entailed": True}]}, False),
        ({"index": 1, "changes": "moved [2]", "faithful": True, "links": [{"id": "L1", "entailed": True}]}, False),
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": [{"id": ["L1"], "entailed": True}]}, False),
        ({"index": 2, "changes": "[ok]", "faithful": True, "links": [{"id": "L1", "entailed": True}]}, False),
    ])
    def test_a_rewrite_passes_only_when_faithful_and_every_link_entailed(self, monkeypatch, verdict, accepted):
        monkeypatch.setattr(em, "chat_completion", lambda *_a, **_k: _reply([verdict]))
        link = _link()
        assert em.ai_review([em.ReviewPair("o", "r", (link,))]) == ["accepted" if accepted else "rejected"]
        assert link.entailed is accepted

    @pytest.mark.parametrize("raw", ["not json", json.dumps([{"index": 1, "faithful": True}]),
                                     _reply([{"index": 1, "faithful": True, "links": []},
                                             {"index": 1, "faithful": False, "links": []}])])
    def test_malformed_or_conflicting_verdicts_reject(self, monkeypatch, raw):
        monkeypatch.setattr(em, "chat_completion", lambda *_a, **_k: raw)
        assert em.ai_review([em.ReviewPair("o", "r")]) == ["rejected"]

    def test_no_answer_is_unavailable_not_rejected(self, monkeypatch):
        monkeypatch.setattr(em, "chat_completion", lambda *_a, **_k: None)
        assert em.ai_review([em.ReviewPair("o", "r")]) is None
        assert asyncio.run(em.review_rewrites([em.ReviewPair("o", "r")], em.time.monotonic())) == ["unavailable"]

    def test_the_review_is_skipped_without_time_and_bounded_by_what_is_left(self, monkeypatch):
        calls = []
        monkeypatch.setattr(em, "chat_completion",
                            lambda *_a, **kwargs: calls.append(kwargs) or _reply([{"index": 1, "faithful": True}]))
        clock = {"now": 1000.0}
        monkeypatch.setattr(em, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
        started = 1000.0 - 52.0
        assert asyncio.run(em.review_rewrites([em.ReviewPair("o", "r")], started)) == ["unavailable"]
        assert calls == []
        started = 1000.0 - 38.0
        assert asyncio.run(em.review_rewrites([em.ReviewPair("o", "r")], started)) == ["accepted"]
        assert calls[0]["deadline"] == pytest.approx(1017.0) and calls[0]["request_timeout"] == 45.0

    def test_a_timeout_is_unavailable(self, monkeypatch):
        async def timeout(*_args, **_kwargs):
            raise BlockingWorkTimeout("slow")

        monkeypatch.setattr(em, "run_blocking", timeout)
        assert asyncio.run(em.review_rewrites([em.ReviewPair("o", "r")], em.time.monotonic())) == ["unavailable"]

    def test_the_review_prompt_keeps_every_calibrated_rule_and_asks_about_links(self):
        for phrase in ("keeps the doer and the share the original gives it", "does not make a finished verb faithful",
                       "even when the rest is a plain trim", "must be a faithful translation",
                       "Tag each change with the rule it breaks", "entailed=true only if",
                       "A pair with any entailed=false is faithful=false"):
            assert phrase in em.REVIEW_SYSTEM_PROMPT, phrase
