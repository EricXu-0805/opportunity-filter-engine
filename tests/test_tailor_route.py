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
from backend.lib.release_scope import opportunity_visible_in_release
from backend.main import app
from backend.routes import tailor as tailor_module
from src.evidence import is_actionable_target

client = TestClient(app)


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
        assert resp.json() == {"ai_available": True}

    def test_status_false_when_no_provider(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        resp = client.get("/api/tailor/status")
        assert resp.status_code == 200
        assert resp.json() == {"ai_available": False}


class TestExtractBullets:
    """R71-G: POST /api/tailor/extract-bullets — resume text → bullet lines."""

    def test_empty_text_returns_empty_heuristic(self):
        resp = client.post("/api/tailor/extract-bullets", json={"resume_text": "   "})
        assert resp.status_code == 200
        body = resp.json()
        assert body == {"bullets": [], "method": "heuristic"}

    def test_no_provider_uses_glyph_heuristic(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        resume = (
            "EDUCATION\n"
            "• Built a thermal sensor in Java for the ME 270 capstone\n"
            "- Wrote a 12-page final lab report on heat transfer\n"
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
    fabricated tool or metric."""

    RESUME = (
        "Designed a thermal sensor in Java and validated it against ME 270 "
        "data\nPresented results at the undergraduate symposium"
    ).lower()

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

    def test_cjk_bullet_still_grounded_by_containment(self):
        resume = "负责设计热传感器并完成 ME 270 数据验证"
        assert tailor_module._bullet_grounded("设计热传感器", resume)
        assert not tailor_module._bullet_grounded("部署 Kubernetes 集群", resume)

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

        Expected: every bullet is flagged, method degrades to 'fallback',
        and the warnings array names the fabricated tokens. The user sees
        their originals, not the fabricated rewrite.
        """
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = json.dumps({
            "bullets": [
                {
                    "text": (
                        "Built scalable ML pipelines using PyTorch and "
                        "deployed Kubernetes clusters for distributed training."
                    ),
                    "source_evidence": "fabricated",
                },
                {
                    "text": (
                        "Authored peer-reviewed paper on transformer "
                        "architectures published at NeurIPS."
                    ),
                    "source_evidence": "fabricated",
                },
            ],
        })
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
        # All AI bullets rejected -> degrade to passthrough.
        assert body["method"] == "fallback"
        assert any("rejected_fabrication" in w for w in body["warnings"])
        # The user gets their own bullet back, not the fabricated one.
        assert any("Java" in b["text"] for b in body["tailored_bullets"])
        # Pytorch / kubernetes should not have leaked through.
        joined = " ".join(b["text"] for b in body["tailored_bullets"]).lower()
        assert "pytorch" not in joined
        assert "kubernetes" not in joined

    def test_valid_tailored_passes_through(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Profile has Python + ML coursework — re-using those terms is OK."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = json.dumps({
            "bullets": [
                {
                    "text": (
                        "Implemented machine learning experiments in Python "
                        "during CS 225 coursework."
                    ),
                    "source_evidence": "Python (experienced); CS 225",
                },
            ],
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)

        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Worked on Python projects in CS 225"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        assert len(body["tailored_bullets"]) == 1
        # source_evidence is preserved on accepted bullets.
        assert body["tailored_bullets"][0]["source_evidence"]

    def test_generic_prose_is_not_flagged_as_fabrication(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Regression: ordinary verbs and abstract nouns must pass.

        Under STRICT, words like 'demonstrating', 'foundational',
        'understanding', 'applying' were treated as fabricated because they
        were absent from the English filler allowlist, so every grounded
        draft degraded to the passthrough fallback (method='fallback') and
        the tailor feature produced nothing. LENIENT_PROSE flags only
        concreteness-signal tokens, so this grounded rewrite is accepted.
        """
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = json.dumps({
            "bullets": [
                {
                    "text": (
                        "Applied Python during CS 225 coursework, "
                        "demonstrating foundational understanding while "
                        "identifying and analyzing trends."
                    ),
                    "source_evidence": "Python (experienced); CS 225",
                },
            ],
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)

        resp = client.post(
            "/api/tailor",
            json={
                "profile": python_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": ["Worked on Python projects in CS 225"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        assert body["warnings"] == []

    def test_fabrication_lowercase_tool_when_profile_lacks_it(
        self, java_profile, real_opp_id, monkeypatch,
    ):
        """TAILOR-1: an all-lowercase tool (langchain/pinecone) the student
        never listed carries no case/digit signal but is still rejected via the
        pinned taxonomy — it must not slip onto the resume."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = json.dumps({
            "bullets": [
                {
                    "text": "Built RAG pipelines with langchain over a pinecone vector store.",
                    "source_evidence": "fabricated",
                },
            ],
        })
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
        assert body["method"] == "fallback"
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
                "original_bullets": ["Did Python projects in CS 225"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        assert len(body["tailored_bullets"]) == 1


class TestInputCaps:
    """Pydantic ``cap_bullets`` validator drops empty strings & enforces limits."""

    def test_more_than_12_bullets_truncated(self, java_profile, real_opp_id, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)

        bullets = [f"bullet number {i}" for i in range(20)]
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
        # Validator caps the input list at 12 before the route sees it.
        assert len(body["tailored_bullets"]) == 12

    def test_each_bullet_capped_500_chars(
        self, java_profile, real_opp_id, monkeypatch,
    ):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)

        long_bullet = "x" * 2000
        resp = client.post(
            "/api/tailor",
            json={
                "profile": java_profile,
                "opportunity_id": real_opp_id,
                "original_bullets": [long_bullet],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["tailored_bullets"][0]["text"]) == 500

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
                {"text": "Implemented Python ML in CS 225", "source_evidence": "Python"},
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
                    "Did Python coursework in CS 225",
                    "Worked on Python ML projects",
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
    """R71-D: caller-declared output locale selects the system prompt."""

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
        # EN prompt has the English "STRICT RULES:" header verbatim.
        assert "STRICT RULES:" in captured["system"]
        assert "严格规则" not in captured["system"]

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
                "original_bullets": ["Did Python work in CS 225"],
                "locale": "zh",
            },
        )
        assert resp.status_code == 200
        # ZH prompt has the Chinese rules header; EN header must NOT be there.
        assert "严格规则" in captured["system"]
        assert "STRICT RULES:" not in captured["system"]
        body = resp.json()
        # Chinese body still passes the ASCII validator — there are no
        # fabricated ASCII tokens (Python and CS appear in the corpus).
        assert body["method"] == "ai"
        assert "Python" in body["tailored_bullets"][0]["text"]

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
        assert "严格规则" in captured["system"]

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
        assert "STRICT RULES:" in captured["system"]


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
        from backend.routes.tailor import _validate_no_fabrication
        passed, fab = _validate_no_fabrication(
            "Built pipelines with Python and PyTorch.",
            evidence_corpus="java sensors thermodynamics mechanical engineering",
        )
        assert not passed
        assert "python" in fab
        assert "pytorch" in fab

    def test_validator_accepts_when_evidence_present(self):
        from backend.routes.tailor import _validate_no_fabrication
        passed, fab = _validate_no_fabrication(
            "Built Python projects using PyTorch frameworks.",
            evidence_corpus="python pytorch projects machine learning",
        )
        assert passed
        assert fab == []

    def test_validator_allows_opp_vocabulary_in_corpus(self):
        """The opp's own description tokens are in the corpus by design."""
        from backend.routes.tailor import _validate_no_fabrication
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
    """Positional pairing is the only link between a rewrite and the bullet it
    rewrote. The renovation path passes preserve_slots for exactly this reason;
    /api/tailor did not, so one empty item from the model slid every later
    rewrite one slot left and the modal showed each rewrite beside somebody
    else's original."""

    def test_an_empty_item_does_not_shift_the_later_rewrites(
        self, monkeypatch, java_profile, real_opp_id,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        originals = [
            "Tutored 30 students in circuits lab each week",
            "Led the robotics club fundraising drive",
            "Wrote MATLAB analysis for EEG recordings",
        ]
        fake = json.dumps({
            "bullets": [
                {"text": "Tutored 30 students in circuits lab weekly",
                 "source_evidence": originals[0]},
                # The model returns the slot but leaves it empty.
                {"text": "", "source_evidence": ""},
                {"text": "Wrote MATLAB analysis of EEG recordings",
                 "source_evidence": originals[2]},
            ],
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)

        resp = client.post("/api/tailor", json={
            "profile": java_profile,
            "opportunity_id": real_opp_id,
            "original_bullets": originals,
        })
        assert resp.status_code == 200
        pairs = {b["source_index"]: b["text"] for b in resp.json()["tailored_bullets"]}
        # Slot 1 was empty and is simply absent — slot 2 keeps its own index.
        assert 1 not in pairs
        assert "circuits lab" in pairs[0]
        assert "EEG" in pairs[2]


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
