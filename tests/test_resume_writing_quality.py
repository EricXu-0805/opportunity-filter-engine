"""Provider-free writing-quality regressions against the real three résumé routes.

These controlled outputs test claim attribution, not model or human-rated quality.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import data_loader
from backend.lib import evidence_map as em
from backend.lib.release_scope import opportunity_visible_in_release
from backend.main import app
from backend.routes import tailor
from src.evidence import is_actionable_target
from tests import test_tailor_review as review_tests

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
    monkeypatch.setattr(em, "model_for", lambda *args: {})
    return TestClient(app), target["id"]


def write(endpoint, monkeypatch, path, original, proposed, *, other=None, current=None):
    """Post one rewrite (and an optional untouched second bullet) as the model's evidence-map rows."""
    client, opportunity_id = endpoint
    originals = [original] + ([other] if other else [])
    locale = "zh" if em.language(proposed) == "zh" else "en"
    # Target terms come from the target, so a rewrite's new words are never quotable here.
    anchors = [review_tests._anchor(f"t{i}", text) for i, text in
               enumerate(dict.fromkeys([*originals, *([current] if current else [])]), start=1)]
    by_id = {anchor.id: anchor for anchor in anchors}
    monkeypatch.setattr(tailor, "_snapshot_anchors", lambda source, snapshot: anchors)
    calls = []

    def model(messages, **kwargs):
        calls.append(messages)
        if messages[0]["content"].startswith("FAITHFULNESS REVIEW"):
            # A reviewer that accepts everything: only the deterministic gates reject.
            return review_tests._review_all(True)(json.loads(messages[1]["content"]))
        if "REORGANIZE" in messages[0]["content"]:
            return json.dumps({"sections": [{"id": "s1", "bullets": [
                {"id": f"b{i}", "action": "foreground"} for i in range(len(originals))]}]})
        units = json.loads(messages[1]["content"].split("DATA (JSON):\n", 1)[1])["units"]
        rows = [review_tests.declared_row(units[0]["unit_id"], units[0].get("current", units[0]["original"]),
                                          proposed, by_id)]
        rows += [{"unit_id": unit["unit_id"], "links": [], "decision": "keep", "ops": [], "text": None,
                  "keep_reason": "no_link"} for unit in units[1:]]
        return json.dumps({"bullets": rows})

    monkeypatch.setattr(tailor, "chat_completion", model)
    monkeypatch.setattr(em, "chat_completion", model)
    payload = {"profile": PROFILE, "opportunity_id": opportunity_id, "locale": locale}
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
    """The student's own wording stays, with the reason: the contract's or the locks'."""
    kept = ("beyond_allowed_edit", "rewrite_rejected", "cosmetic_only")
    if path.endswith("/renovate"):
        first = result["sections"][0]["bullets"][0]
        assert first["base_text"] == original
        assert first["variants"] == [] and first["current"] == -1 and first["note"] in kept
    elif path.endswith("/bullet"):
        assert result["text"] == (current if current is not None else original)
        assert result["changed"] is False and result["reason_code"] in kept
    else:
        first = result["tailored_bullets"][0]
        assert (first["text"], first["status"]) == (original, "kept") and first["reason_code"] in kept


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
    ("My team built a Python parser. I wrote parser tests.", "I built a Python parser and wrote parser tests. My team built a Python parser."),
    ("I improved parser throughput by 45% and reduced parser latency by 12%.", "I improved parser throughput by 12% and reduced parser latency by 45%."),
    ("I built a Python parser. I did not build the compiler.", "I built a compiler. I did not build the compiler."),
    ("My team built a Python parser. Wrote parser tests.", "Built a Python parser and wrote parser tests. My team built a Python parser."),
    ("Improved parser throughput by 45% and reduced parser latency by 12%.", "Improved parser throughput by 12% and reduced parser latency by 45%."),
    ("Built a Python parser. Did not build the compiler.", "Built a compiler. Did not build the compiler."),
    # Historical “grounded” fixtures must not authenticate new work or quality.
    ("Implemented machine learning experiments in Python", "Built machine learning models in Python for a research project"),
    ("Performed fMRI data analysis in Python", "Analyzed fMRI datasets in Python for the lab's imaging study"),
    ("Implemented machine learning projects in Python for CS 225", "Implemented machine learning experiments in Python during CS 225 coursework."),
    ("Implemented Python ML exercises in CS 225", "Implemented Python ML in CS 225"),
    ("Wrote documentation for a class project", "Wrote clear documentation for a class project"),
])
def test_roles_negation_and_publication_cannot_be_upgraded(endpoint, monkeypatch, path, original, proposed):
    result, calls = write(endpoint, monkeypatch, path, original, proposed)
    assert_rejected(path, result, original)
    # Rejected by a hard gate, never left to a reviewer that would have accepted it.
    assert not any(messages[0]["content"].startswith("FAITHFULNESS REVIEW") for messages in calls)


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
    ("I did not lead the project, but I reviewed its documents.", "I reviewed its documents. I did not lead the project."),
    ("我没有主导项目，但本人审阅文档。", "本人审阅文档。我没有主导项目。"),
    ("I did not lead the project. Reviewed documents.", "Reviewed documents. I did not lead the project."),
    ("我没有主导团队。本人审阅文档。", "本人审阅文档。我没有主导团队。"),
])
def test_local_evidence_and_truthful_reordering_still_work(endpoint, monkeypatch, path, original, proposed):
    result, calls = write(endpoint, monkeypatch, path, original, proposed)
    assert result["warnings"] == []
    if review_tests.english_unproven(original):
        # No two English function words of three letters: kept as written before the review (round 4's
        # default keep), a lost suggestion under (2b).
        assert not any(messages[0]["content"].startswith("FAITHFULNESS REVIEW") for messages in calls)
        assert_rejected(path, result, original)
        return
    # Changed text is shown only after the faithfulness review, even when no rule objects.
    assert any(messages[0]["content"].startswith("FAITHFULNESS REVIEW") for messages in calls)
    if path.endswith("/renovate"):
        assert result["sections"][0]["bullets"][0]["variants"][0]["text"] == proposed
    elif path.endswith("/bullet"):
        assert result["text"] == proposed and result["changed"] is True
    else:
        assert result["tailored_bullets"][0]["text"] == proposed


@pytest.mark.parametrize("path", PATHS)
def test_a_line_shortened_without_permission_is_kept(endpoint, monkeypatch, path):
    # Dropping "measurements" and "across" is a trim, which no route offers.
    original = "Analyzed measurements with PyTorch across 88 samples."
    result, calls = write(endpoint, monkeypatch, path, original, "Analyzed 88 samples with PyTorch.")
    assert_rejected(path, result, original)
    assert not any(messages[0]["content"].startswith("FAITHFULNESS REVIEW") for messages in calls)


def test_manual_current_does_not_become_evidence_and_is_kept_on_rejection(endpoint, monkeypatch):
    original = "I did not lead the project. Reviewed documents."
    current = "Manual draft: I led the project and reviewed the documents."
    result, _ = write(endpoint, monkeypatch, "/api/tailor/bullet", original,
                      "I led the project and reviewed its documents.", current=current)
    assert_rejected("/api/tailor/bullet", result, original, current=current)


@pytest.mark.parametrize("path", PATHS)
def test_source_quote_is_local_even_when_profile_contains_the_text(endpoint, monkeypatch, path):
    original = "Analyzed measurements with PyTorch."
    result, _ = write(endpoint, monkeypatch, path, original, "Analyzed measurements with PyTorch carefully.")
    if path.endswith("/renovate"):
        bullet = result["sections"][0]["bullets"][0]
        assert bullet["variants"] == [] and bullet["base_text"] == original
        return
    row = result if path.endswith("/bullet") else result["tailored_bullets"][0]
    # The evidence shown is this bullet itself, never the profile's "neural signal analysis".
    assert row["source_evidence"] == original
    assert all(link["source_evidence"]["quote"] in original for link in row["links"])


def test_single_bullet_prompt_includes_bounded_public_research_context(monkeypatch):
    captured = []
    monkeypatch.setattr(tailor, "model_for", lambda *args: {})
    monkeypatch.setattr(tailor, "chat_completion", lambda messages, **kwargs: captured.append(messages))
    opp = {"title": "Research assistant", "pi_name": "Professor Sample", "organization": "Signal Lab",
           "description_clean": "Study neural recordings with robust error analysis. " + "X" * 1600 + "OUTSIDE_EXCERPT",
           "description_raw": "PRIVATE_RAW_TARGET", "eligibility": {"skills_required": []}, "keywords": []}
    tailor._ai_tailor_bullets(PROFILE, opp, ["Analyzed measurement uncertainty."],
                              anchors=tailor._snapshot_anchors(opp, opp), single=True)
    prompt = captured[0][1]["content"]
    assert "Study neural recordings with robust error analysis" in prompt
    assert "Professor Sample" in prompt and "Signal Lab" in prompt
    assert "OUTSIDE_EXCERPT" not in prompt and "PRIVATE_RAW_TARGET" not in prompt


def test_reoptimization_prompt_separates_original_facts_from_manual_wording(endpoint, monkeypatch):
    original = "Analyzed measurement uncertainty."
    current = "Manual wording: analyzed measurement uncertainty."
    _, calls = write(endpoint, monkeypatch, "/api/tailor/bullet", original,
                     "Analyzed measurement uncertainty carefully.", current=current)
    assert "SINGLE LINE." in calls[0][0]["content"]
    [unit] = json.loads(calls[0][1]["content"].split("DATA (JSON):\n", 1)[1])["units"]
    assert unit == {"unit_id": "b1", "original": original, "current": current}


@pytest.mark.parametrize(("original", "proposed", "accepted"), [
    ("I did not lead the project.", "I did not lead the project, but later I led it.", False),
    ("The paper was submitted for review, not accepted.", "The paper was submitted for review, not accepted, but it was later accepted.", False),
    ("我没有主导项目。", "我没有主导项目，但后来我主导了项目。", False),
    ("论文已投稿，尚未录用。", "论文已投稿，尚未录用，但后来已录用。", False),
    ("I did not lead the project, but I reviewed its documents.", "I reviewed its documents. I did not lead the project.", True),
    ("我没有主导项目，但本人审阅文档。", "本人审阅文档。我没有主导项目。", True),
])
def test_same_claim_rule_covers_full_target_receipts(original, proposed, accepted):
    from backend.lib import evidence_map as em
    from backend.lib.target_resume_ai import finalize, parse_output

    zh = em.language(original) == "zh"
    unit = {"unit_id": "u1", "section_id": "s1", "block_id": "b1", "original": original,
            "before_text": original, "evidence": {"kind": "experience", "id": "entry", "revision": 1}}
    anchors = em.target_anchors({"description": "审阅文档" if zh else "Review documents", "requirements": []})
    link = {"id": "L1", "anchor": "t1", "term": anchors[0].text, "source": "审阅文档" if zh else "reviewed its documents",
            "relation": "same"}
    raw = json.dumps({"units": [{"unit_id": "u1", "priority": "normal", "reason": "method_relevance", "links": [link],
                                 "decision": "rewrite", "ops": [{"op": "lead_with", "link": "L1"}], "text": proposed,
                                 "keep_reason": None}]})
    results, pending = parse_output(raw, [unit], anchors, "zh" if zh else "en")
    [row] = results + finalize(pending, ["accepted"] * len(pending))
    assert (row["status"] == "suggested") is accepted
    if not accepted:
        assert row["status"] == "unchanged" and row["suggestion"]["proposed_text"] is None
        # The claim locks alone refuse it too, whatever the contract says first.
        locked = em.gate(em.Outcome("u1", "pending", text=proposed, ops=["lead_with"]), em.Unit("u1", original, original))
        assert locked.code == "rewrite_rejected"


def test_single_bullet_prompt_allows_already_public_raw_description_fallback(monkeypatch):
    captured = []
    monkeypatch.setattr(tailor, "model_for", lambda *args: {})
    monkeypatch.setattr(tailor, "chat_completion", lambda messages, **kwargs: captured.append(messages))
    public = {"title": "Research", "description_clean": "", "description_raw": "Public methods context.\nA second line.",
              "eligibility": {}, "keywords": []}
    tailor._ai_tailor_bullets(PROFILE, public, ["Analyzed measurements."],
                              anchors=tailor._snapshot_anchors(public, public), single=True)
    anchors = json.loads(captured[0][1]["content"].split("DATA (JSON):\n", 1)[1])["anchors"]
    assert [anchor["text"] for anchor in anchors] == ["Public methods context", "A second line"]


@pytest.mark.parametrize(("original", "proposed"), [
    ("The paper is not yet accepted.", "The paper is not yet accepted, but it was later accepted."),
    ("I have not yet led the project.", "I have not yet led the project, but later I led it."),
])
def test_temporal_not_yet_remains_negative(original, proposed):
    from backend.lib.target_resume_ai_grounding import claim_upgrade_detected

    assert claim_upgrade_detected(proposed, original)
    assert not claim_upgrade_detected(original, original)
