"""Contract tests for the saved-search weekly email digest.

Covers GET /api/cron/saved-searches/digest (CRON_SECRET-guarded sender)
and GET /api/email/digest-unsubscribe (HMAC-token opt-out). All Supabase
and Resend traffic is stubbed at the httpx / _send_via_resend boundary —
tests never touch the network. The core invariants pinned here:

  * no email is ever sent without digest_opt_in (the Supabase query
    filters on it; rows the stub returns ARE the opted-in set)
  * one digest per search per 7 days (last_digest_sent_at throttle)
  * RESEND env unset -> status "skipped", zero sends (push.py pattern)
  * unsubscribe signing-secret unset -> sender refuses to run at all
  * unsubscribe token: valid flips the row off; tampered/expired -> 400
"""

from __future__ import annotations

import os
import sys
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.data_loader import load_opportunities_by_id
from backend.lib.release_scope import opportunity_visible_in_release
from backend.main import app
from backend.routes import saved_searches as ss_mod
from src.evidence import faculty_availability_status, is_actionable_target

client = TestClient(app)

AUTH = {"Authorization": "Bearer cron-ok"}

# Both carry a reviewed source_type, because every served record does and an
# unreviewed one is no longer actionable — a digest fixture without one would
# be testing the 26-row exception while claiming to test the happy path. One
# of each confirmed kind, so the renderer's kind-specific copy is exercised
# rather than assumed.
_OPP_A = {"id": "opp-a", "title": "Vision Lab RA", "organization": "UIUC ECE",
          "source_type": "campus_program", "deadline": "2026-07-01"}
_OPP_B = {"id": "opp-b", "title": "NLP Internship", "organization": "Acme AI",
          "source_type": "campus_program", "deadline": ""}


def _digest_row(**overrides):
    row = {
        "id": "11111111-2222-3333-4444-555555555555",
        "name": "ML research",
        "digest_email": "user@example.com",
        "new_match_ids": ["opp-a", "opp-b"],
        "last_digest_sent_at": None,
    }
    row.update(overrides)
    return row


def _set_digest_env(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "cron-ok")
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    monkeypatch.setenv("RESEND_API_KEY", "fake")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "from@example.com")
    monkeypatch.setenv("RESTORE_LINK_SECRET", "digest-secret")


def _install_stubs(monkeypatch, *, rows, sends=None, patches=None,
                   opportunities=None, profiles=None):
    """Stub the digest route's three exits: Supabase httpx traffic,
    the Resend send helper, and the opportunities data file."""

    class _Resp:
        def __init__(self, data=None):
            self._data = data
            self.status_code = 200
            self.text = ""

        def json(self):
            return self._data

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            # The route reads the student's own profile to decide what its
            # matcher would exclude for them. Unsupplied means "unreadable",
            # which the route treats as "filter nothing" — so every test
            # written before this behaviour existed still describes it.
            if "/rest/v1/profiles" in url:
                return _Resp(profiles or [])
            return _Resp(rows)

        async def patch(self, url, **kwargs):
            if patches is not None:
                patches.append({"url": url, **kwargs})
            return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    async def _fake_send(**kwargs):
        if sends is not None:
            sends.append(kwargs)

    monkeypatch.setattr(ss_mod, "_send_via_resend", _fake_send)
    monkeypatch.setattr(
        ss_mod, "load_opportunities",
        lambda: opportunities if opportunities is not None else [_OPP_A, _OPP_B],
    )
    # Per-recipient quota is in-memory module state shared across tests.
    from backend.routes import email as email_mod
    email_mod._recipient_sends.clear()


class TestDigestCronAuth:
    def test_503_when_cron_secret_unset(self, monkeypatch):
        monkeypatch.delenv("CRON_SECRET", raising=False)
        r = client.get("/api/cron/saved-searches/digest")
        assert r.status_code == 503

    def test_401_when_wrong_secret(self, monkeypatch):
        monkeypatch.setenv("CRON_SECRET", "cron-ok")
        r = client.get("/api/cron/saved-searches/digest",
                       headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


class TestDigestCronSkips:
    def test_skipped_when_supabase_env_missing(self, monkeypatch):
        monkeypatch.setenv("CRON_SECRET", "cron-ok")
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "skipped"
        assert "SUPABASE_URL" in body["missing"]

    def test_skipped_when_resend_unset(self, monkeypatch):
        _set_digest_env(monkeypatch)
        monkeypatch.delenv("RESEND_API_KEY", raising=False)
        monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "skipped"
        assert body["reason"] == "resend not configured"

    def test_skipped_when_signing_secret_unset(self, monkeypatch):
        # Opt-in mail without a working unsubscribe link must never go out.
        _set_digest_env(monkeypatch)
        monkeypatch.delenv("RESTORE_LINK_SECRET", raising=False)
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row()], sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "skipped"
        assert sends == []


class TestDigestCronSend:
    def test_mixed_digest_labels_faculty_contact_without_opening_deadline(self):
        subject, html, text = ss_mod._render_digest_email(
            "ML research",
            [
                {
                    "id": "faculty-ada",
                    "title": "Ada profile",
                    "organization": "Test University",
                    "source_type": "faculty_research",
                    "deadline": "2099-12-31",
                },
                {
                    "id": "reu-1",
                    "title": "Real REU",
                    "organization": "Test University",
                    "source_type": "campus_program",
                    "deadline": "2027-02-01",
                },
            ],
            "https://example.test/unsubscribe",
        )

        assert subject.startswith("2 new matches")
        for body in (html, text):
            assert "Faculty contact profile" in body
            assert "current opening not confirmed" in body
            assert "2099-12-31" not in body
            assert "Opportunity listing" in body
            assert "2027-02-01" in body

    def test_happy_path_sends_one_email_and_stamps_sent_at(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        patches: list = []
        _install_stubs(monkeypatch, rows=[_digest_row()], sends=sends, patches=patches)

        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["sent"] == 1
        assert body["errors"] == []

        assert len(sends) == 1
        send = sends[0]
        assert send["to"] == "user@example.com"
        assert "ML research" in send["subject"]
        assert "Vision Lab RA" in send["html"]
        assert "/opportunities/opp-a" in send["html"]
        assert "digest-unsubscribe" in send["html"]
        assert "digest-unsubscribe" in send["text"]

        assert len(patches) == 1
        assert patches[0]["json"].keys() == {"last_digest_sent_at", "new_match_ids"}
        assert patches[0]["json"]["new_match_ids"] == []
        assert patches[0]["params"]["id"] == f"eq.{_digest_row()['id']}"

    def test_caps_items_at_ten_newest_first_with_overflow(self, monkeypatch):
        # new_match_ids accumulates oldest-first: opp-14 is the newest match.
        _set_digest_env(monkeypatch)
        opps = [{"id": f"opp-{i}", "title": f"Opp {i}", "organization": "Org",
                 "source_type": "campus_program", "deadline": ""} for i in range(15)]
        sends: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=[o["id"] for o in opps])],
            sends=sends, opportunities=opps,
        )
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.json()["sent"] == 1
        html = sends[0]["html"]
        assert "Opp 14" in html and "Opp 5" in html  # newest ten kept
        assert "Opp 4" not in html  # oldest five overflow
        assert html.index("Opp 14") < html.index("Opp 5")  # newest first
        assert sends[0]["subject"].startswith("15 new matches")  # whole batch
        assert "+5 more in the app" in html
        assert "+5 more in the app" in sends[0]["text"]

    def test_newest_first_in_text_body(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row()], sends=sends)
        client.get("/api/cron/saved-searches/digest", headers=AUTH)
        text = sends[0]["text"]
        # stored order is [opp-a, opp-b]; opp-b is newer so it renders first
        assert text.index("NLP Internship") < text.index("Vision Lab RA")

    def test_throttles_within_seven_days(self, monkeypatch):
        _set_digest_env(monkeypatch)
        recent = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(last_digest_sent_at=recent)],
                       sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        body = r.json()
        assert body["sent"] == 0
        assert body["throttled"] == 1
        assert sends == []

    def test_sends_again_after_seven_days(self, monkeypatch):
        _set_digest_env(monkeypatch)
        stale = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(last_digest_sent_at=stale)],
                       sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert r.json()["sent"] == 1
        assert len(sends) == 1

    def test_skips_rows_without_new_matches(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(new_match_ids=[])], sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        body = r.json()
        assert body["sent"] == 0
        assert body["skipped"] == 1
        assert sends == []

    def test_skips_invalid_stored_email(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(digest_email="not-an-email")],
                       sends=sends)
        r = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        body = r.json()
        assert body["sent"] == 0
        assert body["skipped"] == 1
        assert sends == []

    def test_escapes_html_in_titles(self, monkeypatch):
        _set_digest_env(monkeypatch)
        evil = {"id": "opp-x", "title": "<script>alert(1)</script>",
                "organization": "Org", "source_type": "campus_program", "deadline": ""}
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row(new_match_ids=["opp-x"])],
                       sends=sends, opportunities=[evil])
        client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert "<script>alert(1)</script>" not in sends[0]["html"]
        assert "&lt;script&gt;" in sends[0]["html"]


class TestDigestTextIsNeverMailedRaw:
    """The same leak the manual digests had, on the automated path.

    A weekly digest prints a corpus title and organization under our brand to
    someone who is not looking at the page. ``stanford-f0a974ed2bd2`` is a real
    record whose title is an address, and the addresses that hide in scraped
    text are rarely plain — so the shared detector decides, not a local check.
    Every row here is actionable, because this sender only mails actionable
    rows: a non-actionable one never reaches the renderer at all.
    """

    CONTACT_SHAPES = [
        ("plain", "vpue-fellowships@stanford.edu"),
        ("percent-encoded", "vpue-fellowships%40stanford.edu"),
        ("html-entity", "vpue-fellowships&#64;stanford.edu"),
        ("split-across-markup", "vpue-fellowships<span>@</span>stanford.edu"),
        ("bracket-obfuscated", "vpue-fellowships [at] stanford [dot] edu"),
        ("word-obfuscated", "vpue-fellowships at stanford dot edu"),
    ]

    # No surviving value may contain "stanford" — the domain check below is
    # the only thing that catches the obfuscated shapes, and a sibling field
    # mentioning the university would mask it.
    CLEAN = {
        "title": "Fellowships programme",
        "organization": "Undergraduate Research Office",
        "deadline": "2026-07-01",
    }

    @pytest.mark.parametrize("field", ["title", "organization", "deadline"])
    @pytest.mark.parametrize(
        ("label", "poison"), CONTACT_SHAPES, ids=[s[0] for s in CONTACT_SHAPES],
    )
    def test_an_address_in_a_digest_row_is_redacted(
        self, monkeypatch, field, label, poison,
    ):
        _set_digest_env(monkeypatch)
        poisoned = {"id": "opp-poison", "source_type": "campus_program",
                    **self.CLEAN}
        poisoned[field] = poison
        sends: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=["opp-a", "opp-poison"])],
            sends=sends,
            opportunities=[_OPP_A, poisoned],
        )
        client.get("/api/cron/saved-searches/digest", headers=AUTH)

        assert len(sends) == 1, label
        body = sends[0]["html"] + sends[0]["text"]
        # Local part and domain separately: the obfuscated shapes never spell
        # the assembled address, so matching only on that would pass while the
        # reader can still read it.
        assert "vpue-fellowships" not in body, label
        assert "stanford" not in body.lower(), label
        assert "[email redacted]" in sends[0]["html"], label
        assert "[email redacted]" in sends[0]["text"], label
        # The poisoned row kept its other fields, and the clean row beside it
        # is untouched — one field's address does not blank a digest.
        for name, value in self.CLEAN.items():
            if name == field:
                continue
            assert value in body, (label, name)
        assert "Vision Lab RA" in body, label
        assert "UIUC ECE" in body, label

    def test_the_users_own_search_name_keeps_its_own_address(self, monkeypatch):
        # The search name is what the student typed. It travels into the
        # subject and the footer, and it is not corpus text — only the item
        # title and organization are.
        _set_digest_env(monkeypatch)
        poisoned = {"id": "opp-poison", "title": "vpue-fellowships@stanford.edu",
                    "organization": "Undergraduate Research Office",
                    "source_type": "campus_program", "deadline": ""}
        sends: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(name="alerts for ada.lovelace@illinois.edu",
                              new_match_ids=["opp-poison"])],
            sends=sends,
            opportunities=[poisoned],
        )
        client.get("/api/cron/saved-searches/digest", headers=AUTH)

        assert len(sends) == 1
        assert "ada.lovelace@illinois.edu" in sends[0]["subject"]
        assert "ada.lovelace@illinois.edu" in sends[0]["html"]
        assert "ada.lovelace@illinois.edu" in sends[0]["text"]
        # The corpus title in the same message is still redacted.
        body = sends[0]["html"] + sends[0]["text"]
        assert "vpue-fellowships" not in body
        assert "[email redacted]" in body

    def test_an_ordinary_digest_is_untouched(self, monkeypatch):
        # The control. Redacting every row would satisfy every assertion above.
        _set_digest_env(monkeypatch)
        sends: list = []
        _install_stubs(monkeypatch, rows=[_digest_row()], sends=sends)
        client.get("/api/cron/saved-searches/digest", headers=AUTH)

        assert len(sends) == 1
        body = sends[0]["html"] + sends[0]["text"]
        assert "[email redacted]" not in body
        assert "Vision Lab RA" in body
        assert "UIUC ECE" in body
        assert "NLP Internship" in body
        assert "Acme AI" in body
        # _OPP_A carries a real date; it renders as one.
        assert "due 2026-07-01" in body


class TestTheQueueStopsCarryingDeadTargets:
    """A pending queue accumulates for up to a week before it mails.

    Filtering only at render time would leave a closed target queued forever,
    re-examined every night and mailed the moment anything else joins it. The
    removal has to be written back. But "we cannot see it" is not "it ended":
    an id the corpus does not currently contain stays queued, because a shard
    that failed to load must never quietly empty someone's shortlist.
    """

    CLOSED = {
        "id": "opp-closed", "title": "Past URAP project", "organization": "UCB",
        "deadline": "", "metadata": {"is_active": True, "urap_status": "closed"},
    }
    STOPPED = {
        "id": "opp-stop", "title": "Prof. Rivera", "organization": "UCR",
        "deadline": "", "source_type": "faculty_research",
        "description_raw": "I am not currently accepting undergraduate students.",
        "metadata": {"is_active": True},
    }
    # Nobody has reviewed what this is, so it is dead for queue purposes in
    # exactly the same way — and unlike the three above, it is dead without
    # any source having said anything.
    UNREVIEWED = {
        "id": "opp-unreviewed", "title": "Unreviewed record", "organization": "UIUC",
        "deadline": "2099-12-31", "paid": "yes",
        "metadata": {"is_active": True},
    }

    def test_a_non_actionable_id_is_removed_from_the_stored_queue(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        patches: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=["opp-a", "opp-closed", "opp-stop", "opp-unreviewed"])],
            sends=sends, patches=patches,
            opportunities=[_OPP_A, self.CLOSED, self.STOPPED, self.UNREVIEWED],
        )
        client.get("/api/cron/saved-searches/digest", headers=AUTH)

        # Written back, not merely skipped while rendering.
        cleanup = patches[0]["json"]
        assert cleanup == {"new_match_ids": ["opp-a"]}
        # And the digest that did go out describes only the live one.
        assert len(sends) == 1
        assert "Past URAP project" not in sends[0]["html"]
        assert "Prof. Rivera" not in sends[0]["html"]
        assert "Vision Lab RA" in sends[0]["html"]

    def test_an_id_the_corpus_cannot_currently_see_stays_queued(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        patches: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=["opp-a", "opp-vanished"])],
            sends=sends, patches=patches, opportunities=[_OPP_A],
        )
        client.get("/api/cron/saved-searches/digest", headers=AUTH)

        # No cleanup PATCH for the missing id — only the post-send bookkeeping.
        cleanups = [p for p in patches if set(p["json"]) == {"new_match_ids"}]
        assert cleanups == [], "an absent record is unknown, not ended"

    def test_a_queue_of_only_dead_targets_mails_nothing_but_still_clears(
        self, monkeypatch,
    ):
        _set_digest_env(monkeypatch)
        sends: list = []
        patches: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=["opp-closed", "opp-stop", "opp-unreviewed"])],
            sends=sends, patches=patches,
            opportunities=[_OPP_A, self.CLOSED, self.STOPPED, self.UNREVIEWED],
        )
        response = client.get("/api/cron/saved-searches/digest", headers=AUTH)

        assert response.status_code == 200
        assert sends == [], "nothing to say, so no provider call and no email"
        # One write, and it empties the queue: without it the same two dead ids
        # would be re-examined every night forever.
        assert patches == [{
            "url": patches[0]["url"], "params": patches[0]["params"],
            "headers": patches[0]["headers"], "json": {"new_match_ids": []},
        }]
        from backend.routes import email as email_mod
        assert email_mod._recipient_sends.get("user@example.com", []) == []

    def test_a_send_clears_what_it_mailed_but_keeps_what_it_could_not_see(
        self, monkeypatch,
    ):
        """The mixed queue, which is where a blanket clear does its damage.

        One id resolves and mails; one is missing from this run's corpus. The
        success stamp used to empty the whole column, so the unresolved id —
        never mailed about, possibly just a shard that failed to load — was
        thrown away by the send of an unrelated match.
        """
        _set_digest_env(monkeypatch)
        sends: list = []
        patches: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=["opp-vanished", "opp-a"])],
            sends=sends, patches=patches, opportunities=[_OPP_A],
        )
        client.get("/api/cron/saved-searches/digest", headers=AUTH)

        assert len(sends) == 1
        assert "Vision Lab RA" in sends[0]["html"]
        assert "opp-vanished" not in sends[0]["html"]

        stamps = [p for p in patches if "last_digest_sent_at" in p["json"]]
        assert len(stamps) == 1
        assert stamps[0]["json"]["new_match_ids"] == ["opp-vanished"]

    def test_a_queue_of_only_unseen_ids_neither_mails_nor_forgets(self, monkeypatch):
        _set_digest_env(monkeypatch)
        sends: list = []
        patches: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=["opp-vanished", "opp-also-gone"])],
            sends=sends, patches=patches, opportunities=[_OPP_A],
        )
        client.get("/api/cron/saved-searches/digest", headers=AUTH)

        assert sends == []
        assert patches == [], "nothing resolved, so nothing is decided"

    def test_the_recipient_slot_is_reserved_after_the_render_not_before(self):
        """Static order check: nothing between the reservation and the send.

        A render failure or a key-building failure between the two would spend
        a recipient's anti-bombing slot on a send that never happened, and this
        loop swallows per-row errors — so the loss would be silent.
        """
        import inspect

        source = inspect.getsource(ss_mod.saved_searches_digest)
        reserve = source.index("_enforce_recipient_quota(to_email)")
        render = source.index("_render_digest_email(")
        key = source.index('build_idempotency_key("digest"')
        send = source.index("await _send_via_resend(")

        assert render < reserve, "render before reserving"
        assert key < reserve, "build the idempotency key before reserving"
        assert reserve < send, "and reserve immediately before sending"


class TestRefreshAccumulatesNewMatches:
    """new_match_ids must survive nightly refreshes until a digest is sent —
    the digest is throttled to one per 7 days, so overwriting the column with
    each night's diff would silently drop ~6/7 of a week's matches."""

    def _refresh_row(self, **overrides):
        row = {
            "id": "11111111-2222-3333-4444-555555555555",
            "filters_json": {},
            "query": "",
            "last_result_ids": [],
            "new_match_ids": [],
            # These cases are about accumulation ACROSS runs, so the row has
            # run before. A row with no last_run_at is a first run, which
            # establishes a baseline rather than calling everything new.
            "last_run_at": "2026-09-01T00:00:00+00:00",
        }
        row.update(overrides)
        return row

    def test_a_searchs_first_run_establishes_a_baseline_instead_of_mailing_it(
        self, monkeypatch,
    ):
        """last_result_ids defaults to '{}', so the first diff called the whole
        match-set new: a digest titled "200 new matches" hours after the search
        was created, under copy reading "since we last checked"."""
        _set_digest_env(monkeypatch)
        patches: list = []
        row = self._refresh_row(last_run_at=None)
        _install_stubs(monkeypatch, rows=[row], patches=patches)

        client.get("/api/cron/saved-searches/refresh", headers=AUTH)

        body = patches[0]["json"]
        assert body["new_match_ids"] == []
        # The baseline itself is recorded, so the next run has something to
        # diff against.
        assert body["last_result_ids"] == ["opp-a", "opp-b"]

    def test_unions_fresh_diff_with_pending_ids(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        # opp-a was already in last night's result set; opp-old accumulated
        # from an earlier refresh and has since left the corpus — it must
        # survive until the digest clears it, not vanish overnight.
        row = self._refresh_row(last_result_ids=["opp-a"],
                                new_match_ids=["opp-old", "opp-b"])
        _install_stubs(monkeypatch, rows=[row], patches=patches)

        r = client.get("/api/cron/saved-searches/refresh", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

        body = patches[0]["json"]
        assert body["last_result_ids"] == ["opp-a", "opp-b"]
        # opp-b is both pending and freshly diffed — deduped, order kept
        assert body["new_match_ids"] == ["opp-old", "opp-b"]

    def test_the_nightly_refresh_drops_known_dead_ids_and_keeps_unseen_ones(
        self, monkeypatch,
    ):
        """The other half of the cleanup, and its own implementation.

        The digest filters its queue too, but the refresh runs six nights out
        of seven — so a closed target left here is re-carried all week and
        mails the moment anything joins it. Same rule, separately enforced:
        known-dead goes, corpus-absent stays.
        """
        _set_digest_env(monkeypatch)
        patches: list = []
        closed = {
            "id": "opp-closed", "title": "Past project", "organization": "UCB",
            "deadline": "", "metadata": {"is_active": True, "urap_status": "closed"},
        }
        reference = {
            "id": "opp-ref", "title": "Reference record", "organization": "UCB",
            "deadline": "", "metadata": {"is_active": True, "reference_only": True},
        }
        inactive = {
            "id": "opp-inactive", "title": "Retired listing", "organization": "UIUC",
            "deadline": "", "metadata": {"is_active": False},
        }
        stopped = {
            "id": "opp-stop", "title": "Prof. Rivera", "organization": "UCR",
            "deadline": "", "source_type": "faculty_research",
            "description_raw": "I am not currently accepting undergraduate students.",
            "metadata": {"is_active": True},
        }
        row = self._refresh_row(
            last_result_ids=["opp-a"],
            new_match_ids=[
                "opp-closed", "opp-ref", "opp-inactive", "opp-stop",
                "opp-vanished", "opp-a",
            ],
        )
        _install_stubs(
            monkeypatch, rows=[row], patches=patches,
            opportunities=[_OPP_A, _OPP_B, closed, reference, inactive, stopped],
        )

        response = client.get("/api/cron/saved-searches/refresh", headers=AUTH)
        assert response.status_code == 200

        body = patches[0]["json"]
        # The current result set never contains a dead target: the candidate
        # list is filtered before matching, so all four are gone from both
        # columns and cannot come back on the next diff.
        assert body["last_result_ids"] == ["opp-a", "opp-b"]
        for dead in ("opp-closed", "opp-ref", "opp-inactive", "opp-stop"):
            assert dead not in body["new_match_ids"], dead
            assert dead not in body["last_result_ids"], dead
        # Absent from this run's corpus is not evidence of anything, so it
        # keeps its place in the queue — ahead of tonight's new match.
        assert body["new_match_ids"] == ["opp-vanished", "opp-a", "opp-b"]

    def test_cap_keeps_newest_ids(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        pending = [f"pending-{i}" for i in range(ss_mod.NEW_MATCH_IDS_CAP - 1)]
        row = self._refresh_row(new_match_ids=pending)
        _install_stubs(monkeypatch, rows=[row], patches=patches)

        client.get("/api/cron/saved-searches/refresh", headers=AUTH)

        got = patches[0]["json"]["new_match_ids"]
        assert len(got) == ss_mod.NEW_MATCH_IDS_CAP
        assert "pending-0" not in got  # oldest aged out
        assert got[-2:] == ["opp-a", "opp-b"]  # fresh matches kept


SID = "11111111-2222-3333-4444-555555555555"


def _unsub_url(sid: str = SID, ts: int | None = None, sig: str | None = None) -> str:
    ts = int(time.time()) if ts is None else ts
    sig = ss_mod._sign_digest_unsub(sid, ts) if sig is None else sig
    return f"/api/email/digest-unsubscribe?sid={sid}&t={ts}&s={sig}"


class TestDigestUnsubscribe:
    def _install_patch_stub(self, monkeypatch, patches, status_code=204):
        class _Resp:
            def __init__(self):
                self.status_code = status_code
                self.text = ""

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def patch(self, url, **kwargs):
                patches.append({"url": url, **kwargs})
                return _Resp()

        import httpx
        monkeypatch.setattr(httpx, "AsyncClient", _Client)

    def test_get_only_confirms_and_does_not_mutate(self, monkeypatch):
        # Mail security scanners prefetch GET links: a bare open must never
        # change subscription state, only render the signed confirm form.
        _set_digest_env(monkeypatch)
        patches: list = []
        self._install_patch_stub(monkeypatch, patches)

        r = client.get(_unsub_url())
        assert r.status_code == 200
        assert "confirm" in r.text.lower()
        assert 'method="post"' in r.text.lower()
        assert patches == []

    def test_valid_post_flips_opt_in_off(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        self._install_patch_stub(monkeypatch, patches)

        r = client.post(_unsub_url())
        assert r.status_code == 200
        assert "unsubscribed" in r.text.lower()

        assert len(patches) == 1
        body = patches[0]["json"]
        assert body["digest_opt_in"] is False
        assert body["digest_unsubscribed_at"]
        assert patches[0]["params"]["id"] == f"eq.{SID}"

    def test_tampered_sid_rejected(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        self._install_patch_stub(monkeypatch, patches)
        ts = int(time.time())
        sig = ss_mod._sign_digest_unsub(SID, ts)
        other_sid = "99999999-2222-3333-4444-555555555555"
        r = client.get(_unsub_url(sid=other_sid, ts=ts, sig=sig))
        assert r.status_code == 400
        assert patches == []

    def test_tampered_post_rejected_before_any_write(self, monkeypatch):
        # The POST shares the same token validator as the GET.
        _set_digest_env(monkeypatch)
        patches: list = []
        self._install_patch_stub(monkeypatch, patches)
        r = client.post(_unsub_url(sig="00" * 16))
        assert r.status_code == 400
        assert patches == []

    def test_garbage_signature_rejected(self, monkeypatch):
        _set_digest_env(monkeypatch)
        patches: list = []
        self._install_patch_stub(monkeypatch, patches)
        r = client.get(_unsub_url(sig="00" * 16))
        assert r.status_code == 400
        assert patches == []

    def test_expired_token_rejected(self, monkeypatch):
        _set_digest_env(monkeypatch)
        old = int(time.time()) - (ss_mod.DIGEST_UNSUB_TTL_DAYS * 86400 + 60)
        r = client.get(_unsub_url(ts=old))
        assert r.status_code == 400

    def test_non_uuid_sid_rejected(self, monkeypatch):
        _set_digest_env(monkeypatch)
        r = client.get("/api/email/digest-unsubscribe?sid=..%2Fetc&t=1&s=ab")
        assert r.status_code == 400

    def test_503_when_secret_unset(self, monkeypatch):
        monkeypatch.delenv("RESTORE_LINK_SECRET", raising=False)
        r = client.get(_unsub_url(sig="ab" * 16))
        assert r.status_code == 503

    def test_bare_payload_signature_rejected(self, monkeypatch):
        # The "digest-unsub|" context prefix is what scopes the token to this
        # action: a signature over the bare "id|ts" (no prefix) — the shape any
        # other feature signing under RESTORE_LINK_SECRET would produce — must
        # be rejected, so tokens can't be replayed across contexts.
        import hashlib
        import hmac
        _set_digest_env(monkeypatch)
        ts = int(time.time())
        secret = ss_mod._restore_signing_secret().encode()
        bare_sig = hmac.new(secret, f"{SID}|{ts}".encode(), hashlib.sha256).digest()[:16].hex()
        digest_sig = ss_mod._sign_digest_unsub(SID, ts)
        assert bare_sig != digest_sig
        r = client.get(_unsub_url(ts=ts, sig=bare_sig))
        assert r.status_code == 400


class TestDigestRenderer:
    def test_subject_singular_plural(self):
        s1, _, _ = ss_mod._render_digest_email("X", [_OPP_A], "https://u")
        s2, _, _ = ss_mod._render_digest_email("X", [_OPP_A, _OPP_B], "https://u")
        assert s1.startswith("1 new match ")
        assert s2.startswith("2 new matches ")

    def test_unsubscribe_link_present_in_both_bodies(self):
        url = "https://api.example.com/api/email/digest-unsubscribe?sid=x&t=1&s=ab"
        _, html, text = ss_mod._render_digest_email("X", [_OPP_A], url)
        # html attribute-escapes the query-string ampersands; text keeps it raw
        assert url.replace("&", "&amp;") in html
        assert url in text

    def test_overflow_counts_into_subject_and_bodies(self):
        s, html, text = ss_mod._render_digest_email("X", [_OPP_A], "https://u", overflow=7)
        assert s.startswith("8 new matches ")
        assert "+7 more in the app" in html
        assert "+7 more in the app" in text

    def test_no_overflow_line_when_batch_fits(self):
        _, html, text = ss_mod._render_digest_email("X", [_OPP_A], "https://u")
        assert "more in the app" not in html
        assert "more in the app" not in text


# `src.evidence.target_truth` derives its answer from the record's OWN fields
# — a wire `target_truth` key on a synthetic fixture is inert and would make
# every case below silently actionable. So the canonical markers are used:
# a reviewed source_type plus metadata.is_active.
_LIVE = {"source_type": "campus_program", "metadata": {"is_active": True}}
_DEAD = {"source_type": "campus_program", "metadata": {"is_active": False}}


def _render_one(opp):
    return ss_mod._render_digest_email("ML research", [opp], "https://x/unsub")


class TestTheDigestDescribesTargetsLikeEveryOtherEmail:
    """The saved-search digest kept its own describer, and it drifted.

    email.py's `_describe` is the one place a mailed row is built: it applies
    displayed_title (drop an honorific the record's own rank contradicts),
    then the lifecycle neutralizer (drop a terminal "(applications open)" on a
    record we will not call open), then safe_public_text — and it carries the
    research-inactive advisory. This digest reimplemented a subset and had
    none of that.

    Scope note: on today's corpus, after the loader plus the release and
    actionability filters, ZERO of the 131,568 visible+actionable records
    change under either title helper. These are defence-in-depth against
    reuse and future regression, NOT a live leak. The two P1s in this batch
    are the URL and the advisory, which DO reproduce on committed data.
    """

    def test_a_legacy_honorific_is_not_reintroduced(self):
        record = {
            "id": "faculty-1",
            "title": "Research with Prof. Dana Reyes — ECE",
            "organization": "Test University",
            "source_type": "faculty_research",
            "metadata": {"faculty_title": "Lecturer"},
        }
        snapshot = deepcopy(record)

        _subject, html, text = _render_one(record)

        for part in (html, text):
            assert "Research with Dana Reyes — ECE" in part
            assert "Research with Prof." not in part
        # The renderer describes; it never edits the corpus row it was handed.
        assert record == snapshot

    def test_a_non_actionable_listing_loses_its_opening_claim(self):
        _subject, html, text = _render_one({
            "id": "listing-closed-1",
            "title": "Past Program (applications open)",
            "organization": "Test University",
            **_DEAD,
        })
        for part in (html, text):
            assert "Past Program" in part
            assert "applications open" not in part.casefold()

    def test_a_confirmed_open_listing_keeps_its_suffix_byte_for_byte(self):
        # The over-redaction control: an open listing may say it is open.
        _subject, html, text = _render_one({
            "id": "listing-open-1",
            "title": "Summer REU (applications open)",
            "organization": "Test University",
            **_LIVE,
        })
        for part in (html, text):
            assert "Summer REU (applications open)" in part

    @pytest.mark.parametrize("title", [
        "Open House",
        "X (applications open) — archived",
    ])
    def test_ordinary_titles_are_untouched(self, title):
        _subject, html, text = _render_one({
            "id": "listing-2", "title": title,
            "organization": "Test University",
            **_LIVE,
        })
        for part in (html, text):
            assert title in part

    def test_an_address_in_a_title_is_redacted_by_the_shared_boundary(self):
        _subject, html, text = _render_one({
            "id": "listing-3", "title": "vpue-fellowships@stanford.edu",
            "organization": "Test University",
            **_LIVE,
        })
        for part in (html, text):
            assert "stanford.edu" not in part
            assert "[email redacted]" in part


class TestTheDigestLinkSurvivesTheIdItWasGiven:
    """An id goes into a URL PATH, so it needs percent-encoding.

    HTML escaping is a different job and never was one — it leaves a space or
    a `#` intact — and the plain-text part is not escaped at all. 217 of the
    131,568 visible+actionable records carry ids that need encoding.
    """

    def test_a_real_committed_id_with_a_space_is_encoded_in_both_parts(self):
        record = load_opportunities_by_id().get("faculty-social work-e62c849b")
        assert record is not None, (
            "control id 'faculty-social work-e62c849b' is gone from the corpus"
        )
        # It must actually be a row a digest can carry, or this proves nothing
        # about a link anyone would ever receive.
        assert opportunity_visible_in_release(record)
        assert is_actionable_target(record)

        _subject, html, text = _render_one(record)

        for part in (html, text):
            assert "faculty-social%20work-e62c849b" in part
            # The raw form is what breaks the link; it must not appear at all.
            assert "faculty-social work-e62c849b" not in part

    def test_every_reserved_character_is_encoded_including_slash(self):
        # safe='' on purpose: a `/` inside an id is data, not a path segment
        # boundary. A `#` would otherwise truncate the URL at the fragment.
        _subject, html, text = _render_one({
            "id": "weird/id#frag %ok", "title": "Odd id",
            "organization": "Test University",
            **_LIVE,
        })
        for part in (html, text):
            assert "weird%2Fid%23frag%20%25ok" in part
            assert "weird/id#frag" not in part

    def test_an_ordinary_id_is_unchanged(self):
        _subject, html, text = _render_one({
            "id": "uiuc-siebel-ugresearch", "title": "Ordinary",
            "organization": "Test University",
            **_LIVE,
        })
        for part in (html, text):
            assert "/opportunities/uiuc-siebel-ugresearch" in part


class TestResearchInactiveIsSaidOutLoud:
    """A warning, not a refusal.

    "I have no active research right now" is a different statement from "do
    not ask me": the row stays actionable and stays in the digest. What it
    must not do is arrive unqualified. The manual email says so; this digest
    silently did not, and the record below is visible and actionable on
    committed data.
    """

    ADVISORY = "Source reports no current active research — this is not an opening"

    def test_the_real_committed_record_carries_the_advisory(self):
        record = load_opportunities_by_id().get("faculty-arizona-phys-888d3f7f")
        assert record is not None, (
            "control id 'faculty-arizona-phys-888d3f7f' is gone from the corpus"
        )
        assert faculty_availability_status(record) == "research_inactive"
        # Visible AND actionable: the advisory only matters because this row
        # genuinely reaches a real digest rather than being filtered out.
        assert opportunity_visible_in_release(record)
        assert is_actionable_target(record), "the row must still be actionable"

        _subject, html, text = _render_one(record)

        for part in (html, text):
            assert self.ADVISORY in part
        # Still present as a row, not refused out of the digest.
        for part in (html, text):
            assert "Drew Milsom" in part

    def test_an_ordinary_row_carries_no_advisory(self):
        _subject, html, text = _render_one({
            "id": "listing-4", "title": "Ordinary Listing",
            "organization": "Test University",
            **_LIVE,
        })
        for part in (html, text):
            assert "no current active research" not in part


class TestTheCronSendCarriesAllOfIt:
    """End to end through the route, captured at the provider boundary."""

    def test_a_sent_digest_shows_the_corrected_title_and_the_advisory(
        self, monkeypatch,
    ):
        record = {
            "id": "faculty-cron-1",
            "title": "Research with Prof. Dana Reyes (applications open)",
            "organization": "Test University",
            "source_type": "faculty_research",
            "metadata": {
                "faculty_title": "Lecturer",
                "faculty_availability_status": "research_inactive",
            },
            "deadline": "2099-12-31",
        }
        _set_digest_env(monkeypatch)
        sends: list[dict] = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=["faculty-cron-1"])],
            sends=sends,
            opportunities=[record],
        )

        resp = client.get("/api/cron/saved-searches/digest", headers=AUTH)
        assert resp.status_code == 200
        assert sends, "the digest never reached the provider"
        html = sends[0]["html"]
        text = sends[0]["text"]
        for part in (html, text):
            assert "Research with Dana Reyes" in part
            assert "Research with Prof." not in part
            assert "applications open" not in part.casefold()
            assert "2099-12-31" not in part
            assert TestResearchInactiveIsSaidOutLoud.ADVISORY in part


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


class TestTheDigestKeepsWhatItPromised:
    """The email renders 10 matches and says "+5 more in the app", with a
    button to go find them. The post-send patch cleared new_match_ids down to
    the unresolvable ids, so the badge vanished, savedSearchToUrl dropped its
    highlight, and the overflow could not be identified by any action the
    student could take."""

    def test_the_overflow_it_advertised_survives_the_send(self, monkeypatch):
        _set_digest_env(monkeypatch)
        opps = [{"id": f"opp-{i}", "title": f"Opp {i}", "organization": "Org",
                 "source_type": "campus_program", "deadline": ""} for i in range(15)]
        sends: list = []
        patches: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(new_match_ids=[o["id"] for o in opps])],
            sends=sends, patches=patches, opportunities=opps,
        )

        client.get("/api/cron/saved-searches/digest", headers=AUTH)

        assert "+5 more in the app" in sends[0]["html"]
        kept = patches[0]["json"]["new_match_ids"]
        # The ten it showed close their window; the five it pointed at stay.
        assert sorted(kept) == sorted(f"opp-{i}" for i in range(5))


class TestTheDigestSendsWhatTheSiteWouldShow:
    """ranker.hard_exclusion calls itself "the single reason-coded
    implementation of every rule that drops a record from a profile's result
    universe" and lists its consumers. This cron was not one of them: it built
    the universe from release scope and target truth alone, both
    profile-independent. Replaying the real path for a JHU profile, 2,085 of
    3,122 matched ids (66.8%) were records the site would never show that
    student — Berkeley campus-only programs a JHU student cannot join."""

    DEVICE = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    @staticmethod
    def _campus_opp(opportunity_id: str, school: str) -> dict:
        return {
            "id": opportunity_id, "title": f"{school} lab", "organization": school,
            "source_type": "campus_program", "deadline": "2026-07-01",
            "school": school, "audience": "campus_only",
        }

    def _run(self, monkeypatch, *, profiles, queue, opportunities):
        _set_digest_env(monkeypatch)
        sends: list = []
        patches: list = []
        _install_stubs(
            monkeypatch,
            rows=[_digest_row(device_id=self.DEVICE, new_match_ids=queue)],
            sends=sends, patches=patches,
            opportunities=opportunities, profiles=profiles,
        )
        client.get("/api/cron/saved-searches/digest", headers=AUTH)
        return sends, patches

    def test_another_campus_only_program_is_not_mailed(self, monkeypatch):
        mine = self._campus_opp("opp-mine", "jhu")
        theirs = self._campus_opp("opp-theirs", "ucb")
        sends, _ = self._run(
            monkeypatch,
            profiles=[{"id": self.DEVICE, "profile_data": {"home_school": "jhu"}}],
            queue=["opp-mine", "opp-theirs"],
            opportunities=[mine, theirs],
        )
        assert len(sends) == 1
        html = sends[0]["html"]
        assert "jhu lab" in html
        assert "ucb lab" not in html

    def test_an_id_the_corpus_cannot_see_is_still_left_alone(self, monkeypatch):
        """The exclusion set is positive — built over the corpus — so absence
        from tonight's load is never mistaken for "not for you". A negative
        test against the eligible set would empty the queue on a bad shard."""
        mine = self._campus_opp("opp-mine", "jhu")
        _, patches = self._run(
            monkeypatch,
            profiles=[{"id": self.DEVICE, "profile_data": {"home_school": "jhu"}}],
            queue=["opp-mine", "opp-vanished"],
            opportunities=[mine],
        )
        cleanups = [p for p in patches if set(p["json"]) == {"new_match_ids"}]
        assert cleanups == [], "an absent record is unknown, not ineligible"

    def test_an_unreadable_profile_filters_nothing(self, monkeypatch):
        """A profile the cron cannot read must leave the digest exactly as it
        was, rather than filtering on a guess."""
        mine = self._campus_opp("opp-mine", "jhu")
        theirs = self._campus_opp("opp-theirs", "ucb")
        sends, _ = self._run(
            monkeypatch,
            profiles=[],
            queue=["opp-mine", "opp-theirs"],
            opportunities=[mine, theirs],
        )
        assert len(sends) == 1
        assert "ucb lab" in sends[0]["html"]
