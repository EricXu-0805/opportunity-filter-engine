"""The contract and the claim locks read one unit at the 6,000-character cap in bounded time.

The claim locks used to read main's attribution parser twice per rewrite, pairing every
claim with every fact of the evidence, so a guest's 6,000 characters of negated facts or
a run of spaces held a request, and the event loop with it, for minutes. That reading is
gone. The checks now run on a worker with a deadline, but a regex holds the GIL while it
runs and a timed-out worker keeps running, so the bound has to come from the code: these
tests hold every unit to BUDGET_SECONDS of process time and every request to a short
event-loop heartbeat. The units are adversarial lines at the cap (repeated denials, a run
of spaces, repeated verbs, years, status and qualifier words, commas, Chinese status marks)
and two ordinary ones; the requests are the shapes the fifth review sent through
/api/tailor and full target.
"""
from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from backend.lib import evidence_map as em
from backend.lib import target_resume_ai as engine
from backend.main import app
from tests.test_tailor_review import CAP_SHAPES, PROFILE, _repeat_to, _verb_first_model, endpoint  # noqa: F401
from tests.test_target_resume_ai import PATH as FULL_TARGET_PATH
from tests.test_target_resume_ai import accept_all, payload, row
from tests.test_target_resume_ai import endpoint as full_target_endpoint  # noqa: F401

CAP = em.MAX_TEXT_CHARACTERS
BUDGET_SECONDS = 0.25
HEARTBEAT_SECONDS = 0.25


def _fit(unit, size):
    return (unit * max(1, size // len(unit)))[:size].rstrip() or unit


def _cut(text, limit):
    return text[:limit].rsplit(" ", 1)[0] if len(text) > limit else text


def _negated(denial):
    def shape(mode):
        evidence = _fit(f"led y. {denial} z. ", CAP)
        if mode == "tailor":
            body = _cut(_fit("led y. ", 470), 470)
            return evidence, "Responsible for leading y. " + body, "Led y. " + body
        return evidence, evidence, denial.capitalize() + " z. " + evidence.replace(f"{denial} z. ", "", 1)
    return shape


def _positive(mode):
    evidence = _fit("built a parser. ", CAP)
    if mode == "tailor":
        body = _cut(_fit("built a parser. ", 460), 460)
        return evidence, "Responsible for building a parser. " + body, "Built a parser. " + body
    return evidence, evidence, "Built a parser. " + evidence


def _space_run(mode):
    evidence = "Built a" + " " * (CAP - 45) + "website for the lab and tested it."
    return evidence, "Responsible for building a website for the lab.", "Built a website for the lab."


def _developed_then_team(mode):
    evidence = _fit("developed ", CAP // 2) + " " + _fit("with my team ", CAP - CAP // 2)
    return evidence, "Responsible for developing x with my team.", "Developed x with my team."


REALISTIC = ("Research assistant in the Cognitive Aging Lab since Fall 2025, scheduling 40 participants a week and "
             "running EEG sessions with two graduate students; I cleaned the recordings in Python and wrote MATLAB "
             "scripts that reduced artifact review time by 30%. Co-authoring a poster for SfN 2026 (in preparation). ")


def _realistic(mode):
    evidence = _fit(REALISTIC, CAP)
    if mode == "tailor":
        return evidence, _cut(REALISTIC, 480), (
            "Scheduled 40 participants a week and ran EEG sessions with two graduate students as research assistant "
            "in the Cognitive Aging Lab since Fall 2025; I cleaned the recordings in Python.")
    return evidence, evidence, evidence.replace(
        "Research assistant in the Cognitive Aging Lab since Fall 2025, scheduling", "Scheduled", 1)


PUBLICATION = ("Xu G., Lee S. (2025). Sleep spindles and memory consolidation in older adults. Preprint, submitted to "
               "Journal of Neuroscience; under review. ")

# shape -> mode -> (evidence, the wording a rewrite starts from, the rewrite)
SHAPES = {
    "negated facts": _negated("never led"),
    "negated facts, did not": _negated("did not lead"),
    "positive facts": _positive,
    "space run in an object": _space_run,
    "helped building": lambda mode: (_fit("helped building ", CAP), "Helped building a robot.",
                                     "Helped building a robot."),
    "developed, then with my team": _developed_then_team,
    "years": lambda mode: (_fit("2024 ", CAP), "Built a parser in 2024.", "In 2024, built a parser."),
    "status words": lambda mode: (_fit("preprints ", CAP), "Posted two preprints.", "Two preprints posted."),
    "qualifiers": lambda mode: (_fit("helped analyze about 40 samples, ", CAP), "Helped analyze about 40 samples.",
                                "About 40 samples: helped analyze them."),
    "zh done": lambda mode: (_fit("开发了网站，", CAP), "开发了网站。", "网站：开发了。"),
    "zh under way": lambda mode: (_fit("系统开发中，", CAP), "系统开发中。", "开发中的系统。"),
    "commas": lambda mode: (_fit("a, ", CAP), "Built a, b, c.", "Built a, b and c."),
    "realistic": _realistic,
    "publication list": lambda mode: (_fit(PUBLICATION, CAP), _cut(PUBLICATION, 480),
                                      "Sleep spindles and memory consolidation in older adults: preprint, submitted."),
}
MODES = {"tailor": "tailor", "full target": "fulltarget"}


def _unit(evidence, current, mode, support):
    """Full target rewrites the whole line, so its wording is its evidence; a support line takes half of it."""
    if mode == "fulltarget":
        current = evidence
    if not support:
        return em.Unit("b1", evidence, current)
    half = len(evidence) // 2
    own = evidence[:half]
    return em.Unit("b1", own, own if mode == "fulltarget" else current, support=(("s1", evidence[half:]),))


def _declarations(rewrite):
    """The moves a model may declare for the rewrite: each opens a different path through the contract."""
    word = next((word for word in rewrite.split() if len(word) > 3), rewrite.split()[0]).strip(".,;:")
    anchors = {"t1": em.Anchor("t1", {"field": "description", "requirement_index": None, "start": 0,
                                      "end": len(word), "quote": word})}
    link = [{"id": "L1", "anchor": "t1", "term": word, "source": word, "relation": "same"}]
    return anchors, [([{"op": "verb_first"}], []), ([{"op": "personal_first"}], []),
                     ([{"op": "lead_with", "link": "L1"}], link)]


def _seconds(read):
    """Process time of the fastest of up to three runs; a run within the budget ends the search."""
    best = float("inf")
    for _ in range(3):
        started = time.process_time()
        read()
        best = min(best, time.process_time() - started)
        if best <= BUDGET_SECONDS:
            break
    return best


@pytest.mark.parametrize("support", [False, True], ids=["alone", "with a support line"])
@pytest.mark.parametrize("mode", list(MODES))
@pytest.mark.parametrize("shape", list(SHAPES))
def test_a_unit_at_the_cap_is_checked_within_the_budget(shape, mode, support):
    evidence, current, rewrite = SHAPES[shape](MODES[mode])
    unit = _unit(evidence, current, MODES[mode], support)
    anchors, declarations = _declarations(rewrite)
    language = em.language(unit.current)
    contract = 0.0
    for ops, links in declarations:
        declared = {"unit_id": "b1", "decision": "rewrite", "text": rewrite, "keep_reason": None, "links": links,
                    "ops": ops}
        contract = max(contract, _seconds(
            lambda declared=declared: em.check_rewrite(unit, declared, anchors, output_language=language)))
    # Every rewrite is read by the locks here, whether or not a declaration passes the contract.
    locks = _seconds(lambda: em.gate(em.Outcome("b1", "pending", text=rewrite), unit))
    assert contract + locks <= BUDGET_SECONDS, (contract, locks)


async def _heartbeat(send):
    """``send``'s response and the gaps between /api/tailor/status answers while it ran."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
        request = asyncio.create_task(send(client))
        gaps, last = [], time.perf_counter()
        while not request.done():
            await client.get("/api/tailor/status")
            now = time.perf_counter()
            gaps.append(now - last)
            last = now
            await asyncio.sleep(0.005)
        return await request, gaps


ROUTE_SHAPES = {
    **CAP_SHAPES,
    "repeated claims": (_repeat_to("led y. ", 5999), "Responsible for leading y. " + _repeat_to("led y. ", 470),
                        "Led y. " + _repeat_to("led y. ", 470)),
}
# What each request comes back with once its checks have run: kept by a lock, or shown after the review.
ROUTE_OUTCOMES = {"denials": "rewrite_rejected", "space run": None, "developed with my team": "rewrite_rejected",
                  "repeated claims": None}


@pytest.mark.parametrize("shape", list(ROUTE_SHAPES))
@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/bullet"])
def test_the_event_loop_answers_while_tailor_checks_a_request_at_the_cap(endpoint, monkeypatch, path, shape):  # noqa: F811
    _, opportunity_id = endpoint
    evidence, current, rewrite = ROUTE_SHAPES[shape]
    calls: list[str] = []
    _verb_first_model(monkeypatch, rewrite, calls)
    body = {"profile": PROFILE, "opportunity_id": opportunity_id, "locale": "en"}
    if path.endswith("/bullet"):
        body.update(base_text=evidence, current_text=current)
    else:
        body.update(original_bullets=[current], source_bullets=[evidence])
    response, gaps = asyncio.run(_heartbeat(lambda client: client.post(path, json=body)))
    assert response.status_code == 200, response.text
    answer = response.json()
    reason = answer["reason_code"] if path.endswith("/bullet") else answer["tailored_bullets"][0]["reason_code"]
    assert reason == ROUTE_OUTCOMES[shape]
    assert calls == (["generate"] if reason else ["generate", "review"])
    assert max(gaps) <= HEARTBEAT_SECONDS, max(gaps)


def test_the_event_loop_answers_while_full_target_checks_a_line_at_the_cap(full_target_endpoint, monkeypatch):  # noqa: F811
    _, doc, _, _ = full_target_endpoint
    lead = "Responsible for leading y. "
    original = lead + _repeat_to("led y. not led z. ", CAP - len(lead))
    rewrite = "Led y. " + original[len(lead):]
    doc["base_snapshot"]["experience_entries"][0].update(text=original, source={"kind": "manual"})
    line = doc["document"]["sections"][1]["blocks"][0]["lines"][1]
    line.update(original=original, text=original)
    accept_all(monkeypatch)
    monkeypatch.setattr(engine, "chat_completion", lambda *args, **kwargs: json.dumps(
        {"units": [row(line["id"], text=rewrite, ops=[{"op": "verb_first"}])]}))
    response, gaps = asyncio.run(_heartbeat(
        lambda client: client.post(FULL_TARGET_PATH, json=payload(doc, [line["id"]]))))
    assert response.status_code == 200, response.text
    [receipt] = response.json()["receipts"]
    assert (receipt["status"], receipt["suggestion"]["proposed_text"]) == ("suggested", rewrite), receipt
    assert max(gaps) <= HEARTBEAT_SECONDS, max(gaps)
