"""Tests for the résumé-renovation staged routes + metering scaffold.

Same non-negotiable anti-fabrication spec as ``/tailor``: no stage may put a
skill/tool/metric the student never stated into their résumé. The structural
stages (structure, macro plan) emit IDs / verbatim extraction only, so they
cannot fabricate; the one prose stage (bullet rewrite) routes through the same
STUDENT-only ``validate_no_fabrication`` and falls back to ``base_text`` on
rejection.

Covers, mirroring ``test_tailor_route.py``:
  * structure: empty → heuristic; no provider → glyph heuristic; AI sections
    with an ungrounded bullet dropped; malformed JSON → heuristic.
  * renovate: 404; no bullets; no provider passthrough; bad plan passthrough;
    happy path (foreground rewritten + grounded, kept bullet at base, order
    applied); fabrication dropped to base; unknown plan IDs ignored.
  * bullet: 404; empty; no provider; grounded rewrite; fabrication → unchanged;
    malformed JSON → unchanged.
  * metering: OFF by default; record_usage no-ops disabled; check_quota allows.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import types

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend import data_loader
from backend.lib import metering
from backend.main import app
from backend.routes import tailor as tailor_module

client = TestClient(app)


@pytest.fixture
def real_opp_id() -> str:
    by_id = data_loader.load_opportunities_by_id()
    assert by_id, "data loader should return at least one opportunity"
    return next(iter(by_id.keys()))


@pytest.fixture
def python_profile() -> dict:
    return {
        "name": "Test Student",
        "school": "UIUC",
        "year": "junior",
        "major": "Computer Science",
        "college": "Grainger College of Engineering",
        "hard_skills": [
            {"name": "Python", "level": "experienced"},
            {"name": "machine learning", "level": "experienced"},
        ],
        "coursework": ["CS 124", "CS 225"],
        "research_interests_text": "machine learning systems",
    }


def _chat_router(handlers):
    """Return a fake chat_completion that dispatches on the system prompt.

    ``handlers`` is a list of (marker_substring, response_str). The first marker
    found in the system message wins. Lets one flow (macro plan + rewrite) return
    different JSON per LLM call.
    """
    def _fake(messages, *a, **k):
        system = messages[0]["content"] if messages else ""
        for marker, resp in handlers:
            if marker in system:
                return resp
        return None
    return _fake


# --------------------------------------------------------------------------- #
# /tailor/structure
# --------------------------------------------------------------------------- #
class TestStructure:
    def test_empty_resume_returns_empty(self):
        resp = client.post("/api/tailor/structure", json={"resume_text": "  "})
        assert resp.status_code == 200
        body = resp.json()
        assert body["sections"] == []
        assert body["method"] == "heuristic"

    def test_no_provider_uses_glyph_heuristic(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        resume = (
            "EXPERIENCE\n"
            "• Built a thermal sensor in Java for the ME 270 capstone\n"
            "- Wrote a 12-page final lab report on heat transfer\n"
        )
        resp = client.post("/api/tailor/structure", json={"resume_text": resume})
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "heuristic"
        assert len(body["sections"]) == 1
        texts = [b["text"] for b in body["sections"][0]["bullets"]]
        assert any("thermal sensor in Java" in t for t in texts)
        # Every bullet carries a stable id for downstream renovate/rollback.
        assert all(b["id"] for b in body["sections"][0]["bullets"])

    def test_ai_structures_and_drops_ungrounded_bullet(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        resume = (
            "Research Assistant, Fluids Lab\n"
            "Designed a thermal sensor in Java and validated it against ME 270 data\n"
        )
        fake = json.dumps({
            "sections": [{
                "heading": "Research",
                "kind": "research",
                "bullets": [
                    "Designed a thermal sensor in Java and validated it against ME 270 data",
                    "Trained PyTorch transformer models on Kubernetes clusters",  # ungrounded
                ],
            }],
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)
        resp = client.post("/api/tailor/structure", json={"resume_text": resume})
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        joined = " ".join(b["text"] for s in body["sections"] for b in s["bullets"]).lower()
        assert "thermal sensor" in joined
        assert "pytorch" not in joined  # fabricated bullet filtered by grounding
        assert "kubernetes" not in joined

    def test_ai_malformed_json_falls_back(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: "not json")
        resume = "• Built a thermal sensor in Java for the ME 270 capstone\n"
        resp = client.post("/api/tailor/structure", json={"resume_text": resume})
        assert resp.status_code == 200
        assert resp.json()["method"] == "heuristic"

    def test_ai_structure_keeps_cjk_bullets(self, monkeypatch):
        """A pure-Chinese bullet has zero ASCII tokens; grounding falls back to
        whitespace-normalized substring containment instead of dropping it."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        resume = "研究经历\n在实验室负责小鼠行为实验的数据分析并撰写实验报告\n"
        fake = json.dumps({"sections": [{
            "heading": "研究经历", "kind": "research",
            "bullets": ["在实验室负责小鼠行为实验的数据分析并撰写实验报告"],
        }]})
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)
        resp = client.post("/api/tailor/structure", json={"resume_text": resume})
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        texts = [b["text"] for s in body["sections"] for b in s["bullets"]]
        assert any("小鼠行为实验" in t for t in texts)

    def test_ai_structure_still_drops_invented_cjk_bullet(self, monkeypatch):
        """The CJK fallback is containment-based, so an invented Chinese bullet
        (not verbatim in the résumé) is still rejected."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        resume = "研究经历\n在实验室负责小鼠行为实验的数据分析并撰写实验报告\n"
        fake = json.dumps({"sections": [{
            "heading": "研究经历", "kind": "research",
            "bullets": ["主导开发了大规模分布式深度学习训练平台并发表顶会论文"],
        }]})
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)
        resp = client.post("/api/tailor/structure", json={"resume_text": resume})
        assert resp.status_code == 200
        body = resp.json()
        # Invented bullet dropped -> no AI sections survive -> heuristic path.
        joined = json.dumps(body, ensure_ascii=False)
        assert "分布式深度学习" not in joined


# --------------------------------------------------------------------------- #
# /tailor/renovate
# --------------------------------------------------------------------------- #
def _sections_payload():
    return [{
        "id": "s1",
        "heading": "Research",
        "kind": "research",
        "bullets": [
            {"id": "s1b1", "text": "Implemented machine learning experiments in Python for CS 225"},
            {"id": "s1b2", "text": "Wrote documentation for a class project"},
        ],
    }]


class TestRenovate:
    def test_opportunity_not_found_returns_404(self, python_profile):
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": "definitely-not-real",
            "sections": _sections_payload(),
        })
        assert resp.status_code == 404

    def test_no_bullets_returns_fallback(self, python_profile, real_opp_id):
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": [{"id": "s1", "heading": "X", "kind": "other", "bullets": []}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "fallback"
        assert "no_bullets_provided" in body["warnings"]

    def test_no_provider_passthrough_all_base(self, python_profile, real_opp_id, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "fallback"
        assert "llm_not_configured" in body["warnings"]
        # Every bullet sits at its base_text (current == -1, no variants).
        bullets = [b for s in body["sections"] for b in s["bullets"]]
        assert len(bullets) == 2
        assert all(b["current"] == -1 and b["variants"] == [] for b in bullets)
        assert all(b["base_text"] for b in bullets)

    def test_bad_macro_plan_passthrough(self, python_profile, real_opp_id, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: "not json")
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "fallback"
        assert "macro_plan_failed" in body["warnings"]

    def test_happy_path_foreground_rewritten_grounded(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        plan = json.dumps({"sections": [{"id": "s1", "bullets": [
            {"id": "s1b1", "action": "foreground"},
            {"id": "s1b2", "action": "demote"},
        ]}]})
        # Rewrite stays within the student's material (Python, machine learning, CS 225).
        rewrite = json.dumps({"bullets": [{
            "text": "Built machine learning experiments in Python during CS 225 coursework",
            "source_evidence": "machine learning experiments in Python for CS 225",
        }]})
        monkeypatch.setattr(
            tailor_module, "chat_completion",
            _chat_router([("REORGANIZE", plan), ("rewrite a student", rewrite)]),
        )
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        sec = body["sections"][0]
        by_id = {b["id"]: b for b in sec["bullets"]}
        # Foregrounded bullet gets a macro variant, current points at it.
        fg = by_id["s1b1"]
        assert fg["action"] == "foreground"
        assert fg["current"] == 0
        assert len(fg["variants"]) == 1
        assert fg["variants"][0]["source"] == "macro"
        assert "Python" in fg["variants"][0]["text"]
        # Demoted bullet stays at base (no rewrite requested).
        assert by_id["s1b2"]["current"] == -1
        assert by_id["s1b2"]["variants"] == []
        # Plan ordering respected: foreground before demote.
        assert [b["id"] for b in sec["bullets"]] == ["s1b1", "s1b2"]

    def test_fabricated_rewrite_dropped_to_base(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        plan = json.dumps({"sections": [{"id": "s1", "bullets": [
            {"id": "s1b1", "action": "foreground"},
        ]}]})
        # Rewrite smuggles in Rust + Kubernetes — the student lists neither.
        rewrite = json.dumps({"bullets": [{
            "text": "Deployed Kubernetes clusters and wrote Rust services for the lab",
            "source_evidence": "fabricated",
        }]})
        monkeypatch.setattr(
            tailor_module, "chat_completion",
            _chat_router([("REORGANIZE", plan), ("rewrite a student", rewrite)]),
        )
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert resp.status_code == 200
        body = resp.json()
        # The AI plan WAS applied (reorder/actions), so method stays "ai"; the
        # rejected rewrite is reported in warnings and the foreground bullet
        # sits safely at its base_text.
        assert body["method"] == "ai"
        assert any("rejected_fabrication" in w for w in body["warnings"])
        fg = next(b for s in body["sections"] for b in s["bullets"] if b["id"] == "s1b1")
        assert fg["current"] == -1 and fg["variants"] == []
        # The fabricated tokens must not reach any bullet content (base_text or
        # variant text). They legitimately appear in the rejection *warning*,
        # which is exactly the point — so scan only the rendered bullets.
        bullet_text = " ".join(
            b["base_text"] + " " + " ".join(v["text"] for v in b["variants"])
            for s in body["sections"] for b in s["bullets"]
        ).lower()
        assert "kubernetes" not in bullet_text and "rust" not in bullet_text

    def test_unknown_plan_ids_ignored(self, python_profile, real_opp_id, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        # Plan references a section + bullet that don't exist -> plan dropped ->
        # passthrough (structural safety: only input IDs are ever honored).
        plan = json.dumps({"sections": [{"id": "ghost", "bullets": [
            {"id": "ghostb", "action": "foreground"},
        ]}]})
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: plan)
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "fallback"
        assert "macro_plan_failed" in body["warnings"]
        # Both original bullets preserved at base despite the ghost plan.
        assert len([b for s in body["sections"] for b in s["bullets"]]) == 2

    def test_zero_foreground_plan_is_still_ai(self, python_profile, real_opp_id, monkeypatch):
        """A successful plan with no foregrounded bullets (all keep/demote) is
        an AI result — the reorder was applied — not a fallback."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        plan = json.dumps({"sections": [{"id": "s1", "bullets": [
            {"id": "s1b2", "action": "keep"},
            {"id": "s1b1", "action": "demote"},
        ]}]})
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: plan)
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        assert body["warnings"] == []
        # Plan's bullet order applied (b2 before b1); everything at base.
        sec = body["sections"][0]
        assert [b["id"] for b in sec["bullets"]] == ["s1b2", "s1b1"]
        assert all(b["current"] == -1 for b in sec["bullets"])

    def test_multi_section_reorder_applies_plan_order(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        sections = [
            {"id": "s1", "heading": "Projects", "kind": "projects",
             "bullets": [{"id": "s1b1", "text": "Wrote documentation for a class project"}]},
            {"id": "s2", "heading": "Research", "kind": "research",
             "bullets": [{"id": "s2b1", "text": "Implemented machine learning experiments in Python"}]},
        ]
        plan = json.dumps({"sections": [
            {"id": "s2", "bullets": [{"id": "s2b1", "action": "keep"}]},
            {"id": "s1", "bullets": [{"id": "s1b1", "action": "demote"}]},
        ]})
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: plan)
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": sections,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"
        assert [s["id"] for s in body["sections"]] == ["s2", "s1"]

    def test_rewrite_count_mismatch_drops_batch(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Positional pairing is the only rewrite↔bullet-id link; if the model
        returns fewer rewrites than foregrounded bullets, the whole batch is
        dropped (base_text floor) instead of mis-attaching rewrites."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        plan = json.dumps({"sections": [{"id": "s1", "bullets": [
            {"id": "s1b1", "action": "foreground"},
            {"id": "s1b2", "action": "foreground"},
        ]}]})
        rewrite = json.dumps({"bullets": [{  # ONE rewrite for TWO foregrounded
            "text": "Built machine learning experiments in Python during CS 225 coursework",
            "source_evidence": "machine learning experiments in Python",
        }]})
        monkeypatch.setattr(
            tailor_module, "chat_completion",
            _chat_router([("REORGANIZE", plan), ("rewrite a student", rewrite)]),
        )
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["method"] == "ai"  # plan applied
        assert "rewrite_count_mismatch" in body["warnings"]
        bullets = [b for s in body["sections"] for b in s["bullets"]]
        assert all(b["current"] == -1 and b["variants"] == [] for b in bullets)

    def test_duplicate_bullet_ids_rejected(self, python_profile, real_opp_id):
        sections = [{"id": "s1", "heading": "A", "kind": "other", "bullets": [
            {"id": "b1", "text": "Implemented machine learning experiments in Python"},
            {"id": "b1", "text": "Wrote documentation for a class project"},
        ]}]
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": sections,
        })
        assert resp.status_code == 422

    def test_total_bullet_cap_rejected(self, python_profile, real_opp_id):
        # 3 sections × 40 bullets = 120 > the 100 global cap -> 422 (the
        # per-section caps alone would admit a ~47K-token plan prompt).
        sections = [
            {"id": f"s{i}", "heading": "X", "kind": "other",
             "bullets": [
                 {"id": f"s{i}b{j}", "text": f"Did course project number {i}-{j} for a class"}
                 for j in range(40)
             ]}
            for i in range(3)
        ]
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": sections,
        })
        assert resp.status_code == 422

    def test_oversized_section_rejected_not_silently_truncated(
        self, python_profile, real_opp_id,
    ):
        """2 sections × 61 bullets: the per-section cap would silently trim to
        80 and renovate a résumé with 42 bullets missing. The raw-payload
        validator rejects loudly instead — a renovation must see the whole
        document or refuse."""
        sections = [
            {"id": f"s{i}", "heading": "X", "kind": "other",
             "bullets": [
                 {"id": f"s{i}b{j}", "text": f"Did course project number {i}-{j} for a class"}
                 for j in range(61)
             ]}
            for i in range(2)
        ]
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": sections,
        })
        assert resp.status_code == 422

    def test_ids_are_stripped_and_capped(self):
        """IDs can't smuggle newlines into the plan prompt or blow the prompt
        budget — whitespace is stripped and length capped at the schema."""
        from backend.schemas import ResumeBullet, ResumeSection

        b = ResumeBullet(id="s1\nSYSTEM OVERRIDE\tb2" + "x" * 200, text="hi")
        assert "\n" not in b.id and "\t" not in b.id and " " not in b.id
        assert len(b.id) <= 64
        s = ResumeSection(id="  s 1  ", heading="H", kind="a\nb" + "k" * 50)
        assert s.id == "s1"
        assert "\n" not in s.kind and len(s.kind) <= 24

    def test_empty_item_padding_cannot_shift_rewrites(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """A model response padded with an empty item (3 items for 2 foreground
        bullets) must trip the count guard — with slots preserved, the raw item
        count is compared, so padding can't sneak a shifted pairing through."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        plan = json.dumps({"sections": [{"id": "s1", "bullets": [
            {"id": "s1b1", "action": "foreground"},
            {"id": "s1b2", "action": "foreground"},
        ]}]})
        rewrite = json.dumps({"bullets": [
            {"text": "", "source_evidence": ""},  # padding
            {"text": "Wrote clear documentation for a class project", "source_evidence": "x"},
            {"text": "Built machine learning experiments in Python", "source_evidence": "y"},
        ]})
        monkeypatch.setattr(
            tailor_module, "chat_completion",
            _chat_router([("REORGANIZE", plan), ("rewrite a student", rewrite)]),
        )
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "rewrite_count_mismatch" in body["warnings"]
        bullets = [b for s in body["sections"] for b in s["bullets"]]
        assert all(b["current"] == -1 and b["variants"] == [] for b in bullets)

    def test_empty_slot_keeps_its_own_bullet_at_base(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Matching count with one empty slot: that bullet stays at base while
        the OTHER bullet gets its own (not a shifted) rewrite."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        plan = json.dumps({"sections": [{"id": "s1", "bullets": [
            {"id": "s1b1", "action": "foreground"},
            {"id": "s1b2", "action": "foreground"},
        ]}]})
        rewrite = json.dumps({"bullets": [
            {"text": "", "source_evidence": ""},  # slot for s1b1: no rewrite
            {"text": "Wrote clear documentation for a class project", "source_evidence": "x"},
        ]})
        monkeypatch.setattr(
            tailor_module, "chat_completion",
            _chat_router([("REORGANIZE", plan), ("rewrite a student", rewrite)]),
        )
        resp = client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert resp.status_code == 200
        body = resp.json()
        by_id = {b["id"]: b for b in body["sections"][0]["bullets"]}
        assert by_id["s1b1"]["current"] == -1 and by_id["s1b1"]["variants"] == []
        assert by_id["s1b2"]["current"] == 0
        assert "documentation" in by_id["s1b2"]["variants"][0]["text"].lower()


# --------------------------------------------------------------------------- #
# /tailor/bullet
# --------------------------------------------------------------------------- #
class TestOptimizeBullet:
    def _payload(self, profile, opp_id, **over):
        base = {
            "profile": profile,
            "opportunity_id": opp_id,
            "current_text": "Implemented machine learning experiments in Python",
            "base_text": "Implemented machine learning experiments in Python",
        }
        base.update(over)
        return base

    def test_opportunity_not_found_returns_404(self, python_profile):
        resp = client.post("/api/tailor/bullet", json=self._payload(python_profile, "nope"))
        assert resp.status_code == 404

    def test_empty_current_returns_empty(self, python_profile, real_opp_id):
        resp = client.post("/api/tailor/bullet", json=self._payload(
            python_profile, real_opp_id, current_text="  ", base_text="",
        ))
        assert resp.status_code == 200
        body = resp.json()
        assert body["text"] == "" and body["changed"] is False

    def test_no_provider_returns_unchanged(self, python_profile, real_opp_id, monkeypatch):
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(k, raising=False)
        resp = client.post("/api/tailor/bullet", json=self._payload(python_profile, real_opp_id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["changed"] is False
        assert body["text"] == "Implemented machine learning experiments in Python"
        assert "llm_not_configured" in body["warnings"]

    def test_grounded_rewrite_changes(self, python_profile, real_opp_id, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = json.dumps({
            "text": "Built machine learning models in Python for a research project",
            "source_evidence": "machine learning experiments in Python",
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)
        resp = client.post("/api/tailor/bullet", json=self._payload(python_profile, real_opp_id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["changed"] is True
        assert "Python" in body["text"]

    def test_fabrication_returns_unchanged(self, python_profile, real_opp_id, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = json.dumps({
            "text": "Deployed Kubernetes clusters and trained PyTorch models",
            "source_evidence": "fabricated",
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)
        resp = client.post("/api/tailor/bullet", json=self._payload(python_profile, real_opp_id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["changed"] is False
        assert body["text"] == "Implemented machine learning experiments in Python"
        assert any("rejected_fabrication" in w for w in body["warnings"])

    def test_malformed_json_returns_unchanged(self, python_profile, real_opp_id, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: "garbage")
        resp = client.post("/api/tailor/bullet", json=self._payload(python_profile, real_opp_id))
        assert resp.status_code == 200
        body = resp.json()
        assert body["changed"] is False
        assert "llm_failed_or_invalid_json" in body["warnings"]

    def test_base_text_terms_stay_grounded_on_retailored_bullet(
        self, python_profile, real_opp_id, monkeypatch,
    ):
        """Re-optimizing an already-tailored bullet (current ≠ base) may reuse a
        concrete term that survives only in base_text — the corpus includes the
        base floor, so it passes the gate."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        fake = json.dumps({
            "text": "Analyzed fMRI datasets in Python for the lab's imaging study",
            "source_evidence": "fMRI data analysis in Python",
        })
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: fake)
        resp = client.post("/api/tailor/bullet", json=self._payload(
            python_profile, real_opp_id,
            current_text="Performed data analysis in Python for an imaging study",
            base_text="Performed fMRI data analysis in Python",
        ))
        assert resp.status_code == 200
        body = resp.json()
        assert body["changed"] is True
        assert "fMRI" in body["text"]


# --------------------------------------------------------------------------- #
# metering scaffold (OFF by default)
# --------------------------------------------------------------------------- #
class TestMetering:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("OFE_METERING_ENABLED", raising=False)
        assert metering.metering_enabled() is False

    def test_record_usage_noops_when_disabled(self, monkeypatch):
        monkeypatch.delenv("OFE_METERING_ENABLED", raising=False)
        wrote = asyncio.run(metering.record_usage("dev-1", "renovation"))
        assert wrote is False

    def test_check_quota_allows_when_disabled(self, monkeypatch):
        monkeypatch.delenv("OFE_METERING_ENABLED", raising=False)
        decision = asyncio.run(metering.check_quota("dev-1", "renovation"))
        assert decision.allowed is True
        assert decision.reason == "metering_disabled"

    def test_record_usage_skips_when_enabled_but_unconfigured(self, monkeypatch):
        # Enabled but no service-role env -> still no-op (never raises, never
        # writes to a half-configured deploy).
        monkeypatch.setenv("OFE_METERING_ENABLED", "1")
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        wrote = asyncio.run(metering.record_usage("dev-1", "renovation"))
        assert wrote is False


class TestMeteringWiring:
    """The routes actually schedule usage recording (the plan's promise), and
    the background recorder resolves the caller's uid without ever raising."""

    def test_renovate_schedules_usage(self, python_profile, real_opp_id, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: "not json")
        calls: list[str] = []
        monkeypatch.setattr(
            tailor_module, "_schedule_usage", lambda auth, feature: calls.append(feature),
        )
        client.post("/api/tailor/renovate", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "sections": _sections_payload(),
        })
        assert calls == ["renovation"]

    def test_bullet_schedules_usage(self, python_profile, real_opp_id, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setattr(tailor_module, "chat_completion", lambda *a, **k: "garbage")
        calls: list[str] = []
        monkeypatch.setattr(
            tailor_module, "_schedule_usage", lambda auth, feature: calls.append(feature),
        )
        client.post("/api/tailor/bullet", json={
            "profile": python_profile,
            "opportunity_id": real_opp_id,
            "current_text": "Implemented machine learning experiments in Python",
            "base_text": "",
        })
        assert calls == ["bullet_optimize"]

    def test_record_usage_bg_noop_when_disabled(self, monkeypatch):
        monkeypatch.delenv("OFE_METERING_ENABLED", raising=False)
        touched: list[int] = []

        class Boom:
            def __init__(self, **kw):
                touched.append(1)

        monkeypatch.setattr(
            tailor_module, "httpx", types.SimpleNamespace(AsyncClient=Boom),
        )
        asyncio.run(tailor_module._record_usage_bg("Bearer tok", "renovation"))
        assert touched == []  # short-circuited before any HTTP client was built

    def test_record_usage_bg_records_resolved_uid(self, monkeypatch):
        monkeypatch.setenv("OFE_METERING_ENABLED", "1")
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "srk")

        class FakeResp:
            status_code = 200

            def json(self):
                return {"id": "uid-1"}

        class FakeClient:
            def __init__(self, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, headers=None):
                return FakeResp()

        monkeypatch.setattr(
            tailor_module, "httpx", types.SimpleNamespace(AsyncClient=FakeClient),
        )
        recorded: list[tuple[str, str]] = []

        async def fake_record(uid, feature, **kw):
            recorded.append((uid, feature))
            return True

        monkeypatch.setattr(tailor_module, "record_usage", fake_record)
        asyncio.run(tailor_module._record_usage_bg("Bearer tok", "renovation"))
        assert recorded == [("uid-1", "renovation")]

    def test_record_usage_bg_swallows_errors(self, monkeypatch):
        monkeypatch.setenv("OFE_METERING_ENABLED", "1")
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "srk")

        class Boom:
            def __init__(self, **kw):
                raise RuntimeError("network down")

        monkeypatch.setattr(
            tailor_module, "httpx", types.SimpleNamespace(AsyncClient=Boom),
        )
        # Must not raise — metering is strictly best-effort.
        asyncio.run(tailor_module._record_usage_bg("Bearer tok", "renovation"))
