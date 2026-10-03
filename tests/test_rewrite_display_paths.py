"""Every line a rewrite route offers the student was reviewed, and keeps its original's language.

Acceptance criteria (1) and (3) of fix/tailor-review, end to end and
provider-free. The generation call, the renovation plan and the faithfulness
review are stubbed at ``chat_completion``, as tests/test_tailor_review.py does.
For each route (/api/tailor, /api/tailor/renovate, /api/tailor/bullet and the
full-target suggestions) the test collects every text the response offers in
place of a line - the rewrite, and the version without the posting's terms -
and compares it with the texts the review was asked about.

Run from the repository root:
    python -m pytest tests/test_rewrite_display_paths.py -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend import data_loader
from backend.lib import evidence_map as em
from backend.lib import target_resume_ai
from backend.lib.release_scope import opportunity_visible_in_release
from backend.lib.target_resume_ai_validation import fingerprint, units_for
from backend.main import app
from backend.routes import tailor
from src.evidence import is_actionable_target
from tests import test_target_resume_ai as full_target

TAILOR_PATHS = ("/api/tailor", "/api/tailor/renovate", "/api/tailor/bullet")
ALL_PATHS = (*TAILOR_PATHS, "full-target")
PROFILE = {"name": "Sample Student", "school": "UIUC", "year": "sophomore", "major": "Psychology",
           "hard_skills": [{"name": "R", "level": "experienced", "confirmed": True}],
           "coursework": ["PSYC 238"], "research_interests_text": "human factors"}


def _rewrite(text, ops, links=()):
    return {"links": list(links), "decision": "rewrite", "ops": list(ops), "text": text, "keep_reason": None}


# Two relabels to the same term, listed in the opposite order to where they stand in the line, plus
# verb_first. The rewrite is faithful; undoing the relabels in list order puts each source back in the
# other's place, so the version "without the posting's terms" says notebooks cleaned the data.
SWAPPED_ORIGINAL = "Responsible for writing Python scripts for data cleaning and Python notebooks for plotting."
SWAPPED_REWRITE = "Wrote Python code for data cleaning and Python code for plotting."
SWAPPED_ALTERNATIVE = "Wrote Python notebooks for data cleaning and Python scripts for plotting."
SWAPPED_ANCHOR = "Experience writing Python code is required."
SWAPPED_ROW = _rewrite(SWAPPED_REWRITE, [
    {"op": "relabel", "link": "L2", "from": "Python notebooks", "to": "Python code"},
    {"op": "relabel", "link": "L1", "from": "Python scripts", "to": "Python code"},
    {"op": "verb_first"}], [
    {"id": "L1", "anchor": "t1", "term": "Python code", "source": "Python scripts", "relation": "same"},
    {"id": "L2", "anchor": "t1", "term": "Python code", "source": "Python notebooks", "relation": "same"}])

# One relabel plus verb_first: the plainest alternative, still never sent to the review.
PLAIN_ORIGINAL = "Responsible for writing Python scripts for data cleaning."
PLAIN_REWRITE = "Wrote Python code for data cleaning."
PLAIN_ROW = _rewrite(PLAIN_REWRITE, [{"op": "relabel", "link": "L1", "from": "Python scripts", "to": "Python code"},
                                     {"op": "verb_first"}],
                     [{"id": "L1", "anchor": "t1", "term": "Python code", "source": "Python scripts", "relation": "same"}])

# A Chinese-framed line that language() counts as English. A relabel replaces its Chinese 脑电 with the
# English "brain": the doc says cross-language relabels are not offered.
MIXED_ORIGINAL = "负责 脑电 signal preprocessing, feature extraction, model training 和 classification"
MIXED_REWRITE = "负责 brain signal preprocessing, feature extraction, model training 和 classification"
MIXED_ANCHOR = "We study brain signal processing in children."
MIXED_ROW = _rewrite(MIXED_REWRITE, [{"op": "relabel", "link": "L1", "from": "脑电 signal", "to": "brain signal"}],
                     [{"id": "L1", "anchor": "t1", "term": "brain signal", "source": "脑电 signal", "relation": "same"}])

# The same kind of line with its Chinese conjunction 和 written as "and" (function words are no tokens).
CONJUNCTION_ORIGINAL = "负责 data cleaning, feature engineering, model training 和 deployment"
CONJUNCTION_REWRITE = "负责 model training, data cleaning, feature engineering and deployment"
CONJUNCTION_ANCHOR = "Experience with model training is a plus."
CONJUNCTION_ROW = _rewrite(CONJUNCTION_REWRITE, [{"op": "lead_with", "link": "L1"}], [
    {"id": "L1", "anchor": "t1", "term": "model training", "source": "model training", "relation": "same"}])

# An English line rewritten with a tail in a script that is neither Latin nor CJK ideographs.
VERB_FIRST_ORIGINAL = "Research assistant in the Fluids Lab, analyzing Python simulation data for CS 225."
VERB_FIRST_REWRITE = "Analyzed Python simulation data for CS 225 as a research assistant in the Fluids Lab."
OTHER_SCRIPT_TAILS = {"katakana": " (フルイド・ラボ)", "hangul": " (유체 연구실)", "cyrillic": " (лаборатория)",
                      "full-width latin": " (ＰｙＴｏｒｃｈ)"}
ANY_ANCHOR = "We study fluid dynamics with simulations."


def _anchor(ident, text):
    return em.Anchor(ident, {"field": "description", "requirement_index": None, "start": 0, "end": len(text),
                             "quote": text})


def review_by(faithful):
    """A reviewer that answers ``faithful(pair)`` for each pair and marks every link the same way."""
    def answer(payload):
        verdicts = []
        for pair in payload["pairs"]:
            ok = faithful(pair)
            verdicts.append({"index": pair["index"], "changes": "[ok]", "faithful": ok,
                             "links": [{"id": link["id"], "entailed": ok} for link in pair.get("links", [])],
                             "problem": "" if ok else "unsupported"})
        return json.dumps({"verdicts": verdicts})
    return answer


ACCEPT_ALL = review_by(lambda pair: True)


@pytest.fixture
def opportunity(monkeypatch):
    target = next(opp for opp in data_loader.load_opportunities_by_id().values()
                  if opportunity_visible_in_release(opp) and is_actionable_target(opp))
    monkeypatch.setattr(tailor, "load_opportunities_by_id", lambda: {target["id"]: target})
    monkeypatch.setattr(tailor, "is_configured", lambda: True)
    monkeypatch.setattr(tailor, "_schedule_usage", lambda *args: None)
    monkeypatch.setattr(tailor, "model_for", lambda *args: {})
    monkeypatch.setattr(em, "model_for", lambda *args: {})
    monkeypatch.setattr(target_resume_ai, "model_for", lambda *args: {})
    return target["id"]


def post_tailor(opportunity_id, monkeypatch, path, cases, review, *, anchors, locale="en", sections=None,
                current=None, plan=None):
    """POST ``cases`` [(original, row)] through ``path``; the model answers each unit with its case's row.

    Returns (body, review payloads). ``review`` is a string, None or a callable taking the payload.
    """
    reviews: list[dict] = []
    anchor_list = [_anchor(f"t{i}", text) for i, text in enumerate(anchors, start=1)]
    monkeypatch.setattr(tailor, "_snapshot_anchors", lambda source, snapshot: anchor_list)
    by_original = {original: row for original, row in cases}

    def model(messages, **kwargs):
        system = messages[0]["content"]
        if system.startswith("FAITHFULNESS REVIEW"):
            payload = json.loads(messages[1]["content"])
            reviews.append(payload)
            return review(payload) if callable(review) else review
        if "REORGANIZE" in system:
            return json.dumps(plan or {"sections": [{"id": "s1", "bullets": [
                {"id": f"b{i}", "action": "foreground"} for i in range(len(cases))]}]})
        units = json.loads(messages[1]["content"].split("DATA (JSON):\n", 1)[1])["units"]
        return json.dumps({"bullets": [{"unit_id": unit["unit_id"], **by_original[unit["original"]]}
                                       for unit in units if unit["original"] in by_original]})

    monkeypatch.setattr(tailor, "chat_completion", model)
    monkeypatch.setattr(em, "chat_completion", model)
    payload = {"profile": PROFILE, "opportunity_id": opportunity_id, "locale": locale}
    if path.endswith("/renovate"):
        payload["sections"] = sections or [{"id": "s1", "heading": "Projects", "kind": "projects", "bullets": [
            {"id": f"b{i}", "text": original} for i, (original, _) in enumerate(cases)]}]
    elif path.endswith("/bullet"):
        assert len(cases) == 1
        payload.update(base_text=cases[0][0], current_text=current or cases[0][0])
    else:
        payload["original_bullets"] = [original for original, _ in cases]
    response = TestClient(app).post(path, json=payload)
    assert response.status_code == 200, response.text
    return response.json(), reviews


def post_full_target(monkeypatch, original, row, review, *, description, locale="en"):
    """Full target with ``original`` as its experience line; the model answers it with ``row``.

    The target's description is ``description``; its first sentence is anchor t1.
    Returns (the line's receipt, review payloads).
    """
    doc = full_target.make_doc(original)
    target = full_target.route.authoritative_target({
        "id": "target", "title": "Research", "organization": "Example Lab", "source_url": "https://example.edu/lab",
        "description_clean": description, "eligibility": {"skills_required": ["Python"]},
        "source_type": "campus_program", "opportunity_type": "research", "metadata": {"is_active": True}})
    doc["target_snapshot"], doc["base"]["target_signature"] = target, fingerprint(target)
    opp = {"id": "target", "title": target["title"], "organization": target["organization"],
           "source_url": target["source_url"], "description_clean": target["description"],
           "eligibility": {"skills_required": target["requirements"]}, "source_type": "campus_program",
           "opportunity_type": "research", "metadata": {"is_active": True}}
    monkeypatch.setattr(full_target.route, "load_opportunities_by_id", lambda: {"target": opp})
    monkeypatch.setattr(full_target.route, "is_configured", lambda: True)
    monkeypatch.setattr(target_resume_ai.llm_budget, "exhausted", lambda: False)
    units = units_for(doc)[0]
    line = next(unit for unit in units if unit["evidence"]["kind"] == "experience")
    assert line["original"] == original
    rows = [{"unit_id": unit["unit_id"], "priority": "normal", "reason": "method_relevance",
             **(row if unit is line else {"links": [], "decision": "keep", "ops": [], "text": None,
                                          "keep_reason": "no_link"})} for unit in units]
    reviews: list[dict] = []

    def model(messages, **kwargs):
        if messages[0]["content"].startswith("FAITHFULNESS REVIEW"):
            payload = json.loads(messages[1]["content"])
            reviews.append(payload)
            return review(payload) if callable(review) else review
        return json.dumps({"units": rows})

    monkeypatch.setattr(target_resume_ai, "chat_completion", model)
    monkeypatch.setattr(em, "chat_completion", model)
    response = TestClient(app).post(full_target.PATH, json={**full_target.payload(doc), "locale": locale})
    assert response.status_code == 200, response.text
    return next(r for r in response.json()["receipts"] if r["unit_id"] == line["unit_id"]), reviews


def offered(path, body) -> list[list[str]]:
    """For each submitted line, every text the response offers to show in its place."""
    if path == "full-target":
        suggestion = body.get("suggestion") or {}
        return [[text for text in (suggestion.get("proposed_text"), suggestion.get("alternative_text")) if text]]
    if path.endswith("/renovate"):
        return [[text for variant in bullet["variants"] for text in (variant["text"], variant.get("alternative"))
                 if text] for section in body["sections"] for bullet in section["bullets"]]
    if path.endswith("/bullet"):
        return [[text for text in (body["text"], body.get("alternative")) if text] if body["changed"] else []]
    return [[text for text in (row["text"], row.get("alternative")) if text] if row["status"] == "rewritten" else []
            for row in body["tailored_bullets"]]


def reviewed(reviews) -> set[str]:
    return {pair["rewrite"] for payload in reviews for pair in payload["pairs"]}


def run(opportunity, monkeypatch, path, original, row, anchor, review=ACCEPT_ALL, *, locale="en"):
    """(texts offered for the one line, texts the review saw)."""
    if path == "full-target":
        receipt, reviews = post_full_target(monkeypatch, original, row, review, description=anchor, locale=locale)
        return offered(path, receipt)[0], reviewed(reviews)
    body, reviews = post_tailor(opportunity, monkeypatch, path, [(original, row)], review, anchors=[anchor],
                                locale=locale)
    return offered(path, body)[0], reviewed(reviews)


# ------------------------------------------------------------------ criterion (1)

@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize(("original", "row", "anchor"), [
    (PLAIN_ORIGINAL, PLAIN_ROW, SWAPPED_ANCHOR), (SWAPPED_ORIGINAL, SWAPPED_ROW, SWAPPED_ANCHOR)],
    ids=["one-relabel", "two-relabels"])
def test_every_offered_text_was_itself_reviewed(opportunity, monkeypatch, path, original, row, anchor):
    shown, seen = run(opportunity, monkeypatch, path, original, row, anchor)
    assert row["text"] in shown, "the reviewed rewrite itself is offered"
    assert set(shown) <= seen, f"offered without a review of that text: {sorted(set(shown) - seen)}"


@pytest.mark.parametrize("path", ALL_PATHS)
def test_the_version_without_the_terms_never_swaps_the_students_words(opportunity, monkeypatch, path):
    shown, _ = run(opportunity, monkeypatch, path, SWAPPED_ORIGINAL, SWAPPED_ROW, SWAPPED_ANCHOR)
    assert SWAPPED_ALTERNATIVE not in shown


PLAIN_ALTERNATIVE = "Wrote Python scripts for data cleaning."


@pytest.mark.parametrize("path", ALL_PATHS)
def test_the_version_without_the_terms_is_offered_only_on_its_own_accepted_verdict(opportunity, monkeypatch, path):
    shown, seen = run(opportunity, monkeypatch, path, PLAIN_ORIGINAL, PLAIN_ROW, SWAPPED_ANCHOR)
    assert (shown, PLAIN_ALTERNATIVE in seen) == ([PLAIN_REWRITE, PLAIN_ALTERNATIVE], True)
    shown, seen = run(opportunity, monkeypatch, path, PLAIN_ORIGINAL, PLAIN_ROW, SWAPPED_ANCHOR,
                      review_by(lambda pair: pair["rewrite"] != PLAIN_ALTERNATIVE))
    assert (shown, PLAIN_ALTERNATIVE in seen) == ([PLAIN_REWRITE], True)
    # A rejected rewrite offers neither, even when the review accepts the version without the terms.
    shown, _ = run(opportunity, monkeypatch, path, PLAIN_ORIGINAL, PLAIN_ROW, SWAPPED_ANCHOR,
                   review_by(lambda pair: pair["rewrite"] == PLAIN_ALTERNATIVE))
    assert shown == []


@pytest.mark.parametrize("path", TAILOR_PATHS)
def test_the_version_without_the_terms_is_reviewed_with_its_own_links_unwritten(opportunity, monkeypatch, path):
    """The alternative pair carries only the links its remaining operations use, with no term written in."""
    original = "Built a survey dashboard in R for the campus food pantry and analyzed EEG recordings."
    rewrite = "Analyzed EEG data and built a survey dashboard in R for the campus food pantry."
    row = _rewrite(rewrite, [{"op": "relabel", "link": "L1", "from": "EEG recordings", "to": "EEG data"},
                             {"op": "lead_with", "link": "L1"}],
                   [{"id": "L1", "anchor": "t1", "term": "EEG data", "source": "EEG recordings", "relation": "same"}])
    body, reviews = post_tailor(opportunity, monkeypatch, path, [(original, row)], ACCEPT_ALL,
                                anchors=["We analyze EEG data from infants."])
    pairs = {pair["rewrite"]: pair for pair in reviews[0]["pairs"]}
    alternative = "Analyzed EEG recordings and built a survey dashboard in R for the campus food pantry."
    assert pairs[rewrite]["links"][0]["written_as"] == "EEG data"
    assert [link["written_as"] for link in pairs[alternative]["links"]] == [None]
    assert offered(path, body) == [[rewrite, alternative]]


# ------------------------------------------------------------------ criterion (3)

@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize("script", list(OTHER_SCRIPT_TAILS))
def test_a_rewrite_with_words_in_another_script_is_kept(opportunity, monkeypatch, path, script):
    rewrite = VERB_FIRST_REWRITE + OTHER_SCRIPT_TAILS[script]
    shown, _ = run(opportunity, monkeypatch, path, VERB_FIRST_ORIGINAL, _rewrite(rewrite, [{"op": "verb_first"}]),
                   ANY_ANCHOR)
    assert rewrite not in shown


@pytest.mark.parametrize("path", ALL_PATHS)
@pytest.mark.parametrize(("original", "row", "anchor"), [
    (MIXED_ORIGINAL, MIXED_ROW, MIXED_ANCHOR), (CONJUNCTION_ORIGINAL, CONJUNCTION_ROW, CONJUNCTION_ANCHOR)],
    ids=["脑电->brain", "和->and"])
def test_a_rewrite_that_translates_part_of_its_line_is_kept(opportunity, monkeypatch, path, original, row, anchor):
    assert em.language(original) == em.language(row["text"]) == "en"
    shown, _ = run(opportunity, monkeypatch, path, original, row, anchor, locale="zh")
    assert row["text"] not in shown


@pytest.mark.parametrize("path", TAILOR_PATHS)
@pytest.mark.parametrize(("original", "rewrite", "op"), [
    # A Chinese reorder may add 并 beside an English tool name: the line's frame stays Chinese.
    ("用 Python 清洗了 212 份问卷，训练了 3 个模型。", "训练了 3 个模型，并用 Python 清洗了 212 份问卷。", "lead_with"),
    # A letter of another script the line already uses stays.
    ("Research assistant in the Café Lab, analyzing Python simulation data for CS 225.",
     "Analyzed Python simulation data for CS 225 as a research assistant in the Café Lab.", "verb_first"),
], ids=["zh-reorder-adds-并", "accent-already-there"])
def test_a_rewrite_in_its_own_script_still_goes_to_the_review(opportunity, monkeypatch, path, original, rewrite, op):
    links = [{"id": "L1", "anchor": "t1", "term": "3 个模型", "source": "3 个模型", "relation": "same"}]
    row = _rewrite(rewrite, [{"op": op, "link": "L1"}] if op == "lead_with" else [{"op": op}],
                   links if op == "lead_with" else [])
    body, reviews = post_tailor(opportunity, monkeypatch, path, [(original, row)], ACCEPT_ALL,
                                anchors=["我们训练了 3 个模型。" if op == "lead_with" else ANY_ANCHOR])
    assert len(reviews) == 1 and offered(path, body) == [[rewrite]]


# ------------------------------------------------- fallbacks that hold (regression guards)

TWO = [("Analyzed 88 samples with PyTorch and wrote the fluids lab report.",
        _rewrite("Wrote the fluids lab report and analyzed 88 samples with PyTorch.", [{"op": "lead_with", "link": "L1"}],
                 [{"id": "L1", "anchor": "t1", "term": "fluids lab report", "source": "fluids lab report",
                   "relation": "same"}])),
       (VERB_FIRST_ORIGINAL, _rewrite(VERB_FIRST_REWRITE, [{"op": "verb_first"}]))]
TWO_ANCHORS = ["Write the fluids lab report every week."]


@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/renovate"])
@pytest.mark.parametrize(("review", "expected"), [
    # Only one verdict for two pairs: nothing ties it to pair 1 rather than to a renumbered pair 2,
    # so both keep their originals (round-3 review).
    (json.dumps({"verdicts": [{"index": 1, "faithful": True, "links": [{"id": "L1", "entailed": True}]}]}),
     [False, False]),
    # Out of pair order: a swap reads the same as two misnumbered verdicts, so both keep their originals.
    (json.dumps({"verdicts": [{"index": 2, "faithful": True, "links": []},
                              {"index": 1, "faithful": False, "links": [{"id": "L1", "entailed": True}]}]}),
     [False, False]),
    # Complete and in pair order: each verdict counts for its own pair.
    (json.dumps({"verdicts": [{"index": 1, "faithful": False, "links": [{"id": "L1", "entailed": True}]},
                              {"index": 2, "faithful": True, "links": []}]}),
     [False, True]),
    # An index as a string, a non-boolean faithful, a list instead of an object: all fail closed.
    (json.dumps({"verdicts": [{"index": "1", "faithful": True, "links": [{"id": "L1", "entailed": True}]},
                              {"index": 2, "faithful": 1, "links": []}]}), [False, False]),
    (json.dumps([{"index": 1, "faithful": True}, {"index": 2, "faithful": True}]), [False, False]),
    # A corrected second envelope is not read: the whole reply is invalid JSON.
    (json.dumps({"verdicts": []}) + "\n" + json.dumps({"verdicts": [{"index": 1, "faithful": True, "links": [
        {"id": "L1", "entailed": True}]}, {"index": 2, "faithful": True, "links": []}]}), [False, False]),
    (None, [False, False]),
])
def test_partial_misordered_or_malformed_verdicts_keep_their_originals(opportunity, monkeypatch, path, review,
                                                                       expected):
    body, reviews = post_tailor(opportunity, monkeypatch, path, TWO, review, anchors=TWO_ANCHORS)
    assert len(reviews) == 1 and len(reviews[0]["pairs"]) == 2
    shown = offered(path, body)
    assert [row["text"] in texts for (_, row), texts in zip(TWO, shown, strict=True)] == expected


def test_identical_lines_are_reviewed_and_shown_one_by_one(opportunity, monkeypatch):
    original, row = TWO[1]
    body, reviews = post_tailor(opportunity, monkeypatch, "/api/tailor", [(original, row), (original, row)],
                                review_by(lambda pair: pair["index"] == 1), anchors=[ANY_ANCHOR])
    assert len(reviews[0]["pairs"]) == 2
    assert [bool(texts) for texts in offered("/api/tailor", body)] == [True, False]


@pytest.mark.parametrize("path", TAILOR_PATHS)
@pytest.mark.parametrize(("original", "rewrite"), [
    ("2023–2024 | 3.9/4.0", "2023–2024 年 | 3.9/4.0"),            # numbers and symbols only, Chinese added
    ("清洗了212份问卷数据，并完成了统计分析。", "Cleaned 212 questionnaires and completed the statistics."),
    ("Cleaned 212 survey responses in R.", "在 R 中清洗了 212 份问卷。"),
])
def test_a_line_rewritten_into_the_other_script_is_kept_unreviewed(opportunity, monkeypatch, path, original, rewrite):
    body, reviews = post_tailor(opportunity, monkeypatch, path, [(original, _rewrite(rewrite, [{"op": "verb_first"}]))],
                                ACCEPT_ALL, anchors=[ANY_ANCHOR])
    assert (offered(path, body), reviews) == ([[]], [])


def test_blank_and_whitespace_lines_never_reach_the_model(opportunity, monkeypatch):
    calls = []
    monkeypatch.setattr(tailor, "chat_completion", lambda *args, **kwargs: calls.append(args) or None)
    monkeypatch.setattr(em, "chat_completion", lambda *args, **kwargs: calls.append(args) or None)
    client = TestClient(app)
    body = client.post("/api/tailor/bullet", json={"profile": PROFILE, "opportunity_id": opportunity,
                                                    "base_text": "", "current_text": "   "}).json()
    assert (body["text"], body["changed"], calls) == ("", False, [])
    body = client.post("/api/tailor", json={"profile": PROFILE, "opportunity_id": opportunity,
                                            "original_bullets": ["", "  　 "]}).json()
    assert (body["tailored_bullets"], calls) == ([], [])


# ------------------------------------------------------- duplicated ids across sections

def test_a_renovation_with_a_shared_bullet_id_is_refused_before_any_model_call(opportunity, monkeypatch):
    """Outcomes are keyed by bullet id, so two bullets with one id could show each other's rewrite."""
    calls = []
    monkeypatch.setattr(tailor, "chat_completion", lambda *args, **kwargs: calls.append(args) or None)
    monkeypatch.setattr(em, "chat_completion", lambda *args, **kwargs: calls.append(args) or None)
    sections = [{"id": "s1", "heading": "Teaching", "kind": "experience",
                 "bullets": [{"id": "b1", "text": "Tutored 12 students in calculus each week."}]},
                {"id": "s2", "heading": "Research", "kind": "research",
                 "bullets": [{"id": "b 1", "text": VERB_FIRST_ORIGINAL}]}]   # "b 1" is "b1" once whitespace goes
    response = TestClient(app).post("/api/tailor/renovate", json={"profile": PROFILE, "opportunity_id": opportunity,
                                                                  "sections": sections})
    assert (response.status_code, calls) == (422, [])


# ------------------------------------------------------- kept lines carry no rewrite wording

@pytest.mark.parametrize("path", ALL_PATHS)
def test_a_rejected_rewrite_leaves_no_wording_in_the_response(opportunity, monkeypatch, path):
    if path == "full-target":
        body, reviews = post_full_target(monkeypatch, PLAIN_ORIGINAL, PLAIN_ROW, review_by(lambda pair: False),
                                         description=SWAPPED_ANCHOR)
        assert reviews and body["status"] == "unchanged" and offered(path, body) == [[]]
        links = body["suggestion"]["links"]
    else:
        body, reviews = post_tailor(opportunity, monkeypatch, path, [(PLAIN_ORIGINAL, PLAIN_ROW)],
                                    review_by(lambda pair: False), anchors=[SWAPPED_ANCHOR])
        assert reviews and offered(path, body) == [[]]
        if path.endswith("/renovate"):
            links = [link for section in body["sections"] for bullet in section["bullets"]
                     for variant in bullet["variants"] for link in variant["links"]]
        else:
            links = body["tailored_bullets"][0]["links"] if path == "/api/tailor" else body["links"]
    assert links or path.endswith("/renovate")
    # The posting's term itself stays as advice (target_evidence); only the refused wording goes.
    assert [link["written_as"] for link in links if link["written_as"]] == []


@pytest.mark.parametrize("path", ["/api/tailor", "/api/tailor/bullet", "full-target"])
def test_an_accepted_rewrite_still_says_how_it_wrote_the_term(opportunity, monkeypatch, path):
    if path == "full-target":
        body, _ = post_full_target(monkeypatch, PLAIN_ORIGINAL, PLAIN_ROW, ACCEPT_ALL, description=SWAPPED_ANCHOR)
        links = body["suggestion"]["links"]
    else:
        body, _ = post_tailor(opportunity, monkeypatch, path, [(PLAIN_ORIGINAL, PLAIN_ROW)], ACCEPT_ALL,
                              anchors=[SWAPPED_ANCHOR])
        links = body["tailored_bullets"][0]["links"] if path == "/api/tailor" else body["links"]
    assert [link["written_as"] for link in links] == ["Python code"]


# ------------------------------------------------------- more fallbacks that hold

@pytest.mark.parametrize(("review", "status", "code"), [
    (None, "skipped", "rewrite_unchecked"),
    ("not json", "unchanged", "review_rejected"),
    (json.dumps({"verdicts": [{"index": 1, "faithful": True, "links": []}]}), "unchanged", "review_rejected"),
    (json.dumps({"verdicts": [{"index": 1, "faithful": True, "links": [{"id": "L1", "entailed": True}]},
                              {"index": 1, "faithful": False, "links": [{"id": "L1", "entailed": True}]}]}),
     "unchanged", "review_rejected"),
])
def test_full_target_shows_nothing_without_a_faithful_verdict(monkeypatch, review, status, code):
    receipt, reviews = post_full_target(monkeypatch, PLAIN_ORIGINAL, PLAIN_ROW, review, description=SWAPPED_ANCHOR)
    assert len(reviews) == 1
    assert (receipt["status"], receipt["reason_code"]) == (status, code)
    assert offered("full-target", receipt) == [[]]


def test_an_empty_renovation_bullet_gets_no_rewrite(opportunity, monkeypatch):
    sections = [{"id": "s1", "heading": "Projects", "kind": "projects", "bullets": [{"id": "b0", "text": ""}]}]
    body, reviews = post_tailor(opportunity, monkeypatch, "/api/tailor/renovate",
                                [("", _rewrite("搭建了实验平台。", [{"op": "verb_first"}]))], ACCEPT_ALL,
                                anchors=[ANY_ANCHOR], sections=sections)
    assert (offered("/api/tailor/renovate", body), reviews) == ([[]], [])


@pytest.mark.parametrize("path", TAILOR_PATHS)
def test_full_width_punctuation_keeps_a_chinese_rewrite_chinese_and_reviewed(opportunity, monkeypatch, path):
    original, rewrite = "与两名同学搭建了气象站；本人编写了数据采集程序。", "本人编写了数据采集程序。与两名同学搭建了气象站。"
    row = _rewrite(rewrite, [{"op": "personal_first"}])
    body, reviews = post_tailor(opportunity, monkeypatch, path, [(original, row)], review_by(lambda pair: False),
                                anchors=[ANY_ANCHOR], locale="en")
    assert len(reviews) == 1 and offered(path, body) == [[]]
    body, reviews = post_tailor(opportunity, monkeypatch, path, [(original, row)], ACCEPT_ALL, anchors=[ANY_ANCHOR])
    assert offered(path, body) == [[rewrite]] and em.language(rewrite) == em.language(original) == "zh"


# ------------------------------------------------------- a verdict that contradicts itself

# A non-empty "problem" beside faithful=true and "[ok]" tags is not read as a rejection: that shape goes to the
# review's calibration set (docs/resume_writing_quality_contract.md, "Frozen lists"), not into a parsing rule.
@pytest.mark.parametrize(("changes", "problem"), [
    ("dropped 约 [3]", ""), ("dropped 约 【3】", ""), ("dropped 约 ［３］", ""), ("dropped 约 [３]", ""),
    ("删除了“约”［规则3］", ""), ("dropped 约 [rule 3]", ""),
])
def test_a_faithful_verdict_that_names_a_broken_rule_is_not_accepted(monkeypatch, changes, problem):
    """ASCII "[3]" beside faithful=true rejects; so does the same tag in full-width form or 【】 brackets."""
    reply = json.dumps({"verdicts": [{"index": 1, "changes": changes, "faithful": True, "links": [],
                                      "problem": problem}]}, ensure_ascii=False)
    monkeypatch.setattr(em, "chat_completion", lambda messages, **kwargs: reply)
    monkeypatch.setattr(em, "model_for", lambda *args: {})
    assert em.ai_review([em.ReviewPair("约 200 份问卷，本人只负责录入。", "录入了 200 份问卷。")]) == ["rejected"]


def test_a_faithful_verdict_with_ok_tags_and_numbers_is_accepted(monkeypatch):
    reply = json.dumps({"verdicts": [{"index": 1, "changes": "reordered 200 份 [ok]; 【ok】 kept 约", "faithful": True,
                                      "links": [], "problem": ""}]}, ensure_ascii=False)
    monkeypatch.setattr(em, "chat_completion", lambda messages, **kwargs: reply)
    monkeypatch.setattr(em, "model_for", lambda *args: {})
    assert em.ai_review([em.ReviewPair("约 200 份问卷，本人只负责录入。", "本人只负责录入约 200 份问卷。")]) == ["accepted"]


# ------------------------------------------------------- a model answer nested past the recursion limit

DEEP = "[" * 2000


@pytest.mark.parametrize("path", TAILOR_PATHS)
def test_an_answer_nested_past_the_recursion_limit_keeps_the_originals(opportunity, monkeypatch, path):
    """json.loads raises RecursionError, not ValueError, and the routes answered 500 (round-1 CPU review)."""
    body, reviews = post_tailor(opportunity, monkeypatch, path, [(PLAIN_ORIGINAL, PLAIN_ROW)],
                                lambda payload: '{"verdicts":' + DEEP, anchors=[SWAPPED_ANCHOR])
    assert offered(path, body) == [[]]
    original_model = tailor.chat_completion

    def deep_generation(messages, **kwargs):
        if messages[0]["content"].startswith("FAITHFULNESS REVIEW") or "REORGANIZE" in messages[0]["content"]:
            return original_model(messages, **kwargs)
        return '{"bullets":' + DEEP
    monkeypatch.setattr(tailor, "chat_completion", deep_generation)
    payload = {"profile": PROFILE, "opportunity_id": opportunity, "locale": "en"}
    if path.endswith("/renovate"):
        payload["sections"] = [{"id": "s1", "heading": "Projects", "kind": "projects",
                                "bullets": [{"id": "b0", "text": PLAIN_ORIGINAL}]}]
    elif path.endswith("/bullet"):
        payload.update(base_text=PLAIN_ORIGINAL, current_text=PLAIN_ORIGINAL)
    else:
        payload["original_bullets"] = [PLAIN_ORIGINAL]
    response = TestClient(app).post(path, json=payload)
    assert response.status_code == 200 and offered(path, response.json()) == [[]]


def test_a_full_target_answer_nested_past_the_recursion_limit_is_an_invalid_response(monkeypatch):
    receipt, reviews = post_full_target(monkeypatch, PLAIN_ORIGINAL, PLAIN_ROW, '{"verdicts":' + DEEP,
                                        description=SWAPPED_ANCHOR)
    assert (receipt["status"], receipt["reason_code"]) == ("unchanged", "review_rejected")
    units = units_for(full_target.make_doc(PLAIN_ORIGINAL))[0]
    receipts, pending = target_resume_ai.parse_output('{"units":' + DEEP, units, [])
    assert pending == [] and {receipt["reason_code"] for receipt in receipts} == {"invalid_model_response"}
