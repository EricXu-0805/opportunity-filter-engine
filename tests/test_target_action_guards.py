"""Every target action refuses a non-actionable record, before it spends.

These are mutant-killing tests, not smoke tests. Asserting only "the response
was not 200" would survive a guard that runs *after* the provider call, the
usage write, or the auth lookup — which is exactly the bug worth preventing,
because the refusal is free but the work behind it is not. So every collaborator
that costs money, touches a user's account, or reaches the network is replaced
with something that raises on contact, and the assertion is that none of them
were ever contacted.

Three record shapes are exercised everywhere, because they fail closed for three
different reasons and a guard can easily catch one and miss the others:

  * ``closed_active``    — the live shape of the 861 URAP rows: a stated closure
                           sitting next to ``metadata.is_active = True``.
  * ``reference_only``   — published as reference material, never a listing.
  * ``inactive``         — the plain deactivated record that predates all this.
"""

from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import backend.routes.cold_email as cold_email_module
import backend.routes.matches as matches_module
import backend.routes.opportunities as opportunities_module
import backend.routes.tailor as tailor_module
from backend.main import app

client = TestClient(app)

OPPORTUNITY_ID = "target-guard-subject"

PROFILE = {
    "name": "Eric",
    "year": "sophomore",
    "major": "Computer Engineering",
    "school": "UIUC",
    "hard_skills": ["Python"],
    "research_interests_text": "machine learning",
}


def _record(**metadata) -> dict:
    return {
        "id": OPPORTUNITY_ID,
        "source": "ucb_urap_projects",
        "source_type": "ucb_program",
        "title": "Past URAP project",
        "organization": "University of California, Berkeley",
        "description_raw": "A research project.",
        "description_clean": "A research project.",
        "keywords": ["HPC"],
        "url": "https://urapprojects.berkeley.edu/detail.php?id=1",
        "source_url": "https://urapprojects.berkeley.edu/detail.php?id=1",
        "eligibility": {},
        "application": {"application_url": "https://research.berkeley.edu/urap/application/"},
        "metadata": metadata,
    }


def _faculty_record(description: str) -> dict:
    """A faculty profile whose own text states an availability constraint.

    ``source_type`` must be ``faculty_research``: that is what marks a row as a
    profile rather than a posting, and the availability scan is deliberately
    scoped to profiles.
    """
    record = _record()
    record["source_type"] = "faculty_research"
    record["title"] = "Prof. Alex Rivera"
    record["description_raw"] = description
    record["description_clean"] = description
    return record


def _unreviewed_record() -> dict:
    """A live-looking record whose ``source_type`` nobody has classified."""
    record = _record(is_active=True)
    record.pop("source_type", None)
    record["paid"] = "yes"
    record["on_campus"] = True
    record["deadline"] = "2099-12-31"
    return record


NON_ACTIONABLE = {
    "closed_active": _record(urap_status="closed", is_active=True),
    "reference_only": _record(reference_only=True, is_active=True),
    "inactive": _record(is_active=False),
    "faculty_not_accepting": _faculty_record(
        "I am not currently accepting undergraduate students.",
    ),
    # Nobody has reviewed what this is. Every offer-shaped field is populated
    # and poisonous; the truth is the only thing that stops an action.
    "record_kind_unverified": _unreviewed_record(),
}
SHAPES = list(NON_ACTIONABLE)

# States something adjacent and weaker: no active research right now. It is NOT
# a refusal — a student may still write a careful question — so it belongs in
# the actionable set, and any change that folds it in with the four above is
# rewriting one person's claim as another's.
RESEARCH_INACTIVE = _faculty_record(
    "Prof. Rivera is not currently conducting research.",
)


class Tripwire:
    """A stand-in that fails the test if anything ever calls it."""

    def __init__(self, label: str):
        self.label = label
        self.calls = 0

    def __call__(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError(f"{self.label} ran despite a non-actionable target")


@pytest.fixture
def tripwires(monkeypatch):
    """Forbid every paid, persistent, networked or account-touching step."""
    wires: dict[str, Tripwire] = {}

    def forbid(module, attribute):
        key = f"{module.__name__}.{attribute}"
        wire = Tripwire(key)
        monkeypatch.setattr(module, attribute, wire, raising=False)
        wires[key] = wire

    for module in (cold_email_module, tailor_module, opportunities_module, matches_module):
        for attribute in (
            "chat_completion",       # the provider itself
            "run_blocking",          # every worker-thread hop into paid work
            "authenticated_uid",     # account lookup over the network
        ):
            if hasattr(module, attribute):
                forbid(module, attribute)

    forbid(cold_email_module, "_run_engine")
    forbid(cold_email_module, "generate_variants")
    forbid(cold_email_module, "_assert_outreach_allowed")
    forbid(tailor_module, "_schedule_usage")
    forbid(opportunities_module, "_build_chat_system_prompt")
    forbid(matches_module, "_get_or_compute_snapshot")
    forbid(matches_module, "analyze_gaps")
    return wires


@pytest.fixture
def served(monkeypatch):
    """Serve one chosen record from every route module's corpus lookup."""

    def _serve(record: dict) -> None:
        for module in (
            cold_email_module,
            tailor_module,
            opportunities_module,
            matches_module,
        ):
            monkeypatch.setattr(
                module,
                "load_opportunities_by_id",
                lambda record=record: {OPPORTUNITY_ID: record},
                raising=False,
            )

    return _serve


_EXPECTED_REASON = {
    "closed_active": "listing_closed",
    "reference_only": "reference_only",
    "inactive": "inactive",
    "faculty_not_accepting": "faculty_not_accepting",
    "record_kind_unverified": "record_kind_unverified",
}


def _assert_refusal(response, shape: str) -> None:
    assert response.status_code == 409, f"{shape}: expected 409, got {response.status_code}"
    detail = response.json()["detail"]
    assert detail["code"] == "TARGET_NOT_ACTIONABLE"
    assert detail["retryable"] is False
    # Pinned per shape, not merely "one of the valid reasons". A guard that
    # reported every refusal as `listing_closed` would pass a membership check
    # while telling a student a professor's profile was a closed posting.
    assert detail["reason"] == _EXPECTED_REASON[shape.split("/")[-1]]
    assert isinstance(detail["message"], str) and detail["message"]


ACTIONS = [
    ("tailor", "/api/tailor", {
        "opportunity_id": OPPORTUNITY_ID,
        "profile": PROFILE,
        "original_bullets": ["Built a Python prototype"],
    }),
    ("renovate", "/api/tailor/renovate", {
        "opportunity_id": OPPORTUNITY_ID,
        "profile": PROFILE,
        "sections": [{
            "id": "experience",
            "heading": "Experience",
            "kind": "experience",
            "bullets": [{"id": "b1", "text": "Built a Python prototype"}],
        }],
    }),
    ("optimize_bullet", "/api/tailor/bullet", {
        "opportunity_id": OPPORTUNITY_ID,
        "profile": PROFILE,
        "current_text": "Built a Python prototype",
    }),
    ("cold_email", "/api/cold-email", {
        "opportunity_id": OPPORTUNITY_ID,
        "profile": PROFILE,
    }),
    ("cold_email_stream", "/api/cold-email/stream", {
        "opportunity_id": OPPORTUNITY_ID,
        "profile": PROFILE,
    }),
    ("cold_email_variants", "/api/cold-email/variants", {
        "opportunity_id": OPPORTUNITY_ID,
        "profile": PROFILE,
    }),
    ("cold_email_refine", "/api/cold-email/refine", {
        "opportunity_id": OPPORTUNITY_ID,
        "current_body": "Dear Professor,\nHello.\nBest,\nEric",
        "instruction": "make it formal",
        "profile": PROFILE,
    }),
    ("ask_ai", f"/api/opportunities/{OPPORTUNITY_ID}/chat", {
        "message": "Should I apply?",
        "profile": PROFILE,
    }),
    ("ask_ai_sse", f"/api/opportunities/{OPPORTUNITY_ID}/chat?stream=1", {
        "message": "Should I apply?",
        "profile": PROFILE,
    }),
    ("match_gaps", f"/api/matches/{OPPORTUNITY_ID}/gaps", PROFILE),
    ("match_explain", f"/api/matches/{OPPORTUNITY_ID}/explain", PROFILE),
    ("match_explain_llm", f"/api/matches/{OPPORTUNITY_ID}/explain?llm=true", PROFILE),
]


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize(("action", "path", "payload"), ACTIONS, ids=[a[0] for a in ACTIONS])
def test_action_refuses_non_actionable_target_before_spending(
    shape, action, path, payload, served, tripwires,
):
    served(NON_ACTIONABLE[shape])
    response = client.post(path, json=payload)
    _assert_refusal(response, f"{action}/{shape}")
    spent = {name: wire.calls for name, wire in tripwires.items() if wire.calls}
    assert not spent, f"{action}/{shape} touched forbidden collaborators: {spent}"


@pytest.mark.parametrize("shape", SHAPES)
def test_sse_refuses_before_returning_a_generator(shape, served, tripwires):
    """A stream must be refused at the handler, not inside the generator.

    Once StreamingResponse is returned the status line is already 200 and the
    client is committed; a refusal raised inside the generator body arrives as
    a broken stream, after the work has begun.
    """
    served(NON_ACTIONABLE[shape])
    response = client.post(
        "/api/cold-email/stream",
        json={"opportunity_id": OPPORTUNITY_ID, "profile": PROFILE},
    )
    _assert_refusal(response, f"sse/{shape}")
    assert "text/event-stream" not in response.headers.get("content-type", "")


class TestHistoricalDetailRevealsNoContact:
    """A closed listing stays readable. Its contact does not.

    Revealing an address is an action: it ends in a mailto, and for a
    signed-out visitor it exists to justify a sign-in prompt. The status is
    reported as `unavailable` and the auth lookup — a network call — never
    runs, so a historical record costs nothing to render.
    """

    @pytest.fixture
    def served_detail(self, monkeypatch):
        auth_calls: list[str] = []

        async def tripwire_auth(*_args, **_kwargs):
            auth_calls.append("auth")
            raise AssertionError("the auth lookup ran for a non-actionable target")

        def tripwire_status(*_args, **_kwargs):
            auth_calls.append("contact_email_status")
            raise AssertionError(
                "contact visibility was computed for a non-actionable target",
            )

        monkeypatch.setattr(opportunities_module, "authenticated_uid", tripwire_auth)
        # Both, not just auth. Computing the status first and *then* discarding
        # it still reads the address into a local and leaves the reveal one
        # edit away from being serialized; the guard has to come first, and
        # only tripwiring the collaborator downstream of it proves that.
        monkeypatch.setattr(
            opportunities_module, "contact_email_status", tripwire_status,
        )

        def _serve(record: dict):
            monkeypatch.setattr(
                opportunities_module,
                "load_opportunities_by_id",
                lambda: {record["id"]: record},
            )
            # The rollout bridge refuses historical detail to a client that has
            # not proven it can read a target truth, so this class now asks as
            # the current frontend does. Everything it asserts — readable,
            # `unavailable`, no address, no auth/contact call — is unchanged;
            # only the caller's declared capability is.
            return client.get(
                f"/api/opportunities/{record['id']}",
                params={
                    "_release_scope":
                        "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2",
                },
            )

        _serve.auth_calls = auth_calls
        return _serve

    @pytest.mark.parametrize("shape", SHAPES)
    def test_a_non_actionable_detail_reports_unavailable(self, shape, served_detail):
        record = dict(NON_ACTIONABLE[shape])
        record["contact_email"] = "pi@example.edu"
        response = served_detail(record)

        assert response.status_code == 200, "the record stays readable"
        body = response.json()
        assert body["contact_email_status"] == "unavailable"
        assert "contact_email" not in body
        assert "pi@example.edu" not in response.text
        assert served_detail.auth_calls == []

    EVIDENCE_KEYS = (
        "is_active", "urap_status", "listing_status", "reference_only",
        "last_verified", "expires_at",
        # Written by the availability neutralizer onto every scanned faculty
        # row. They are how the answer was reached, not the answer.
        "faculty_availability_status", "faculty_availability_scan_version",
        "faculty_not_accepting_undergraduates_stated",
        "faculty_research_inactive_stated",
    )
    TRUTH_KEYS = {
        "listing_state", "reference_only", "actionable", "accepting_state",
        "reason_code", "verified_at", "expires_at",
    }

    @pytest.mark.parametrize("shape", SHAPES)
    def test_the_evidence_keys_are_not_served(self, shape, served_detail):
        record = dict(NON_ACTIONABLE[shape])
        record["metadata"] = {
            **record["metadata"],
            "last_verified": "2026-07-21T08:18:35",
            "notes": "an unrelated field that must survive",
        }
        body = served_detail(record).json()
        metadata = body.get("metadata") or {}

        for key in self.EVIDENCE_KEYS:
            assert key not in metadata, key
        # Stripping is targeted, not a blanket wipe.
        assert metadata["notes"] == "an unrelated field that must survive"
        # The decision is served in their place, and the timestamp with it.
        assert body["target_truth"]["actionable"] is False
        assert body["target_truth"]["verified_at"] == "2026-07-21T08:18:35"

    def test_a_neutralized_faculty_row_leaks_none_of_its_markers(self, served_detail):
        """The shape the availability neutralizer actually writes.

        The parametrized test above seeds only listing evidence, so it would
        pass whether or not these four keys were stripped. This one carries
        them, which is the only way the assertion means anything.
        """
        record = dict(NON_ACTIONABLE["faculty_not_accepting"])
        record["faculty_availability_status"] = "not_accepting_undergraduates"
        record["metadata"] = {
            "faculty_availability_status": "not_accepting_undergraduates",
            "faculty_availability_scan_version": 1,
            "faculty_not_accepting_undergraduates_stated": True,
            "faculty_research_inactive_stated": False,
            "research_areas_raw": "entomology, pollinator ecology",
        }
        before = deepcopy(record)
        body = served_detail(record).json()
        metadata = body.get("metadata") or {}

        for key in self.EVIDENCE_KEYS:
            assert key not in metadata, key
        assert metadata["research_areas_raw"] == "entomology, pollinator ecology"
        # The top-level field is a deliberate part of the payload — the UI
        # renders its own banner from it — and must survive the strip.
        assert body["faculty_availability_status"] == "not_accepting_undergraduates"
        assert set(body["target_truth"]) == self.TRUTH_KEYS
        assert body["target_truth"]["reason_code"] == "faculty_not_accepting"
        assert body["target_truth"]["actionable"] is False
        assert body["target_truth"]["accepting_state"] == "not_accepting"
        # Copy-on-write: stripping a shared corpus row in place would delete
        # the evidence the next request needs to reach the same verdict.
        assert record == before

    @pytest.mark.parametrize("shape", SHAPES)
    def test_the_truth_envelope_is_exactly_seven_keys(self, shape, served_detail):
        """No internal evidence pointers ride along inside the envelope."""
        body = served_detail(dict(NON_ACTIONABLE[shape])).json()
        assert set(body["target_truth"]) == self.TRUTH_KEYS

    def test_the_batch_endpoint_carries_the_same_envelope(self, monkeypatch):
        record = dict(NON_ACTIONABLE["closed_active"])
        monkeypatch.setattr(
            opportunities_module,
            "load_opportunities",
            lambda: [record],
        )
        monkeypatch.setattr(
            opportunities_module,
            "load_opportunities_by_id",
            lambda: {record["id"]: record},
        )
        response = client.post("/api/opportunities/batch", json={"ids": [OPPORTUNITY_ID]})

        assert response.status_code == 200
        item = response.json()["opportunities"][0]
        assert set(item["target_truth"]) == self.TRUTH_KEYS
        for key in self.EVIDENCE_KEYS:
            assert key not in (item.get("metadata") or {}), key

    def test_the_shared_corpus_record_is_never_mutated(self, served_detail):
        record = dict(NON_ACTIONABLE["closed_active"])
        record["metadata"] = {**record["metadata"], "last_verified": "2026-07-21T08:18:35"}
        before = deepcopy(record)

        served_detail(record)

        # Copy-on-write: stripping happens on the payload, not on the object
        # the in-process corpus cache is still handing to every other reader.
        assert record == before


@pytest.mark.parametrize("missing", [None, "", "   "], ids=["null", "empty", "blank"])
def test_refine_without_a_target_is_rejected_before_any_lookup(
    missing, monkeypatch, tripwires,
):
    """No target, no refine — and the refusal costs nothing to produce."""
    lookups = Tripwire("load_opportunities_by_id")
    monkeypatch.setattr(cold_email_module, "load_opportunities_by_id", lookups)

    payload = {
        "current_body": "Dear Professor,\nHello.\nBest,\nEric",
        "instruction": "make it formal",
        "profile": PROFILE,
    }
    if missing is not None:
        payload["opportunity_id"] = missing

    response = client.post("/api/cold-email/refine", json=payload)

    assert response.status_code == 422
    assert lookups.calls == 0
    spent = {name: wire.calls for name, wire in tripwires.items() if wire.calls}
    assert not spent, f"refine/{missing!r} touched forbidden collaborators: {spent}"
