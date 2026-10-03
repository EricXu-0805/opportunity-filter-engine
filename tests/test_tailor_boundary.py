"""Targeted Resume Tailor trust/control/data-isolation boundary (W13).

The boundary: tailor = specific target + user-confirmed resume facts +
transparent, evidence-backed suggestions + explicit user control. The system
must never invent resume facts (including bare-number metrics), show
fabricated evidence quotes, silently apply suggestions, mix targets, claim
saved state falsely, or expose document-round-trip renovation capabilities.

Client-side halves (save truthfulness, target-response guard, draft
staleness) are pinned by TailorModal.test.tsx / ResumeRenovationModal.test.tsx.
This suite covers: the numeric grounding policy, evidence-quote verification,
target/provenance response stamps, and the document round-trip tripwire.
Existing suites already pin target-required-404s, the student-side-only
corpus, verbatim extraction, and prompt-injection guards
(tests/test_tailor_route.py, tests/test_resume_renovation.py).
"""
from __future__ import annotations

from pathlib import Path

from backend.lib.evidence_map import Anchor, verify_links
from backend.lib.grounding import (
    LENIENT_PROSE,
    LENIENT_PROSE_NUMERIC,
    validate_no_fabrication,
)
from backend.routes.tailor import TAILOR_PIPELINE_VERSION

_REPO = Path(__file__).resolve().parents[1]

_CORPUS = (
    "computer science uiuc python experienced cs 225 "
    "built a data pipeline processing 10,000 records in python"
)


# ---------------------------------------------------------------------------
# Numeric fact boundary: rewrites cannot invent metrics
# ---------------------------------------------------------------------------

class TestNumericGrounding:
    def test_invented_percent_metric_is_rejected(self):
        ok, fab = validate_no_fabrication(
            "Improved throughput 45% with a Python pipeline",
            _CORPUS, policy=LENIENT_PROSE_NUMERIC,
        )
        assert not ok and "45" in fab

    def test_student_stated_metric_passes(self):
        ok, _ = validate_no_fabrication(
            "Processed 10,000 records with a Python pipeline",
            _CORPUS, policy=LENIENT_PROSE_NUMERIC,
        )
        assert ok

    def test_reformatted_grouping_still_matches(self):
        # "10000" vs the corpus "10,000": grouping punctuation is normalized,
        # so honest reformatting isn't punished.
        ok, _ = validate_no_fabrication(
            "Processed 10000 records", _CORPUS, policy=LENIENT_PROSE_NUMERIC,
        )
        assert ok

    def test_invented_year_is_rejected(self):
        ok, fab = validate_no_fabrication(
            "Led the 2023 migration in Python", _CORPUS,
            policy=LENIENT_PROSE_NUMERIC,
        )
        assert not ok and "2023" in fab

    def test_prose_policy_is_unchanged_for_other_surfaces(self):
        # Cold email keeps plain LENIENT_PROSE — this suite must not silently
        # change that contract (a deliberate residual, documented in W12/W13).
        ok, _ = validate_no_fabrication(
            "Improved throughput 45%", _CORPUS, policy=LENIENT_PROSE,
        )
        assert ok

    def test_course_numbers_in_corpus_pass(self):
        ok, _ = validate_no_fabrication(
            "Applied CS 225 data structures in Python", _CORPUS,
            policy=LENIENT_PROSE_NUMERIC,
        )
        assert ok


# ---------------------------------------------------------------------------
# Evidence quotes: shown only when they exist in the student's own bullet
# ---------------------------------------------------------------------------

class TestEvidenceVerification:
    """A link's student-side quote is a literal span of that bullet, found by
    the server; the model's word is never taken for it. Profile fields are not
    quotable at all."""

    BULLET = "Built a data pipeline in Python for CS 225"
    ANCHORS = {"t1": Anchor("t1", {"field": "description", "requirement_index": None, "start": 0, "end": 27,
                                   "quote": "Data pipelines and Kubernetes"})}

    def _quote(self, source):
        links = verify_links([{"id": "L1", "anchor": "t1", "term": "Data pipelines", "source": source,
                               "relation": "same"}], [(None, self.BULLET)], self.ANCHORS)
        return links[0].source_evidence["quote"] if links else ""

    def test_real_quote_is_kept_with_server_offsets(self):
        assert self._quote("data pipeline") == "data pipeline"

    def test_fabricated_quote_is_blanked(self):
        assert self._quote("Deployed production AWS pipelines") == ""

    def test_composite_of_real_facts_is_not_a_quote(self):
        assert self._quote("Python; CS 225") == ""

    def test_profile_skill_is_not_a_quote(self):
        assert self._quote("Python (experienced)") == ""

    def test_word_order_matters(self):
        assert self._quote("pipeline data a Built") == ""


# ---------------------------------------------------------------------------
# Target binding + provenance stamps
# ---------------------------------------------------------------------------

class TestResponseProvenance:
    def test_pipeline_version_constant(self):
        assert TAILOR_PIPELINE_VERSION

    def test_response_schemas_carry_target_echo(self):
        from backend.schemas import (
            BulletOptimizeResponse,
            RenovateResponse,
            TailorResponse,
        )
        for model in (TailorResponse, RenovateResponse, BulletOptimizeResponse):
            fields = model.model_fields
            assert "opportunity_id" in fields, model.__name__
            assert "generated_at" in fields, model.__name__
            assert "pipeline_version" in fields, model.__name__


# ---------------------------------------------------------------------------
# MTP Renovate boundary: document round-trip must not ship silently
# ---------------------------------------------------------------------------

class TestDocumentRoundTripTripwire:
    def test_full_document_export_has_its_own_product_gate(self):
        # M41 explicitly introduces render-only standard PDF/DOCX export.
        # It must not silently turn the old bullet Tailor into a document path.
        from backend.main import _release_feature_for_path
        assert _release_feature_for_path('/api/resume/full-target/export') == 'resume_renovate'
        assert _release_feature_for_path('/api/resume/full-target/export/') == 'resume_renovate'
        reqs = (_REPO / 'requirements.txt').read_text().lower()
        assert 'fpdf2==2.8.8' in reqs
        assert 'python-docx==1.2.0' in reqs
        src = (_REPO / 'backend/routes/target_resume_export.py').read_text()
        assert 'chat_completion' not in src
        assert 'load_opportunities' not in src

    def test_no_export_or_download_route_in_tailor(self):
        src = (_REPO / "backend/routes/tailor.py").read_text()
        for needle in ("/tailor/export", "/tailor/download", "/tailor/docx", "/tailor/pdf"):
            assert needle not in src, f"undocumented renovation export route: {needle}"


class TestAGuessedSkillListIsNotCalledARequirement:
    """`rule_based_tag` writes `eligibility.skills_required` from a regex sweep
    over the posting prose for 2,767 of the 6,349 records that carry it. The
    tailor system prompt authorises the model to reuse "required skills"
    vocabulary when reframing the student's experience, so calling our guess a
    requirement steers the resume they actually send: a bench-and-field biology
    REU whose list reads "Python" pulls the rewrite toward one scripting
    course. #859 stopped the matcher calling it a shortfall and #875 relabelled
    it on the detail page; all three prompt builders still said "Required".
    """

    @staticmethod
    def _opp(inferred: bool) -> dict:
        opp = {
            "id": "buffalo-reu", "title": "Summer REU in Biological Sciences",
            "source_type": "summer_program",
            "eligibility": {"skills_required": ["Python"]}, "metadata": {},
        }
        if inferred:
            opp["metadata"] = {
                "inferred_fields": {"eligibility.skills_required": "rule:llm_tagger"}
            }
        return opp

    def test_a_stated_requirement_is_still_called_one(self):
        from backend.routes.tailor import _skills_line

        assert _skills_line(self._opp(False), "Python") == "- Required skills: Python\n"

    def test_a_tagger_written_list_says_where_it_came_from(self):
        from backend.routes.tailor import _skills_line

        line = _skills_line(self._opp(True), "Python")
        assert "Required skills" not in line
        assert "not stated requirements" in line
        assert "Python" in line

    def test_every_prompt_builder_uses_the_helper(self):
        """The renovation plan is the one prompt that still prints the list; a
        second copy would reintroduce the mislabel silently."""
        import inspect

        from backend.routes import tailor

        source = inspect.getsource(tailor)
        assert source.count('f"- Required skills: {required}\\n"') == 0
        assert source.count("_skills_line(opp, required)") == 1

    def test_a_tagger_written_list_is_never_an_anchor(self):
        """The rewrite prompts quote only anchors, and a guessed list is not one."""
        from backend.routes.tailor import _snapshot_anchors

        stated, guessed = self._opp(False), self._opp(True)
        assert [a.text for a in _snapshot_anchors(stated, stated)] == ["Python"]
        assert _snapshot_anchors(guessed, guessed) == []


class TestKeywordsProvenanceReachesThePrompt:
    """8,858 records carry keywords derived from a professor's OpenAlex topic
    clusters. Handing the model "Keywords: planetary science and exploration"
    steers a resume rewrite toward a guess the lab never made."""

    @staticmethod
    def _opp(inferred: bool) -> dict:
        opp = {
            "id": "bowdoin-eos", "title": "Research with Prof. Rachel J. Beane",
            "source_type": "faculty_research",
            "keywords": ["earthquake and tectonic"], "metadata": {},
        }
        if inferred:
            opp["metadata"] = {
                "inferred_fields": {"keywords": "derived:openalex_topics"}
            }
        return opp

    def test_keywords_the_lab_wrote_are_still_called_keywords(self):
        from backend.routes.tailor import _keywords_line

        line = _keywords_line(self._opp(False), "earthquake and tectonic")
        assert line == "- Keywords: earthquake and tectonic\n"

    def test_topics_read_off_publications_say_so(self):
        from backend.routes.tailor import _keywords_line

        line = _keywords_line(self._opp(True), "earthquake and tectonic")
        assert "- Keywords:" not in line
        assert "not stated by the lab" in line
        assert "earthquake and tectonic" in line

    def test_every_prompt_builder_uses_the_helper(self):
        import inspect

        from backend.routes import tailor

        source = inspect.getsource(tailor)
        assert source.count('f"- Keywords: {keywords}\\n"') == 0
        assert source.count("_keywords_line(opp, keywords)") == 1

    def test_keywords_never_reach_a_rewrite_prompt(self, monkeypatch):
        """Keywords, stated or inferred, are not quotable target text."""
        from backend.routes import tailor

        captured = []
        monkeypatch.setattr(tailor, "chat_completion", lambda messages, **kwargs: captured.append(messages))
        opp = self._opp(True)
        tailor._ai_tailor_bullets({}, opp, ["Mapped fault lines."], anchors=tailor._snapshot_anchors(opp, opp))
        assert "earthquake and tectonic" not in captured[0][1]["content"]
