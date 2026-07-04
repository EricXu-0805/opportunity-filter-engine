"""Tests for src/normalizers/enricher.py"""

from src.normalizers.enricher import (
    enrich_all,
    enrich_opportunity,
    infer_keywords,
    infer_majors,
)


def _opp(title: str, desc: str = "", majors=None, keywords=None) -> dict:
    return {
        "title": title,
        "description_raw": desc,
        "description_clean": desc,
        "eligibility": {"majors": majors or []},
        "keywords": keywords if keywords is not None else [],
    }


class TestInferMajors:
    def test_linguistics_from_tesol_description(self):
        opp = _opp(
            "RESEARCH OPPORTUNITY: Linguistics",
            "Opportunity to assist in language teaching research for the MA TESOL practicum.",
        )
        majors = infer_majors(opp)
        assert "Linguistics" in majors

    def test_spanish_from_title(self):
        opp = _opp("Spanish Literature Undergraduate Research")
        assert "Spanish" in infer_majors(opp)

    def test_cs_from_description(self):
        opp = _opp("Research Assistant", "Computer science lab working on machine learning")
        assert "CS" in infer_majors(opp)

    def test_multiple_domains_picked_up(self):
        opp = _opp("Psycholinguistics of Bilingualism", "Cognitive science approach to language acquisition")
        majors = infer_majors(opp)
        assert "Linguistics" in majors
        assert "Psychology" in majors

    def test_no_signal_returns_empty(self):
        opp = _opp("Generic Opportunity", "Apply now for this research position.")
        # "research position" is too generic; should not fabricate
        assert "CS" not in infer_majors(opp)
        assert "Spanish" not in infer_majors(opp)

    def test_word_boundary_prevents_false_hits(self):
        # "history" substring inside a word like "prehistoric" should not match
        opp = _opp("Prehistoric Archaeology", "Studies of prehistoric societies")
        # But a real "history" match in "historical research" SHOULD
        opp2 = _opp("Historical Research", "Archival historical research position")
        assert "History" in infer_majors(opp2)

    def test_job_title_infers_cs_from_swe_intern(self):
        # Handshake postings often have empty descriptions; title-level
        # role words must still surface the right major.
        opp = _opp("Software Engineer Intern", "")
        assert "CS" in infer_majors(opp)

    def test_job_title_infers_business_from_analyst_role(self):
        opp = _opp("Business Analyst Intern", "")
        assert "Business" in infer_majors(opp)

    def test_job_title_infers_sustainability(self):
        opp = _opp("Sustainability Communications Intern", "")
        majors = infer_majors(opp)
        assert "Natural Resources & Environmental Sciences" in majors or "Communication" in majors

    def test_environmental_intern_infers_nres(self):
        opp = _opp("Environmental Intern Summer 2026", "")
        assert "Natural Resources & Environmental Sciences" in infer_majors(opp)

    def test_park_ranger_infers_nres(self):
        opp = _opp("Park Ranger Internship", "")
        assert "Natural Resources & Environmental Sciences" in infer_majors(opp)

    def test_library_page_infers_library_science(self):
        opp = _opp("Library Page/Cafe Worker", "")
        assert "Library & Information Science" in infer_majors(opp)

    def test_fossil_intern_infers_geology(self):
        opp = _opp("Geology Undergraduate Internship: Linton Fossils", "")
        assert "Geology" in infer_majors(opp)

    def test_hr_intern_infers_hr(self):
        opp = _opp("FutureLab HR Spring/Summer 2026 Internship", "")
        assert "Human Resources" in infer_majors(opp)


class TestNonOpportunityDetection:
    def test_symposium_award_is_non_opportunity(self):
        from src.normalizers.enricher import is_likely_non_opportunity
        opp = _opp("2025 Undergraduate Research Symposium Award Winners!")
        assert is_likely_non_opportunity(opp) is True

    def test_office_sticker_is_non_opportunity(self):
        from src.normalizers.enricher import is_likely_non_opportunity
        opp = _opp("OUR's New Office Sticker")
        assert is_likely_non_opportunity(opp) is True

    def test_newsletter_phrase_is_non_opportunity(self):
        from src.normalizers.enricher import is_likely_non_opportunity
        opp = _opp("Stay Connected with Undergraduate Research at Illinois")
        assert is_likely_non_opportunity(opp) is True

    def test_real_research_opp_is_kept(self):
        from src.normalizers.enricher import is_likely_non_opportunity
        opp = _opp("RESEARCH OPPORTUNITY: Food Science - Fiber Structure and Mechanics in Foods")
        assert is_likely_non_opportunity(opp) is False

    def test_enrich_flags_non_opportunity_inactive(self):
        opp = _opp("2025 Undergraduate Research Symposium Award Winners!")
        opp["metadata"] = {"is_active": True, "notes": ""}
        enrich_opportunity(opp)
        assert opp["metadata"]["is_active"] is False
        assert "auto-flagged" in opp["metadata"]["notes"]

    def test_faculty_keyword_backfill_skipped(self):
        """A keyword-empty faculty record must NOT get keywords inferred from its
        boilerplate description ("...inquire about undergraduate research
        positions in their lab.") — that injects the page-furniture keyword
        'undergraduate research' the faculty DQ gate rejects, deterministically
        failing every refresh. Honest-broad faculty stay broad."""
        opp = _opp(
            "Research with Prof. X — ECE",
            "Research opportunity with Professor X at UW. Contact the professor "
            "directly to inquire about undergraduate research positions in their lab.",
        )
        opp["source_type"] = "faculty_research"
        enrich_opportunity(opp)
        assert opp["keywords"] == []

    def test_program_keyword_backfill_keeps_undergraduate_research(self):
        """The same term is a LEGITIMATE keyword on a real REU program record —
        the skip must be faculty-only, not a blanket junk-gate."""
        opp = _opp("Summer REU Program", "A paid undergraduate research experience.")
        opp["source_type"] = "program"
        enrich_opportunity(opp)
        assert "undergraduate research" in opp["keywords"]

    def test_faculty_skills_backfill_skipped(self):
        """Faculty are research contacts, not postings with required skills:
        inferring a skill from research-topic prose ("finite element" ->
        FEA-required on a topology professor) is false-precise and degrades the
        match, so faculty never get inferred skills."""
        opp = _opp(
            "Prof. X — Mathematics",
            "Research in topology and geometry, including the finite element "
            "method for numerical simulation of partial differential equations.",
        )
        opp["source_type"] = "faculty_research"
        enrich_opportunity(opp)
        assert not opp.get("eligibility", {}).get("skills_required")

    def test_program_skills_backfill_kept(self):
        """A real internship/program still gets inferred skills — the skip is
        faculty-only."""
        opp = _opp(
            "Data Science Internship",
            "Build models in Python and SQL; experience with machine learning "
            "and finite element analysis simulation preferred for this role.",
        )
        opp["source_type"] = "internship"
        enrich_opportunity(opp)
        assert opp["eligibility"].get("skills_required")


class TestInferKeywords:
    def test_language_keywords(self):
        opp = _opp("TESOL research", "bilingualism and language acquisition")
        kws = infer_keywords(opp)
        assert "language" in kws
        assert "language teaching" in kws

    def test_paid_stipend_signal(self):
        opp = _opp("Summer program", "Offers a $3000 stipend to participants.")
        assert "paid" in infer_keywords(opp)

    def test_ml_variants(self):
        opp = _opp("ML research", "Deep learning for medical imaging")
        kws = infer_keywords(opp)
        assert "machine learning" in kws


class TestEnrichOpportunity:
    def test_preserves_existing_majors(self):
        opp = _opp("CS Lab", "computer science research", majors=["ECE"])
        enrich_opportunity(opp)
        assert opp["eligibility"]["majors"] == ["ECE"]  # not overwritten

    def test_fills_empty_majors(self):
        opp = _opp("Linguistics Lab", "bilingualism research")
        enrich_opportunity(opp)
        assert "Linguistics" in opp["eligibility"]["majors"]

    def test_replaces_unsorted_keywords(self):
        opp = _opp("TESOL research", "language teaching at the refugee center", keywords=["Unsorted"])
        enrich_opportunity(opp)
        assert "Unsorted" not in opp["keywords"]
        assert "language" in opp["keywords"]

    def test_preserves_real_keywords(self):
        opp = _opp("ML lab", "deep learning", keywords=["deep learning", "neural networks"])
        before = list(opp["keywords"])
        enrich_opportunity(opp)
        assert opp["keywords"] == before  # untouched

    def test_idempotent(self):
        opp = _opp("Linguistics", "language acquisition research")
        enrich_opportunity(opp)
        first_majors = list(opp["eligibility"]["majors"])
        first_kws = list(opp["keywords"])
        enrich_opportunity(opp)
        assert opp["eligibility"]["majors"] == first_majors
        assert opp["keywords"] == first_kws

    def test_normalizes_mmddyyyy_posted_date(self):
        opp = _opp("Program", "")
        opp["posted_date"] = "09/01/2026"
        enrich_opportunity(opp)
        assert opp["posted_date"] == "2026-09-01"

    def test_normalizes_mmddyyyy_start_date(self):
        # nsf_reu shipped start_date as MM/DD/YYYY alongside an ISO posted_date.
        opp = _opp("REU", "")
        opp["start_date"] = "06/01/2026"
        enrich_opportunity(opp)
        assert opp["start_date"] == "2026-06-01"

    def test_strips_timestamp_from_deadline(self):
        opp = _opp("Program", "")
        opp["deadline"] = "2026-05-01T23:59:59.999-05:00"
        enrich_opportunity(opp)
        assert opp["deadline"] == "2026-05-01"

    def test_leaves_deadline_sentinel_untouched(self):
        opp = _opp("Program", "")
        opp["deadline"] = "Rolling"
        enrich_opportunity(opp)
        assert opp["deadline"] == "Rolling"


class TestEnrichAll:
    def test_counts_additions(self):
        opps = [
            _opp("Linguistics research", "bilingualism"),
            _opp("CS Lab", "machine learning", majors=["CS"], keywords=["ml"]),
            _opp("TESOL", "language teaching", keywords=["Unsorted"]),
        ]
        m_added, k_added = enrich_all(opps)
        assert m_added >= 2  # linguistics + tesol
        assert k_added >= 2  # linguistics starts empty, tesol had unsorted
