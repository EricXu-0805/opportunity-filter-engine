"""Route-level attribution regressions; providers are deterministic local stubs."""
import json
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes import cold_email as ce
from tests.experience_fixtures import confirmed_experience, resume_line_experience

PROFILE = {"name": "Audit Student", "school": "UIUC", "year": "sophomore",
           "major": "Computer Science", "hard_skills": [], "coursework": [],
           "research_interests_text": "research tools"}
OPP = {"id": "attribution-route", "source_type": "campus_program",
       "opportunity_type": "research", "title": "Research Tools", "pi_name": "Pat Lee",
       "organization": "Test University", "keywords": ["Python parser", "Linux setup"],
       "description_raw": "Research on Python parser tools and Linux setup.",
       "eligibility": {"skills_required": []}, "application": {}, "metadata": {"is_active": True}}
TEAM = "My role: I wrote parser tests. Outcome: My team built a Python parser. I did not build the parser."
PROJECTS = ["I improved Python parser throughput by 45%.", "I reduced Linux setup time by 12%."]
BAD = [
    pytest.param([TEAM], "I built a Python parser.", id="team-and-negation-to-i"),
    pytest.param([TEAM], "Working with my team, I built a Python parser.", id="team-prefix-hides-i"),
    pytest.param([TEAM], "With my team, I built a Python parser.", id="preposition-hides-i"),
    pytest.param(["My team built a Python parser. My role: I wrote parser tests."],
                 "I built a Python parser.", id="team-to-i"),
    pytest.param(["I did not build a Python parser."], "I built a Python parser.", id="negation-lost"),
    pytest.param(["I wrote tests for a Python parser."], "I wrote a Python parser.", id="test-target-is-not-built-object"),
    pytest.param(["My team improved parser throughput by 45%. My role: I wrote parser tests."],
                 "I improved parser throughput by 45%.", id="team-metric-to-i"),
    pytest.param(PROJECTS, "I reduced Linux setup time by 45%.", id="project-metric-swapped"),
    pytest.param(["I improved Python parser throughput by 20% with my team."],
                 "I improved Python parser throughput by 20%.", id="team-metric-qualifier-dropped"),
    pytest.param(["Built a Python parser with my team."], "I built a Python parser.", id="team-suffix-dropped"),
    pytest.param(["I improved Python parser throughput by 45% and reduced parser latency by 12%."],
                 "I reduced Python parser latency by 45%.", id="metric-axis-swapped"),
    pytest.param(PROJECTS, "I improved Python parser throughput by 80% and would like to discuss your research.",
                 id="your-does-not-exempt-my-metric"),
]
GOOD = [
    pytest.param([TEAM], "I wrote parser tests. My team built a Python parser. I did not build the parser.", id="roles-preserved"),
    pytest.param(["I did not build a Python parser."], "I did not build a Python parser.", id="negative-preserved"),
    pytest.param(["Built a Python parser for research tools."], "I built a Python parser for research tools.", id="own-work"),
    pytest.param(PROJECTS, "I improved Python parser throughput by 45%.", id="own-project-metric"),
    pytest.param(["Built a Python parser with my team."], "I built a Python parser with my team.", id="team-qualifier-kept"),
    pytest.param(["Improved Python parser throughput by 45 percent."],
                 "I improved Python parser throughput by 45%.", id="equivalent-percent"),
    pytest.param(["Analyzed 10000 samples using Python."], "I analyzed 10,000 samples using Python.", id="equivalent-comma"),
]


def draft(claim):
    return f"Dear Pat Lee,\n\n{claim}\n\nCould we discuss Python parser research?\n\nBest regards,\nAudit Student"


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(ce.router, prefix="/api")
    monkeypatch.setattr(ce, "load_opportunities_by_id", lambda: {OPP["id"]: deepcopy(OPP)})
    monkeypatch.setattr(ce, "corpus_version", lambda: "attribution-route-fixture")
    monkeypatch.setattr(ce, "is_configured", lambda: True)
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "1")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "0")

    async def anonymous(_authorization):
        return None

    def unexpected_provider(*_args, **_kwargs):
        pytest.fail("provider must be explicitly stubbed")

    monkeypatch.setattr(ce, "authenticated_uid", anonymous)
    monkeypatch.setattr(ce, "chat_completion", unexpected_provider)
    return TestClient(app)


def request(client, endpoint, evidence, *, claim=None):
    payload = {"profile": PROFILE, "opportunity_id": OPP["id"], "engine": "ai",
               "experience_evidence": evidence if isinstance(evidence, dict) else confirmed_experience(evidence)}
    if endpoint == "refine":
        payload.update(current_body=draft(claim or "I am interested in Python parser research."),
                       instruction="Make it clearer")
    response = client.post("/api/cold-email" + (f"/{endpoint}" if endpoint else ""), json=payload)
    assert response.status_code == 200, response.text
    if endpoint == "stream":
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
        done = [frame for frame in frames if frame["stage"] == "done"]
        assert len(done) == 1
        return done[0]
    return response.json()


@pytest.mark.parametrize("endpoint", ["", "stream", "refine"])
@pytest.mark.parametrize("evidence,claim", BAD)
def test_generated_claim_cannot_reassign_confirmed_work(client, monkeypatch, endpoint, evidence, claim):
    body = draft(claim)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body if endpoint == "refine" else f"Subject: Research inquiry\n\n{body}")
    result = request(client, endpoint, evidence, claim=claim)
    assert result["method"] in ("template", "local"), result
    assert result["fallback_reason"] == "fabrication", result
    assert claim not in result["body"], result


@pytest.mark.parametrize("endpoint", ["", "refine"])
@pytest.mark.parametrize("evidence,claim", GOOD)
def test_attributed_work_and_equivalent_numbers_remain_usable(client, monkeypatch, endpoint, evidence, claim):
    body = draft(claim)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body if endpoint == "refine" else f"Subject: Research inquiry\n\n{body}")
    result = request(client, endpoint, evidence)
    assert result["method"] == ("llm" if endpoint == "refine" else "ai"), result
    assert claim in result["body"]
    assert result["experience_usage"]["selected"]


# A PDF import confirms each printed line as its own entry, so a bullet's
# result sits one entry below the action it completes. The student's own
# sentence must pass, and the printed bullet must not lend its result or its
# collaborators to anything it does not say.
PRINTED = (
    "Undergraduate Research Assistant, Health Imaging Lab (UIUC) - Jan 2026 - Present\n"
    "- Built a PyTorch pipeline that preprocesses 12,000 chest X-ray images and trains a ResNet-18 baseline,\n"
    "reaching 0.87 AUC on a held-out split.\n"
    "- Built a Python parser\n"
    "with my team.\n"
    "- Wrote SQL and Python ETL jobs that cut a nightly report's runtime from 40 minutes to 9 minutes.\n"
)
XRAY = ("I built a PyTorch pipeline that preprocesses 12,000 chest X-ray images and trains "
        "a ResNet-18 baseline, reaching 0.87 AUC on a held-out split.")


@pytest.mark.parametrize("endpoint", ["", "stream", "refine"])
def test_a_wrapped_bullet_restated_in_first_person_is_usable(client, monkeypatch, endpoint):
    body = draft(XRAY)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body if endpoint == "refine" else f"Subject: Research inquiry\n\n{body}")
    result = request(client, endpoint, resume_line_experience(PRINTED))
    assert result["method"] == ("llm" if endpoint == "refine" else "ai"), result
    assert result.get("fallback_reason") is None
    assert XRAY in result["body"]


@pytest.mark.parametrize("endpoint", ["", "stream", "refine"])
@pytest.mark.parametrize("unconfirmed,claim", [
    pytest.param(["reaching 0.87 AUC on a held-out split."], XRAY, id="result-line-not-confirmed"),
    pytest.param([], XRAY.replace("0.87", "0.95"), id="result-changed"),
    pytest.param([], "I built a Python parser.", id="wrapped-team-qualifier-dropped"),
    pytest.param([], "I wrote SQL and Python ETL jobs that cut a nightly report's runtime from 40 minutes "
                     "to 9 minutes, reaching 0.87 AUC on a held-out split.", id="result-moved-to-next-bullet"),
])
def test_a_wrapped_bullet_lends_nothing_it_does_not_print(client, monkeypatch, endpoint, unconfirmed, claim):
    body = draft(claim)
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: body if endpoint == "refine" else f"Subject: Research inquiry\n\n{body}")
    result = request(client, endpoint, resume_line_experience(PRINTED, unconfirmed=unconfirmed), claim=claim)
    assert result["method"] in ("template", "local"), result
    assert result["fallback_reason"] == "fabrication", result
    assert claim not in result["body"], result


@pytest.mark.parametrize("instruction,changed", [
    pytest.param("Make it shorter and mention my parser tests first.", False, id="no-local-rule-changes-anything"),
    pytest.param("Make it more formal.", True, id="formal-rule-changes-a-phrase"),
])
def test_a_rejected_edit_suggests_only_what_the_local_rules_changed(client, monkeypatch, instruction, changed):
    # Walked 2026-09-30: the AI edit failed the fact check, the "shorter"
    # rule had no filler to drop, and the student was still offered a
    # "suggestion" that differed only by the blank line after the greeting.
    original = draft("I would love to discuss my parser tests.")
    monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: draft("I built a Python parser."))
    response = client.post("/api/cold-email/refine", json={
        "profile": PROFILE, "opportunity_id": OPP["id"], "experience_evidence": confirmed_experience([TEAM]),
        "current_body": original, "instruction": instruction})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["fallback_reason"] == "fabrication"
    assert "I built a Python parser." not in result["body"]
    if changed:
        assert "I would greatly appreciate to discuss my parser tests." in result["body"]
        assert result["applied"] == ["formal"]
    else:
        assert result["body"] == original
        assert result["applied"] == []


@pytest.mark.parametrize("failure", ["unconfigured", "no-output", "timeout"])
def test_local_recovery_does_not_authenticate_an_existing_false_draft(client, monkeypatch, failure):
    if failure == "unconfigured":
        monkeypatch.setattr(ce, "is_configured", lambda: False)
    elif failure == "no-output":
        monkeypatch.setattr(ce, "chat_completion", lambda *_a, **_k: None)
    else:
        async def timeout(*_args, **_kwargs):
            raise ce.BlockingWorkTimeout()
        monkeypatch.setattr(ce, "run_blocking", timeout)
    claim = "I built a Python parser."
    result = request(client, "refine", [TEAM], claim=claim)
    assert result["method"] == "local"
    assert result["fallback_reason"] == "fabrication"
    assert claim not in result["body"]
    assert TEAM in result["body"]


def test_variant_final_output_guard_does_not_trust_its_template_producer(client, monkeypatch):
    claim = "I built a Python parser."
    monkeypatch.setattr(ce, "generate_variants", lambda *_a, **_k: [
        {"id": "unsafe", "label": "Fixture", "text": "Subject: Research inquiry\n\n" + draft(claim)},
    ])
    result = request(client, "variants", [TEAM])
    assert len(result["variants"]) == 1
    variant = result["variants"][0]
    assert claim not in variant["body"]
    assert variant["experience_usage"]["selected"] == []
    assert result["experience_usage"]["selected"] == []


def test_bad_reviewer_cannot_promote_a_team_claim_over_a_supported_draft(client, monkeypatch):
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "2")
    monkeypatch.setenv("OFE_COLD_EMAIL_CRITIQUE", "1")
    good = "I wrote parser tests. My team built a Python parser."
    bad = "I built a Python parser."
    calls = []

    def provider(messages, **_kwargs):
        system = messages[0]["content"]
        if "You are judging candidate" in system:
            calls.append("judge")
            return '{"winner":2}'
        if "You are a strict reviewer" in system:
            calls.append("critique")
            return '{"verdict":"revise","revision_notes":"Make the contribution personal."}'
        if "You are revising" in system:
            calls.append("revise")
            return "Subject: Research inquiry\n\n" + draft(bad)
        calls.append("draft")
        # All initial candidates are correct; judge cannot see an unsafe draft
        # until the critique/revise stage introduces one.
        return "Subject: Research inquiry\n\n" + draft(good)

    monkeypatch.setattr(ce, "chat_completion", provider)
    result = request(client, "", [TEAM])
    assert calls.count("draft") == 2
    assert {"judge", "critique", "revise"} <= set(calls)
    assert result["method"] == "ai", result
    assert good in result["body"]
    assert bad not in result["body"]


def test_ai_usage_receipt_describes_prompt_selection_not_actual_claims(client, monkeypatch):
    # This is the existing public contract, not proof that each receipt was
    # paraphrased or that the selected entries entail every output sentence.
    evidence = ["Built a Python parser.", "Documented Linux setup."]
    body = draft("I am interested in Python parser research.")
    captured = []

    def provider(messages, **_kwargs):
        captured.append(messages[1]["content"])
        return "Subject: Research inquiry\n\n" + body

    monkeypatch.setattr(ce, "chat_completion", provider)
    result = request(client, "", evidence)
    assert result["method"] == "ai", result
    selected = result["experience_usage"]["selected"]
    assert {item["id"] for item in selected} == {"experience-0", "experience-1"}
    assert all(item["excerpt"] in captured[0] for item in selected)
    assert all(item["excerpt"] not in result["body"] for item in selected)


def test_unsafe_parallel_candidate_cannot_win_by_judge_choice(client, monkeypatch):
    monkeypatch.setenv("OFE_COLD_EMAIL_NDRAFT", "2")
    good = "I wrote parser tests. My team built a Python parser."
    bad = "I built a Python parser."
    calls = []

    def provider(messages, **_kwargs):
        system = messages[0]["content"]
        if "You are judging candidate" in system:
            calls.append("judge")
            return '{"winner":2}'
        if "You are revising" in system:
            calls.append("revise")
            return "Subject: Research inquiry\n\n" + draft(bad)
        calls.append("draft")
        # Angle wording differs for non-faculty contacts; this phrase remains
        # stable in both forms and avoids thread scheduling based fixtures.
        claim = bad if "Lead with your fit:" in system else good
        return "Subject: Research inquiry\n\n" + draft(claim)

    monkeypatch.setattr(ce, "chat_completion", provider)
    result = request(client, "", [TEAM])
    assert calls.count("draft") == 2
    assert result["method"] == "ai", result
    assert good in result["body"]
    assert bad not in result["body"]
    assert "judge" not in calls  # Different deterministic scores, no tie.
