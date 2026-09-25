"""Provider-free writing-quality regressions against the real three résumé routes.

These controlled outputs test claim attribution, not model or human-rated quality.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import data_loader
from backend.lib.release_scope import opportunity_visible_in_release
from backend.main import app
from backend.routes import tailor
from src.evidence import is_actionable_target

PATHS = ("/api/tailor", "/api/tailor/renovate", "/api/tailor/bullet")
PROFILE = {
    "name": "Sample Student", "school": "UIUC", "year": "junior", "major": "Computer Science",
    "hard_skills": [{"name": "PyTorch", "level": "experienced", "confirmed": True}],
    "coursework": ["CS 225"], "research_interests_text": "neural signal analysis",
}


@pytest.fixture
def endpoint(monkeypatch):
    target = next(opp for opp in data_loader.load_opportunities_by_id().values()
                  if opportunity_visible_in_release(opp) and is_actionable_target(opp))
    monkeypatch.setattr(tailor, "load_opportunities_by_id", lambda: {target["id"]: target})
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "_schedule_usage", lambda *args: None)
    monkeypatch.setattr(tailor, "model_for", lambda *args: {})
    return TestClient(app), target["id"]


def write(endpoint, monkeypatch, path, original, proposed, *, other=None, current=None, quote=None):
    client, opportunity_id = endpoint
    originals = [original] + ([other] if other else [])
    calls = []

    def model(messages, **kwargs):
        calls.append(messages)
        if "REORGANIZE" in messages[0]["content"]:
            return json.dumps({"section_order": ["s1"], "sections": [{"id": "s1", "bullets": [
                {"id": f"b{i}", "action": "foreground"} for i in range(len(originals))]}]})
        item = {"text": proposed, "source_evidence": quote or original}
        return json.dumps(item if path.endswith("/bullet") else {"bullets": [item] + [
            {"text": other, "source_evidence": other} for _ in originals[1:]]})

    monkeypatch.setattr(tailor, "chat_completion", model)
    payload = {"profile": PROFILE, "opportunity_id": opportunity_id}
    if path.endswith("/renovate"):
        payload["sections"] = [{"id": "s1", "heading": "Projects", "kind": "projects", "bullets": [
            {"id": f"b{i}", "text": value} for i, value in enumerate(originals)]}]
    elif path.endswith("/bullet"):
        payload.update(base_text=original, current_text=current if current is not None else original)
    else:
        payload["original_bullets"] = originals
    response = client.post(path, json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert calls
    return result, calls


def assert_rejected(path, result, original, *, current=None):
    assert result["warnings"], result
    if path.endswith("/renovate"):
        first = result["sections"][0]["bullets"][0]
        assert first["base_text"] == original
        assert first["variants"] == [] and first["current"] == -1
    elif path.endswith("/bullet"):
        assert result["text"] == (current if current is not None else original)
        assert result["changed"] is False
    else:
        assert not any(row["source_index"] == 0 and row["text"] != original for row in result["tailored_bullets"])


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(("original", "proposed"), [
    ("I did not lead the team. I reviewed the documentation.", "I led the team and reviewed the documentation."),
    ("Our team built a parser. I reviewed the documentation.", "I built a parser and reviewed the documentation."),
    ("The paper was submitted for review, not accepted.", "The paper was accepted."),
    ("我没有主导团队。本人审阅文档。", "我主导团队并审阅文档。"),
    ("团队开发了工具。本人负责审阅文档。", "本人开发了工具并审阅文档。"),
    ("论文已投稿，尚未录用。", "论文已录用。"),
    ("Worked on Python projects in CS 225", "Implemented machine learning experiments in Python during CS 225 coursework."),
    ("Worked on Python ML projects", "Built ML models with Python during coursework"),
    ("Did Python work in CS 225", "在 CS 225 课程中用 Python 完成机器学习项目"),
    ("I did not lead the project.", "I did not lead the project, but later I led it."),
    ("The paper was submitted for review, not accepted.", "The paper was submitted for review, not accepted, but it was later accepted."),
    ("我没有主导项目。", "我没有主导项目，但后来我主导了项目。"),
    ("论文已投稿，尚未录用。", "论文已投稿，尚未录用，但后来已录用。"),
])
def test_roles_negation_and_publication_cannot_be_upgraded(endpoint, monkeypatch, path, original, proposed):
    result, _ = write(endpoint, monkeypatch, path, original, proposed)
    assert_rejected(path, result, original)


@pytest.mark.parametrize("path", PATHS)
def test_profile_skill_does_not_establish_its_use_in_this_project(endpoint, monkeypatch, path):
    original = "Analyzed measurements for a classroom experiment."
    proposed = "Analyzed measurements with PyTorch for a classroom experiment."
    result, _ = write(endpoint, monkeypatch, path, original, proposed)
    assert_rejected(path, result, original)


@pytest.mark.parametrize("path", PATHS[:2])
def test_other_project_technology_and_number_cannot_be_transferred(endpoint, monkeypatch, path):
    original = "Analyzed measurements for the biology project."
    other = "Trained PyTorch models on 88 samples in a separate class project."
    result, _ = write(endpoint, monkeypatch, path, original,
                      "Analyzed 88 measurements with PyTorch for the biology project.", other=other)
    assert_rejected(path, result, original)
    # The independently valid other project remains available.
    if path.endswith("/renovate"):
        assert result["sections"][0]["bullets"][1]["base_text"] == other
    else:
        assert any(row["source_index"] == 1 and row["text"] == other for row in result["tailored_bullets"])


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(("original", "proposed"), [
    ("Analyzed measurements with PyTorch across 88 samples.", "Analyzed 88 samples with PyTorch."),
    ("I did not lead the project, but I reviewed its documents.", "I reviewed its documents. I did not lead the project."),
    ("我没有主导项目，但本人审阅文档。", "本人审阅文档。我没有主导项目。"),
    ("I did not lead the project. Reviewed documents.", "Reviewed documents. I did not lead the project."),
    ("我没有主导团队。本人审阅文档。", "本人审阅文档。我没有主导团队。"),
])
def test_local_evidence_and_truthful_reordering_still_work(endpoint, monkeypatch, path, original, proposed):
    result, _ = write(endpoint, monkeypatch, path, original, proposed)
    assert result["warnings"] == []
    if path.endswith("/renovate"):
        assert result["sections"][0]["bullets"][0]["variants"][0]["text"] == proposed
    elif path.endswith("/bullet"):
        assert result["text"] == proposed and result["changed"] is True
    else:
        assert result["tailored_bullets"][0]["text"] == proposed


def test_manual_current_does_not_become_evidence_and_is_kept_on_rejection(endpoint, monkeypatch):
    original = "I did not lead the project. Reviewed documents."
    current = "Manual draft: I led the project and reviewed the documents."
    result, _ = write(endpoint, monkeypatch, "/api/tailor/bullet", original,
                      "I led the project and reviewed its documents.", current=current)
    assert_rejected("/api/tailor/bullet", result, original, current=current)


@pytest.mark.parametrize("path", PATHS)
def test_source_quote_is_local_even_when_profile_contains_the_text(endpoint, monkeypatch, path):
    original = "Analyzed measurements with PyTorch."
    result, _ = write(endpoint, monkeypatch, path, original, "Analyzed measurements with PyTorch carefully.",
                      quote="neural signal analysis")
    if path.endswith("/renovate"):
        row = result["sections"][0]["bullets"][0]["variants"][0]
    elif path.endswith("/bullet"):
        row = result
    else:
        row = result["tailored_bullets"][0]
    assert row["source_evidence"] == ""


def test_single_bullet_prompt_includes_bounded_public_research_context(monkeypatch):
    captured = []
    monkeypatch.setattr(tailor, "model_for", lambda *args: {})
    monkeypatch.setattr(tailor, "chat_completion", lambda messages, **kwargs: captured.append(messages))
    opp = {"title": "Research assistant", "pi_name": "Professor Sample", "organization": "Signal Lab",
           "description_clean": "Study neural recordings with robust error analysis. " + "x" * 1600 + "OUTSIDE_EXCERPT",
           "description_raw": "PRIVATE_RAW_TARGET", "eligibility": {"skills_required": []}, "keywords": []}
    tailor._ai_optimize_bullet(PROFILE, opp, "Analyzed measurement uncertainty.", None)
    prompt = captured[0][1]["content"]
    assert "Study neural recordings with robust error analysis." in prompt
    assert "Professor Sample" in prompt and "Signal Lab" in prompt
    assert "OUTSIDE_EXCERPT" not in prompt and "PRIVATE_RAW_TARGET" not in prompt


def test_reoptimization_prompt_separates_original_facts_from_manual_wording(endpoint, monkeypatch):
    original = "Analyzed measurement uncertainty."
    current = "Manual wording: analyzed measurement uncertainty."
    result, calls = write(endpoint, monkeypatch, "/api/tailor/bullet", original,
                          "Analyzed measurement uncertainty carefully.", current=current)
    assert result["changed"] is True
    prompt = calls[0][1]["content"]
    assert "SOURCE ORIGINAL (facts for this bullet):\n" + original in prompt
    assert "CURRENT WORDING to edit (not new evidence):\n" + current in prompt


@pytest.mark.parametrize(("original", "proposed", "accepted"), [
    ("I did not lead the project.", "I did not lead the project, but later I led it.", False),
    ("The paper was submitted for review, not accepted.", "The paper was submitted for review, not accepted, but it was later accepted.", False),
    ("我没有主导项目。", "我没有主导项目，但后来我主导了项目。", False),
    ("论文已投稿，尚未录用。", "论文已投稿，尚未录用，但后来已录用。", False),
    ("I did not lead the project, but I reviewed its documents.", "I reviewed its documents. I did not lead the project.", True),
    ("我没有主导项目，但本人审阅文档。", "本人审阅文档。我没有主导项目。", True),
])
def test_same_claim_rule_covers_full_target_receipts(original, proposed, accepted):
    from backend.lib.target_resume_ai import parse_output

    unit = {"unit_id": "u1", "section_id": "s1", "block_id": "b1", "original": original,
            "before_text": original, "evidence": {"kind": "experience", "id": "entry", "revision": 1}}
    target = {"description": "Review documents", "requirements": []}
    raw = json.dumps({"units": [{"unit_id": "u1", "priority": "normal", "reason": "Relevant contribution.",
        "target_evidence": [{"field": "description", "requirement_index": None,
                             "start": 0, "end": 16, "quote": "Review documents"}], "proposed_text": proposed}]})
    row = parse_output(raw, [unit], target)[0]
    assert (row["status"] == "suggested") is accepted
    if not accepted:
        assert row["reason_code"] == "ungrounded_rewrite" and row["suggestion"] is None


def test_single_bullet_prompt_allows_already_public_raw_description_fallback(monkeypatch):
    captured = []
    monkeypatch.setattr(tailor, "model_for", lambda *args: {})
    monkeypatch.setattr(tailor, "chat_completion", lambda messages, **kwargs: captured.append(messages))
    public = {"title": "Research", "description_clean": "", "description_raw": "Public methods context.\nA second line.",
              "eligibility": {}, "keywords": []}
    tailor._ai_optimize_bullet(PROFILE, public, "Analyzed measurements.", None)
    assert "Description excerpt: Public methods context. A second line." in captured[0][1]["content"]


@pytest.mark.parametrize(("original", "proposed"), [
    ("The paper is not yet accepted.", "The paper is not yet accepted, but it was later accepted."),
    ("I have not yet led the project.", "I have not yet led the project, but later I led it."),
])
def test_temporal_not_yet_remains_negative(original, proposed):
    from backend.lib.target_resume_ai_grounding import claim_upgrade_detected

    assert claim_upgrade_detected(proposed, original)
    assert not claim_upgrade_detected(original, original)
