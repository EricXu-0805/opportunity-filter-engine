"""Mailed digests describe the corpus, not the browser that asked for them.

A digest arrives in an inbox hours later, under our name, with no way for the
reader to check it. So the client sends ids; the server reads every describing
field from the canonical record at send time.

ROLLOUT BRIDGE: the request models still ACCEPT the legacy describing fields
(title/url/score/source/deadline/record_kind, and subject_hint) because the
frontend and backend deploy independently and the frontend usually lands
first — an old backend still needs them. The contract is that they are
accepted and then completely ignored, so several tests below mail a poisoned
value and assert it never reaches the message. When both sides are on the same
SHA, a follow-up PR drops them and these tests become "rejected" instead.

Every refusal must also be free: each rejection test asserts the recipient
quota was untouched and the provider was never called — a guard that runs
after the send has already cost the thing it was meant to prevent.
"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.main as main_mod
from backend import data_loader
from backend.lib.supabase_auth import SessionIdentity
from backend.main import app
from backend.routes import email as email_mod
from src.evidence import record_kind, target_truth

client = TestClient(app)


def _first(predicate) -> str:
    for opportunity in data_loader.load_opportunities():
        if predicate(opportunity):
            return opportunity["id"]
    raise AssertionError("the corpus no longer contains a record of this shape")


# Chosen by shape rather than hardcoded, so a data refresh cannot silently turn
# one of these into a different kind of record.
LISTING_ID = _first(
    lambda o: record_kind(o) == "listing" and target_truth(o).actionable,
)
FACULTY_ID = _first(
    lambda o: record_kind(o) == "faculty_contact" and target_truth(o).actionable,
)
UNKNOWN_KIND_ID = _first(lambda o: record_kind(o) == "unknown")
CLOSED_ID = "ucb-urap-proj-40703a6958e1"

POISON = {
    "title": "A LIE THE CLIENT MADE UP",
    "url": "https://evil.example/apply-here",
    "score": 99,
    "source": "fabricated_source",
    "deadline": "2099-12-31",
    "record_kind": "listing",
}


@pytest.fixture
def refused(monkeypatch):
    """A configured mailer whose provider raises if it is ever reached."""
    monkeypatch.setenv("RESEND_API_KEY", "fake")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")

    async def forbidden(**_kwargs):
        raise AssertionError("the provider was called for a refused digest")

    monkeypatch.setattr(email_mod, "_send_via_resend", forbidden)
    email_mod._recipient_sends.clear()


@pytest.fixture
def sent(monkeypatch):
    """A configured mailer that captures what would have been delivered."""
    monkeypatch.setenv("RESEND_API_KEY", "fake")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
    captured: dict = {}

    async def capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(email_mod, "_send_via_resend", capture)
    email_mod._recipient_sends.clear()
    return captured


def _quota_used(address: str = "reader@example.com") -> int:
    return len(email_mod._recipient_sends.get(address, []))


READER = "reader@example.com"


@pytest.fixture(autouse=True)
def signed_in_reader(monkeypatch):
    """Every digest test runs as a signed-in reader with a confirmed address.

    Autouse because the alternative is 40 tests that all fail on the sign-in
    check and stop exercising what they were written for. The tests that care
    about identity override this explicitly.
    """

    async def identity(_authorization):
        return SessionIdentity(uid="reader-uid", email=READER)

    monkeypatch.setattr(email_mod, "authenticated_identity", identity)


def _post(path: str, items: list[dict], **extra):
    return client.post(path, json={"email": READER, "items": items, **extra})


class TestRequestShape:
    def test_a_missing_opportunity_id_is_rejected(self, refused):
        response = _post("/api/email/send-matches", [{"title": "legacy only"}])
        assert response.status_code == 422
        assert _quota_used() == 0

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
    def test_a_blank_opportunity_id_is_rejected(self, blank, refused):
        response = _post("/api/email/send-matches", [{"opportunity_id": blank}])
        assert response.status_code == 422
        assert _quota_used() == 0

    def test_an_unrecognised_field_is_still_rejected(self, refused):
        """The bridge widens the contract for known legacy keys only."""
        response = _post(
            "/api/email/send-matches",
            [{"opportunity_id": LISTING_ID, "something_invented": "x"}],
        )
        assert response.status_code == 422
        assert _quota_used() == 0

    def test_an_oversized_id_is_rejected_before_any_lookup(self, refused):
        response = _post("/api/email/send-matches", [{"opportunity_id": "x" * 500}])
        assert response.status_code == 422
        assert _quota_used() == 0


class TestLegacyFieldsAreIgnoredNotTrusted:
    def test_a_poisoned_match_item_never_reaches_the_message(self, sent):
        response = _post(
            "/api/email/send-matches", [{"opportunity_id": LISTING_ID, **POISON}],
        )
        assert response.status_code == 200
        body = sent["html"] + sent["text"]
        for value in ("A LIE THE CLIENT MADE UP", "evil.example", "fabricated_source", "2099-12-31"):
            assert value not in body
        canonical = data_loader.load_opportunities_by_id()[LISTING_ID]
        assert str(canonical["title"]) in body

    def test_a_client_score_is_never_published_as_a_ranking(self, sent):
        response = _post(
            "/api/email/send-matches", [{"opportunity_id": LISTING_ID, "score": 99}],
        )
        assert response.status_code == 200
        assert "99%" not in sent["html"]
        assert "top" not in sent["subject"].lower()

    def test_rows_are_not_numbered_like_a_ranking(self, sent):
        """"#1" read as "best match". The order is just request order."""
        import re

        response = _post("/api/email/send-matches", [
            {"opportunity_id": LISTING_ID},
            {"opportunity_id": FACULTY_ID},
        ])
        assert response.status_code == 200
        # A rank marker, not any "#1" — hex colours like #111827 contain that
        # substring, and asserting on the substring alone passes for the wrong
        # reason once the palette changes.
        rank_marker = re.compile(r"(?:^|>|\s)#\d+(?:\s|<|$)")
        assert not rank_marker.search(sent["text"])
        assert not rank_marker.search(sent["html"])

    def test_the_favorites_summary_does_not_call_everything_a_listing(self, sent):
        response = _post("/api/email/send-favorites", [{"opportunity_id": FACULTY_ID}])
        assert response.status_code == 200
        assert "saved results" in sent["html"]
        assert "saved listings" not in sent["html"]

    def test_a_client_subject_hint_never_becomes_the_subject(self, sent):
        response = _post(
            "/api/email/send-matches",
            [{"opportunity_id": LISTING_ID}],
            subject_hint="YOUR TOP 1 GUARANTEED MATCHES",
        )
        assert response.status_code == 200
        assert "GUARANTEED" not in sent["subject"]

    def test_a_poisoned_favorite_item_never_reaches_the_message(self, sent):
        response = _post(
            "/api/email/send-favorites", [{"opportunity_id": LISTING_ID, **POISON}],
        )
        assert response.status_code == 200
        body = sent["html"] + sent["text"]
        assert "A LIE THE CLIENT MADE UP" not in body
        assert "evil.example" not in body
        assert "2099-12-31" not in body

    def test_the_users_own_notes_and_status_do_survive(self, sent):
        response = _post("/api/email/send-favorites", [{
            "opportunity_id": LISTING_ID,
            "notes": "emailed the PI in March",
            "status": "applied",
        }])
        assert response.status_code == 200
        assert "emailed the PI in March" in sent["html"]
        assert "applied" in sent["html"]


class TestMatchesRefuseTheWholeDigest:
    def test_an_unresolvable_id_refuses_before_the_quota(self, refused):
        response = _post("/api/email/send-matches", [
            {"opportunity_id": LISTING_ID},
            {"opportunity_id": "no-such-record-anywhere"},
        ])
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "TARGET_NOT_ACTIONABLE"
        assert _quota_used() == 0

    def test_one_closed_target_refuses_a_mixed_digest(self, refused):
        """Not a filter: a "top 10" that quietly mails nine is a worse lie."""
        response = _post("/api/email/send-matches", [
            {"opportunity_id": LISTING_ID},
            {"opportunity_id": CLOSED_ID},
        ])
        detail = response.json()["detail"]
        assert response.status_code == 409
        assert detail["code"] == "TARGET_NOT_ACTIONABLE"
        assert detail["reason"] == "listing_closed"
        assert detail["retryable"] is False
        assert _quota_used() == 0

    def test_the_closed_target_is_refused_from_the_first_position_too(self, refused):
        response = _post("/api/email/send-matches", [
            {"opportunity_id": CLOSED_ID},
            {"opportunity_id": LISTING_ID},
        ])
        assert response.status_code == 409
        assert _quota_used() == 0

    def test_a_duplicate_id_is_refused(self, refused):
        """Frozen decision: reject rather than dedupe.

        A repeated id means the caller and the server disagree about what the
        list is; collapsing it silently would mail a shorter digest than the
        one that was asked for.
        """
        response = _post("/api/email/send-matches", [
            {"opportunity_id": LISTING_ID},
            {"opportunity_id": LISTING_ID},
        ])
        # Compared whole, not indexed. A schema 422 carries a pydantic error
        # LIST, so `json()["detail"]["code"]` raises TypeError there — which
        # would report as an error rather than as this contract failing, and
        # would let the old required-id 422 masquerade as a duplicate refusal.
        assert response.status_code == 422
        assert response.json()["detail"] == _DUPLICATE_TARGET
        assert _quota_used() == 0

    def test_over_the_cap_is_rejected_before_any_lookup(self, refused):
        response = _post(
            "/api/email/send-matches",
            [{"opportunity_id": LISTING_ID} for _ in range(51)],
        )
        assert response.status_code == 422
        assert _quota_used() == 0


class TestUnconfirmedKindIsRefusedLikeAnyDeadTarget:
    """CONTRACT CHANGE. 26 real UIUC/UCB projects carry no source_type.

    They used to be actionable and merely labelled "type not confirmed", on
    the grounds that Match and Detail showed them and email alone should not
    disagree. That reasoning held only while they WERE actionable everywhere.

    `record_kind_unverified` is now a refusal in the truth itself, so the
    disagreement is gone in the other direction: Match drops them, actions
    refuse them, and the digest refuses them too. Detail and the source link
    stay readable, which is where a student can still see what the record is.
    """

    def test_a_record_without_a_source_type_is_refused(self, refused):
        response = _post("/api/email/send-matches", [{"opportunity_id": UNKNOWN_KIND_ID}])

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "TARGET_NOT_ACTIONABLE"
        assert detail["reason"] == "record_kind_unverified"
        assert detail["retryable"] is False
        # Says what is unverified, and never implies an opening ended.
        assert "type is unverified" in detail["message"]
        assert _quota_used() == 0

    def test_one_of_them_refuses_the_whole_match_digest(self, refused):
        response = _post("/api/email/send-matches", [
            {"opportunity_id": LISTING_ID},
            {"opportunity_id": FACULTY_ID},
            {"opportunity_id": UNKNOWN_KIND_ID},
        ])
        assert response.status_code == 409
        assert _quota_used() == 0

    def test_a_saved_favorite_of_that_shape_is_kept_and_labelled(self, sent):
        # A shortlist records what the student chose, so it stays — with the
        # reason, source-only, and no deadline or application claim.
        response = _post("/api/email/send-favorites", [{"opportunity_id": UNKNOWN_KIND_ID}])

        assert response.status_code == 200
        body = sent["html"] + sent["text"]
        assert "Record type unverified" in sent["html"]
        assert " · due " not in sent["text"]
        assert "Closed —" not in body
        assert "Reference record" not in body

    def test_a_digest_of_the_two_confirmed_kinds_still_sends(self, sent):
        # The control: this refusal is about the unreviewed kind, not a
        # blanket tightening that broke ordinary digests.
        response = _post("/api/email/send-matches", [
            {"opportunity_id": LISTING_ID},
            {"opportunity_id": FACULTY_ID},
        ])
        assert response.status_code == 200
        assert response.json()["count"] == 2


class TestFacultyContactsAreMailable:
    def test_an_actionable_faculty_profile_is_sent(self, sent):
        """You write to a person; that is a legitimate thing to mail."""
        response = _post("/api/email/send-matches", [{"opportunity_id": FACULTY_ID}])
        assert response.status_code == 200
        assert "Faculty contact profile" in sent["html"]
        assert "opening not confirmed" in sent["html"]

    def test_a_faculty_row_carries_no_deadline_or_application_link(self, sent):
        record = data_loader.load_opportunities_by_id()[FACULTY_ID]
        application_url = (record.get("application") or {}).get("application_url")
        response = _post("/api/email/send-matches", [{"opportunity_id": FACULTY_ID}])

        assert response.status_code == 200
        assert " · due " not in sent["text"]
        if application_url:
            assert application_url not in sent["html"]
        source = str(record.get("source_url") or record.get("url") or "")
        if source:
            assert source in sent["html"]


class TestFavoritesKeepHistoryHonestly:
    def test_a_closed_saved_target_is_kept_and_labelled_precisely(self, sent):
        """A shortlist records what the student chose. It stays — labelled."""
        response = _post("/api/email/send-favorites", [
            {"opportunity_id": CLOSED_ID, "notes": "ask about this"},
        ])
        assert response.status_code == 200
        assert response.json()["count"] == 1
        assert "Closed — no longer accepting applications" in sent["html"]
        # Not the generic label, and nothing inferred about the lab.
        assert "Status unconfirmed" not in sent["html"]

    def test_a_closed_saved_target_shows_no_due_date_and_no_application_link(self, sent):
        record = data_loader.load_opportunities_by_id()[CLOSED_ID]
        application_url = (record.get("application") or {}).get("application_url")
        response = _post("/api/email/send-favorites", [{"opportunity_id": CLOSED_ID}])

        assert response.status_code == 200
        assert " · due " not in sent["text"]
        if application_url:
            assert application_url not in sent["html"]
        assert str(record.get("source_url") or record.get("url")) in sent["html"]

    def test_an_actionable_saved_target_is_not_labelled_historical(self, sent):
        response = _post("/api/email/send-favorites", [{"opportunity_id": LISTING_ID}])
        assert response.status_code == 200
        assert "no longer accepting applications" not in sent["html"]

    def test_a_duplicate_saved_id_is_refused_too(self, refused):
        response = _post("/api/email/send-favorites", [
            {"opportunity_id": LISTING_ID},
            {"opportunity_id": LISTING_ID},
        ])
        assert response.status_code == 422
        assert _quota_used() == 0


# ---------------------------------------------------------------------------
# Stubbed corpora: exact record shapes, so a data refresh cannot turn a test
# into a different case without anyone noticing.
# ---------------------------------------------------------------------------

def _stub_record(opportunity_id: str, **overrides) -> dict:
    record = {
        "id": opportunity_id,
        "title": "Stubbed target",
        "organization": "Test University",
        "source": "test_source",
        "source_type": "campus_program",
        "source_url": "https://example.edu/scraped",
        "url": "https://example.edu/display",
        "deadline": "2099-12-31",
        "application": {"application_url": "https://example.edu/apply-here"},
        "metadata": {"is_active": True},
    }
    record.update(overrides)
    return record


@pytest.fixture
def corpus(monkeypatch):
    """Install a single canonical lookup map for one test."""

    def _install(records: list[dict]):
        by_id = {r["id"]: r for r in records}
        monkeypatch.setattr(email_mod, "load_opportunities_by_id", lambda: by_id)
        return by_id

    return _install


class TestFavoritesLabelEachReasonPrecisely:
    """Not one "Closed" for everything: three states, three sentences."""

    def test_a_reference_only_record_says_reference_not_closed(self, corpus, sent):
        corpus([_stub_record("ref-1", metadata={
            "is_active": True, "reference_only": True,
        })])
        response = _post("/api/email/send-favorites", [{"opportunity_id": "ref-1"}])

        assert response.status_code == 200
        assert "Reference record — not an open listing" in sent["html"]
        assert "Closed" not in sent["html"]
        assert "2099-12-31" not in sent["html"]
        assert "apply-here" not in sent["html"]
        assert "https://example.edu/scraped" in sent["html"]

    def test_an_inactive_record_says_inactive_not_closed(self, corpus, sent):
        corpus([_stub_record("inactive-1", metadata={"is_active": False})])
        response = _post("/api/email/send-favorites", [{"opportunity_id": "inactive-1"}])

        assert response.status_code == 200
        assert "Inactive — no longer carried in the catalog" in sent["html"]
        assert "Closed —" not in sent["html"]
        assert "Reference record" not in sent["html"]
        assert "2099-12-31" not in sent["html"]
        assert "apply-here" not in sent["html"]

    def test_a_closed_listing_says_closed(self, corpus, sent):
        corpus([_stub_record("closed-1", metadata={
            "is_active": True, "urap_status": "closed",
        })])
        response = _post("/api/email/send-favorites", [{"opportunity_id": "closed-1"}])

        assert response.status_code == 200
        assert "Closed — no longer accepting applications" in sent["html"]
        assert "Inactive" not in sent["html"]


def _faculty_stub(opportunity_id: str, statement: str) -> dict:
    """A faculty profile stating its own availability, in the source's words."""
    return _stub_record(
        opportunity_id,
        source_type="faculty_research",
        title="Prof. Alex Rivera",
        description_raw=statement,
        description_clean=statement,
    )


NOT_ACCEPTING = "I am not currently accepting undergraduate students."
RESEARCH_INACTIVE = "Prof. Rivera is not currently conducting research."


class TestFacultyWhoSaidNoIsNotMailedAbout:
    """The one refusal that is about a person rather than a posting.

    The ranker has excluded these from Match for a long time, but a saved id
    reaches /email directly without ever passing through ranking — so before
    this contract, a professor who wrote "do not ask me" could still be mailed
    about. The corpus carries three such rows today.
    """

    def test_a_match_digest_containing_one_refuses_entirely(self, corpus, refused):
        corpus([
            _stub_record("open-1"),
            _faculty_stub("stop-1", NOT_ACCEPTING),
        ])
        response = _post("/api/email/send-matches", [
            {"opportunity_id": "open-1"},
            {"opportunity_id": "stop-1"},
        ])

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "TARGET_NOT_ACTIONABLE"
        # Exactly this reason. Reporting it as `listing_closed` would tell the
        # student a posting closed, which no source here ever said.
        assert detail["reason"] == "faculty_not_accepting"
        assert detail["retryable"] is False
        # Free: the `refused` fixture's provider raises on contact, and the
        # recipient's anti-bombing quota must not be spent on a refusal.
        assert _quota_used() == 0

    def test_the_real_corpus_record_refuses_too(self, refused):
        """Not only the stub: the shape exists in the served corpus."""
        response = _post(
            "/api/email/send-matches",
            [{"opportunity_id": "faculty-ucr-entomology-0fd0dec8"}],
        )
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "faculty_not_accepting"
        assert _quota_used() == 0

    def test_a_saved_favorite_is_kept_but_says_exactly_what_the_source_said(
        self, corpus, sent,
    ):
        corpus([_faculty_stub("stop-1", NOT_ACCEPTING)])
        response = _post("/api/email/send-favorites", [{"opportunity_id": "stop-1"}])

        assert response.status_code == 200
        body = sent["html"] + sent["text"]
        assert (
            "Source profile states this faculty member is not currently accepting "
            "undergraduate students"
        ) in sent["html"]
        # Attributed, and narrow. None of the other three labels apply, and a
        # professor who is not taking undergraduates has not "closed" anything.
        assert "Closed —" not in body
        assert "Reference record" not in body
        assert "Inactive —" not in body
        # Source-only: no application link, no deadline claim.
        assert "apply-here" not in body
        assert "2099-12-31" not in body
        assert "https://example.edu/scraped" in sent["html"]


class TestResearchInactiveIsAWarningNotARefusal:
    """"I have no active research" is not "do not ask me".

    Folding the two together would silently rewrite one person's statement as
    another's and cost a student a legitimate, carefully-worded question. So
    the row still mails — carrying the source's report, and nothing that reads
    like an opening.
    """

    def test_a_match_digest_still_sends_and_carries_the_warning(self, corpus, sent):
        corpus([_faculty_stub("quiet-1", RESEARCH_INACTIVE)])
        response = _post("/api/email/send-matches", [{"opportunity_id": "quiet-1"}])

        assert response.status_code == 200
        assert "Source reports no current active research" in sent["html"]
        assert "Source reports no current active research" in sent["text"]
        assert "this is not an opening" in sent["html"]

    def test_the_real_corpus_record_still_sends(self, sent):
        response = _post(
            "/api/email/send-matches",
            [{"opportunity_id": "faculty-arizona-phys-888d3f7f"}],
        )
        assert response.status_code == 200
        assert "Source reports no current active research" in sent["html"]

    def test_a_favorite_carries_the_warning_too(self, corpus, sent):
        corpus([_faculty_stub("quiet-1", RESEARCH_INACTIVE)])
        response = _post("/api/email/send-favorites", [{"opportunity_id": "quiet-1"}])

        assert response.status_code == 200
        assert "Source reports no current active research" in sent["html"]
        assert "Source reports no current active research" in sent["text"]

    @pytest.mark.parametrize(
        "path", ["/api/email/send-matches", "/api/email/send-favorites"],
    )
    def test_neither_body_claims_an_opening_a_deadline_or_an_application(
        self, path, corpus, sent,
    ):
        corpus([_faculty_stub("quiet-1", RESEARCH_INACTIVE)])
        response = _post(path, [{"opportunity_id": "quiet-1"}])

        assert response.status_code == 200
        body = sent["html"] + sent["text"]
        assert "apply-here" not in body
        assert "2099-12-31" not in body
        assert "due " not in body
        assert "Opportunity listing" not in body

    @pytest.mark.parametrize(
        "path", ["/api/email/send-matches", "/api/email/send-favorites"],
    )
    def test_it_is_never_labelled_as_closed_or_as_a_refusal(self, path, corpus, sent):
        corpus([_faculty_stub("quiet-1", RESEARCH_INACTIVE)])
        response = _post(path, [{"opportunity_id": "quiet-1"}])

        assert response.status_code == 200
        body = sent["html"] + sent["text"]
        assert "Closed —" not in body
        assert "not currently accepting undergraduate" not in body
        assert "Inactive —" not in body
        assert "Reference record" not in body


class TestSourceOnlyLinking:
    @pytest.mark.parametrize(
        ("label", "overrides"),
        [
            ("faculty", {"source_type": "faculty_research"}),
            # Unreviewed kind now goes through favorites: it is no longer
            # actionable, so a match digest refuses it outright. The link rule
            # under test is the same either way.
            ("unknown-kind", {"source_type": None}),
            ("closed listing", {"metadata": {"is_active": True, "urap_status": "closed"}}),
        ],
    )
    def test_a_stale_application_url_is_never_offered(self, label, overrides, corpus, sent):
        """source_url wins over url, and an application URL is offered to
        neither a faculty profile, an unconfirmed kind, nor a closed listing."""
        corpus([_stub_record("link-1", **overrides)])
        path = (
            "/api/email/send-matches"
            if overrides.get("source_type") == "faculty_research"
            else "/api/email/send-favorites"
        )
        response = _post(path, [{"opportunity_id": "link-1"}])

        assert response.status_code == 200, label
        assert "apply-here" not in sent["html"], label
        assert "example.edu/display" not in sent["html"], label
        assert "https://example.edu/scraped" in sent["html"], label


class TestOnlyContractSafeLinksAreMailed:
    """A digest link is clicked hours later, out of context, under our brand.

    The old check here was `startswith("http")`, which accepts far more than
    the API projection does: embedded credentials, an embedded address (
    ``http://vpue-fellowships@stanford.edu/`` is a real shape in this corpus),
    whitespace and newlines inside the value, and several URLs crammed into
    one field. Each of those renders as a clickable link the reader has no way
    to check.

    Both endpoints are exercised: matches and favorites build their rows
    through the same `_describe`, and a fix that only reached one of them
    would leave the other mailing whatever it was handed.
    """

    POISON: list[tuple[str, str]] = [
        ("javascript", "javascript:alert(document.domain)"),
        ("data", "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="),
        ("userinfo", "https://attacker.example:hunter2@evil.test/apply"),
        ("embedded-email", "http://vpue-fellowships@stanford.edu/"),
        ("leading-space", "   https://evil.test/apply"),
        ("trailing-newline", "https://evil.test/apply\n"),
        ("interior-newline", "https://evil.test/ap\nply"),
        ("interior-space", "https://evil.test/ap ply"),
        # Whitespace-separated fields, which the contract already refuses. A
        # nested absolute URL is NOT here: `https://good.test/a;https://evil…`
        # parses to a single destination on good.test, and one real corpus
        # record's only link is a URLDefense wrapper of exactly that shape.
        ("space-separated-pair", "https://good.test/a https://evil.test/b"),
        ("newline-separated-pair", "https://good.test/a\nhttps://evil.test/b"),
        ("missing-host", "https:///apply"),
        ("bad-port", "https://evil.test:notaport/apply"),
    ]

    @pytest.mark.parametrize(("label", "poison"), POISON, ids=[p[0] for p in POISON])
    @pytest.mark.parametrize("path", ["/api/email/send-matches", "/api/email/send-favorites"])
    def test_a_poisoned_canonical_url_is_never_linked(
        self, path, label, poison, corpus, sent,
    ):
        # Every canonical candidate is poisoned, so there is no safe link to
        # fall back to and the row must render as plain text.
        corpus([_stub_record(
            "link-1",
            source_url=poison, url=poison,
            application={"application_url": poison},
        )])
        response = _post(path, [{"opportunity_id": "link-1"}])

        assert response.status_code == 200, label
        body = sent["html"] + sent["text"]
        assert poison.strip() not in body, label
        assert "evil.test" not in body, label
        assert "attacker.example" not in body, label
        assert "javascript:" not in body, label
        assert "data:text/html" not in body, label
        # The row is still there, and its title is NOT an anchor. Checking for
        # the absence of `href=` outright would be checking the footer, which
        # legitimately links back to the app.
        assert "Stubbed target" in sent["html"], label
        assert ">Stubbed target</a>" not in sent["html"], label
        # The plain-text part too. Half the recipients read that one, and it
        # has its own "(no link)" branch that a HTML-only assertion misses.
        assert "Stubbed target" in sent["text"], label
        assert "(no link)" in sent["text"], label

    @pytest.mark.parametrize("path", ["/api/email/send-matches", "/api/email/send-favorites"])
    @pytest.mark.parametrize("wrapped", [
        # A mail-gateway rewrite. One real corpus record
        # (faculty-ucsd-hwsph-8fd2db9c) has this as its ONLY link, so a rule
        # that treated the nested URL as a second destination would leave that
        # professor's row with nothing to click.
        "https://urldefense.com/v3/__https://profiles.ucsd.edu/pooyan.kazemian__;!!x$",
        "https://example.edu/apply?next=https%3A%2F%2Fexample.edu%2Fdone",
    ])
    def test_a_wrapper_or_return_address_is_still_mailed(
        self, path, wrapped, corpus, sent,
    ):
        corpus([_stub_record("link-1", source_url=wrapped, url=None, application={})])
        response = _post(path, [{"opportunity_id": "link-1"}])

        assert response.status_code == 200
        assert wrapped in sent["text"]
        assert ">Stubbed target</a>" in sent["html"]

    @pytest.mark.parametrize("path", ["/api/email/send-matches", "/api/email/send-favorites"])
    def test_the_real_urldefense_record_keeps_its_only_link(self, path, sent):
        """A receipt against the served corpus, not a stub.

        `faculty-ucsd-hwsph-8fd2db9c` has one link and it is a URLDefense
        rewrite. The whole point of the URL boundary is to remove links we
        cannot vouch for — removing the only link a real record has, because
        its path contains another URL, is the opposite failure.
        """
        record = data_loader.load_opportunities_by_id().get("faculty-ucsd-hwsph-8fd2db9c")
        if record is None:
            pytest.skip("record not present in this corpus generation")
        wrapped = record.get("source_url") or record.get("url")

        response = _post(path, [{"opportunity_id": "faculty-ucsd-hwsph-8fd2db9c"}])

        assert response.status_code == 200
        assert wrapped in sent["text"]
        assert wrapped in sent["html"]
        assert str(record.get("title")) in sent["html"]
        # Still a faculty contact, and still not an application.
        assert "Faculty contact profile" in sent["html"]
        assert " · due " not in sent["text"]

    @pytest.mark.parametrize("path", ["/api/email/send-matches", "/api/email/send-favorites"])
    def test_an_unsafe_application_url_falls_back_to_the_safe_source(
        self, path, corpus, sent,
    ):
        # The bug this pins: choosing `apply or source` on the RAW values let
        # an unsafe application URL win, and sanitizing the winner then left
        # the reader with no link at all — losing a perfectly good source page
        # because of a field they were never going to see.
        corpus([_stub_record(
            "link-1",
            source_url="https://example.edu/scraped",
            url="https://example.edu/display",
            application={"application_url": "javascript:alert(1)"},
        )])
        response = _post(path, [{"opportunity_id": "link-1"}])

        assert response.status_code == 200
        assert "https://example.edu/scraped" in sent["html"]
        assert "https://example.edu/scraped" in sent["text"]
        assert "javascript:" not in sent["html"] + sent["text"]

    @pytest.mark.parametrize("path", ["/api/email/send-matches", "/api/email/send-favorites"])
    def test_an_unsafe_source_url_falls_back_to_the_safe_display_url(
        self, path, corpus, sent,
    ):
        corpus([_stub_record(
            "link-1",
            source_url="https://user:pw@evil.test/scraped",
            url="https://example.edu/display",
            application={},
        )])
        response = _post(path, [{"opportunity_id": "link-1"}])

        assert response.status_code == 200
        assert "https://example.edu/display" in sent["html"]
        assert "https://example.edu/display" in sent["text"]
        assert "evil.test" not in sent["html"] + sent["text"]

    @pytest.mark.parametrize("path", ["/api/email/send-matches", "/api/email/send-favorites"])
    def test_a_legitimate_query_and_fragment_survive(self, path, corpus, sent):
        # The control. Some application portals need both, so a fix that
        # stripped them would break real links while passing every test above.
        safe = "https://example.edu/apply?program=reu&cohort=2027#requirements"
        corpus([_stub_record("link-1", source_url=safe, url=safe, application={})])
        response = _post(path, [{"opportunity_id": "link-1"}])

        assert response.status_code == 200
        assert "program=reu&amp;cohort=2027#requirements" in sent["html"]
        assert safe in sent["text"]

    @pytest.mark.parametrize("path", ["/api/email/send-matches", "/api/email/send-favorites"])
    def test_a_legacy_client_url_is_never_used_as_a_fallback(
        self, path, corpus, sent,
    ):
        # The rollout bridge accepts the client's describing fields and ignores
        # them. "Ignored" has to hold when the canonical record has no usable
        # link either — otherwise the one case where the server has nothing to
        # say is exactly the case where the client gets to say it.
        corpus([_stub_record(
            "link-1",
            source_url="javascript:alert(1)", url="javascript:alert(2)",
            application={"application_url": "javascript:alert(3)"},
        )])
        item = {
            "opportunity_id": "link-1",
            "url": "https://client-supplied.test/looks-fine",
            "source": "client_source",
            "title": "CLIENT TITLE",
        }
        # `organization` is a match-only legacy field; the favorites model does
        # not declare it and rejects the request outright, which is its own
        # (stronger) form of ignoring it.
        if path.endswith("send-matches"):
            item["organization"] = "CLIENT ORG"
        response = _post(path, [item])

        assert response.status_code == 200
        body = sent["html"] + sent["text"]
        assert "client-supplied.test" not in body
        assert "CLIENT TITLE" not in body
        assert "CLIENT ORG" not in body
        # `source` is a declared legacy field on BOTH request models, so it is
        # the one most likely to be quietly believed. The row's source label
        # comes from the canonical record or from nowhere.
        assert "client_source" not in body
        # The canonical label is what renders. Asserted on the HTML part,
        # which is where both templates print the source; the favorites text
        # part carries status/title/link only.
        assert "test_source" in sent["html"]
        # The canonical title renders, unlinked — the client's URL did not
        # quietly become the row's link — in both parts.
        assert ">Stubbed target</a>" not in sent["html"]
        assert "Stubbed target" in sent["text"]
        assert "(no link)" in sent["text"]

    @pytest.mark.parametrize("path", ["/api/email/send-matches", "/api/email/send-favorites"])
    def test_a_client_supplied_record_kind_never_reclassifies_a_faculty_row(
        self, path, sent,
    ):
        # A real faculty record from the served corpus, with the client
        # insisting it is a listing and supplying a deadline and an
        # application URL. Kind is decided from the canonical record; believing
        # the caller here would print "Opportunity listing … due" over a
        # directory page.
        response = _post(path, [{
            "opportunity_id": FACULTY_ID,
            "record_kind": "listing",
            "deadline": "2099-12-31",
            "url": "https://client-supplied.test/apply-now",
        }])

        assert response.status_code == 200
        body = sent["html"] + sent["text"]
        assert "Faculty contact profile" in body
        assert "Opportunity listing" not in body
        assert "2099-12-31" not in body
        assert " · due " not in sent["text"]
        assert "client-supplied.test" not in body


class TestCorpusTextIsNeverMailedRaw:
    """The link boundary was only half the leak.

    ``stanford-f0a974ed2bd2`` is a real, release-visible record whose TITLE is
    ``vpue-fellowships@stanford.edu``. Its URLs are the same address, so the
    link contract already refuses them — and then both templates printed the
    title, the source name and the organization straight into the HTML and the
    plain-text part, where nothing looked at them at all. A hidden address
    published under our brand, to a reader who never asked for it.

    Same boundary the API projection uses on descriptions, applied per field:
    a redacted title must not take the source label down with it, and the row
    must still appear. Both endpoints, because both build their rows through
    the one ``_describe``.
    """

    # Each is a shape the shared detector already recognises — verified
    # against the helper, not assumed. The point of listing several is that
    # `title` is scraped text: a collector that copies a mailto out of markup
    # produces the split and entity forms, and a human-written directory line
    # produces the obfuscated ones.
    CONTACT_SHAPES: list[tuple[str, str]] = [
        ("plain", "vpue-fellowships@stanford.edu"),
        ("in-a-sentence", "Fellowships, write vpue-fellowships@stanford.edu"),
        ("percent-encoded", "vpue-fellowships%40stanford.edu"),
        ("html-entity", "vpue-fellowships&#64;stanford.edu"),
        ("split-across-markup", "vpue-fellowships<span>@</span>stanford.edu"),
        ("bracket-obfuscated", "vpue-fellowships [at] stanford [dot] edu"),
        ("word-obfuscated", "vpue-fellowships at stanford dot edu"),
    ]

    # Only the fields each template actually prints, and in which part. Both
    # parts must always be free of the address; the placeholder can only be
    # demanded where the field is rendered at all. A favorites row prints the
    # source label in the HTML alone — its text part carries status, title,
    # link and notes — so requiring a marker there would be a test asking the
    # template to grow a line it does not have.
    RENDERED: list[tuple[str, str, bool]] = [
        ("/api/email/send-matches", "title", True),
        ("/api/email/send-matches", "source", True),
        ("/api/email/send-matches", "organization", True),
        ("/api/email/send-matches", "deadline", True),
        ("/api/email/send-favorites", "title", True),
        ("/api/email/send-favorites", "source", False),
        # The due line is printed by both parts of both templates, for a
        # confirmed listing — which the stub is.
        ("/api/email/send-favorites", "deadline", True),
    ]

    @pytest.mark.parametrize(
        ("label", "poison"), CONTACT_SHAPES, ids=[s[0] for s in CONTACT_SHAPES],
    )
    @pytest.mark.parametrize(
        ("path", "field", "in_text"), RENDERED,
        ids=[f"{p.rsplit('/', 1)[1]}-{f}" for p, f, _ in RENDERED],
    )
    def test_an_address_in_corpus_text_is_redacted_field_by_field(
        self, path, field, in_text, label, poison, corpus, sent,
    ):
        corpus([_stub_record("text-1", **{field: poison})])
        response = _post(path, [{"opportunity_id": "text-1"}])

        assert response.status_code == 200, label
        body = sent["html"] + sent["text"]
        # The local part and the domain, separately: the obfuscated shapes
        # never contain the assembled address, so asserting only on
        # "vpue-fellowships@stanford.edu" would pass while the reader can
        # still read it off the page. Both parts, always — half the recipients
        # read the plain-text one.
        assert "vpue-fellowships" not in body, label
        assert "stanford" not in body.lower(), label
        # The row did not silently vanish, and it says why the field is gone.
        assert "[email redacted]" in sent["html"], label
        if in_text:
            assert "[email redacted]" in sent["text"], label

    @pytest.mark.parametrize(
        ("path", "field", "in_text"), RENDERED,
        ids=[f"{p.rsplit('/', 1)[1]}-{f}" for p, f, _ in RENDERED],
    )
    def test_redacting_one_field_leaves_the_others_alone(
        self, path, field, in_text, corpus, sent,
    ):
        # Each field is its own decision. Blanking the whole row when one
        # field carries an address would lose the title of every record whose
        # source label happens to contain one.
        corpus([_stub_record("text-1", **{field: "vpue-fellowships@stanford.edu"})])
        response = _post(path, [{"opportunity_id": "text-1"}])

        assert response.status_code == 200
        survivors = {
            "title": "Stubbed target",
            "source": "test_source",
            "organization": "Test University",
            "deadline": "2099-12-31",
        }
        del survivors[field]
        for name, value in survivors.items():
            if name == "organization" and path.endswith("send-favorites"):
                continue
            assert value in sent["html"], name

    @pytest.mark.parametrize("path", ["/api/email/send-matches", "/api/email/send-favorites"])
    def test_ordinary_corpus_text_is_untouched(self, path, corpus, sent):
        # The control this whole class needs. Redacting everything would pass
        # every assertion above.
        corpus([_stub_record("text-1")])
        response = _post(path, [{"opportunity_id": "text-1"}])

        assert response.status_code == 200
        assert "[email redacted]" not in sent["html"] + sent["text"]
        assert "Stubbed target" in sent["html"]
        assert "test_source" in sent["html"]
        # An ordinary date is still an ordinary date, in both parts.
        assert "2099-12-31" in sent["html"]
        assert "2099-12-31" in sent["text"]

    def test_the_students_own_notes_and_status_keep_their_own_addresses(
        self, corpus, sent,
    ):
        # The boundary is "text we read off the corpus", not "text". A student
        # who wrote a contact into their own note is mailing themselves their
        # own words, and redacting those would be this fix overreaching into
        # the one part of the digest that was never ours to edit. Both
        # user-owned fields, because a blanket redaction would take both.
        corpus([_stub_record("text-1", title="vpue-fellowships@stanford.edu")])
        response = _post("/api/email/send-favorites", [{
            "opportunity_id": "text-1",
            "notes": "reply to my advisor at ada.lovelace@illinois.edu first",
            "status": "sent to grad@illinois.edu",
        }])

        assert response.status_code == 200
        assert "ada.lovelace@illinois.edu" in sent["html"]
        assert "ada.lovelace@illinois.edu" in sent["text"]
        # Status renders raw in the HTML badge (the uppercasing there is CSS)
        # and upper-cased in the plain-text prefix. Asserted in the shape each
        # part actually has — the template is not the thing under test.
        assert "sent to grad@illinois.edu" in sent["html"]
        assert "[SENT TO GRAD@ILLINOIS.EDU]" in sent["text"]
        # And the corpus title beside it is still redacted, so this is not
        # simply a digest with the boundary switched off.
        assert "vpue-fellowships" not in sent["html"] + sent["text"]
        assert "[email redacted]" in sent["html"]

    def test_the_real_stanford_record_mails_without_its_address(self, sent):
        """A receipt against the served corpus, not a stub.

        Favorites is the endpoint that can reach it: the record is deactivated,
        so a matches digest refuses it outright, while a saved shortlist keeps
        a dead row and labels it. That is exactly the path that published the
        address.
        """
        # Hard, not skipped. This receipt is the reason the fix exists; a
        # corpus generation that no longer contains the record has to fail
        # here and be re-pinned deliberately, not quietly stop being checked.
        record = data_loader.load_opportunities_by_id().get("stanford-f0a974ed2bd2")
        assert record is not None, "the frozen corpus must still carry this record"
        assert record.get("title") == "vpue-fellowships@stanford.edu"

        response = _post(
            "/api/email/send-favorites",
            [{"opportunity_id": "stanford-f0a974ed2bd2"}],
        )

        assert response.status_code == 200
        assert "vpue-fellowships@stanford.edu" not in sent["html"]
        assert "vpue-fellowships@stanford.edu" not in sent["text"]
        assert "vpue-fellowships" not in sent["html"] + sent["text"]
        # Still in the shortlist the student saved, and still labelled.
        assert "[email redacted]" in sent["html"]
        assert "[email redacted]" in sent["text"]
        assert "no longer carried" in sent["html"]
        # Its only URL is the same address, so there was never a link to give.
        assert "(no link)" in sent["text"]
        assert "href=\"http://vpue" not in sent["html"]
        # The source label is clean and survives the title's redaction.
        assert "stanford_research_programs" in sent["html"]


class TestFavoritesRefusalsAreFree:
    def test_an_unresolvable_id_costs_nothing(self, corpus, refused):
        corpus([_stub_record("known-1")])
        response = _post("/api/email/send-favorites", [
            {"opportunity_id": "known-1"},
            {"opportunity_id": "never-existed"},
        ])
        assert response.status_code == 409
        assert _quota_used() == 0

    def test_a_duplicate_costs_nothing(self, corpus, refused):
        corpus([_stub_record("known-1")])
        response = _post("/api/email/send-favorites", [
            {"opportunity_id": "known-1"},
            {"opportunity_id": "known-1"},
        ])
        assert response.status_code == 422
        assert _quota_used() == 0

    @pytest.mark.parametrize(
        "overlong",
        [{"notes": "n" * 5000}, {"status": "s" * 500}],
        ids=["notes", "status"],
    )
    def test_an_overlong_user_field_costs_nothing(self, overlong, corpus, refused):
        corpus([_stub_record("known-1")])
        response = _post(
            "/api/email/send-favorites", [{"opportunity_id": "known-1", **overlong}],
        )
        assert response.status_code == 422
        assert _quota_used() == 0

    def test_the_cap_is_enforced_before_the_corpus_is_even_loaded(self, monkeypatch, refused):
        """A 51-item payload must not cost a corpus load, let alone a send."""
        def boom():
            raise AssertionError("the corpus was loaded for an over-cap request")

        monkeypatch.setattr(email_mod, "load_opportunities_by_id", boom)
        response = _post(
            "/api/email/send-favorites",
            [{"opportunity_id": f"id-{i}"} for i in range(51)],
        )
        assert response.status_code == 422
        assert _quota_used() == 0


class _TrackingLock:
    """A real lock that counts its own use.

    Wraps rather than replaces the lock, so the code under test still gets
    genuine mutual exclusion while the test can see whether the critical
    sections were entered at all.
    """

    def __init__(self, inner):
        self._inner = inner
        self.entered = 0
        self.exited = 0
        self.max_depth = 0

    def __enter__(self):
        self._inner.__enter__()
        self.entered += 1
        self.max_depth = max(self.max_depth, self.entered - self.exited)
        return self

    def __exit__(self, *exc):
        self.exited += 1
        return self._inner.__exit__(*exc)


class TestTheThreeQuotasMeasureDifferentThings:
    """Per-IP, global spend and per-recipient are not interchangeable.

    Treating them alike is the tempting mistake, and both directions are bugs:

      * per-IP counts ARRIVALS. It is abuse control, so a client hammering
        closed ids must still accrue toward its own cap and eventually 429.
        Refunding it would hand an attacker an unmetered endpoint.
      * global counts PAID WORK. No provider reached means nothing to bill, so
        a refusal must give the slot back — otherwise one client's stale ids
        exhaust every other user's ceiling.
      * per-recipient counts ATTEMPTS THAT REACH THE PROVIDER. A manual send
        carries no idempotency key, so a timeout may well have been delivered;
        refunding an ambiguous failure would let a retry loop bomb an address
        straight through the cap meant to stop it.
    """

    @pytest.fixture
    def metered(self, monkeypatch):
        """The middleware actually enabled, with all three buckets empty.

        conftest sets OFE_DISABLE_RATE_LIMIT=1 for the whole session, so
        without this the middleware short-circuits and every accounting
        assertion below would pass vacuously.
        """
        monkeypatch.setattr(main_mod, "RATE_LIMIT_DISABLED", False)
        main_mod._rate_buckets.clear()
        main_mod._global_buckets.clear()
        email_mod._recipient_sends.clear()

        def counts() -> dict[str, int]:
            return {
                "ip": sum(len(v) for v in main_mod._rate_buckets.values()),
                "global": len(main_mod._global_buckets["email"]),
                "recipient": _quota_used(),
            }

        return counts

    @pytest.fixture
    def provider(self, monkeypatch):
        """A configured mailer that records every attempt."""
        monkeypatch.setenv("RESEND_API_KEY", "fake")
        monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
        attempts: list[str] = []

        async def record(**kwargs):
            attempts.append(kwargs["to"])

        monkeypatch.setattr(email_mod, "_send_via_resend", record)
        return attempts

    @pytest.mark.parametrize(
        ("label", "items", "expected_status"),
        [
            ("closed", [{"opportunity_id": "closed-1"}], 409),
            ("faculty_stop", [{"opportunity_id": "stop-1"}], 409),
            ("unresolved", [{"opportunity_id": "never-existed"}], 409),
            ("empty", [], 400),
            (
                "duplicate",
                [{"opportunity_id": "open-1"}, {"opportunity_id": "open-1"}],
                422,
            ),
            # Both legacy refusals go through the same accounting. Raised as a
            # bare HTTPException instead of `prework_refusal` they would look
            # identical to a client and still burn a slot of the global email
            # ceiling — one old client's stale locators would eat every other
            # user's budget. `open-1` and `closed-1` share a title and a url,
            # so the second item below is genuinely ambiguous.
            (
                "legacy_unresolved",
                [{"title": "Nothing like this", "url": "https://example.edu/display"}],
                409,
            ),
            (
                "legacy_ambiguous",
                [{"title": "Stubbed target", "url": "https://example.edu/display"}],
                409,
            ),
        ],
    )
    def test_a_prework_refusal_costs_no_spend_but_still_counts_as_a_visit(
        self, label, items, expected_status, corpus, metered, provider,
    ):
        corpus([
            _stub_record("open-1"),
            _stub_record("closed-1", metadata={"is_active": True, "urap_status": "closed"}),
            _faculty_stub("stop-1", NOT_ACCEPTING),
        ])
        response = client.post(
            "/api/email/send-matches",
            json={"email": "reader@example.com", "items": items},
        )

        assert response.status_code == expected_status, label
        assert metered() == {"ip": 1, "global": 0, "recipient": 0}, label
        assert provider == [], label

    def test_a_schema_refusal_costs_no_spend_either(self, metered, provider):
        response = client.post(
            "/api/email/send-matches",
            json={"email": "not-an-email", "items": [{"opportunity_id": "x"}]},
        )
        assert response.status_code == 422
        assert metered() == {"ip": 1, "global": 0, "recipient": 0}
        assert provider == []

    @pytest.mark.parametrize(
        ("path", "renderer"),
        [
            ("/api/email/send-matches", "_render_match_email"),
            ("/api/email/send-favorites", "_render_favorites_email"),
        ],
    )
    def test_a_render_failure_spends_no_recipient_quota(
        self, path, renderer, corpus, metered, provider, monkeypatch,
    ):
        """The recipient slot is reserved last, after the body exists.

        A per-recipient send is deliberately never refunded — an ambiguous
        provider failure may well have been delivered. That makes reserving
        early strictly worse than reserving late: a body that fails to render
        never reached Resend at all, yet the student would have paid a slot out
        of a daily allowance no retry can win back.

        Resolution and actionability run earlier still, so this pins the one
        ordering the refusal tests cannot see: they never get as far as the
        renderer.
        """
        reached: list[str] = []

        def explode(_items):
            reached.append(renderer)
            raise RuntimeError("render failed")

        monkeypatch.setattr(email_mod, renderer, explode)
        corpus([_stub_record("open-1")])
        raised: list[BaseException] = []
        try:
            client.post(path, json={
                "email": "reader@example.com",
                "items": [{"opportunity_id": "open-1"}],
            })
        except Exception as exc:
            raised.append(exc)

        # Without these two the assertions below would pass on a request that
        # simply succeeded, or one refused long before the renderer.
        assert reached == [renderer]
        assert raised
        assert metered()["recipient"] == 0
        assert provider == []

    def test_an_unconfigured_mailer_costs_no_spend(self, corpus, metered, monkeypatch):
        corpus([_stub_record("open-1")])
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)
        response = client.post(
            "/api/email/send-matches",
            json={"email": "reader@example.com", "items": [{"opportunity_id": "open-1"}]},
        )
        assert response.status_code == 503
        assert metered() == {"ip": 1, "global": 0, "recipient": 0}

    def test_a_successful_send_spends_all_three(self, corpus, metered, provider):
        corpus([_stub_record("open-1")])
        response = client.post(
            "/api/email/send-matches",
            json={"email": "reader@example.com", "items": [{"opportunity_id": "open-1"}]},
        )
        assert response.status_code == 200
        assert metered() == {"ip": 1, "global": 1, "recipient": 1}
        assert provider == ["reader@example.com"]

    def test_a_provider_failure_still_spends_global_and_recipient(
        self, corpus, metered, monkeypatch,
    ):
        """An attempt that reached Resend counts, whatever Resend then said.

        Without an idempotency key a 5xx does not prove the mail was not
        delivered, so refunding here is what lets a retry loop bomb an address.

        The failure is raised the way the real wrapper raises it — an
        HTTPException that becomes a 502 response — precisely so this request
        travels back through the middleware. A bare exception would escape
        `call_next` and never reach the refund branch at all, which would leave
        "refund any error response" alive as an untested mutant.
        """
        corpus([_stub_record("open-1")])
        monkeypatch.setenv("RESEND_API_KEY", "fake")
        monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
        attempts: list[str] = []

        async def explode(**kwargs):
            attempts.append(kwargs["to"])
            raise HTTPException(status_code=502, detail="Email delivery failed")

        monkeypatch.setattr(email_mod, "_send_via_resend", explode)
        response = client.post(
            "/api/email/send-matches",
            json={"email": "reader@example.com", "items": [{"opportunity_id": "open-1"}]},
        )

        assert response.status_code == 502
        assert attempts == ["reader@example.com"], "the provider was reached"
        assert metered() == {"ip": 1, "global": 1, "recipient": 1}
        # A real delivery failure is not a prework refusal and must not be
        # tagged as one — that is the difference between "we spent nothing"
        # and "we may have spent everything".
        assert "X-Refused-Before-Work" not in response.headers

    def test_the_recipient_cap_refunds_spend_but_not_the_visit(
        self, corpus, metered, provider, monkeypatch,
    ):
        corpus([_stub_record("open-1")])
        # Per-IP and per-recipient are both 3 in production, so the per-IP gate
        # would fire first and this would test the wrong cap. Widening only the
        # per-IP one isolates the recipient contract.
        monkeypatch.setitem(
            main_mod.RATE_LIMITS, "/api/email/send-matches", (50, 3600),
        )
        body = {"email": "reader@example.com", "items": [{"opportunity_id": "open-1"}]}
        for _ in range(email_mod._RECIPIENT_SEND_LIMIT):
            assert client.post("/api/email/send-matches", json=body).status_code == 200

        capped = client.post("/api/email/send-matches", json=body)

        assert capped.status_code == 429
        counts = metered()
        assert counts["ip"] == email_mod._RECIPIENT_SEND_LIMIT + 1, "arrivals all count"
        # The refused one gave its spend slot back; the delivered ones kept theirs.
        assert counts["global"] == email_mod._RECIPIENT_SEND_LIMIT
        assert counts["recipient"] == email_mod._RECIPIENT_SEND_LIMIT
        assert len(provider) == email_mod._RECIPIENT_SEND_LIMIT

    def test_concurrent_sends_cannot_overshoot_the_recipient_cap(
        self, corpus, metered, provider, monkeypatch,
    ):
        """Reserve before sending, not count after.

        Requests that only counted on success would each see room while the
        others were still in flight, and the address would receive more mail
        than its cap allows. Reserving first makes the check and the increment
        one step, so the overshoot cannot happen.

        Scope note: this drives them concurrently on one event loop, which
        pins the CAP. It cannot distinguish the module lock from its absence —
        the reserve body contains no await, so a single loop serializes it
        either way. The lock is there for the threadpool case.
        """
        import asyncio

        import httpx

        corpus([_stub_record("open-1")])
        monkeypatch.setitem(
            main_mod.RATE_LIMITS, "/api/email/send-matches", (50, 3600),
        )
        limit = email_mod._RECIPIENT_SEND_LIMIT
        body = {"email": "reader@example.com", "items": [{"opportunity_id": "open-1"}]}

        async def fire_all() -> list[int]:
            transport = httpx.ASGITransport(app=main_mod.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as async_client:
                responses = await asyncio.gather(*[
                    async_client.post("/api/email/send-matches", json=body)
                    for _ in range(limit + 2)
                ])
            return [r.status_code for r in responses]

        statuses = asyncio.run(fire_all())

        assert statuses.count(200) == limit, "never more sends than the cap allows"
        assert statuses.count(429) == 2
        assert len(provider) == limit, "and the provider saw exactly that many"
        assert metered()["recipient"] == limit

    def test_the_recipient_check_and_reserve_run_inside_the_lock(self, monkeypatch):
        """Deterministic, unlike a thread race.

        The concurrency test above passes with or without the lock, because a
        single event loop serializes a body containing no await. This one holds
        the lock's own accounting to the contract: entered once, exited once,
        around the read-modify-write.
        """
        spy = _TrackingLock(email_mod._recipient_lock)
        monkeypatch.setattr(email_mod, "_recipient_lock", spy)
        email_mod._recipient_sends.clear()

        email_mod._enforce_recipient_quota("reader@example.com")

        assert spy.entered == 1
        assert spy.exited == 1
        assert _quota_used() == 1

    def test_reserve_and_refund_are_each_their_own_critical_section(
        self, corpus, metered, provider, monkeypatch,
    ):
        """Two entries per refused request: reserve, then give the slot back.

        The five-minute purge would add a third, so it is stepped over — this
        is about the reserve and refund sections, not the housekeeping one.
        """
        corpus([_faculty_stub("stop-1", NOT_ACCEPTING)])
        monkeypatch.setattr(main_mod, "_last_purge", time.time())
        spy = _TrackingLock(main_mod._rate_lock)
        monkeypatch.setattr(main_mod, "_rate_lock", spy)

        response = client.post(
            "/api/email/send-matches",
            json={"email": "reader@example.com", "items": [{"opportunity_id": "stop-1"}]},
        )

        assert response.status_code == 409
        assert spy.entered >= 2, "reserve and refund are both guarded"
        assert spy.exited == spy.entered, "every section released its lock"
        # Held across synchronous statements only: an await inside would park
        # the event loop with the lock held and deadlock every other request.
        assert spy.max_depth == 1, "the sections never nest"

    def test_repeated_bad_requests_reach_the_per_ip_cap_without_spending(
        self, corpus, metered, provider,
    ):
        """The limiter working: bad traffic is throttled, not subsidised."""
        corpus([_stub_record("open-1")])
        max_requests, _window = main_mod.RATE_LIMITS.get(
            main_mod._rate_limit_key("/api/email/send-matches"), main_mod.DEFAULT_RATE,
        )
        body = {"email": "reader@example.com", "items": [{"opportunity_id": "gone"}]}
        statuses = [
            client.post("/api/email/send-matches", json=body).status_code
            for _ in range(max_requests + 1)
        ]

        assert statuses[:max_requests] == [409] * max_requests
        assert statuses[-1] == 429, "the per-IP bucket must still fill up"
        assert metered()["global"] == 0
        assert provider == []

    def test_a_saturated_global_ceiling_does_not_stop_the_ip_bucket_filling(
        self, corpus, metered, provider, monkeypatch,
    ):
        """Order mutant: appending per-IP after the global check.

        With the ceiling full every request 429s at the global gate. If the
        per-IP append sits behind that gate, the attacker's own bucket never
        grows and they can hammer forever.
        """
        corpus([_stub_record("open-1")])
        monkeypatch.setattr(main_mod, "GLOBAL_EMAIL_PER_HOUR", 0)
        body = {"email": "reader@example.com", "items": [{"opportunity_id": "open-1"}]}

        for _ in range(3):
            assert client.post("/api/email/send-matches", json=body).status_code == 429

        counts = metered()
        assert counts["ip"] == 3, "arrivals counted even while the ceiling is full"
        assert counts["global"] == 0, "a rejected request reserves no spend"
        assert counts["recipient"] == 0
        assert provider == []

    @pytest.mark.parametrize("rate_limiting", [True, False], ids=["enabled", "disabled"])
    def test_the_internal_refusal_marker_never_reaches_a_client(
        self, rate_limiting, corpus, metered, provider, monkeypatch,
    ):
        """It is a channel between the guard and the middleware, not an API."""
        monkeypatch.setattr(main_mod, "RATE_LIMIT_DISABLED", not rate_limiting)
        corpus([_faculty_stub("stop-1", NOT_ACCEPTING)])
        response = client.post(
            "/api/email/send-matches",
            json={"email": "reader@example.com", "items": [{"opportunity_id": "stop-1"}]},
        )

        assert response.status_code == 409
        assert "X-Refused-Before-Work" not in response.headers
        assert not any(
            h.lower() == "x-refused-before-work" for h in response.headers
        )

    def test_two_reservations_in_the_same_tick_release_only_the_refused_one(
        self, corpus, metered, provider, monkeypatch,
    ):
        """Identity slots, not timestamps.

        Both requests reserve at the same frozen clock reading. If the refund
        removed "a float equal to now", it could retire the slot belonging to
        the send that actually went out, leaving the refused one counted and
        the delivered one free.
        """
        corpus([
            _stub_record("open-1"),
            _faculty_stub("stop-1", NOT_ACCEPTING),
        ])
        frozen = 1_800_000_000.0
        monkeypatch.setattr(main_mod.time, "time", lambda: frozen)

        ok = client.post(
            "/api/email/send-matches",
            json={"email": "reader@example.com", "items": [{"opportunity_id": "open-1"}]},
        )
        assert ok.status_code == 200
        # Captured before the second request, so the assertion below is about
        # object identity rather than about a count and a timestamp. Both
        # slots carry the same `frozen` reading, so a refund that scanned for a
        # matching timestamp would delete THIS one and leave the refused
        # request's slot in its place — same length, same timestamp, wrong
        # slot, and a test that only counted would call that correct.
        successful_slot = main_mod._global_buckets["email"][0]
        assert isinstance(successful_slot, main_mod._RateSlot)

        refused_response = client.post(
            "/api/email/send-matches",
            json={"email": "reader@example.com", "items": [{"opportunity_id": "stop-1"}]},
        )

        assert refused_response.status_code == 409
        remaining = main_mod._global_buckets["email"]
        assert len(remaining) == 1, "exactly one slot survives"
        assert remaining[0] is successful_slot, "and it is the send that happened"
        assert provider == ["reader@example.com"]


class TestADigestNeverPrintsAnOpeningClaimItCannotSupport:
    """`_describe` reads the RAW corpus record, so it skipped both title rules.

    Detail and match cards drop an unsupported "Prof." honorific and a
    "(applications open)" suffix before anything renders. A digest read
    `record["title"]` straight from the corpus, so a saved-favorites email was
    the one surface that reintroduced both — in an inbox, under our name,
    hours after anyone could check it.
    """

    # Both real rows: no `source_type`, so unreviewed, and a title that says
    # applications are open.
    URSA_ID = "b27723bb1ca91202"
    URSA_TITLE = "URSA — Undergraduate Research in Scientific Advancement"
    DRP_ID = "a22e863a3bd7ce87"
    DRP_TITLE = "CS DRP — Directed Reading Program (Computer Science, Winter Break)"

    @pytest.mark.parametrize("opportunity_id,base_title", [
        (URSA_ID, URSA_TITLE),
        (DRP_ID, DRP_TITLE),
    ])
    def test_send_favorites_prints_the_neutral_title_in_both_parts(
        self, sent, opportunity_id, base_title,
    ):
        raw = data_loader.load_opportunities_by_id()[opportunity_id]
        assert raw["title"].casefold().endswith("(applications open)")

        response = _post("/api/email/send-favorites", [{"opportunity_id": opportunity_id}])
        assert response.status_code == 200

        for part in (sent["html"], sent["text"]):
            assert base_title in part
            # The claim itself is gone from BOTH parts. A fix applied only to
            # the HTML leaves it in the plain-text alternative, which is what
            # a text-only client renders.
            assert "applications open" not in part.casefold()
            # Still labelled for what it is, and still source-only: no due
            # line and no apply affordance for a record we cannot vouch for.
            assert "Record type unverified" in part
        assert "due " not in sent["text"].casefold()

    def test_send_matches_still_refuses_these_before_any_work(self, refused):
        # The digest-level refusal is unchanged: a matches digest is a list of
        # things worth acting on, and an unreviewed row is not one.
        response = _post("/api/email/send-matches", [{"opportunity_id": self.URSA_ID}])
        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "record_kind_unverified"
        assert _quota_used() == 0

    def test_a_lecturer_is_not_promoted_to_professor_in_either_part(
        self, sent, monkeypatch,
    ):
        # `displayed_title` is what removes an honorific the record's own
        # stated rank contradicts. The digest skipped it entirely, so a
        # Lecturer went out as "Prof." in a mailed shortlist — a claim about a
        # named real person's job title, sent under our name.
        record = {
            "id": "rank-poison-1",
            "source_type": "faculty_research",
            # The exact legacy prefix `displayed_title` rewrites, and the rank
            # at `metadata.faculty_title` where `stated_rank` reads it. A
            # top-level `faculty_title` or a bare "Prof. X" exercises neither.
            "title": "Research with Prof. Dana Reyes — Systems",
            "url": "https://example.edu/people/reyes",
            "metadata": {"faculty_title": "Lecturer"},
        }
        monkeypatch.setattr(
            email_mod, "load_opportunities_by_id", lambda: {"rank-poison-1": record},
        )

        response = _post("/api/email/send-favorites", [{"opportunity_id": "rank-poison-1"}])
        assert response.status_code == 200

        for part in (sent["html"], sent["text"]):
            assert "Research with Dana Reyes — Systems" in part
            assert "Research with Prof." not in part
        # The corpus record itself is untouched — only the projection changed.
        assert record["title"] == "Research with Prof. Dana Reyes — Systems"


# ---------------------------------------------------------------------------
# The legacy identity bridge
# ---------------------------------------------------------------------------
# Vercel and Render deploy independently. HEAD's bundle mails items with NO
# `opportunity_id` — it sends the describing fields and nothing else — so for
# the length of the rollout window that old client talks to this backend and
# every send it makes 422s.
#
# The bridge resolves those items against the corpus by an EXACT public
# locator: the (public title, public top-level url) pair the client was served
# in the first place. Nothing is trimmed, casefolded or fuzzily matched, and
# nothing else the client sent is allowed to break a tie — a digest that
# GUESSED which record the reader meant would be exactly the false claim the
# rest of this file exists to prevent. Zero matches and two matches are both
# refusals, and the id path is untouched.

LEGACY_TITLE = "Stubbed target"
LEGACY_URL = "https://example.edu/display"

# Written out in full rather than compared field by field. A refusal a client
# branches on is a wire contract: the code it switches on, the reason it logs,
# the sentence it shows a reader, and whether its retry layer may fire again.
# Asserting only `reason` lets the message drift into something that reads like
# a server fault, and lets `retryable` flip without a single test noticing.
_LEGACY_UNRESOLVED = {
    "code": "TARGET_NOT_ACTIONABLE",
    "reason": "legacy_identity_unresolved",
    "message": (
        "One of these results no longer matches a current record. "
        "Refresh and try again."
    ),
    "retryable": False,
}
_LEGACY_AMBIGUOUS = {
    "code": "TARGET_NOT_ACTIONABLE",
    "reason": "legacy_identity_ambiguous",
    "message": (
        "One of these results matches more than one current record. "
        "Refresh and try again."
    ),
    "retryable": False,
}
_DUPLICATE_TARGET = {
    "code": "DUPLICATE_TARGET",
    "reason": "duplicate_opportunity_id",
    "message": "The same result was listed twice. Refresh and try again.",
    "retryable": False,
}
_MISSING_TARGET = {
    "code": "TARGET_NOT_ACTIONABLE",
    "reason": "unresolved",
    "message": "One of these results is no longer available. Refresh and try again.",
    "retryable": False,
}

# A Lecturer whose legacy title calls them "Prof.". `displayed_title` drops the
# honorific the record's own stated rank contradicts, so the public title the
# client was SERVED differs from the raw corpus title — which makes this the one
# fixture that can tell a locator built from the projection apart from one built
# from `record["title"]`.
LECTURER_RAW_TITLE = "Research with Prof. Dana Reyes — Systems"
LECTURER_PUBLIC_TITLE = "Research with Dana Reyes — Systems"
LECTURER_URL = "https://example.edu/people/reyes"


def _lecturer_stub() -> dict:
    return _stub_record(
        "lecturer-1",
        source_type="faculty_research",
        title=LECTURER_RAW_TITLE,
        url=LECTURER_URL,
        metadata={"is_active": True, "faculty_title": "Lecturer"},
    )


# The Lecturer above has no `pi_name`, so the faculty projection leaves its
# title alone and only `displayed_title` moves it — which means it cannot tell
# whether `faculty_safe_public_record` is in the chain at all. This one is the
# mirror image: a directory heading `displayed_title` has no opinion about,
# which the faculty projection replaces with the person's name. Between them,
# dropping EITHER step from the locator is caught.
DIRECTORY_RAW_TITLE = "Undergraduate Research Directory — Systems Group"
DIRECTORY_PI_NAME = "Dana Reyes"
DIRECTORY_URL = "https://example.edu/directory"


def _directory_stub() -> dict:
    return _stub_record(
        "directory-1",
        source_type="faculty_research",
        title=DIRECTORY_RAW_TITLE,
        pi_name=DIRECTORY_PI_NAME,
        url=DIRECTORY_URL,
        metadata={"is_active": True},
    )


def _legacy(**overrides) -> dict:
    """One old-client item: describing fields, no id."""
    item = {"title": LEGACY_TITLE, "url": LEGACY_URL}
    item.update(overrides)
    return item


class TestALegacyItemResolvesOnlyToOneExactRecord:
    def test_a_unique_legacy_match_sends_and_says_only_canonical_things(
        self, corpus, sent,
    ):
        corpus([_stub_record("open-1")])
        response = _post("/api/email/send-matches", [_legacy(
            source="fabricated_source",
            deadline="2098-01-01",
            organization="CLIENT ORG",
            record_kind="faculty_contact",
            score=99,
        )])

        assert response.status_code == 200
        assert response.json()["count"] == 1
        body = sent["html"] + sent["text"]
        # Every describing field is re-read from the record it resolved to.
        assert "Stubbed target" in body
        assert "test_source" in sent["html"]
        assert "Test University" in sent["html"]
        assert "Opportunity listing" in body
        # And none of the client's version of those fields survives.
        for lie in ("fabricated_source", "2098-01-01", "CLIENT ORG", "99%"):
            assert lie not in body, lie
        assert "Faculty contact profile" not in body

    def test_a_unique_legacy_favorite_keeps_the_users_own_words(self, corpus, sent):
        corpus([_stub_record("open-1")])
        response = _post("/api/email/send-favorites", [_legacy(
            notes="emailed the PI in March", status="applied",
        )])

        assert response.status_code == 200
        assert "emailed the PI in March" in sent["html"]
        assert "applied" in sent["html"]
        assert "Stubbed target" in sent["html"]

    def test_poisoning_every_other_field_cannot_move_the_identity(
        self, corpus, sent,
    ):
        """Only title and url are the key.

        If source, deadline, organization, kind or score took part in the
        lookup, an old client that had drifted on any one of them would stop
        resolving — and the reader would be told their saved result no longer
        exists because a scraped source label changed.
        """
        corpus([_stub_record("open-1")])
        response = _post("/api/email/send-matches", [_legacy(
            source="not_the_source",
            deadline="1999-01-01",
            organization="Not The University",
            record_kind="unknown",
            score=0,
        )])

        assert response.status_code == 200
        assert "Stubbed target" in sent["html"]

    def test_an_id_still_wins_over_every_legacy_field_beside_it(self, corpus, sent):
        """A current client sends both. The id decides, alone."""
        corpus([
            _stub_record("open-1"),
            _stub_record(
                "other-1",
                title="Other target",
                url="https://example.edu/other",
                organization="Wrong University",
            ),
        ])
        response = _post("/api/email/send-matches", [{
            "opportunity_id": "open-1",
            "title": "Other target",
            "url": "https://example.edu/other",
            "organization": "Wrong University",
        }])

        assert response.status_code == 200
        body = sent["html"] + sent["text"]
        assert "Stubbed target" in body
        assert "Other target" not in body
        assert "Wrong University" not in body

    @pytest.mark.parametrize(
        ("label", "item"),
        [
            ("omitted", {"title": LEGACY_TITLE, "url": LEGACY_URL}),
            ("explicit-null", {
                "opportunity_id": None, "title": LEGACY_TITLE, "url": LEGACY_URL,
            }),
        ],
    )
    @pytest.mark.parametrize(
        "path", ["/api/email/send-matches", "/api/email/send-favorites"],
    )
    def test_both_ways_of_saying_no_id_take_the_bridge(
        self, path, label, item, corpus, sent,
    ):
        """A missing key and an explicit `null` are the same statement.

        Old clients do both — one omits the field, another serializes the
        absent value — and a bridge that only recognised one of them would
        422 half the fleet for a difference the reader cannot see.
        """
        corpus([_stub_record("open-1")])
        response = _post(path, [item])

        assert response.status_code == 200, label
        assert "Stubbed target" in sent["html"], label


class TestTheLocatorIsTheProjectedPublicTitleNotTheRawOne:
    """The client echoes back what it was SERVED.

    A locator built from `record["title"]` would look up a string no client was
    ever given: the public projection strips an honorific the record's own
    stated rank contradicts before the title reaches a card. Under that mistake
    every faculty row whose legacy title says "Prof." stops resolving, and the
    reader is told their saved result no longer exists.
    """

    def test_the_public_title_resolves(self, corpus, sent):
        corpus([_lecturer_stub()])
        response = _post(
            "/api/email/send-matches",
            [_legacy(title=LECTURER_PUBLIC_TITLE, url=LECTURER_URL)],
        )

        assert response.status_code == 200
        assert LECTURER_PUBLIC_TITLE in sent["html"]
        assert "Prof." not in sent["html"] + sent["text"]

    def test_the_raw_corpus_title_does_not(self, corpus, refused):
        corpus([_lecturer_stub()])
        response = _post(
            "/api/email/send-matches",
            [_legacy(title=LECTURER_RAW_TITLE, url=LECTURER_URL)],
        )

        assert response.status_code == 409
        assert response.json()["detail"] == _LEGACY_UNRESOLVED
        assert _quota_used() == 0

    def test_each_case_isolates_a_different_projection_step(self):
        """Neither fixture can stand in for the other.

        The Lecturer is untouched by the faculty projection (no `pi_name` to
        rewrite to), and the directory heading is untouched by
        `displayed_title` (no honorific to strip). A locator missing either
        step still resolves one of them — and fails the other.
        """
        from backend.lib.position_truth import displayed_title
        from src.evidence import faculty_safe_public_record

        lecturer = _lecturer_stub()
        assert displayed_title(lecturer) == LECTURER_PUBLIC_TITLE
        assert faculty_safe_public_record(lecturer)["title"] == LECTURER_RAW_TITLE

        directory = _directory_stub()
        assert displayed_title(directory) == DIRECTORY_RAW_TITLE
        assert faculty_safe_public_record(directory)["title"] == DIRECTORY_PI_NAME

    def test_the_faculty_projected_name_resolves(self, corpus, sent):
        corpus([_directory_stub()])
        response = _post(
            "/api/email/send-matches",
            [_legacy(title=DIRECTORY_PI_NAME, url=DIRECTORY_URL)],
        )

        assert response.status_code == 200
        assert response.json()["count"] == 1
        # Resolved BY the public name, and described AS the public name. When
        # the locator and the rendered row disagree, the digest names a record
        # the reader was never shown — it would resolve "Dana Reyes" and then
        # print a directory heading over it.
        assert DIRECTORY_PI_NAME in sent["html"]
        assert DIRECTORY_PI_NAME in sent["text"]
        assert DIRECTORY_RAW_TITLE not in sent["html"] + sent["text"]

    def test_the_raw_directory_heading_does_not(self, corpus, refused):
        corpus([_directory_stub()])
        response = _post(
            "/api/email/send-matches",
            [_legacy(title=DIRECTORY_RAW_TITLE, url=DIRECTORY_URL)],
        )

        assert response.status_code == 409
        assert response.json()["detail"] == _LEGACY_UNRESOLVED
        assert _quota_used() == 0


class TestEveryStepOfTheLocatorChainIsLoadBearing:
    """One fixture per projection step, each isolating a different omission.

    The two faculty cases above cover `faculty_safe_public_record` and
    `displayed_title`. These cover the remaining two — the lifecycle neutralizer
    and the text/URL boundaries — so dropping ANY link from the chain in
    `_public_locator` turns a resolving request into a refusal (or, worse, lets
    a locator resolve that the API would never have published).
    """

    def test_a_lifecycle_suffix_is_neutralized_in_the_locator(self, corpus, sent):
        # Unreviewed kind, so the neutralizer applies and the card said
        # "URSA Program" while the corpus row still says "(applications open)".
        corpus([_stub_record(
            "lifecycle-1", source_type=None, title="URSA Program (applications open)",
        )])
        response = _post("/api/email/send-favorites", [_legacy(title="URSA Program")])

        assert response.status_code == 200
        assert "applications open" not in (sent["html"] + sent["text"]).casefold()

    def test_the_raw_lifecycle_title_does_not_resolve(self, corpus, refused):
        corpus([_stub_record(
            "lifecycle-1", source_type=None, title="URSA Program (applications open)",
        )])
        response = _post(
            "/api/email/send-favorites",
            [_legacy(title="URSA Program (applications open)")],
        )

        assert response.status_code == 409
        assert response.json()["detail"] == _LEGACY_UNRESOLVED
        assert _quota_used() == 0

    def test_a_redacted_title_is_what_the_client_holds(self, corpus, sent):
        # `stanford-f0a974ed2bd2` is this shape for real: the TITLE is an
        # address, so every surface shows the placeholder and that placeholder
        # is the only title any client was ever given.
        corpus([_stub_record("addr-1", title="vpue-fellowships@stanford.edu")])
        response = _post("/api/email/send-matches", [_legacy(title="[email redacted]")])

        assert response.status_code == 200
        assert "[email redacted]" in sent["html"]
        assert "vpue-fellowships" not in sent["html"] + sent["text"]

    def test_the_unredacted_address_does_not_resolve(self, corpus, refused):
        """Otherwise the locator is a lookup table from address to record."""
        corpus([_stub_record("addr-1", title="vpue-fellowships@stanford.edu")])
        response = _post(
            "/api/email/send-matches",
            [_legacy(title="vpue-fellowships@stanford.edu")],
        )

        assert response.status_code == 409
        assert response.json()["detail"] == _LEGACY_UNRESOLVED
        assert _quota_used() == 0

    @pytest.mark.parametrize(
        ("label", "unsafe"),
        [
            ("javascript", "javascript:alert(1)"),
            ("embedded-credentials", "https://attacker.example:hunter2@evil.test/x"),
        ],
    )
    def test_an_unsafe_top_level_url_locates_on_the_empty_string(
        self, label, unsafe, corpus, sent,
    ):
        # The public URL contract refuses it, so the client was served no URL
        # for this record at all — and "" is exactly what it echoes back.
        corpus([_stub_record("unsafe-1", url=unsafe)])
        response = _post("/api/email/send-favorites", [_legacy(url="")])

        assert response.status_code == 200, label
        assert "evil.test" not in sent["html"] + sent["text"], label
        assert "javascript:" not in sent["html"] + sent["text"], label

    @pytest.mark.parametrize(
        ("label", "unsafe"),
        [
            ("javascript", "javascript:alert(1)"),
            ("embedded-credentials", "https://attacker.example:hunter2@evil.test/x"),
        ],
    )
    def test_the_raw_unsafe_url_does_not_resolve(
        self, label, unsafe, corpus, refused,
    ):
        corpus([_stub_record("unsafe-1", url=unsafe)])
        response = _post("/api/email/send-favorites", [_legacy(url=unsafe)])

        assert response.status_code == 409, label
        assert response.json()["detail"] == _LEGACY_UNRESOLVED, label
        assert _quota_used() == 0, label


class TestAnIdThatResolvesToNothingNeverFallsBackToTheLocator:
    """The id is a statement, not a hint.

    A client that sends an id is claiming to know which record it means. If
    that id no longer resolves, quietly resolving its describing fields instead
    would mail a DIFFERENT record than the one requested — and the reader would
    have no way to tell, because everything printed would be internally
    consistent.
    """

    @pytest.mark.parametrize(
        "path", ["/api/email/send-matches", "/api/email/send-favorites"],
    )
    def test_a_dead_id_beside_a_resolvable_locator_still_refuses(
        self, path, corpus, refused,
    ):
        corpus([_stub_record("open-1")])
        response = _post(path, [{
            "opportunity_id": "no-such-record-anywhere",
            "title": LEGACY_TITLE,
            "url": LEGACY_URL,
        }])

        assert response.status_code == 409
        # The id's own refusal, not the locator's — they are different
        # sentences and a client branches on the difference.
        assert response.json()["detail"] == _MISSING_TARGET
        assert _quota_used() == 0


class TestTheLegacyLocatorIsExact:
    @pytest.mark.parametrize(
        ("label", "overrides"),
        [
            ("lowercased-title", {"title": "stubbed target"}),
            ("uppercased-title", {"title": "STUBBED TARGET"}),
            ("leading-space-title", {"title": " Stubbed target"}),
            ("trailing-space-title", {"title": "Stubbed target "}),
            ("prefix-title", {"title": "Stubbed"}),
            ("longer-title", {"title": "Stubbed target (Test University)"}),
            ("trailing-slash-url", {"url": "https://example.edu/display/"}),
            ("cased-path-url", {"url": "https://example.edu/Display"}),
            ("http-url", {"url": "http://example.edu/display"}),
            # URL whitespace, not only title whitespace. The public URL
            # contract already refuses a value with leading or interior
            # spaces, so a resolver that trimmed before looking up would
            # accept a locator the API would never have served.
            ("leading-space-url", {"url": " https://example.edu/display"}),
            ("trailing-space-url", {"url": "https://example.edu/display "}),
            ("interior-space-url", {"url": "https://example.edu/dis play"}),
            ("trailing-newline-url", {"url": "https://example.edu/display\n"}),
        ],
    )
    def test_a_near_miss_is_not_the_same_record(self, label, overrides, corpus, refused):
        corpus([_stub_record("open-1")])
        response = _post("/api/email/send-matches", [_legacy(**overrides)])

        assert response.status_code == 409, label
        assert response.json()["detail"] == _LEGACY_UNRESOLVED, label
        assert _quota_used() == 0, label

    @pytest.mark.parametrize(
        ("label", "url"),
        [
            ("top-level", "https://example.edu/display"),
            ("source", "https://example.edu/scraped"),
            ("application", "https://example.edu/apply-here"),
        ],
    )
    def test_only_the_top_level_url_is_the_locator(self, label, url, corpus, sent):
        """`_describe` prefers source_url, and the row LINKS to the apply URL.

        Neither is the identity. The client was served the record's top-level
        `url`, so that is the only value it can be asked to echo back.

        One fixture, not `sent` AND `refused`: those patch the same provider,
        the second one wins, and the positive case then fails inside a spy that
        was only meant to guard the negatives.
        """
        corpus([_stub_record("open-1")])
        response = _post("/api/email/send-favorites", [_legacy(url=url)])

        if label == "top-level":
            assert response.status_code == 200
            assert "Stubbed target" in sent["html"]
        else:
            assert response.status_code == 409, label
            assert response.json()["detail"] == _LEGACY_UNRESOLVED, label
            assert _quota_used() == 0, label

    def test_a_record_with_no_top_level_url_resolves_on_the_empty_string(
        self, corpus, sent,
    ):
        corpus([_stub_record("nourl-1", url=None)])
        response = _post("/api/email/send-favorites", [_legacy(url="")])

        assert response.status_code == 200
        assert "Stubbed target" in sent["html"]


class TestAnUnresolvableOrAmbiguousLegacyItemIsRefusedForFree:
    def test_no_candidate_refuses_before_the_quota(self, corpus, refused):
        corpus([_stub_record("open-1")])
        response = _post("/api/email/send-matches", [_legacy(title="Nothing like this")])

        assert response.status_code == 409
        assert response.json()["detail"] == _LEGACY_UNRESOLVED
        assert _quota_used() == 0

    @pytest.mark.parametrize(
        "path", ["/api/email/send-matches", "/api/email/send-favorites"],
    )
    def test_two_candidates_refuse_rather_than_pick_one(self, path, corpus, refused):
        """The live row must NOT quietly win over the historical one.

        Both were published under the same title and the same URL, so the
        request genuinely does not say which the reader saved. Preferring the
        actionable one would mail a live opening to someone who had shortlisted
        a closed record — a fabricated claim, arrived at silently.

        Favorites refuses too: a shortlist keeps history, but "we could not
        tell which record this is" is an identity failure, not a history one.
        """
        corpus([
            _stub_record("twin-live"),
            _stub_record(
                "twin-dead", metadata={"is_active": True, "urap_status": "closed"},
            ),
        ])
        response = _post(path, [_legacy()])

        assert response.status_code == 409
        assert response.json()["detail"] == _LEGACY_AMBIGUOUS
        assert _quota_used() == 0


class TestOnlyReleaseVisibleRecordsCanBeResolved:
    """The index is built from the release surface, not the raw corpus.

    Fellowships are hidden by the current release scope, and the id path
    already refuses one through `release_visible_opportunity_by_id`. Indexing
    `lookup.values()` instead would hand the legacy path a private back door
    into exactly the records the release decided not to publish — and, worse,
    would let a hidden record collide with a visible one and turn a perfectly
    resolvable request into a permanent ambiguity refusal.
    """

    @pytest.fixture(autouse=True)
    def _fellowships_hidden(self, monkeypatch):
        """`tests/conftest.py` opens every release feature for the suite.

        That is the right default nearly everywhere, but this class is
        specifically about a record the release HIDES — under the suite-wide
        patch the fellowship below is visible and every assertion here passes
        while proving nothing. So the production answer is restored for that
        ONE feature, delegating every other feature to whatever is already
        installed rather than flipping a global other tests depend on.
        """
        from backend.lib import release_scope

        installed = release_scope.feature_enabled

        def only_fellowships_hidden(feature):
            return False if feature == "fellowships" else installed(feature)

        monkeypatch.setattr(
            release_scope, "feature_enabled", only_fellowships_hidden,
        )

    def _fellowship(self, opportunity_id: str, **overrides) -> dict:
        return _stub_record(
            opportunity_id, opportunity_type="fellowship", **overrides,
        )

    def test_the_release_really_does_hide_fellowships(self):
        """Otherwise both tests below pass without proving anything."""
        from backend.lib.release_scope import opportunity_visible_in_release

        assert opportunity_visible_in_release(self._fellowship("f-probe")) is False
        assert opportunity_visible_in_release(_stub_record("v-probe")) is True

    def test_a_hidden_record_sharing_the_key_does_not_create_ambiguity(
        self, corpus, sent,
    ):
        corpus([_stub_record("visible-1"), self._fellowship("hidden-1")])
        response = _post("/api/email/send-matches", [_legacy()])

        assert response.status_code == 200
        assert "Stubbed target" in sent["html"]

    @pytest.mark.parametrize(
        "path", ["/api/email/send-matches", "/api/email/send-favorites"],
    )
    def test_a_key_unique_to_a_hidden_record_resolves_to_nothing(
        self, path, corpus, refused,
    ):
        corpus([
            _stub_record("visible-1"),
            self._fellowship(
                "hidden-1",
                title="Hidden fellowship",
                url="https://example.edu/hidden",
            ),
        ])
        response = _post(path, [
            _legacy(title="Hidden fellowship", url="https://example.edu/hidden"),
        ])

        assert response.status_code == 409
        assert response.json()["detail"] == _LEGACY_UNRESOLVED
        assert _quota_used() == 0

    @pytest.mark.parametrize(
        ("label", "item"),
        [
            ("no-url", {"title": LEGACY_TITLE}),
            ("no-title", {"url": LEGACY_URL}),
            ("neither", {}),
            ("empty-title", {"title": "", "url": LEGACY_URL}),
            ("null-title", {"title": None, "url": LEGACY_URL}),
            ("null-url", {"title": LEGACY_TITLE, "url": None}),
            ("numeric-title", {"title": 17, "url": LEGACY_URL}),
            ("numeric-url", {"title": LEGACY_TITLE, "url": 17}),
            ("blank-id", {"opportunity_id": "", "title": LEGACY_TITLE, "url": LEGACY_URL}),
            ("spaces-id", {"opportunity_id": "   ", "title": LEGACY_TITLE, "url": LEGACY_URL}),
            ("tab-id", {"opportunity_id": "\t\n", "title": LEGACY_TITLE, "url": LEGACY_URL}),
        ],
    )
    @pytest.mark.parametrize(
        "path", ["/api/email/send-matches", "/api/email/send-favorites"],
    )
    def test_an_unusable_identity_is_a_schema_refusal(
        self, path, label, item, corpus, refused,
    ):
        """A blank id is malformed, never an invitation to fall back.

        Reading "" as "this client is old, use the title" would let a current
        client with one empty field silently address a DIFFERENT record than
        the one it holds the id for.
        """
        corpus([_stub_record("open-1")])
        response = _post(path, [item])

        assert response.status_code == 422, label
        assert _quota_used() == 0, label


class TestCanonicalIdentityIsWhatGetsDeduplicated:
    def test_an_id_and_a_legacy_item_naming_one_record_is_a_duplicate(
        self, corpus, refused,
    ):
        """Deduplication happens AFTER resolution.

        Compared as request shapes these two items look nothing alike, so a
        pre-resolution check passes them both and the reader gets the same row
        twice under a count that says one.
        """
        corpus([_stub_record("open-1")])
        response = _post("/api/email/send-matches", [
            {"opportunity_id": "open-1"},
            _legacy(),
        ])

        # Compared whole, not indexed. A schema 422 carries a pydantic error
        # LIST, so `json()["detail"]["code"]` raises TypeError there — which
        # would report as an error rather than as this contract failing, and
        # would let the old required-id 422 masquerade as a duplicate refusal.
        assert response.status_code == 422
        assert response.json()["detail"] == _DUPLICATE_TARGET
        assert _quota_used() == 0

    def test_two_legacy_items_naming_one_record_are_a_duplicate(
        self, corpus, refused,
    ):
        corpus([_stub_record("open-1")])
        response = _post("/api/email/send-favorites", [_legacy(), _legacy()])

        # Compared whole, not indexed. A schema 422 carries a pydantic error
        # LIST, so `json()["detail"]["code"]` raises TypeError there — which
        # would report as an error rather than as this contract failing, and
        # would let the old required-id 422 masquerade as a duplicate refusal.
        assert response.status_code == 422
        assert response.json()["detail"] == _DUPLICATE_TARGET
        assert _quota_used() == 0

    def test_two_different_records_are_not_a_duplicate(self, corpus, sent):
        """The control: deduplication must not collapse a legitimate pair."""
        corpus([
            _stub_record("open-1"),
            _stub_record("open-2", title="Another target", url="https://example.edu/two"),
        ])
        response = _post("/api/email/send-matches", [
            _legacy(),
            _legacy(title="Another target", url="https://example.edu/two"),
        ])

        assert response.status_code == 200
        assert response.json()["count"] == 2


class TestHistoryIsRefusedByMatchesAndKeptByFavorites:
    HISTORICAL = {"metadata": {"is_active": True, "urap_status": "closed"}}

    def test_a_uniquely_resolved_historical_favorite_stays_and_is_labelled(
        self, corpus, sent,
    ):
        corpus([_stub_record("closed-1", **self.HISTORICAL)])
        response = _post("/api/email/send-favorites", [_legacy(notes="ask about this")])

        assert response.status_code == 200
        assert "Closed — no longer accepting applications" in sent["html"]
        assert "ask about this" in sent["html"]
        # Source-only, exactly as the id path renders it.
        assert " · due " not in sent["text"]
        assert "apply-here" not in sent["html"]
        assert "https://example.edu/scraped" in sent["html"]

    def test_the_same_historical_row_refuses_the_whole_match_digest(
        self, corpus, refused,
    ):
        corpus([_stub_record("closed-1", **self.HISTORICAL)])
        response = _post("/api/email/send-matches", [_legacy()])

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "TARGET_NOT_ACTIONABLE"
        assert detail["reason"] == "listing_closed"
        assert _quota_used() == 0

    def test_a_legacy_faculty_row_that_said_no_still_refuses(self, corpus, refused):
        corpus([_faculty_stub("stop-1", NOT_ACCEPTING)])
        response = _post(
            "/api/email/send-matches",
            [_legacy(title="Prof. Alex Rivera")],
        )

        assert response.status_code == 409
        assert response.json()["detail"]["reason"] == "faculty_not_accepting"
        assert _quota_used() == 0


class TestTheLegacyScanCostsOneSnapshotAndNoEventLoopTime:
    def test_the_corpus_is_read_once_for_a_multi_item_request(
        self, monkeypatch, sent,
    ):
        """One snapshot, one index.

        Resolving per item could straddle a corpus refresh and mail a digest
        assembled from two generations of the data. The second snapshot below
        describes the same ids differently; if anything read it, it would show.
        """
        first = {r["id"]: r for r in [
            _stub_record("open-1"),
            _stub_record("open-2", title="Another target", url="https://example.edu/two"),
        ]}
        second = {r["id"]: r for r in [
            _stub_record("open-1", organization="SECOND SNAPSHOT"),
            _stub_record(
                "open-2", title="Another target", url="https://example.edu/two",
                organization="SECOND SNAPSHOT",
            ),
        ]}
        calls: list[int] = []

        def loader():
            calls.append(1)
            return second if len(calls) > 1 else first

        builds: list[int] = []
        real_index = email_mod._build_legacy_index

        def counting_index(lookup):
            builds.append(1)
            return real_index(lookup)

        monkeypatch.setattr(email_mod, "load_opportunities_by_id", loader)
        monkeypatch.setattr(email_mod, "_build_legacy_index", counting_index)
        response = _post("/api/email/send-matches", [
            _legacy(),
            _legacy(title="Another target", url="https://example.edu/two"),
        ])

        assert response.status_code == 200
        assert calls == [1], "the loader is called exactly once per request"
        # The loader count alone does not kill rebuilding the index per item:
        # a resolver that re-scanned the SAME snapshot for every item reads the
        # corpus once and still pays the full scan N times.
        assert builds == [1], "the locator index is built exactly once per request"
        assert "SECOND SNAPSHOT" not in sent["html"] + sent["text"]

    def test_the_legacy_scan_never_runs_on_the_event_loop(
        self, corpus, sent, monkeypatch,
    ):
        """Scanning every release-visible record takes seconds.

        Run inline in an async handler it blocks the ONE event loop this
        process has, so every other in-flight request — matches, detail,
        health — stops until it finishes. It has to be offloaded, and the only
        proof that it was is that no running loop is visible from inside it.
        """
        import asyncio

        seen: dict[str, bool] = {}
        real = email_mod._build_legacy_index

        def spy(lookup):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                seen["on_event_loop"] = False
            else:
                seen["on_event_loop"] = True
            return real(lookup)

        monkeypatch.setattr(email_mod, "_build_legacy_index", spy)
        corpus([_stub_record("open-1")])
        response = _post("/api/email/send-matches", [_legacy()])

        assert response.status_code == 200
        assert seen == {"on_event_loop": False}

    def test_another_request_is_served_while_the_scan_is_still_running(
        self, corpus, sent, monkeypatch,
    ):
        """Liveness, not just placement.

        "No running loop is visible in here" proves the call was offloaded. It
        does not prove the loop stayed USABLE — that is what a stalled service
        actually looks like to everyone else. So: hold the scan open, and
        require an unrelated request to complete end-to-end before releasing
        it. Every wait is bounded, so a mutant that runs the scan inline fails
        in seconds rather than hanging the suite.
        """
        import asyncio
        import threading

        import httpx

        started = threading.Event()
        release = threading.Event()
        real = email_mod._build_legacy_index

        def blocking(lookup):
            started.set()
            # Bounded: inline on the event loop nothing can ever release this,
            # so it gives up and the request fails instead of hanging.
            if not release.wait(timeout=5.0):
                raise AssertionError(
                    "the event loop was blocked — no other request could be served",
                )
            return real(lookup)

        monkeypatch.setattr(email_mod, "_build_legacy_index", blocking)
        corpus([_stub_record("open-1")])

        async def drive():
            transport = httpx.ASGITransport(app=main_mod.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as async_client:
                digest = asyncio.create_task(async_client.post(
                    "/api/email/send-matches",
                    json={"email": "reader@example.com", "items": [_legacy()]},
                ))
                for _ in range(300):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.01)
                assert started.is_set(), "the scan never started"

                # The whole point: this must complete while the scan is held.
                light = await asyncio.wait_for(
                    async_client.get("/api/health"), timeout=3.0,
                )
                release.set()
                return light, await asyncio.wait_for(digest, timeout=15.0)

        light, digest = asyncio.run(drive())

        assert light.status_code == 200, "an unrelated request was starved"
        assert digest.status_code == 200

    @pytest.mark.parametrize(
        "path", ["/api/email/send-matches", "/api/email/send-favorites"],
    )
    def test_an_id_only_request_never_builds_the_index_at_all(
        self, path, corpus, sent, monkeypatch,
    ):
        """The current client pays nothing for the bridge."""
        def forbidden(_lookup):
            raise AssertionError("the legacy index was built for an id-only request")

        monkeypatch.setattr(email_mod, "_build_legacy_index", forbidden)
        corpus([_stub_record("open-1")])
        response = _post(path, [{"opportunity_id": "open-1"}])

        assert response.status_code == 200


class TestOnlyTheSignedInReaderCanBeMailed:
    """A digest goes to the address the account proved it owns, or nowhere.

    Before this, both endpoints took the recipient straight off the wire with
    no session at all: an unauthenticated POST would mail a JoinALab-branded
    digest to any address a stranger named, over the domain that also carries
    every magic link. #790 had already closed the other half — every describing
    field is re-read from the corpus, so the CONTENT could no longer be
    forged — which left exactly this: real mail, real corpus, arbitrary
    recipient.

    Refusals here must also be free. They run before the recipient quota and
    before the provider, so an abusive caller cannot spend either.
    """

    @pytest.fixture
    def anonymous(self, monkeypatch):
        async def identity(_authorization):
            return None

        monkeypatch.setattr(email_mod, "authenticated_identity", identity)

    @pytest.fixture
    def unconfirmed(self, monkeypatch):
        async def identity(_authorization):
            return SessionIdentity(uid="reader-uid", email=None)

        monkeypatch.setattr(email_mod, "authenticated_identity", identity)

    @pytest.mark.parametrize("path", ["/api/email/send-matches",
                                      "/api/email/send-favorites"])
    def test_a_stranger_cannot_mail_anyone(self, path, refused, anonymous):
        r = _post(path, [{"opportunity_id": LISTING_ID}])
        assert r.status_code == 401
        assert r.json()["detail"]["code"] == "SIGN_IN_REQUIRED"
        assert _quota_used() == 0

    @pytest.mark.parametrize("path", ["/api/email/send-matches",
                                      "/api/email/send-favorites"])
    def test_an_unconfirmed_address_is_not_a_send_target(self, path, refused,
                                                          unconfirmed):
        r = _post(path, [{"opportunity_id": LISTING_ID}])
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "EMAIL_NOT_CONFIRMED"
        assert _quota_used() == 0

    @pytest.mark.parametrize("path", ["/api/email/send-matches",
                                      "/api/email/send-favorites"])
    def test_naming_someone_else_is_refused_not_silently_redirected(self, path,
                                                                     refused):
        """Quietly mailing the reader instead would leave them believing a
        message went to the address they typed. Say no out loud."""
        r = client.post(path, json={"email": "someone.else@example.com",
                                    "items": [{"opportunity_id": LISTING_ID}]})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "RECIPIENT_NOT_SELF"
        assert _quota_used("someone.else@example.com") == 0
        assert _quota_used() == 0

    @pytest.mark.parametrize("path", ["/api/email/send-matches",
                                      "/api/email/send-favorites"])
    def test_the_session_address_is_what_is_actually_mailed(self, path, sent):
        """Not the request body's — even when they agree, the value that
        reaches the provider comes from the session."""
        r = client.post(path, json={"email": "READER@Example.COM",
                                    "items": [{"opportunity_id": LISTING_ID}]})
        assert r.status_code == 200, r.text
        assert sent["to"] == READER

    @pytest.mark.parametrize("path", ["/api/email/send-matches",
                                      "/api/email/send-favorites"])
    def test_an_omitted_recipient_is_accepted_and_resolved_from_the_session(
        self, path, sent,
    ):
        """The field is a rollout bridge, not a requirement: a client that has
        stopped sending it must not 422 during the deploy window."""
        r = client.post(path, json={"items": [{"opportunity_id": LISTING_ID}]})
        assert r.status_code == 200, r.text
        assert sent["to"] == READER
