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
from backend.main import app
from backend.routes import tailor as tailor_module

client = TestClient(app)


@pytest.fixture
def real_opp_id() -> str:
    """Return the first available opportunity id from the live data file.

    Using a real id keeps the test honest about the `load_opportunities_by_id`
    contract — if the loader changes shape, this fixture breaks loudly.
    """
    by_id = data_loader.load_opportunities_by_id()
    assert by_id, "data loader should return at least one opportunity"
    return next(iter(by_id.keys()))


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


class TestUnitHelpers:
    """Unit tests for the validator + evidence builder, no HTTP layer."""

    def test_hard_claims_extracts_5plus_char_tokens(self):
        from backend.routes.tailor import _hard_claims
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

    def test_evidence_corpus_includes_profile_and_opp(self):
        from backend.routes.tailor import _build_evidence_corpus
        profile = {
            "major": "Computer Science",
            "research_interests_text": "machine learning systems",
            "hard_skills": [{"name": "Python", "level": "experienced"}],
            "coursework": ["CS 225"],
        }
        opp = {
            "title": "Compilers research",
            "description_clean": "build LLVM compiler passes",
            "keywords": ["compilers", "LLVM"],
            "eligibility": {"skills_required": ["C++"], "skills_preferred": []},
        }
        corpus = _build_evidence_corpus(profile, opp, ["Did Python projects"])
        # Profile signal.
        assert "python" in corpus
        assert "cs 225" in corpus
        assert "machine learning" in corpus
        # Opportunity signal.
        assert "compiler" in corpus
        assert "llvm" in corpus
        # Original bullet signal.
        assert "did python projects" in corpus
