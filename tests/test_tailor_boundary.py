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

from backend.lib.grounding import (
    LENIENT_PROSE,
    LENIENT_PROSE_NUMERIC,
    validate_no_fabrication,
)
from backend.routes.tailor import (
    TAILOR_PIPELINE_VERSION,
    _build_evidence_corpus,
    _verify_evidence,
)

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
# Evidence quotes: shown only when they exist in the student's material
# ---------------------------------------------------------------------------

class TestEvidenceVerification:
    def _corpus(self):
        profile = {
            "major": "Computer Science", "school": "UIUC", "college": "",
            "hard_skills": [{"name": "Python", "level": "experienced"}],
            "coursework": ["CS 225"],
        }
        return _build_evidence_corpus(profile, ["Built a data pipeline in Python"])

    def test_real_quote_is_kept(self):
        corpus = self._corpus()
        assert _verify_evidence("Built a data pipeline", corpus)

    def test_composite_citation_of_real_facts_is_kept(self):
        corpus = self._corpus()
        assert _verify_evidence("Python (experienced); CS 225", corpus)

    def test_fabricated_quote_is_blanked(self):
        corpus = self._corpus()
        assert _verify_evidence("Deployed production AWS pipelines", corpus) == ""

    def test_composite_with_one_invented_fragment_is_blanked(self):
        corpus = self._corpus()
        assert _verify_evidence("CS 225; Kubernetes certification", corpus) == ""

    def test_empty_evidence_stays_empty(self):
        assert _verify_evidence("", self._corpus()) == ""

    def test_word_order_matters(self):
        # Evidence is a contiguous quote, not a bag of words.
        corpus = self._corpus()
        assert _verify_evidence("pipeline data a Built", corpus) == ""


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
    def test_no_document_generation_dependencies(self):
        # DOCX/PDF generation, template conversion, and formatting round-trips
        # belong to the separate MTP Renovate product area. None of it exists
        # today; if a dependency appears, the W13 gating requirements apply
        # BEFORE it ships (hidden until that product meets its own bar).
        forbidden = ("python-docx", "reportlab", "weasyprint", "mammoth",
                     "pypdf", "fpdf", "docxtpl")
        reqs = (_REPO / "requirements.txt").read_text().lower()
        for dep in forbidden:
            assert dep not in reqs, f"document round-trip dependency shipped: {dep}"
        pkg = (_REPO / "frontend/package.json").read_text().lower()
        for dep in ("jspdf", "pdfkit", "docx", "html2pdf"):
            assert f'"{dep}"' not in pkg, f"document round-trip dependency shipped: {dep}"

    def test_no_export_or_download_route_in_tailor(self):
        src = (_REPO / "backend/routes/tailor.py").read_text()
        for needle in ("/tailor/export", "/tailor/download", "/tailor/docx", "/tailor/pdf"):
            assert needle not in src, f"undocumented renovation export route: {needle}"
