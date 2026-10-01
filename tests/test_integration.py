"""
End-to-end integration tests for the Opportunity Filter Engine.
Covers: collector→normalizer pipeline, tagger updates, ranker sanity,
        cold email generator, resume advisor, and data integrity.

Run with: pytest tests/test_integration.py -v
"""

import copy
import functools
import json
import os
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.matcher.ranker import rank_all, rank_opportunity
from src.normalizers.normalizer import normalize
from src.parsers.llm_tagger import _build_full_text, apply_updates, needs_tagging, rule_based_tag
from src.recommender.cold_email import (
    _detect_lab_type,
    generate_cold_email,
    generate_variants,
)
from src.recommender.resume_advisor import analyze_gaps

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "opportunities.json")


@functools.lru_cache(maxsize=1)
def _load_real_data():
    # Parsed once per session and shared read-only across every test that reads
    # the real corpus. The file is 300 MB+; re-parsing it per test was pure
    # redundant CI cost. Do not mutate the returned records.
    if not os.path.exists(DATA_PATH):
        pytest.skip("No processed data file")
    with open(DATA_PATH) as f:
        return json.load(f)


_SAMPLE_PROFILE = {
    "name": "Test Student",
    "school": "UIUC",
    "year": "sophomore",
    "major": "CS",
    "secondary_interests": ["ECE", "Data Science"],
    "international_student": True,
    "hard_skills": ["Python", "Java", "C++"],
    "coursework": ["CS 124", "STAT 107"],
    "experience_level": "beginner",
    "resume_ready": True,
    "can_cold_email": True,
    "projects": [
        {"name": "ChatBot", "description": "Built a chatbot using Python and Flask"}
    ],
    "preferences": {
        "min_match_threshold": 0,
        "exclude_citizenship_restricted": True,
    },
}


@pytest.fixture
def sample_profile():
    # Deep-copied so a test that mutates its profile can't leak into another.
    return copy.deepcopy(_SAMPLE_PROFILE)


@pytest.fixture(scope="module")
def sanity_ranked_results():
    # The ranker-sanity tests each assert a different invariant over the SAME
    # rank_all(sample_profile, corpus) result. Ranking the full 128k-record
    # corpus is ~25s, so compute it once and share it read-only rather than
    # re-ranking per assertion. rank_all mutates neither its profile nor the
    # corpus, so the shared result is safe.
    return rank_all(copy.deepcopy(_SAMPLE_PROFILE), _load_real_data())


@pytest.fixture
def sample_opportunity():
    return {
        "id": "test-opp-001",
        "title": "ML Research Assistant — Data Science Lab",
        "organization": "University of Illinois",
        "department": "Computer Science",
        "lab_or_program": "Data Science Lab",
        "pi_name": "Prof. Jane Smith",
        "url": "https://example.com/opportunity/machine-learning-reu",
        "on_campus": True,
        "opportunity_type": "research",
        "paid": "yes",
        "deadline": (date.today() + timedelta(days=30)).isoformat(),
        "description_raw": "Looking for undergrads with Python and machine learning experience.",
        "description_clean": "Looking for undergrads with Python and ML experience.",
        "keywords": ["machine learning", "data science"],
        "eligibility": {
            "preferred_year": ["sophomore", "junior"],
            "majors": ["CS", "ECE", "STAT"],
            "skills_required": ["Python"],
            "skills_preferred": ["PyTorch", "pandas"],
            "international_friendly": "yes",
            "citizenship_required": False,
            "eligibility_text_raw": "",
        },
        "application": {
            "contact_method": "email",
            "requires_resume": "yes",
            "requires_cover_letter": "no",
            "requires_recommendation": "no",
            "application_effort": "low",
        },
        "metadata": {"is_active": True},
    }


# ── Test: Collector → Normalizer Pipeline ────────────────


class TestNormalizerPipeline:
    def test_normalize_produces_valid_schema(self):
        raw = {
            "title": "Summer REU in Biology",
            "description_raw": "A 10-week summer program for undergraduate researchers.",
            "url": "https://example.com/reu",
            "source": "test",
        }
        result = normalize(raw)
        assert result["id"], "Normalized entry must have an id"
        assert result["title"] == "Summer REU in Biology"
        assert isinstance(result["eligibility"], dict)
        assert "skills_required" in result["eligibility"]
        assert "preferred_year" in result["eligibility"]
        assert result["source"] == "test"

    def test_normalize_extracts_skills_from_description(self):
        raw = {
            "title": "Research Position",
            "description_raw": "Must know Python and R for data analysis. MATLAB preferred.",
            "url": "https://example.com",
        }
        result = normalize(raw)
        skills = result["eligibility"]["skills_required"] + result["eligibility"]["skills_preferred"]
        assert "Python" in skills or "R" in skills

    def test_normalize_handles_empty_input(self):
        raw = {"title": "Minimal Entry", "url": "https://example.com"}
        result = normalize(raw)
        assert result["title"] == "Minimal Entry"
        assert isinstance(result["eligibility"], dict)


# ── Test: Tagger Actually Updates Fields ────────────────


class TestTaggerUpdates:
    def test_rule_based_tag_extracts_skills_from_title(self):
        opp = {
            "title": "Python Developer for Data Science Lab",
            "description_raw": "",
            "description_clean": "",
            "url": "",
            "keywords": ["data science"],
            "eligibility": {
                "skills_required": [],
                "skills_preferred": [],
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "international_friendly": "unknown",
            },
            "paid": "unknown",
        }
        updates = rule_based_tag(opp)
        assert not updates.get("skills_required") and not updates.get("skills_preferred")
        assert "Python" in updates["skill_mentions"]

    def test_rule_based_tag_extracts_from_url_path(self):
        opp = {
            "title": "Summer Program",
            "description_raw": "",
            "description_clean": "",
            "url": "https://example.com/opportunity/chemistry-reu-colorado-state",
            "keywords": [],
            "eligibility": {
                "skills_required": [],
                "skills_preferred": [],
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "international_friendly": "unknown",
            },
            "paid": "unknown",
        }
        full_text = _build_full_text(opp)
        assert "chemistry" in full_text.lower()

    def test_rule_based_tag_extracts_from_keywords(self):
        opp = {
            "title": "Research Assistant",
            "description_raw": "",
            "description_clean": "",
            "url": "",
            "keywords": ["machine learning", "computer vision"],
            "lab_or_program": "CV Lab",
            "eligibility": {
                "skills_required": [],
                "skills_preferred": [],
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "international_friendly": "unknown",
            },
            "paid": "unknown",
        }
        updates = rule_based_tag(opp)
        all_skills = updates.get("skills_required", []) + updates.get("skills_preferred", [])
        assert all_skills == [], "Domain keywords cannot establish skill requirements"
        assert "Python" not in updates.get("skill_mentions", [])

    def test_apply_updates_modifies_opportunity(self):
        opp = {
            "description_raw": "Python is required.",
            "paid": "unknown",
            "eligibility": {
                "skills_required": [],
                "skills_preferred": [],
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "international_friendly": "unknown",
            },
        }
        updates = {
            "paid": "yes",
            "skills_required": ["Python"],
            "international_friendly": "yes",
            "citizenship_required": False,
        }
        changed = apply_updates(opp, updates)
        assert changed is True
        assert opp["paid"] == "yes"
        assert opp["eligibility"]["skills_required"] == ["Python"]
        assert opp["eligibility"]["international_friendly"] == "yes"

    def test_tagger_leaves_real_faculty_profiles_alone(self):
        """No faculty profile in the real corpus is an opening-tag candidate.

        Sampling the corpus for taggable records is not a valid gate in the
        other direction: a fully tagged corpus legitimately yields zero
        updates, and a non-empty update dict can still be a no-op. The
        deterministic positive path lives in the fixtures above and in
        tests/test_refresh_auto_tag.py.
        """
        data = _load_real_data()
        faculty = [o for o in data if o.get("source_type") == "faculty_research"]
        assert faculty, "Real corpus should contain faculty_research records"

        flagged = [o.get("id") for o in faculty if needs_tagging(o) is not False]
        assert not flagged, (
            f"{len(flagged)} faculty profiles flagged for tagging, e.g. {flagged[:5]}"
        )

        tagged = [o.get("id") for o in faculty if rule_based_tag(o) != {}]
        assert not tagged, (
            f"{len(tagged)} faculty profiles produced tag updates, e.g. {tagged[:5]}"
        )


# ── Test: Ranker Produces Sane Results ────────────────


class TestRankerSanity:
    def test_rank_all_returns_results(self, sanity_ranked_results):
        assert len(sanity_ranked_results) > 0, "Ranker should return results on real data"

    def test_scores_in_valid_range(self, sanity_ranked_results):
        for r in sanity_ranked_results:
            assert 0 <= r.final_score <= 100
            assert 0 <= r.eligibility_score <= 100
            assert 0 <= r.readiness_score <= 100
            assert 0 <= r.upside_score <= 100

    def test_results_sorted_by_label_then_score(self, sanity_ranked_results):
        # Labels are cut per opportunity type (F2), so a mixed selection lists
        # High Priority, Good Match, Reach, then low fit, each by score.
        order = ("high_priority", "good_match", "reach", "low_fit")
        for current, following in zip(sanity_ranked_results, sanity_ranked_results[1:], strict=False):
            assert order.index(current.bucket) <= order.index(following.bucket)
            if current.bucket == following.bucket:
                assert current.final_score >= following.final_score

    def test_good_match_scores_high(self, sample_profile, sample_opportunity):
        result = rank_opportunity(sample_profile, sample_opportunity)
        assert result.final_score >= 60, "A well-matched opportunity should score >= 60"
        assert result.bucket in ("high_priority", "good_match")

    def test_buckets_are_valid(self, sanity_ranked_results):
        valid_buckets = {"high_priority", "good_match", "reach", "low_fit"}
        for r in sanity_ranked_results:
            assert r.bucket in valid_buckets


# ── Test: Cold Email Generator ────────────────


class TestColdEmailGenerator:
    def test_generates_non_empty_output(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert len(email) > 0
        assert len(email.split()) <= 200  # reasonable length

    def test_includes_student_name(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert sample_profile["name"] in email

    def test_includes_pi_name(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert "Smith" in email or "Professor" in email

    def test_includes_lab_name(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert "Data Science Lab" in email

    def test_includes_skills(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert "Python" in email

    def test_has_subject_line(self, sample_profile, sample_opportunity):
        email = generate_cold_email(sample_profile, sample_opportunity)
        assert email.startswith("Subject:")

    def test_handles_minimal_profile(self, sample_opportunity):
        minimal = {"name": "", "year": "freshman", "major": "CS", "school": "UIUC"}
        email = generate_cold_email(minimal, sample_opportunity)
        assert len(email) > 0
        assert "Subject:" in email

    def test_handles_minimal_opportunity(self, sample_profile):
        minimal = {"id": "min", "title": "Some Research", "eligibility": {}}
        email = generate_cold_email(sample_profile, minimal)
        assert len(email) > 0

    def test_on_real_data(self, sample_profile):
        data = _load_real_data()
        for opp in data[:5]:
            email = generate_cold_email(sample_profile, opp)
            assert len(email) > 50, f"Email too short for {opp.get('title')}"


class TestLabTypeDetection:
    def test_wet_lab_from_biology_department(self):
        opp = {
            "title": "Undergraduate research in protein folding",
            "department": "Molecular and Cellular Biology",
            "description_clean": "Looking for students to assist with cell culture and Western blot.",
            "keywords": ["protein", "cell biology"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "wet"

    def test_wet_lab_from_techniques_even_without_department(self):
        opp = {
            "title": "Summer fellowship",
            "department": "",
            "description_clean": "PCR, gel electrophoresis, and sterile technique daily.",
            "keywords": [],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "wet"

    def test_dry_lab_from_cs_department(self):
        opp = {
            "title": "ML research with deep neural networks",
            "department": "Computer Science",
            "description_clean": "Looking for students with Python and PyTorch experience.",
            "keywords": ["machine learning", "deep learning"],
            "eligibility": {"skills_required": ["Python", "PyTorch"]},
        }
        assert _detect_lab_type(opp) == "dry"

    def test_ece_with_medical_application_keywords_stays_dry(self):
        # Real UIUC shape (observed live 2026-08-07): the department's
        # ampersand form matched neither "electrical engineering" nor "ece",
        # muting the highest-weight dry signal, while "medical" inside an
        # application phrase ("healthcare and medical technologies") scored
        # wet — a chip-architecture group got wet-lab PCR guidance.
        opp = {
            "title": "Research with Prof. Nam Sung Kim — ECE (beyond cmos, ai applications, healthcare and medical technologies)",
            "department": "Electrical & Computer Engineering",
            "description_clean": "Research opportunity with Professor Nam Sung Kim in the Electrical & Computer Engineering at UIUC. Research areas: beyond cmos, ai applications, healthcare and medical technologies, wearable and mobile computing.",
            "keywords": ["beyond cmos", "ai applications", "healthcare and medical technologies", "wearable and mobile computing"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "dry"

    def test_theory_ece_with_mathematical_biology_stays_dry(self):
        # Byte-real record faculty-ece-817eb026 (Bruce Hajek — stochastic
        # analysis / information theory). One phrase, "mathematical biology",
        # used to fire TWO wet vocabulary entries per field ("biology" and its
        # substring "bio"), inflating wet to 8 vs dry 6 and routing a theory
        # group to bench-technique guidance. Counted once per span, the true
        # balance is wet 4 : dry 6.
        opp = {
            "title": "Research with Prof. Bruce Hajek — ECE (mathematical biology, information theory, stochastic analysis)",
            "department": "Electrical & Computer Engineering",
            "description_clean": "Research opportunity with Professor Bruce Hajek in the Electrical & Computer Engineering at UIUC. Research areas: mathematical biology, information theory, stochastic analysis. Contact the professor directly to inquire about undergraduate research positions in their lab.",
            "keywords": ["mathematical biology", "information theory", "stochastic analysis"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "dry"

    def test_short_entries_do_not_fire_inside_names(self):
        # Short vocabulary entries used to match as bare substrings, turning
        # names into phantom signals: "law" AND "aws" both live inside
        # "Lawson", "irb" inside "Anirban", and every University of Delaware
        # record carried a humanities "law" point from the school name. A CS
        # professor literally named Delaware classified humanities.
        cs_delaware = {
            "title": "Research with Prof. Benjamin J. Delaware — CS",
            "department": "Department of Computer Science",
            "lab_or_program": "Prof. Benjamin J. Delaware's Research Group",
            "description_clean": "Research opportunity with Professor Benjamin J. Delaware in the Department of Computer Science at the University of Delaware.",
            "keywords": [],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(cs_delaware) == "dry"
        # "aws" inside "Dawson" gave DRY a phantom point that outvoted the
        # real humanities department signal.
        cmst_dawson = {
            "title": "Research with Prof. Taylor Dawson — CMST",
            "department": "Department of Communication Studies",
            "lab_or_program": "Prof. Taylor Dawson's Research Group",
            "description_clean": "Research opportunity with Professor Taylor Dawson in the Department of Communication Studies.",
            "keywords": [],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(cmst_dawson) == "humanities"
        # "irb" inside "Anirban" must not outvote a Biomedical Engineering
        # department (byte-real shape: faculty-casewestern-bme-14eda861).
        bme_anirban = {
            "title": "Research with Prof. Anirban Sen Gupta — BME",
            "department": "Department of Biomedical Engineering",
            "lab_or_program": "Prof. Anirban Sen Gupta's Research Group",
            "description_clean": "Research opportunity with Anirban Sen Gupta in the Department of Biomedical Engineering at Case Western Reserve University.",
            "keywords": [],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(bme_anirban) == "wet"

    def test_bio_keeps_prefix_rights_but_not_mid_word(self):
        # "bio" must still catch prefix disciplines the vocabulary lacks as
        # words ("biophysics") — a plant-biology group whose PI is named
        # Lawson stays wet — but must not fire mid-word: a psychologist
        # studying autobiographical memory is not a bench lab.
        ib_lawson = {
            "title": "Research with Prof. Tracy Lawson — IB (Photosynthesis, Photosystem, Stomatal Conductance)",
            "department": "School of Integrative Biology",
            "lab_or_program": "Prof. Tracy Lawson's Research Group",
            "description_clean": "Research opportunity with Professor Tracy Lawson in the School of Integrative Biology at UIUC. Research areas: Photosynthesis, Photosystem, Stomatal Conductance.",
            "keywords": ["Photosynthesis", "Photosystem", "Stomatal Conductance"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(ib_lawson) == "wet"
        psych_memory = {
            "title": "Research with Prof. Lance Rips — PSYCH (autobiographical memory)",
            "department": "Department of Psychology",
            "lab_or_program": "Prof. Lance Rips's Research Group",
            "description_clean": "Research opportunity in the Department of Psychology. Research areas: autobiographical memory.",
            "keywords": ["autobiographical memory"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(psych_memory) == "humanities"

    def test_nested_vocabulary_entries_count_once_per_span(self):
        # "microbiology" contains three wet entries as substrings
        # (microbiology, biology, bio) — one word must be one signal, or
        # every biology-family department triple-counts against dry/humanities.
        # A genuinely wet department must still classify wet afterwards.
        opp = {
            "title": "Undergraduate research in bacterial genetics",
            "department": "Microbiology",
            "description_clean": "Assist with cell culture and sequencing.",
            "keywords": [],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "wet"

    def test_humanities_lab_from_psychology(self):
        opp = {
            "title": "Research assistant — behavioral psychology",
            "department": "Psychology",
            "description_clean": "Qualitative coding of interviews using NVivo. IRB protocol experience preferred.",
            "keywords": ["psychology", "qualitative"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "humanities"

    def test_defaults_to_dry_on_no_signal(self):
        opp = {
            "title": "Research opportunity",
            "department": "",
            "description_clean": "Contact the professor for details.",
            "keywords": [],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "dry"

    def test_computational_imaging_in_bioengineering_is_not_a_bench_lab(self):
        # Byte-real shapes faculty-bioe-4156cbf9 (Yoram Bresler) and
        # faculty-bioe-b4e047a5 (Hua Li), walked 2026-09-30: both were badged
        # Wet Lab and a CS student was told to lead with PCR and cell culture.
        # "medical" and "clinical" say where the work is applied, not that it
        # happens at a bench, and imaging / signal-processing work had no dry
        # vocabulary at all to answer the department's "bio".
        def faculty(keywords, areas):
            return {"source_type": "faculty_research", "title": "Research with Prof. X",
                    "department": "Bioengineering", "lab_or_program": "", "keywords": keywords,
                    "metadata": {"research_areas_raw": areas}, "eligibility": {"skills_required": []}}

        bresler = faculty(
            ["biomedical imaging systems", "inverse problems", "compressed sensing", "sparse representations",
             "machine learning", "biomedical", "medical imaging"],
            "Biomedical imaging systems, inverse problems, compressed sensing, sparse representations, "
            "machine learning, big data, Statistical signal and image processing")
        hua_li = faculty(
            ["image-guided adaptive radiation therapy", "deep learning for clinical decision-making",
             "medical physicist", "carle cancer center", "urbana",
             "task-based medical imaging quality assessment", "early cancer detection"],
            "Image-guided adaptive radiation therapy, Functional image-based tumor response assessment and "
            "predication, Task-based medical imaging quality assessment, Medical imaging and image analysis "
            "for diagnosis and radiation therapy, Deep learning for clinical decision-making, Bioimaging at "
            "Multi-Scale")
        assert _detect_lab_type(bresler) == "dry"
        assert _detect_lab_type(hua_li) == "dry"
        # The same department with bench work in its own research stays wet.
        tissue = faculty(["tissue engineering", "cell culture", "stem cells"],
                         "Cell mechanics, tissue engineering, microscopy of live cells")
        assert _detect_lab_type(tissue) == "wet"

    def test_an_application_domain_alone_makes_no_lab_claim(self):
        # A theologian of "Medical Ethics" or a nurse studying "clinical trial
        # transparency" names a field the work serves, not a bench, a code
        # base or an archive; the dry default would tell them to link GitHub.
        # A department that is itself the prior keeps it.
        def faculty(department, keywords):
            return {"source_type": "faculty_research", "title": "Research with Prof. X",
                    "department": department, "lab_or_program": "", "keywords": keywords,
                    "metadata": {}, "eligibility": {"skills_required": []}}

        assert _detect_lab_type(faculty("School of Theology and Ministry",
                                        ["Moral Theology and Christian Ethics", "Medical Ethics"])) is None
        assert _detect_lab_type(faculty("College of Nursing",
                                        ["clinical trial transparency", "informed consent"])) is None
        assert _detect_lab_type(faculty("Department of Medicine", ["heart failure"])) == "wet"

    def test_bench_work_named_after_the_field_it_serves_stays_wet(self):
        # Setting "medicine" aside inside every word moved real benches to Dry
        # Lab (review of the fix above, 2026-09-30). "Nanomedicine" and
        # "Regenerative Medicine" name bench work, and so do drug delivery and
        # biomaterials, under a mechanical or materials department as well.
        # Byte-real keywords of faculty-cornell-mae-89be0901,
        # faculty-uf-mse-637c113b, faculty-stanford-mse-0ce19e87,
        # faculty-ucf-mse-e0682e23, faculty-psu-matse-39a9b708 and
        # faculty-uf-mse-f9ef175c.
        def faculty(department, keywords, areas=""):
            return {"source_type": "faculty_research", "title": "Research with Prof. X",
                    "department": department, "lab_or_program": "", "keywords": keywords,
                    "metadata": {"research_areas_raw": areas}, "eligibility": {"skills_required": []}}

        assert _detect_lab_type(faculty("Sibley School of Mechanical & Aerospace Engineering", [
            "Drug Delivery and Nanomedicine", "Polymers and Soft Matter", "Energy Systems",
            "Mechanics of Biological Materials", "Biomedical Imaging and Instrumentation",
            "Materials Synthesis and Processing", "Nanotechnology", "Biomedical Engineering"])) == "wet"
        regenerative = ["Polymer Synthesis", "Hydrogels", "Drug Delivery", "Bioprinting",
                        "Tissue Engineering and Regenerative Medicine"]
        assert _detect_lab_type(faculty("Materials Science & Engineering", regenerative,
                                        ", ".join(regenerative))) == "wet"
        assert _detect_lab_type(faculty("Department of Materials Science & Engineering", [
            "biomaterials in regenerative medicine", "engineered proteins", "microfluidics and photolithography",
            "stem cell differentiation", "tissue engineering", "injectable materials"])) == "wet"
        assert _detect_lab_type(faculty("Department of Materials Science and Engineering", [
            "Molecular engineering and self assembly", "Biomaterials", "Polyelectrolyte complexation",
            "Soft materials characterization", "Nanomedicine"])) == "wet"
        assert _detect_lab_type(faculty("Department of Materials Science and Engineering", [
            "Drug Delivery Systems", "Stimuli-sensitive materials", "Bioresponsive materials",
            "Self-assembly"])) == "wet"
        biomaterials = ["Biomaterials", "hydrogels", "cell-material interactions", "bioinspired materials",
                        "peptide materials", "mechanical properties"]
        assert _detect_lab_type(faculty("Materials Science & Engineering", biomaterials,
                                        ", ".join(biomaterials))) == "wet"

    def test_a_field_word_inside_another_word_is_no_bench_either(self):
        # "Biomedicine", "Telemedicine" and "Medicalization" name the field
        # the work serves just as "medicine" does: a language-model group, a
        # business-school telehealth study and a social-welfare critique of
        # medicalization (faculty-usc-cs-02bb7b92, faculty-wpi-bus-575bb40e,
        # faculty-ucla-socwel-3d2fd3e3) are not benches. A department name is
        # a prior only through the whole word, so a telemedicine program is
        # not a medical school.
        def faculty(department, keywords):
            return {"source_type": "faculty_research", "title": "Research with Prof. X",
                    "department": department, "lab_or_program": "", "keywords": keywords,
                    "metadata": {}, "eligibility": {"skills_required": []}}

        assert _detect_lab_type(faculty("Thomas Lord Department of Computer Science", [
            "Next Generation in Biomedicine", "large language models", "reinforcement learning"])) == "dry"
        assert _detect_lab_type(faculty("The Business School", [
            "Health Information Technology Implementations", "Mobile Health / Telehealth / Telemedicine",
            "Technology Innovation", "System Usability"])) is None
        assert _detect_lab_type(faculty("Social Welfare", [
            "Coercive mental health care", "Controlled substances", "Data justice", "Deprescribing",
            "Harm reduction", "History of ideas", "Medicalization", "Mental health"])) == "humanities"
        assert _detect_lab_type(faculty("Telemedicine and Digital Health Program",
                                        ["mobile app development", "python"])) == "dry"

    def test_wet_wins_over_dry_buzzword(self):
        """A wet-lab posting that mentions Python for analysis should
        not be misrouted to dry. Wet-lab signals (cell culture, microscopy)
        get 3x weight from the department field plus 2x from title."""
        opp = {
            "title": "Cell biology REU — microscopy and image analysis",
            "department": "Cell and Developmental Biology",
            "description_clean": "Use Python for image analysis after wet-bench microscopy work.",
            "keywords": ["cell biology", "microscopy"],
            "eligibility": {"skills_required": []},
        }
        assert _detect_lab_type(opp) == "wet"


class TestLabTypeAwareTemplates:
    def test_wet_lab_subject_says_inquiry(self, sample_profile):
        opp = {
            "id": "wet-1", "title": "Biology research",
            "department": "Molecular Biology", "lab_or_program": "Smith Lab",
            "pi_name": "Prof. Smith",
            "description_clean": "PCR and cell culture daily.",
            "keywords": ["biology"], "eligibility": {"skills_required": []},
        }
        email = generate_cold_email(sample_profile, opp)
        first_line = email.split("\n")[0]
        assert "Research Inquiry" in first_line

    def test_dry_lab_subject_says_interest(self, sample_profile):
        opp = {
            "id": "dry-1", "title": "ML research",
            "department": "Computer Science", "lab_or_program": "Smith Lab",
            "pi_name": "Prof. Smith",
            "description_clean": "Python and PyTorch required.",
            "keywords": ["machine learning"],
            "eligibility": {"skills_required": ["Python"]},
        }
        email = generate_cold_email(sample_profile, opp)
        first_line = email.split("\n")[0]
        assert "Undergraduate Research Interest" in first_line

    def test_humanities_subject_says_assistant_interest(self, sample_profile):
        opp = {
            "id": "hum-1", "title": "Sociology RA",
            "department": "Sociology", "lab_or_program": "Smith Lab",
            "pi_name": "Prof. Smith",
            "description_clean": "Qualitative interviews and survey design.",
            "keywords": ["sociology"], "eligibility": {"skills_required": []},
        }
        email = generate_cold_email(sample_profile, opp)
        first_line = email.split("\n")[0]
        assert "Research Assistant Interest" in first_line

    def test_wet_lab_ask_mentions_safety_training(self, sample_profile):
        opp = {
            "id": "wet-2", "title": "Bio research",
            "department": "Biology", "description_clean": "PCR work.",
            "keywords": ["biology"], "eligibility": {"skills_required": []},
        }
        email = generate_cold_email(sample_profile, opp)
        assert "safety training" in email.lower() or "graduate mentor" in email.lower()

    def test_humanities_ask_does_not_invent_task_assignments(self, sample_profile):
        opp = {
            "id": "hum-2", "title": "History RA",
            "department": "History", "description_clean": "Archival research.",
            "keywords": ["history"], "eligibility": {"skills_required": []},
        }
        email = generate_cold_email(sample_profile, opp)
        assert "first step" in email.lower()
        assert "literature review" not in email.lower()
        assert "qualitative coding" not in email.lower()

    def test_variants_include_lab_type_field(self, sample_profile):
        opp = {
            "id": "dry-2", "title": "CS research",
            "department": "Computer Science",
            "description_clean": "ML work in Python.",
            "keywords": ["computer science"],
            "eligibility": {"skills_required": ["Python"]},
        }
        variants = generate_variants(sample_profile, opp)
        assert len(variants) == 3
        for v in variants:
            assert v["lab_type"] == "dry"


# ── Test: Resume Advisor ────────────────


class TestResumeAdvisor:
    def test_identifies_missing_skills(self, sample_profile, sample_opportunity):
        gaps = analyze_gaps(sample_profile, sample_opportunity)
        assert isinstance(gaps["missing_skills"], list)
        # PyTorch and pandas are preferred but not in profile
        assert "PyTorch" in gaps["missing_skills"] or "pandas" in gaps["missing_skills"]

    def test_suggests_coursework(self, sample_profile, sample_opportunity):
        gaps = analyze_gaps(sample_profile, sample_opportunity)
        assert isinstance(gaps["suggested_coursework"], list)
        assert len(gaps["suggested_coursework"]) > 0

    def test_provides_resume_tips(self, sample_profile, sample_opportunity):
        gaps = analyze_gaps(sample_profile, sample_opportunity)
        assert isinstance(gaps["resume_tips"], list)
        assert len(gaps["resume_tips"]) > 0

    def test_provides_preparation_timeline(self, sample_profile, sample_opportunity):
        gaps = analyze_gaps(sample_profile, sample_opportunity)
        assert isinstance(gaps["preparation_timeline"], list)
        for item in gaps["preparation_timeline"]:
            assert "skill" in item
            assert "estimated_time" in item
            assert "priority" in item
            assert item["priority"] in ("high", "medium")

    def test_no_gaps_for_perfect_match(self):
        profile = {
            "hard_skills": ["Python", "PyTorch", "pandas"],
            "coursework": [],
            "experience_level": "strong",
            "resume_ready": True,
            "projects": [{"name": "Demo", "description": "A project"}],
        }
        opp = {
            "eligibility": {
                "skills_required": ["Python"],
                "skills_preferred": ["PyTorch", "pandas"],
            },
            "opportunity_type": "research",
            "application": {},
        }
        gaps = analyze_gaps(profile, opp)
        assert len(gaps["missing_skills"]) == 0
        assert len(gaps["preparation_timeline"]) == 0

    def test_on_real_data(self, sample_profile):
        data = _load_real_data()
        for opp in data[:5]:
            gaps = analyze_gaps(sample_profile, opp)
            assert isinstance(gaps, dict)
            assert "missing_skills" in gaps
            assert "resume_tips" in gaps


# ── Test: Data Integrity — All Records ────────────────


class TestAllRecordsIntegrity:
    def test_all_records_have_required_fields(self):
        data = _load_real_data()
        required_fields = ["id", "title", "url", "eligibility"]
        for opp in data:
            for field in required_fields:
                assert field in opp and opp[field], \
                    f"Record '{opp.get('title', 'UNKNOWN')}' missing required field '{field}'"

    def test_all_eligibility_dicts_have_structure(self):
        data = _load_real_data()
        for opp in data:
            elig = opp.get("eligibility", {})
            assert isinstance(elig, dict), f"Bad eligibility in: {opp.get('title')}"
            assert "preferred_year" in elig, f"Missing preferred_year: {opp.get('title')}"
            assert isinstance(elig["preferred_year"], list)

    def test_no_duplicate_ids(self):
        data = _load_real_data()
        ids = [o["id"] for o in data]
        assert len(ids) == len(set(ids)), "Duplicate IDs found"

    def test_all_paid_values_valid(self):
        data = _load_real_data()
        valid_paid = {"yes", "no", "stipend", "unknown"}
        for opp in data:
            assert opp.get("paid", "unknown") in valid_paid, \
                f"Invalid paid value in: {opp.get('title')}"

    def test_all_intl_values_valid(self):
        data = _load_real_data()
        valid_intl = {"yes", "no", "unknown"}
        for opp in data:
            intl = opp.get("eligibility", {}).get("international_friendly", "unknown")
            assert intl in valid_intl, f"Invalid international_friendly in: {opp.get('title')}"


def test_extract_years_advanced_undergraduate_excludes_underclassmen():
    """'advanced undergraduate' is an explicit no-freshman signal — the AAAS
    Mass Media Fellowship said exactly this yet displayed 'Accepts freshman
    students' because the phrase fell through to the all-years default."""
    from src.normalizers.normalizer import _extract_years
    years = _extract_years(
        "placing advanced undergraduate, graduate, and post-graduate level "
        "scientists at media organizations"
    )
    assert years == ["junior", "senior"]
