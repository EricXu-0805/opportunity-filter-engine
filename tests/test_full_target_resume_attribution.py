"""Synthetic full-target API regressions with a local provider stub.

These test a bounded attribution gate, not model quality or source truth.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from backend.lib import evidence_map
from backend.lib import target_resume_ai as engine
from backend.lib.target_resume_ai_validation import confirmed_document, fingerprint, units_for
from backend.main import app
from backend.routes import target_resume_ai as route

PATH = "/api/tailor/full-target/suggestions"
TEAM = "My team built a Python parser. I wrote parser tests."
TEAM_BAD = "I built a Python parser and wrote parser tests. My team built a Python parser."
METRICS = "I improved parser throughput by 45% and reduced parser latency by 12%."
METRICS_BAD = "I improved parser throughput by 12% and reduced parser latency by 45%."
DENIAL = "I built a Python parser. I did not build the compiler."
DENIAL_BAD = "I built a compiler. I did not build the compiler."
BAD = [
    pytest.param(TEAM, TEAM_BAD, id="team-personal"),
    pytest.param(TEAM, "Built a Python parser and wrote parser tests. My team built a Python parser.", id="team-fragment"),
    pytest.param(METRICS, METRICS_BAD, id="metric-personal"),
    pytest.param(METRICS, "Improved parser throughput by 12% and reduced parser latency by 45%.", id="metric-fragment"),
    pytest.param(DENIAL, DENIAL_BAD, id="denial-personal"),
    pytest.param(DENIAL, "Built a compiler. I did not build the compiler.", id="denial-fragment"),
]
GOOD = [
    pytest.param("I wrote parser tests using Python.", "I wrote parser tests.", id="personal-shortening"),
    pytest.param(TEAM, "I wrote parser tests. My team built a Python parser.", id="team-preserved"),
    pytest.param("Built a Python parser using NumPy.", "Built a Python parser.", id="personal-fragment"),
    pytest.param("I wrote parser tests.", "Wrote parser tests.", id="omit-personal-subject"),
    pytest.param("I improved throughput by 45% using Python.", "I improved throughput by 45 percent.", id="percent-format"),
    pytest.param("I analyzed 10000 samples using Python.", "I analyzed 10,000 samples.", id="thousands-format"),
    pytest.param("I improved throughput by 4.5 times.", "I improved throughput by 4.5x.", id="times-format"),
    pytest.param("I did not lead the project. Reviewed documents.", "Reviewed documents. I did not lead the project.", id="negative-preserved"),
    pytest.param("团队开发了工具。本人负责审阅文档。", "本人负责审阅文档。团队开发了工具。", id="zh-role-preserved"),
    pytest.param("论文已投稿，尚未录用。", "论文已投稿，尚未录用。", id="zh-publication-unchanged"),
]


def _fact(ident, value):
    return {"id": ident, "revision": 1, "status": "confirmed", "value": value, "source": {"kind": "manual"}}


def _document(originals, opportunity):
    raw = "\n".join(originals)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    entries, activities = [], []
    start = 0
    for index, original in enumerate(originals):
        ident = f"exp-{index}"
        entries.append({"id": ident, "revision": 1, "status": "confirmed", "text": original,
                        "source": {"kind": "resume", "signature": digest, "quote": original,
                                   "start": start, "end": start + len(original)}})
        activities.append({"id": f"project-{index}", "kind": "project",
                           "title": _fact(f"title-{index}", f"Research project {index}"),
                           "details": [{"id": ident, "revision": 1}]})
        start += len(original) + 1
    master = {"version": 1, "id": "master", "revision": 1, "source_signature": digest,
              "basics": {"name": _fact("name", "Fixture Student"), "links": []},
              "education": [], "activities": activities, "publications": [], "skills": [], "other_sections": [],
              "section_order": ["basics", "education", "activities", "publications", "skills"], "unmapped_ranges": []}
    snapshot = {"resume_text": raw, "experience_entries": entries, "resume_master": master}
    target = route.authoritative_target(opportunity)
    document = confirmed_document(snapshot, digest)
    for section in document["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for line in block["lines"]:
                line.update(text=line["original"], included=True)
    return {"kind": "full_resume", "version": 1, "id": "full-draft", "opportunity_id": opportunity["id"],
            "base": {"master_id": "master", "master_revision": 1, "source_signature": digest,
                     "profile_signature": "v1:sha256:" + "a" * 64, "target_signature": fingerprint(target)},
            "base_snapshot": snapshot, "target_snapshot": target,
            "document": document}


# Moves the evidence-map contract admits, tried in order for each proposal.
CANDIDATE_OPS = ([{"op": "personal_first"}], [{"op": "verb_first"}], [{"op": "personal_first"}, {"op": "verb_first"}])


@dataclass
class Endpoint:
    client: TestClient
    opportunity: dict
    calls: list = field(default_factory=list)
    reviews: list = field(default_factory=list)
    proposed: dict = field(default_factory=dict)
    wrong_quote: bool = False
    locale: str = "en"

    def _row(self, unit, anchors):
        """A v6 row: keep with a Python link, or the proposal with operations the contract admits when any do."""
        term = "Pyth" if self.wrong_quote else "Python"
        links = [{"id": "L1", "anchor": "t2", "term": term, "source": "Python", "relation": "same"}] \
            if "Python" in unit["original"] else []
        base = {"unit_id": unit["unit_id"], "priority": "high", "reason": "method_relevance", "links": links}
        proposal = self.proposed.get(unit["unit_id"])
        if proposal is None:
            return {**base, "decision": "keep", "ops": [], "text": None, "keep_reason": "no_link"}
        em_unit = evidence_map.Unit(unit["unit_id"], unit["original"], unit["original"], keyed=True)
        rows = [{**base, "decision": "rewrite", "ops": ops, "text": proposal, "keep_reason": None}
                for ops in CANDIDATE_OPS]
        by_id = {anchor.id: anchor for anchor in anchors}
        return next((row for row in rows if evidence_map.check_rewrite(
            em_unit, row, by_id, output_language=self.locale, extra_keys=("priority", "reason")).status == "pending"),
            rows[0])

    def model(self, messages, **kwargs):
        self.calls.append((deepcopy(messages), deepcopy(kwargs)))
        units = json.loads(messages[1]["content"])["units"]
        anchors = evidence_map.target_anchors(route.authoritative_target(self.opportunity))
        return json.dumps({"units": [self._row(unit, anchors) for unit in units]})

    def review(self, pairs, deadline=None):
        self.reviews.append([(pair.original, pair.rewrite) for pair in pairs])
        return ["accepted"] * len(pairs)

    def submit(self, doc, proposals, *, include_facts=False):
        units, _ = units_for(doc)
        selected = units if include_facts else [unit for unit in units if unit["evidence"]["kind"] == "experience"]
        self.proposed = {unit["unit_id"]: proposals.get(unit["evidence"]["id"]) for unit in selected}
        before = deepcopy(doc)
        response = self.client.post(PATH, json={"version": 1, "request_id": "attribution-fixture", "locale": self.locale,
                                               "draft": doc, "document_signature": fingerprint(doc),
                                               "selected_unit_ids": [unit["unit_id"] for unit in selected]})
        assert doc == before
        assert "private" in response.headers["cache-control"] and "no-store" in response.headers["cache-control"]
        return response


@pytest.fixture
def endpoint(monkeypatch):
    opportunity = {"id": "full-attribution-target", "title": "Research Tools", "organization": "Example Lab",
                   "source_url": "https://example.edu/lab", "description_clean": "Research Python parsers.",
                   "eligibility": {"skills_required": ["Python"]}, "source_type": "campus_program",
                   "opportunity_type": "research", "metadata": {"is_active": True}}
    result = Endpoint(TestClient(app), opportunity)
    monkeypatch.setattr(route, "load_opportunities_by_id", lambda: {opportunity["id"]: opportunity})
    monkeypatch.setattr(route, "is_configured", lambda: True)
    monkeypatch.setattr(engine.llm_budget, "exhausted", lambda: False)
    monkeypatch.setattr(engine, "chat_completion", result.model)
    monkeypatch.setattr(evidence_map, "ai_review", result.review)
    return result


def _receipts(response, endpoint, doc):
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(endpoint.calls) == 1  # One mocked dispatch, no automatic rejection retry.
    # One generation call, plus the review when a rewrite reached it.
    assert result["logical_calls"] == 1 + bool(endpoint.reviews)
    assert result["document_signature"] == fingerprint(doc)
    assert result["base"] == doc["base"] and result["opportunity_id"] == doc["opportunity_id"]
    return result, {row["evidence"]["id"]: row for row in result["receipts"]}


def _rejected(row, before_text, endpoint):
    """Kept with its advice by the contract or a claim lock, never shown, never reviewed."""
    assert row["status"] == "unchanged", row
    assert row["reason_code"] in ("beyond_allowed_edit", "rewrite_rejected")
    assert row["suggestion"]["proposed_text"] is None and row["before_text"] == before_text
    assert all(before_text not in original for batch in endpoint.reviews for original, _ in batch)


@pytest.mark.parametrize("original,proposed", BAD)
def test_three_attribution_failures_are_refused_through_real_route(endpoint, original, proposed):
    doc = _document([original], endpoint.opportunity)
    result, rows = _receipts(endpoint.submit(doc, {"exp-0": proposed}), endpoint, doc)
    _rejected(rows["exp-0"], original, endpoint)
    assert result["method"] == "ai" and endpoint.reviews == []


@pytest.mark.parametrize("original,proposed", GOOD)
def test_supported_roles_fragments_and_number_formats_stay_usable(endpoint, original, proposed):
    """A faithful edit is reviewed and suggested, or kept because the contract offers
    no such move (a trim, a reformat); it is never refused as a fabrication."""
    doc = _document([original], endpoint.opportunity)
    result, rows = _receipts(endpoint.submit(doc, {"exp-0": proposed}), endpoint, doc)
    row = rows["exp-0"]
    if row["status"] == "suggested":
        assert row["suggestion"]["proposed_text"] == proposed and endpoint.reviews == [[(original, proposed)]]
    else:
        assert row["status"] == "unchanged" and row["reason_code"] in ("beyond_allowed_edit", "cosmetic_only")
        assert row["suggestion"]["proposed_text"] is None
    assert row["before_text"] == original and result["method"] == "ai"


@pytest.mark.parametrize("original,proposed,locale", [(*GOOD[1].values, "en"), (*GOOD[8].values, "zh")])
def test_an_own_part_first_reorder_is_reviewed_and_suggested(endpoint, original, proposed, locale):
    """The output language follows the UI locale, so the Chinese reorder is asked for in Chinese."""
    endpoint.locale = locale
    doc = _document([original], endpoint.opportunity)
    _, rows = _receipts(endpoint.submit(doc, {"exp-0": proposed}), endpoint, doc)
    assert rows["exp-0"]["status"] == "suggested" and rows["exp-0"]["suggestion"]["ops"] == ["personal_first"]


def test_mixed_batch_keeps_valid_suggestion_and_every_original_without_retry(endpoint):
    originals = [TEAM, METRICS, DENIAL, "I wrote parser tests using Python."]
    doc = _document(originals, endpoint.opportunity)
    # Failure must preserve even the student's existing manual wording, not replace it with the original.
    manual = "My retained manual wording"
    for section in doc["document"]["sections"]:
        for block in section["blocks"]:
            for line in block["lines"]:
                if line["evidence"]["id"] == "exp-0":
                    line["text"] = manual
    result, rows = _receipts(endpoint.submit(doc, {"exp-0": TEAM_BAD, "exp-1": METRICS_BAD,
                                                  "exp-2": DENIAL_BAD, "exp-3": "I wrote parser tests."}), endpoint, doc)
    for index, expected in enumerate([manual, METRICS, DENIAL]):
        _rejected(rows[f"exp-{index}"], expected, endpoint)
    # Dropping "using Python" is a trim, which no route offers.
    assert rows["exp-3"]["status"] == "unchanged" and rows["exp-3"]["reason_code"] == "beyond_allowed_edit"
    assert result["method"] == "ai" and len(rows) == 4
    prompt = json.loads(endpoint.calls[0][0][1]["content"])
    assert [unit["original"] for unit in prompt["units"]] == originals
    assert manual not in endpoint.calls[0][0][1]["content"]


@pytest.mark.parametrize("first,second,borrowed", [
    pytest.param("I reduced parser latency by 12%.", "I reduced parser latency by 45%.",
                 "I reduced parser latency by 45%.", id="cross-entry-number"),
    pytest.param("I wrote parser tests.", "I built a Python parser.",
                 "I built a Python parser.", id="cross-entry-action"),
    pytest.param("Project A: I improved accuracy by 45%.", "Project B: I improved accuracy by 12%.",
                 "Project B: I improved accuracy by 45%.", id="cross-project-label"),
])
def test_other_selected_entries_cannot_authorize_this_units_claim(endpoint, first, second, borrowed):
    doc = _document([first, second], endpoint.opportunity)
    result, rows = _receipts(endpoint.submit(doc, {"exp-0": borrowed, "exp-1": second}), endpoint, doc)
    _rejected(rows["exp-0"], first, endpoint)
    assert rows["exp-1"]["status"] == "unchanged" and rows["exp-1"]["suggestion"] is not None
    assert result["method"] == "ai"


def test_long_experience_tail_is_checked_without_truncating_the_original(endpoint):
    prefix = "I wrote parser tests. " * 250
    original, proposed = prefix + METRICS, prefix + METRICS_BAD
    assert 5000 < len(original) < 6000
    doc = _document([original], endpoint.opportunity)
    _, rows = _receipts(endpoint.submit(doc, {"exp-0": proposed}), endpoint, doc)
    _rejected(rows["exp-0"], original, endpoint)
    assert json.loads(endpoint.calls[0][0][1]["content"])["units"][0]["original"] == original


@pytest.mark.parametrize("target_id,description", [
    ("parser-lab", "Our lab builds Python parsers."),
    ("research-lab", "I built a Python parser and wrote parser tests. Research Python tools."),
])
def test_different_target_texts_never_supply_personal_achievements(endpoint, target_id, description):
    endpoint.opportunity.update(id=target_id, description_clean=description)
    doc = _document([TEAM], endpoint.opportunity)
    _, rows = _receipts(endpoint.submit(doc, {"exp-0": TEAM_BAD}), endpoint, doc)
    _rejected(rows["exp-0"], TEAM, endpoint)


def test_protected_fact_rewrite_is_rejected_while_valid_experience_survives(endpoint):
    doc = _document([TEAM], endpoint.opportunity)
    result, rows = _receipts(endpoint.submit(doc, {"title-0": "Invented supervisor title",
                                                  "exp-0": "I wrote parser tests. My team built a Python parser."},
                                                  include_facts=True), endpoint, doc)
    assert rows["title-0"]["status"] == "skipped" and rows["title-0"]["reason_code"] == "invalid_model_response"
    assert rows["title-0"]["suggestion"] is None and rows["title-0"]["before_text"] == "Research project 0"
    assert rows["exp-0"]["status"] == "suggested" and result["method"] == "partial"
    assert result["manifest"]["protected_unit_count"] == 1
    assert "Fixture Student" not in endpoint.calls[0][0][1]["content"]


def test_a_link_to_text_the_target_does_not_have_is_dropped(endpoint):
    doc = _document(["I wrote parser tests using Python."], endpoint.opportunity)
    endpoint.wrong_quote = True
    _, rows = _receipts(endpoint.submit(doc, {}), endpoint, doc)
    suggestion = rows["exp-0"]["suggestion"]
    assert suggestion["links"] == [] and suggestion["target_evidence"] == []
    assert suggestion["priority"] == "normal"  # "high" needs a verified link


def test_target_changed_before_request_is_refused_without_provider(endpoint):
    doc = _document(["I wrote parser tests."], endpoint.opportunity)
    endpoint.opportunity["description_clean"] = "Different current target requirements"
    response = endpoint.submit(doc, {"exp-0": "Wrote parser tests."})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "target_changed"
    assert endpoint.calls == []
