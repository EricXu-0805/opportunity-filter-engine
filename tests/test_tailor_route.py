"""Tests for ``POST /api/tailor`` — resume bullet tailoring.

The anti-fabrication test is the **non-negotiable** spec for this feature.
If the model says the student "Built ML pipelines in Python" but the
profile has no Python, the route MUST degrade to the local passthrough
and surface the violation in ``warnings``. That contract lives in
``test_fabrication_python_when_profile_has_none``.

Other tests cover the graceful-degradation contract (mirrors cold-email):
  * 404 only when the opportunity doesn't exist
  * Empty bullets → 200 with a hint
  * No LLM provider configured → fallback
  * LLM returns non-JSON → fallback
  * LLM returns valid JSON drawing only from profile + opp → method="ai"
"""

from __future__ import annotations

import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend import data_loader
from backend.lib import evidence_map
from backend.lib.release_scope import opportunity_visible_in_release
from backend.main import app
from backend.routes import tailor as tailor_module
from src.evidence import is_actionable_target

client = TestClient(app)


@pytest.fixture(autouse=True)
def _faithful_review(monkeypatch):
    """Every changed rewrite now goes to the faithfulness review, which
    tests/test_tailor_review.py covers. These fakes answer every model call with
    one rewrite reply, so the review verdict is given here: faithful, with every
    declared link entailed."""
    def accept(pairs, deadline=None):
        for pair in pairs:
            for link in pair.links:
                link.entailed = True
        return ["accepted"] * len(pairs)

    monkeypatch.setattr(evidence_map, "ai_review", accept)


def em_row(unit_id, text=None, *, ops=(), links=(), keep_reason="no_link"):
    """One evidence-map row as the model returns it."""
    return {"unit_id": unit_id, "links": list(links), "decision": "rewrite" if text else "keep",
            "ops": list(ops), "text": text, "keep_reason": None if text else keep_reason}


def em_reply(*rows):
    return json.dumps({"bullets": list(rows)})


# A role-noun opener rewritten verb first: the plainest change the contract admits.
RA = "Research assistant in the Fluids Lab, analyzing Python simulation data for CS 225."
RA_VERB_FIRST = "Analyzed Python simulation data for CS 225 as a research assistant in the Fluids Lab."


@pytest.fixture
def real_opp_id() -> str:
    """Return the first available opportunity id from the live data file.

    Using a real id keeps the test honest about the `load_opportunities_by_id`
    contract — if the loader changes shape, this fixture breaks loudly.
    """
    by_id = data_loader.load_opportunities_by_id()
    assert by_id, "data loader should return at least one opportunity"
    opportunity_id = next(
        (
            opportunity_id
            for opportunity_id, opportunity in by_id.items()
            if opportunity_visible_in_release(opportunity)
            and is_actionable_target(opportunity)
        ),
        None,
    )
    assert opportunity_id is not None, (
        "corpus should contain at least one release-visible actionable opportunity"
    )
    return opportunity_id


@pytest.fixture
def java_profile() -> dict:
    """Profile that knows Java only — has no Python anywhere on it.

    Used by the core anti-fabrication test to assert the validator
    catches the model inventing 'Python' when the student never claimed
    it. Keep this profile free of any token an LLM might smuggle in.
    """
    return {
        "name": "Test Student",
        "school": "UIUC",
        "year": "junior",
        "major": "Mechanical Engineering",
        "college": "Grainger College of Engineering",
        "secondary_interests": [],
        "international_student": False,
        "seeking_type": ["research"],
        "desired_fields": [],
        "hard_skills": [{"name": "Java", "level": "experienced"}],
        "coursework": ["ME 270"],
        "experience_level": "some",
        "resume_ready": True,
        "can_cold_email": True,
        "research_interests_text": "thermodynamics and fluid dynamics",
        "linkedin_url": "",
        "github_url": "",
        "search_weight": 50,
    }


@pytest.fixture
def python_profile() -> dict:
    """Profile that DOES list Python — control case for the validator."""
    return {
        "name": "Test Student",
        "school": "UIUC",
        "year": "junior",
        "major": "Computer Science",
        "college": "Grainger College of Engineering",
        "secondary_interests": [],
        "international_student": False,
        "seeking_type": ["research"],
        "desired_fields": [],
        "hard_skills": [
            {"name": "Python", "level": "experienced"},
            {"name": "PyTorch", "level": "familiar"},
        ],
        "coursework": ["CS 124", "CS 225"],
        "experience_level": "some",
        "resume_ready": True,
        "can_cold_email": True,
        "research_interests_text": "machine learning systems",
        "linkedin_url": "",
        "github_url": "",
        "search_weight": 50,
    }


class TestTailorContract:
    """High-level route contract (mirrors TestColdEmailEngine in test_backend_api)."""

    def test_opportunity_not_found_returns_404(self, java_profile):
        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": "definitely-not-a-real-id",
                "original_bullets": ["did some research"],
            },
        )
        assert resp.status_code == 404

    def test_empty_bullets_returns_empty_with_hint(self, java_profile, real_opp_id):
        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": [],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["tailored_bullets"] == []
        assert body["method"] == "fallback"
        assert "no_bullets_provided" in body["warnings"]

    def test_no_llm_provider_falls_back_to_originals(
        self, java_profile, real_opp_id, monkeypatch,
    ):
        # Strip every provider env var the chain consults.
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)

        bullets = ["Designed a thermal sensor in Java", "Wrote ME 270 lab report"]
        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": bullets,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "fallback"
        assert [b["text"] for b in body["tailored_bullets"]] == bullets
        assert "llm_not_configured" in body["warnings"]


class TestStatus:
    """R71-G: GET /api/tailor/status reports AI availability for the UI banner."""

    def test_status_true_when_provider_configured(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        resp = client.get("/api/tailor/status")
        assert resp.status_code == 200
        assert resp.json() == {"ai_available": True, "pipeline_version": tailor_module.TAILOR_PIPELINE_VERSION}

    def test_status_false_when_no_provider(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        resp = client.get("/api/tailor/status")
        assert resp.status_code == 200
        assert resp.json() == {"ai_available": False, "pipeline_version": tailor_module.TAILOR_PIPELINE_VERSION}


class TestExtractBullets:
    """R71-G: POST /api/tailor/extract-bullets — resume text → bullet lines."""

    def test_empty_text_returns_empty_heuristic(self):
        resp = client.post("/api/tailor/extract-bullets", json={"resume_text": "   "})
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "bullets": [], "method": "heuristic", "warnings": [], "processing": None,
            "generated_at": body["generated_at"], "pipeline_version": tailor_module.TAILOR_PIPELINE_VERSION,
        }
        assert body["generated_at"]

    def test_no_provider_uses_glyph_heuristic(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        resume = (
            "EDUCATION\n"
            "• Built a thermal sensor in Java for the ME 270 capstone\n"
            "- Wrote a 12-page final lab report on heat transfer\n"
            # A lowercase row right under a glyph row with no closing mark wraps that bullet
            # (_resume_rows); under a heading it is a row of its own.
            "OTHER\n"
            "not a bullet line at all\n"
        )
        resp = client.post("/api/tailor/extract-bullets", json={"resume_text": resume})
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "heuristic"
        assert "Built a thermal sensor in Java for the ME 270 capstone" in body["bullets"]
        assert "Wrote a 12-page final lab report on heat transfer" in body["bullets"]
        assert "EDUCATION" not in body["bullets"]
        assert "not a bullet line at all" not in body["bullets"]

    def test_ai_extracts_dark_bullets(self, monkeypatch):
        """LLM finds accomplishment lines with no glyph (the whole point)."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        resume = (
            "Research Assistant, Fluids Lab\n"
            "Designed a thermal sensor in Java and validated it against ME 270 data\n"
            "Presented results at the undergraduate symposium\n"
        )
        fake = json.dumps({
            "bullets": [
                "Designed a thermal sensor in Java and validated it against ME 270 data",
                "Presented results at the undergraduate symposium",
            ],
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)
        resp = client.post("/api/tailor/extract-bullets", json={"resume_text": resume})
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        assert len(body["bullets"]) == 2
        assert any("thermal sensor in Java" in b for b in body["bullets"])

    def test_ai_invented_bullet_is_dropped(self, monkeypatch):
        """A bullet the model fabricated (not grounded in the resume) is filtered."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        resume = "Designed a thermal sensor in Java for the ME 270 capstone project\n"
        fake = json.dumps({
            "bullets": [
                "Designed a thermal sensor in Java for the ME 270 capstone project",
                "Deployed Kubernetes clusters and trained PyTorch transformer models",
            ],
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)
        resp = client.post("/api/tailor/extract-bullets", json={"resume_text": resume})
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        joined = " ".join(body["bullets"]).lower()
        assert "thermal sensor" in joined
        # The ungrounded fabricated bullet was dropped by the grounding check.
        assert "kubernetes" not in joined
        assert "pytorch" not in joined

    def test_ai_malformed_json_falls_back_to_heuristic(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: "garbage not json")
        resume = "• Built a thermal sensor in Java for the ME 270 capstone\n"
        resp = client.post("/api/tailor/extract-bullets", json={"resume_text": resume})
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "heuristic"
        assert any("thermal sensor" in b for b in body["bullets"])


class TestBulletGrounding:
    """Extraction is documented as VERBATIM, so grounding is contiguous
    containment (NFKC + collapsed whitespace), not token overlap. The old 60%
    token-overlap rule let the model copy most of a line and append a
    fabricated tool or metric. The bullet must also start and end where a
    résumé line or bullet does: a cut can drop the student's qualifier."""

    RESUME = (
        "Designed a thermal sensor in Java and validated it against ME 270 "
        "data\nPresented results at the undergraduate symposium"
    )

    def test_verbatim_line_is_grounded(self):
        assert tailor_module._bullet_grounded(
            "Designed a thermal sensor in Java and validated it against ME 270 data",
            self.RESUME,
        )

    def test_copied_line_with_appended_tool_is_rejected(self):
        # >60% of tokens overlap the resume — the old rule passed this.
        assert not tailor_module._bullet_grounded(
            "Designed a thermal sensor in Java and validated it against "
            "ME 270 data using PyTorch",
            self.RESUME,
        )

    def test_copied_line_with_appended_metric_is_rejected(self):
        assert not tailor_module._bullet_grounded(
            "Presented results at the undergraduate symposium to 500 attendees",
            self.RESUME,
        )

    def test_whitespace_and_case_differences_tolerated(self):
        assert tailor_module._bullet_grounded(
            "designed a Thermal  sensor\nin java and validated it against me 270 data",
            self.RESUME,
        )

    def test_nfkc_normalizes_fullwidth_glyphs(self):
        # Full-width "Ｊａｖａ" normalizes to ASCII "java" under NFKC.
        assert tailor_module._bullet_grounded(
            "Designed a thermal sensor in Ｊａｖａ and validated it against ME 270 data",
            self.RESUME,
        )

    def test_cjk_bullet_is_grounded_as_its_whole_line(self):
        resume = "负责设计热传感器并完成 ME 270 数据验证\n协助博士生设计热传感器的外壳。"
        assert tailor_module._bullet_grounded("负责设计热传感器并完成 ME 270 数据验证", resume)
        assert tailor_module._bullet_grounded("协助博士生设计热传感器的外壳", resume)
        assert not tailor_module._bullet_grounded("设计热传感器", resume)
        assert not tailor_module._bullet_grounded("设计热传感器的外壳。", resume)   # drops 协助博士生
        assert not tailor_module._bullet_grounded("部署 Kubernetes 集群", resume)

    @pytest.mark.parametrize("cut", [
        "survey 50 farmers about irrigation practices",          # drops "Planned to"
        "lead the robotics team build",                          # drops "Did not" and the student's own part
        "Did not lead the robotics team build",                  # drops "; I wired the sensors"
        "Built a dashboard for the lab",                         # the wrapped line's "that was never deployed" dropped
        "that was never deployed",                               # a wrapped line on its own
    ])
    def test_a_cut_inside_a_line_is_not_grounded(self, cut):
        resume = ("EXPERIENCE\n"
                  "• Planned to survey 50 farmers about irrigation practices\n"
                  "• Did not lead the robotics team build; I wired the sensors\n"
                  "• Built a dashboard for the lab\n"
                  "  that was never deployed.\n")
        assert not tailor_module._bullet_grounded(cut, resume)

    @pytest.mark.parametrize("line", [
        "Planned to survey 50 farmers about irrigation practices",
        "• Planned to survey 50 farmers about irrigation practices",
        "Did not lead the robotics team build; I wired the sensors",
        "Built a dashboard for the lab that was never deployed",         # wrapped lines joined, final mark dropped
        "Built a dashboard for the lab that was never deployed.",
        "Wrote the methods section",                                     # after an inline glyph
    ])
    def test_a_whole_line_bullet_or_wrapped_bullet_is_grounded(self, line):
        resume = ("EXPERIENCE\n"
                  "• Planned to survey 50 farmers about irrigation practices\n"
                  "• Did not lead the robotics team build; I wired the sensors\n"
                  "• Built a dashboard for the lab\n"
                  "  that was never deployed.\n"
                  "Research Assistant • Wrote the methods section\n")
        assert tailor_module._bullet_grounded(line, resume)

    # Round-3 review (criterion 1): a row that opens with a capital, a digit, a CJK character or
    # "(" was read as a line of its own, so the first physical row of a wrapped glyph bullet was
    # accepted and the rest of the student's line (often its status) was dropped.
    WRAPPED = ("EXPERIENCE\n"
               "• Co-authored a paper on soil moisture sensing for the campus farm\n"
               "Under review at the ICRA 2026 workshop\n"
               "• Wrote a grant proposal for the robotics club\n"
               "(in preparation, not yet submitted)\n"
               "• Surveyed farmers about irrigation schedules in\n"
               "12 villages; the analysis is planned for spring\n"
               "• 搭建了校园农场的土壤湿度传感器网络并整理数据\n"
               "计划于 2026 年投稿\n"
               "• Built a weather station with two classmates.\n"
               "PROJECTS\n"
               "• Analyzed 88 samples with PyTorch\n"
               "\n"
               "Teaching Assistant, CS 225\n")

    @pytest.mark.parametrize("cut", [
        "Co-authored a paper on soil moisture sensing for the campus farm",    # capital: "Under review"
        "Wrote a grant proposal for the robotics club",                         # "(in preparation ...)"
        "Surveyed farmers about irrigation schedules in",                       # digit: "12 villages ..."
        "搭建了校园农场的土壤湿度传感器网络并整理数据",                              # CJK: "计划于 2026 年投稿"
        "Under review at the ICRA 2026 workshop",                               # a continuation on its own
        "计划于 2026 年投稿",
    ])
    def test_the_first_row_of_a_wrapped_glyph_bullet_is_not_grounded(self, cut):
        assert not tailor_module._bullet_grounded(cut, self.WRAPPED)

    @pytest.mark.parametrize("line", [
        "Co-authored a paper on soil moisture sensing for the campus farm Under review at the ICRA 2026 workshop",
        "Wrote a grant proposal for the robotics club (in preparation, not yet submitted)",
        "Surveyed farmers about irrigation schedules in 12 villages; the analysis is planned for spring",
        "搭建了校园农场的土壤湿度传感器网络并整理数据计划于 2026 年投稿",       # a CJK wrap joins with no space
        "搭建了校园农场的土壤湿度传感器网络并整理数据 计划于 2026 年投稿",
        "Built a weather station with two classmates.",                         # a closing mark ends the item
        "Analyzed 88 samples with PyTorch",                                      # a heading row or a blank row
    ])
    def test_a_whole_wrapped_glyph_bullet_is_grounded(self, line):
        assert tailor_module._bullet_grounded(line, self.WRAPPED)

    def test_a_title_case_heading_ends_the_glyph_bullet_above_it(self):
        resume = ("Experience\n• Ran 40 soil moisture trials for the campus farm\n"
                  "Honors and Awards\n• Received the Dean's research grant\n")
        assert tailor_module._bullet_grounded("Ran 40 soil moisture trials for the campus farm", resume)
        assert tailor_module._heuristic_bullets(resume) == ["Ran 40 soil moisture trials for the campus farm",
                                                            "Received the Dean's research grant"]

    def test_the_heuristic_keeps_each_wrapped_glyph_bullet_whole(self):
        assert tailor_module._heuristic_bullets(self.WRAPPED, limit=1000) == [
            "Co-authored a paper on soil moisture sensing for the campus farm Under review at the ICRA 2026 workshop",
            "Wrote a grant proposal for the robotics club (in preparation, not yet submitted)",
            "Surveyed farmers about irrigation schedules in 12 villages; the analysis is planned for spring",
            "搭建了校园农场的土壤湿度传感器网络并整理数据计划于 2026 年投稿",
            "Built a weather station with two classmates.",
            "Analyzed 88 samples with PyTorch",
        ]

    def test_paraphrase_is_rejected(self):
        assert not tailor_module._bullet_grounded(
            "Validated a Java thermal sensor against ME 270 data",
            self.RESUME,
        )


class TestAntiFabrication:
    """The non-negotiable test: model cannot smuggle in unlisted skills."""

    def test_fabrication_python_when_profile_has_none(
        self, java_profile, real_opp_id, monkeypatch,
    ):
        """Java-only profile + LLM that hallucinates Python expertise.

        Expected: the bullet comes back as the student wrote it, with the
        reason, and no fabricated word reaches the response.
        """
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = em_reply(em_row("b1", "Built scalable ML pipelines using PyTorch and deployed Kubernetes clusters "
                                     "for distributed training.", ops=[{"op": "verb_first"}]))
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)

        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Designed a thermal sensor in Java"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        [bullet] = body["tailored_bullets"]
        assert bullet["status"] == "kept" and bullet["text"] == "Designed a thermal sensor in Java"
        assert bullet["reason_code"] in ("beyond_allowed_edit", "rewrite_rejected")
        joined = json.dumps(body).lower()
        assert "pytorch" not in joined and "kubernetes" not in joined

    def test_valid_tailored_passes_through(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """The current original establishes the work and its quoted evidence."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = em_reply(em_row("b1", RA_VERB_FIRST, ops=[{"op": "verb_first"}]))
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)

        resp = client.post(
            "/api/tailor",
            json={"profile": python_profile, "opportunity_id": real_opp_id, "original_bullets": [RA]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        [bullet] = body["tailored_bullets"]
        assert (bullet["status"], bullet["text"], bullet["ops"]) == ("rewritten", RA_VERB_FIRST, ["verb_first"])
        # The evidence shown is the student's own bullet.
        assert bullet["source_evidence"] == RA

    def test_generic_prose_is_not_flagged_as_fabrication(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Ordinary verbs and abstract nouns are not fabricated vocabulary.

        Under STRICT, words like 'demonstrating', 'foundational',
        'understanding', 'applying' were treated as fabricated because they
        were absent from the English filler allowlist. LENIENT_PROSE flags only
        concreteness-signal tokens, so none of these words is a fabrication.

        Words the original never used still cannot enter a rewrite: the
        evidence map's closed vocabulary keeps both drafts below, and the
        appended ", demonstrating ..." clause is a relevance claim besides.
        """
        from backend.lib.grounding import LENIENT_PROSE_NUMERIC, validate_no_fabrication

        original = "Worked on Python projects in CS 225"
        padded = ("Applied Python during CS 225 coursework, "
                  "demonstrating foundational understanding while "
                  "identifying and analyzing trends.")
        plain = "Applied foundational Python understanding across CS 225 projects."
        assert validate_no_fabrication(padded, original, policy=LENIENT_PROSE_NUMERIC) == (True, [])
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = em_reply(em_row("b1", padded, ops=[{"op": "verb_first"}]),
                        em_row("b2", plain, ops=[{"op": "verb_first"}]))
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)

        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": [original, original],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        assert [(b["status"], b["text"]) for b in body["tailored_bullets"]] == [("kept", original)] * 2
        assert {b["reason_code"] for b in body["tailored_bullets"]} == {"beyond_allowed_edit"}

    def test_fabrication_lowercase_tool_when_profile_lacks_it(
        self, java_profile, real_opp_id, monkeypatch,
    ):
        """TAILOR-1: an all-lowercase tool (langchain/pinecone) the student
        never listed carries no case/digit signal but is still refused — it
        must not slip onto the resume."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = em_reply(em_row("b1", "Built RAG pipelines with langchain over a pinecone vector store.",
                               ops=[{"op": "verb_first"}]))
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)
        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Designed a thermal sensor in Java"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        joined = " ".join(b["text"] for b in body["tailored_bullets"]).lower()
        assert "langchain" not in joined and "pinecone" not in joined

    def test_posting_tech_term_not_grounded_by_corpus(self):
        """TAILOR-2: a concrete tech term that appears only in the posting must
        NOT ground a student's tailored claim — the evidence corpus is
        student-side only, so the model cannot assert the exact skill the
        posting screens for that the student lacks."""
        from backend.lib.grounding import LENIENT_PROSE, validate_no_fabrication
        from backend.routes.tailor import _build_evidence_corpus

        profile = {"hard_skills": [{"name": "Java", "level": "experienced"}], "coursework": []}
        corpus = _build_evidence_corpus(profile, ["Built a thermal sensor in Java"])
        passed, fab = validate_no_fabrication(
            "Trained deep learning models in PyTorch.", corpus, policy=LENIENT_PROSE,
        )
        assert not passed and "pytorch" in fab

    def test_datelike_coursework_does_not_enter_the_corpus(self):
        """A venue/date entry ("CVPR 2026") stored as coursework must not seed
        the evidence corpus: its tokens would let a fabricated claim like
        "presented at CVPR" pass the grounding gate."""
        from backend.routes.tailor import _build_evidence_corpus

        profile = {"hard_skills": [], "coursework": ["CVPR 2026", "ECE 391"]}
        corpus = _build_evidence_corpus(profile, [])
        assert "cvpr" not in corpus
        assert "ece 391" in corpus


class TestLlmFailureModes:
    def test_malformed_json_falls_back(
        self, java_profile, real_opp_id, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(
            tailor_module, "chat_completion",
            lambda *a, **k: "not even close to JSON — model went off-script",
        )

        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Designed a thermal sensor in Java"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "fallback"
        assert "llm_failed_or_invalid_json" in body["warnings"]

    def test_llm_returns_none_falls_back(
        self, java_profile, real_opp_id, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: None)

        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Designed a thermal sensor in Java"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "fallback"
        assert "llm_failed_or_invalid_json" in body["warnings"]

    def test_json_with_markdown_fence_still_parses(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Some providers ignore 'no markdown fences' — we strip and parse."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fenced = "```json\n" + json.dumps({
            "bullets": [{
                "text": "Implemented Python machine learning projects in CS 225",
                "source_evidence": "Python; CS 225",
            }],
        }) + "\n```"
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fenced)

        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Implemented Python machine learning projects for CS 225"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        assert len(body["tailored_bullets"]) == 1


class TestInputCaps:
    """Over-limit bullets are refused with the limit named, never cut down.

    The validator used to keep the first 12 bullets and the first 500
    characters of each, so a student got a rewrite of text they never wrote
    in full and no word that anything was missing."""

    @staticmethod
    def _post(profile, opp_id, bullets):
        return client.post(
            "/api/tailor",
            json={"profile": profile, "opportunity_id": opp_id, "original_bullets": bullets},
        )

    @pytest.fixture(autouse=True)
    def _no_provider(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)

    def test_more_than_12_bullets_refused(self, java_profile, real_opp_id):
        resp = self._post(java_profile, real_opp_id, [f"bullet number {i}" for i in range(13)])
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "TAILOR_INPUT_TOO_LARGE"
        assert detail["max_bullets"] == 12 and detail["max_characters_per_bullet"] == 500
        assert "12" in detail["message"] and "500" in detail["message"]

    def test_exactly_12_bullets_all_kept(self, java_profile, real_opp_id):
        bullets = [f"bullet number {i}" for i in range(12)]
        resp = self._post(java_profile, real_opp_id, bullets)
        assert resp.status_code == 200
        assert [b["text"] for b in resp.json()["tailored_bullets"]] == bullets

    def test_blank_lines_do_not_count_toward_the_limit(self, java_profile, real_opp_id):
        bullets = [f"bullet number {i}" for i in range(12)]
        resp = self._post(java_profile, real_opp_id, bullets + ["", "   "])
        assert resp.status_code == 200
        assert len(resp.json()["tailored_bullets"]) == 12

    def test_bullet_over_500_chars_refused(self, java_profile, real_opp_id):
        resp = self._post(java_profile, real_opp_id, ["x" * 501])
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "TAILOR_INPUT_TOO_LARGE"

    def test_bullet_of_500_chars_kept_whole(self, java_profile, real_opp_id):
        resp = self._post(java_profile, real_opp_id, ["x" * 500])
        assert resp.status_code == 200
        assert resp.json()["tailored_bullets"][0]["text"] == "x" * 500

    def test_refusal_returns_the_global_llm_slot(self, java_profile, real_opp_id, monkeypatch):
        from backend import main as main_mod

        monkeypatch.setattr(main_mod, "RATE_LIMIT_DISABLED", False)
        main_mod._rate_buckets.clear()
        main_mod._global_buckets.clear()
        try:
            resp = self._post(java_profile, real_opp_id, [f"bullet number {i}" for i in range(13)])
            assert resp.status_code == 422
            assert main_mod._global_buckets["llm"] == []
        finally:
            main_mod._rate_buckets.clear()
            main_mod._global_buckets.clear()

    def test_empty_string_bullets_dropped(
        self, java_profile, real_opp_id, monkeypatch,
    ):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)

        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["", "   ", "actual content"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["tailored_bullets"]) == 1
        assert body["tailored_bullets"][0]["text"] == "actual content"


class TestSourceBullets:
    """After "Use kept as new originals" each bullet travels with its source.

    source_bullets[i] is bullet i's only evidence; original_bullets[i] is its
    current wording, which the model rewrites and the student keeps when the
    rewrite is refused. The sources of one request are capped as a whole,
    like the 12 x 500 characters of the bullets themselves.
    """
    SOURCE = "Cleaned 212 survey responses in R and built 3 charts."
    CURRENT = "Built 3 charts and cleaned 212 survey responses in R."
    OTHER = "Tutored 30 students in CS 124."

    @staticmethod
    def _post(profile, opp_id, bullets, sources):
        return client.post("/api/tailor", json={"profile": profile, "opportunity_id": opp_id,
                                                "original_bullets": bullets, "source_bullets": sources})

    @pytest.mark.parametrize("sources", [
        ["one source"],                                   # fewer sources than bullets
        ["one source", "two", "three"],                   # more
        ["x" * 3001, "y" * 3000],                         # 6,001 characters in all
        ["x" * 6001, "y"],                                # one source over the cap
    ])
    def test_sources_that_do_not_fit_are_refused_before_any_work(self, java_profile, real_opp_id, monkeypatch,
                                                                 sources):
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: pytest.fail("no model call"))
        resp = self._post(java_profile, real_opp_id, ["first bullet", "second bullet"], sources)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert (detail["code"], detail["field"], detail["max_source_characters"]) == (
            "TAILOR_INPUT_TOO_LARGE", "source_bullets", 6000)
        assert "6000" in detail["message"]

    def test_sources_of_exactly_the_cap_are_accepted(self, java_profile, real_opp_id, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        resp = self._post(java_profile, real_opp_id, ["first bullet", "second bullet"], ["x" * 3000, "y" * 3000])
        assert resp.status_code == 200
        assert [b["source_evidence"] for b in resp.json()["tailored_bullets"]] == ["x" * 3000, "y" * 3000]

    def test_the_source_is_the_evidence_and_the_bullet_is_the_wording(self, python_profile, real_opp_id,
                                                                     monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        anchor = evidence_map.Anchor("t1", {"field": "description", "requirement_index": None, "start": 0,
                                            "end": 31, "quote": "Cleaned survey responses with R"})
        monkeypatch.setattr(tailor_module, "_snapshot_anchors", lambda source, snapshot: [anchor])
        rewrite = "Cleaned 212 survey responses in R and built 3 charts."
        captured, reviewed = {}, []

        def fake_chat(messages, **kwargs):
            captured["units"] = json.loads(messages[1]["content"].split("DATA (JSON):\n", 1)[1])["units"]
            captured["system"] = messages[0]["content"]
            link = {"id": "L1", "anchor": "t1", "term": "Cleaned survey responses", "source": "Cleaned 212 survey responses",
                    "relation": "same"}
            return em_reply(em_row("b1", rewrite, ops=[{"op": "lead_with", "link": "L1"}], links=[link]),
                            em_row("b2"))

        def review(pairs, deadline=None):
            reviewed.extend((pair.original, pair.rewrite) for pair in pairs)
            for pair in pairs:
                for link in pair.links:
                    link.entailed = True
            return ["accepted"] * len(pairs)

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)
        monkeypatch.setattr(evidence_map, "ai_review", review)
        resp = self._post(python_profile, real_opp_id, [self.CURRENT, self.OTHER], [self.SOURCE, self.OTHER])
        assert resp.status_code == 200, resp.text
        # The model sees the source as the original and the bullet as its current wording.
        assert captured["units"] == [{"unit_id": "b1", "original": self.SOURCE, "current": self.CURRENT},
                                     {"unit_id": "b2", "original": self.OTHER}]
        assert 'may also carry "current"' in captured["system"]
        # The review judges the rewrite against the source, never against reviewed wording.
        assert reviewed == [(self.SOURCE, rewrite)]
        first, second = resp.json()["tailored_bullets"]
        assert (first["status"], first["text"], first["source_evidence"]) == ("rewritten", rewrite, self.SOURCE)
        assert (second["status"], second["text"], second["source_evidence"]) == ("kept", self.OTHER, self.OTHER)

    def test_a_refused_rewrite_keeps_the_current_wording_not_the_source(self, python_profile, real_opp_id,
                                                                        monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        anchor = evidence_map.Anchor("t1", {"field": "description", "requirement_index": None, "start": 0,
                                            "end": 31, "quote": "Cleaned survey responses with R"})
        monkeypatch.setattr(tailor_module, "_snapshot_anchors", lambda source, snapshot: [anchor])
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: em_reply(em_row("b1")))
        resp = self._post(python_profile, real_opp_id, [self.CURRENT], [self.SOURCE])
        [bullet] = resp.json()["tailored_bullets"]
        assert (bullet["status"], bullet["text"], bullet["source_evidence"]) == ("kept", self.CURRENT, self.SOURCE)


class TestSourceIndex:
    """R71-E: every TailoredBullet carries the matching original index."""

    def test_fallback_source_indices_are_positional(
        self, java_profile, real_opp_id, monkeypatch,
    ):
        """Local fallback passthrough preserves [0, 1, 2, …] indices."""
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)

        bullets = ["alpha bullet", "beta bullet", "gamma bullet"]
        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": bullets,
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "fallback"
        # source_index aligns with input position so the UI can pair
        # each fallback bullet back to its matching textarea row.
        assert [b["source_index"] for b in body["tailored_bullets"]] == [0, 1, 2]

    def test_ai_path_source_indices_match_submission(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """LLM-accepted bullets keep their index into original_bullets."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = json.dumps({
            "bullets": [
                {"text": "Implemented Python ML exercises in CS 225.", "source_evidence": "Python"},
                {"text": "Built ML models with Python during coursework", "source_evidence": "Python"},
            ],
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)

        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": [
                    "Implemented Python ML exercises in CS 225",
                    "Built Python ML models during coursework",
                ],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        # The prompt mandates same-order rewrites, so accepted[i] points
        # back to original_bullets[i].
        indices = [b["source_index"] for b in body["tailored_bullets"]]
        assert indices == [0, 1]

    def test_ai_overproduction_clamped_to_input_length(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Misbehaving model returns N+1 bullets — source_index clamps."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = json.dumps({
            "bullets": [
                {"text": "Python ML in CS 225", "source_evidence": "Python"},
                {"text": "More Python ML work", "source_evidence": "Python"},
                # Extra bullet the model invented past the submitted count.
                {"text": "Yet another Python project", "source_evidence": "Python"},
            ],
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)

        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Did Python coursework"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        # All three accepted, but every source_index clamps to the single
        # input bullet — frontend won't dereference out of bounds.
        for b in body["tailored_bullets"]:
            assert b["source_index"] == 0


class TestLocale:
    """R71-D: the caller's UI locale selects the system prompt's language; each rewrite keeps its bullet's (w14.1)."""

    def test_default_locale_is_en(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Omitting `locale` keeps EN behavior — the schema default."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        captured: dict = {}

        def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            return json.dumps({"bullets": [
                {"text": "Implemented Python ML projects in CS 225", "source_evidence": "Python"},
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)
        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Did Python work in CS 225"],
            },
        )
        assert resp.status_code == 200
        # The EN prompt says each rewrite keeps its original's language; the ZH rule is absent.
        assert "Write each rewrite in the language of its own original" in captured["system"]
        assert "每条改写都用它自己原文的语言" not in captured["system"]

    def test_locale_zh_uses_chinese_prompt(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        captured: dict = {}

        def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            return json.dumps({"bullets": [
                {
                    "text": "在 CS 225 课程中用 Python 完成机器学习项目",
                    "source_evidence": "Python; CS 225",
                },
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)
        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Implemented machine learning projects in Python for CS 225"],
                "locale": "zh",
            },
        )
        assert resp.status_code == 200
        # The UI locale chooses the instructions' language; the rule keeps this English bullet in English.
        assert "每条改写都用它自己原文的语言，英文原文仍写英文" in captured["system"]
        assert "Write each rewrite in the language of its own original" not in captured["system"]
        body = resp.json()
        # A reply without evidence-map rows keeps the student's own bullet.
        assert body["method"] == "ai"
        assert body["tailored_bullets"][0]["text"] == "Implemented machine learning projects in Python for CS 225"
        assert body["tailored_bullets"][0]["reason_code"] == "model_unavailable"

    def test_locale_zh_cn_normalized_to_zh(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Locale-region tags ('zh-CN', 'zh_TW') normalize to 'zh'."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        captured: dict = {}

        def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            return json.dumps({"bullets": [
                {"text": "用 Python 在 CS 225 做实验", "source_evidence": "Python"},
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)
        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Did Python work in CS 225"],
                "locale": "zh-CN",
            },
        )
        assert resp.status_code == 200
        assert "每条改写都用它自己原文的语言" in captured["system"]

    def test_unknown_locale_falls_back_to_en(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Forward-compatible: 'fr' or random strings don't 422, fall to EN."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        captured: dict = {}

        def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            return json.dumps({"bullets": [
                {"text": "Implemented Python ML projects in CS 225", "source_evidence": "Python"},
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)
        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Did Python work in CS 225"],
                "locale": "fr-FR",
            },
        )
        assert resp.status_code == 200
        # 'fr' is not 'zh', so we fall to the EN prompt — no 422.
        assert "Write each rewrite in the language of its own original" in captured["system"]


class TestSkillLevelThreading:
    """Skill proficiency levels reach the LLM prompt and the system prompt
    tells the model to honor them (highlight expert/experienced, never
    overclaim beginner). Plain-string skills stay valid with no level."""

    @pytest.fixture
    def leveled_profile(self, python_profile) -> dict:
        return {
            **python_profile,
            "hard_skills": [
                {"name": "Python", "level": "expert"},
                {"name": "Java", "level": "beginner"},
            ],
        }

    def test_levels_threaded_into_user_prompt(
        self, leveled_profile, real_opp_id, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        captured: dict = {}

        def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            captured["user"] = messages[1]["content"]
            return json.dumps({"bullets": [
                {"text": "Implemented Python ML projects in CS 225", "source_evidence": "Python"},
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)
        resp = client.post(
            "/api/tailor",
            json={
                "profile": leveled_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Did Python work in CS 225"],
            },
        )
        assert resp.status_code == 200
        assert "- Python (expert)" in captured["user"]
        assert "- Java (beginner)" in captured["user"]

    def test_neither_prompt_asks_the_model_to_hedge_inside_a_bullet(self):
        """Honesty about a level is a prohibition, not a phrase to insert.

        Rule 5 used to say "frame it as exposure or foundational familiarity",
        and the model did exactly that. A live /api/tailor draft came back as
        "Built a Python-based reconstruction algorithm, DRAWING ON FOUNDATIONAL
        PYTHON EXPOSURE, to process undersampled MRI k-space data" — from an
        original bullet reading "Built a Python pipeline that reconstructed
        undersampled MRI k-space data, cutting scan time 30%".

        The bullet is the student's own statement, and building the thing is
        stronger evidence of the skill than any self-reported tag. Inserting a
        hedge makes their resume argue against them, which is its own
        inaccuracy — the same one the level rules exist to prevent, pointing
        the other way. The per-bullet renovation prompt has always been
        prohibition-only; these two now match it.
        """
        for prompt in (tailor_module._SYSTEM_PROMPT_EN,
                       tailor_module._SYSTEM_PROMPT_ZH):
            assert "foundational familiarity" not in prompt
            assert "有基础、接触过" not in prompt
        # The prohibition itself stays, in both languages.
        assert "never present a beginner skill" in tailor_module._SYSTEM_PROMPT_EN
        assert "绝不能写成精通或熟练掌握" in tailor_module._SYSTEM_PROMPT_ZH

    def test_en_system_prompt_states_level_honesty_rule(
        self, leveled_profile, real_opp_id, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        captured: dict = {}

        def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            return json.dumps({"bullets": [
                {"text": "Implemented Python ML projects in CS 225", "source_evidence": "Python"},
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)
        resp = client.post(
            "/api/tailor",
            json={
                "profile": leveled_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Did Python work in CS 225"],
            },
        )
        assert resp.status_code == 200
        assert "self-reported" in captured["system"]
        assert "never present a beginner skill" in captured["system"]

    def test_zh_system_prompt_states_level_honesty_rule(
        self, leveled_profile, real_opp_id, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        captured: dict = {}

        def fake_chat(messages, **kwargs):
            captured["system"] = messages[0]["content"]
            return json.dumps({"bullets": [
                {"text": "在 CS 225 用 Python 完成机器学习项目", "source_evidence": "Python"},
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)
        resp = client.post(
            "/api/tailor",
            json={
                "profile": leveled_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Did Python work in CS 225"],
                "locale": "zh",
            },
        )
        assert resp.status_code == 200
        assert "自评水平" in captured["system"]
        assert "绝不能" in captured["system"]

    def test_plain_string_skill_has_no_level_suffix(self, monkeypatch):
        """Backward compat: a raw string skill renders as a bare '- Name'
        line — no '(level)' annotation is invented for it."""
        captured: dict = {}

        def fake_chat(messages, **kwargs):
            captured["user"] = messages[1]["content"]
            return json.dumps({"bullets": [
                {"text": "Used MATLAB for signal analysis", "source_evidence": "MATLAB"},
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)
        out = tailor_module._ai_tailor_bullets(
            {"name": "S", "major": "EE", "year": "junior", "hard_skills": ["MATLAB"]},
            {"title": "Lab", "eligibility": {}, "keywords": []},
            ["Did MATLAB signal work"],
        )
        assert out is not None
        assert "- MATLAB\n" in captured["user"]
        assert "- MATLAB (" not in captured["user"]


class TestAnUnconfirmedImportIsNotEmphasised:
    """The prompt speaks at the CLAIMABLE level; the evidence corpus keeps the
    stored one.

    Two different questions, and collapsing them breaks the feature in opposite
    directions. The prompt decides what the model is told to lead with, so an
    unconfirmed import must arrive as `beginner` or the system rules tell it to
    emphasise a level the student never chose. The corpus decides which words
    may appear at all, so it must keep the stored level — narrowing it makes a
    legitimate composite citation like "Python (experienced)" read as
    fabrication and get the whole bullet rejected.
    """

    _IMPORTED = {
        "name": "S", "major": "EE", "year": "junior",
        "hard_skills": [{"name": "Python", "level": "experienced",
                         "source": "resume"}],
    }

    @staticmethod
    def _capture(monkeypatch, captured):
        def fake_chat(messages, **kwargs):
            captured["user"] = messages[1]["content"]
            return json.dumps({"bullets": [
                {"text": "Used Python for analysis", "source_evidence": "Python"},
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", fake_chat)

    def test_the_prompt_receives_the_withheld_level(self, monkeypatch):
        captured: dict = {}
        self._capture(monkeypatch, captured)
        out = tailor_module._ai_tailor_bullets(
            self._IMPORTED, {"title": "Lab", "eligibility": {}, "keywords": []},
            ["Did Python work"])
        assert out is not None
        assert "- Python (beginner)" in captured["user"]
        assert "- Python (experienced)" not in captured["user"]

    def test_the_corpus_still_admits_the_stored_level(self):
        """Otherwise the model may not even mention what the resume says."""
        corpus = tailor_module._build_evidence_corpus(self._IMPORTED, [])
        assert "experienced" in corpus
        assert "python" in corpus

    def test_a_confirmed_import_reaches_the_prompt_at_its_real_level(
        self, monkeypatch,
    ):
        captured: dict = {}
        self._capture(monkeypatch, captured)
        profile = dict(self._IMPORTED)
        profile["hard_skills"] = [{"name": "Python", "level": "experienced",
                                   "source": "resume", "confirmed": True}]
        out = tailor_module._ai_tailor_bullets(
            profile, {"title": "Lab", "eligibility": {}, "keywords": []},
            ["Did Python work"])
        assert out is not None
        assert "- Python (experienced)" in captured["user"]


class TestUnitHelpers:
    """Unit tests for the validator + evidence builder, no HTTP layer."""

    def test_hard_claims_extracts_5plus_char_tokens(self):
        from backend.lib.grounding import hard_claims as _hard_claims
        claims = _hard_claims("Built Python pipelines for ML in CS")
        # 'built' filtered by common-filler at validation time, but extract-
        # level it shows up. We only care these 5+ char tokens are *found*.
        assert "python" in claims
        assert "pipelines" in claims
        # 'ml' and 'cs' too short; 'for' too short.
        assert "ml" not in claims
        assert "cs" not in claims

    def test_validator_flags_unlisted_skill(self):
        from backend.lib.grounding import validate_no_fabrication as _validate_no_fabrication
        passed, fab = _validate_no_fabrication(
            "Built pipelines with Python and PyTorch.",
            evidence_corpus="java sensors thermodynamics mechanical engineering",
        )
        assert not passed
        assert "python" in fab
        assert "pytorch" in fab

    def test_validator_accepts_when_evidence_present(self):
        from backend.lib.grounding import validate_no_fabrication as _validate_no_fabrication
        passed, fab = _validate_no_fabrication(
            "Built Python projects using PyTorch frameworks.",
            evidence_corpus="python pytorch projects machine learning",
        )
        assert passed
        assert fab == []

    def test_validator_allows_opp_vocabulary_in_corpus(self):
        """The opp's own description tokens are in the corpus by design."""
        from backend.lib.grounding import validate_no_fabrication as _validate_no_fabrication
        # 'compiler' isn't in profile, but opp description mentions it.
        passed, fab = _validate_no_fabrication(
            "Wrote compiler passes in Python during coursework",
            evidence_corpus=(
                "python coursework computer science compiler passes systems"
            ),
        )
        assert passed, f"expected pass, got fabricated={fab}"

    def test_evidence_corpus_is_student_side_only(self):
        # TAILOR-2: the evidence corpus that grounds concrete tech/credential
        # claims must be the STUDENT side only — folding in the posting's own
        # skills_required / description let the model claim exactly the
        # technologies the posting screens for that the student never listed.
        from backend.routes.tailor import _build_evidence_corpus
        profile = {
            "major": "Computer Science",
            "research_interests_text": "machine learning systems",
            "hard_skills": [{"name": "Python", "level": "experienced"}],
            "coursework": ["CS 225"],
        }
        corpus = _build_evidence_corpus(profile, ["Did Python projects"])
        # Profile + original-bullet signal is present.
        assert "python" in corpus
        assert "cs 225" in corpus
        assert "machine learning" in corpus
        assert "did python projects" in corpus


class TestEachRewriteStaysWithItsOwnBullet:
    """A rewrite is paired to its bullet by unit id, never by position. Every
    submitted bullet comes back once, in order: a rewrite, or the bullet as
    written with the reason."""

    def test_rows_out_of_order_or_missing_stay_with_their_own_bullets(
        self, monkeypatch, java_profile, real_opp_id,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        originals = ["Tutored 30 students in circuits lab each week", RA,
                     "Wrote MATLAB analysis for EEG recordings"]
        fake = em_reply(
            em_row("b2", RA_VERB_FIRST, ops=[{"op": "verb_first"}]),
            em_row("b3"),
            # b1 is missing; an unknown id and a second b3 row are ignored.
            em_row("b9", "Tutored 30 students weekly.", ops=[{"op": "verb_first"}]),
        )
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)

        resp = client.post("/api/tailor", json={
            "profile": java_profile,
            "opportunity_id": real_opp_id,
            "original_bullets": originals,
        })
        assert resp.status_code == 200
        rows = resp.json()["tailored_bullets"]
        assert [(row["source_index"], row["status"], row["reason_code"]) for row in rows] == [
            (0, "kept", "model_unavailable"), (1, "rewritten", None), (2, "kept", "no_link")]
        assert [row["text"] for row in rows] == [originals[0], RA_VERB_FIRST, originals[2]]


class TestEveryBulletTheStudentSubmittedIsSent:
    """The modal prefills 12, /extract-bullets returns 12 and the schema keeps
    12, but the prompt was built from the first 8. The last four were never
    sent, and the modal then told the student they "couldn't be grounded in
    your profile" — naming a grounding failure that never happened."""

    def test_all_twelve_reach_the_prompt(self, monkeypatch, java_profile, real_opp_id):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        originals = [f"Ran experiment number {n} in the fluids lab" for n in range(1, 13)]
        seen: dict[str, str] = {}

        def capture(*args, **kwargs):
            messages = args[0] if args else kwargs.get("messages", [])
            seen["prompt"] = " ".join(str(m.get("content", "")) for m in messages)
            return json.dumps({"bullets": [
                {"text": b, "source_evidence": b} for b in originals
            ]})

        monkeypatch.setattr(tailor_module, "chat_completion", capture)
        resp = client.post("/api/tailor", json={
            "profile": java_profile,
            "opportunity_id": real_opp_id,
            "original_bullets": originals,
        })
        assert resp.status_code == 200
        assert "experiment number 12" in seen["prompt"]
        assert len(resp.json()["tailored_bullets"]) == 12


@pytest.mark.parametrize("field", ["original_bullets", "source_bullets"])
@pytest.mark.parametrize("junk", [0, [], {}], ids=["ints", "empty lists", "empty dicts"])
def test_a_body_of_wrongly_typed_bullets_is_one_short_error(field, junk):
    """Round 1, criterion (4): 524,287 wrongly typed items in a 1 MiB body made 524,287 validation errors and a
    36 MB 422, built and encoded on the event loop (4-7 s; scripts/request_parse_lag.py). The list's length is
    checked first now, and a 422 names at most its first 20 errors."""
    items = [junk] * 300_000
    body = {"profile": {"name": "Sample Student"}, "opportunity_id": "any", field: items}
    if field == "source_bullets":
        body["original_bullets"] = ["Built a robot."]
    response = TestClient(app).post("/api/tailor", json=body)
    assert response.status_code == 422
    assert 1 <= len(response.json()["detail"]) <= 20 and len(response.content) < 4096


def test_two_hundred_bullets_still_get_the_named_refusal(real_opp_id):
    """The schema bound sits far above the route's own limit, which still refuses by name."""
    response = TestClient(app).post("/api/tailor", json={
        "profile": {"name": "Sample Student"}, "opportunity_id": real_opp_id,
        "original_bullets": [f"Built robot number {i}." for i in range(200)]})
    assert response.status_code == 422
    assert "TAILOR_INPUT_TOO_LARGE" in response.text
