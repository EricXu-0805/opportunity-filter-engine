"""Cold Email trust / freshness / outbound authorization boundary (W12).

The boundary: a cold email may help the user PREPARE outreach, but the system
must never use unverified professor facts, serve stale personalized drafts as
current, interpret preparation as sending, fabricate outreach records, or
send mail without the user doing it themselves.

Send-semantics and idempotency live client-side and are pinned by
frontend/src/components/ColdEmailModal.tracking.test.tsx (copy/open record
nothing; Confirm-sent writes exactly one status via the device+opportunity
upsert). This suite covers the backend halves: recipient bars, draft
provenance/freshness, the empty-signal research-claim gate, responsiveness
event semantics, and the no-outbound-capability tripwire.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

from backend.lib.contact_visibility import contact_email_status, verified_send_target
from backend.routes.cold_email import (
    COLD_EMAIL_PIPELINE_VERSION,
    _source_freshness,
    _ungrounded_research_claim,
)
from backend.routes.responsiveness import CONTACT_STATUSES, REPLIED_STATUSES
from src.evidence import is_unit_mailbox_email


def _faculty(email: str, *, active: bool = True, source: str | None = None,
             department: str = "Department of English") -> dict:
    md: dict = {"is_active": active}
    if source is not None:
        md["email_source"] = source
    return {
        "source_type": "faculty_research",
        "contact_email": email,
        "department": department,
        "metadata": md,
    }


# ---------------------------------------------------------------------------
# Recipient truth: only approved recipient types enter professor outreach
# ---------------------------------------------------------------------------

class TestRecipientBars:
    def test_personal_faculty_email_is_a_send_target(self):
        assert verified_send_target(_faculty("jdoe@illinois.edu")) == "jdoe@illinois.edu"

    def test_synthesized_email_never_a_send_target(self):
        assert verified_send_target(_faculty("jdoe@stanford.edu", source="constructed_sunetid")) == ""

    def test_unit_mailbox_never_a_professor_recipient(self):
        # "Dear Prof. X" to the department office misfires — serve-time
        # backstop for page_scan grabs collector hygiene never saw.
        for local in ("office", "info", "advising", "gradoffice"):
            assert verified_send_target(_faculty(f"{local}@illinois.edu")) == ""

    def test_department_stem_localpart_never_a_professor_recipient(self):
        assert verified_send_target(_faculty("english@illinois.edu")) == ""

    def test_program_records_keep_unit_contacts(self):
        # A program's contact IS legitimately a unit/program mailbox — the
        # bar is faculty-only (recipient-type distinction, not a blanket ban).
        opp = {"source_type": "campus_program", "contact_email": "info@grainger.illinois.edu",
               "department": "Grainger Engineering", "metadata": {"is_active": True}}
        assert verified_send_target(opp) == "info@grainger.illinois.edu"

    def test_inactive_record_email_is_unavailable(self):
        # A departed professor's stored address must not hand out an outreach
        # target — the premise of the email ("I saw your lab") is stale.
        opp = _faculty("jdoe@illinois.edu", active=False)
        assert verified_send_target(opp) == ""
        status, email = contact_email_status(opp, authenticated=True)
        assert status == "unavailable" and email == ""

    def test_legacy_unstamped_email_still_passes(self):
        # Provenance never gates data that predates stamping (W7a contract).
        assert verified_send_target(_faculty("jdoe@illinois.edu")) != ""

    def test_unit_mailbox_predicate_is_exact_match(self):
        # A personal username containing a unit word must never be clipped.
        assert not is_unit_mailbox_email("infante@illinois.edu")
        assert not is_unit_mailbox_email("deanna.smith@illinois.edu")
        assert is_unit_mailbox_email("info@illinois.edu")
        assert is_unit_mailbox_email("english@illinois.edu", "Department of English")
        # The stem match is per-record: english@ is only a unit inbox for an
        # English department, not globally.
        assert not is_unit_mailbox_email("english@illinois.edu", "Department of Physics")


# ---------------------------------------------------------------------------
# Draft provenance + freshness
# ---------------------------------------------------------------------------

class TestSourceFreshness:
    def _at(self, days_ago: int) -> str:
        return (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)).isoformat()

    def test_fresh_within_ttl(self):
        opp = {"metadata": {"is_active": True, "last_verified": self._at(5)}}
        assert _source_freshness(opp) == "fresh"

    def test_stale_beyond_ttl(self):
        opp = {"metadata": {"is_active": True, "last_verified": self._at(90)}}
        assert _source_freshness(opp) == "stale"

    def test_inactive_wins_over_recency(self):
        opp = {"metadata": {"is_active": False, "last_verified": self._at(1)}}
        assert _source_freshness(opp) == "inactive"

    def test_missing_last_verified_is_unknown_not_fresh(self):
        assert _source_freshness({"metadata": {"is_active": True}}) == "unknown"

    def test_junk_last_verified_is_unknown(self):
        assert _source_freshness({"metadata": {"last_verified": "yesterday-ish"}}) == "unknown"

    def test_pipeline_version_is_stamped_constant(self):
        assert COLD_EMAIL_PIPELINE_VERSION  # non-empty; response schema carries it


# ---------------------------------------------------------------------------
# Empty-signal research claims: no signal → no "your work on X"
# ---------------------------------------------------------------------------

class TestUngroundedResearchClaim:
    _NO_SIGNAL = {"research_area": "", "research_topic": "", "research_areas_raw": "",
                  "recent_works": []}

    def test_claim_without_signal_is_rejected(self):
        body = "I was fascinated by your work on machine learning systems."
        assert _ungrounded_research_claim(self._NO_SIGNAL, body)

    def test_research_in_variant_is_rejected(self):
        assert _ungrounded_research_claim(
            self._NO_SIGNAL, "I have followed your research in coastal ecology.")

    def test_claim_with_signal_is_allowed_for_vocab_gate_to_judge(self):
        parts = dict(self._NO_SIGNAL, research_area="graph neural networks")
        body = "I was fascinated by your work on graph neural networks."
        assert not _ungrounded_research_claim(parts, body)

    def test_generic_bucket_is_not_source_evidence(self):
        parts = dict(self._NO_SIGNAL, research_area="Machine Learning")
        assert _ungrounded_research_claim(
            parts,
            "I was fascinated by your work on machine learning systems.",
        )

    def test_verified_works_count_as_signal(self):
        parts = dict(self._NO_SIGNAL, recent_works=[{"title": "A Paper", "year": 2026}])
        assert not _ungrounded_research_claim(parts, "your work on transformers")

    def test_claim_free_body_passes_without_signal(self):
        body = ("I am a sophomore studying computer science and would love to "
                "learn about undergraduate research openings in your lab.")
        assert not _ungrounded_research_claim(self._NO_SIGNAL, body)


# ---------------------------------------------------------------------------
# Tracking semantics: only confirmed statuses are outreach signals
# ---------------------------------------------------------------------------

class TestTrackingSemantics:
    def test_contacted_is_a_contact_status(self):
        # The cold-email Confirm-sent attestation writes 'contacted' — it must
        # count toward contacted_n (and never toward replies).
        assert "contacted" in CONTACT_STATUSES
        assert "contacted" not in REPLIED_STATUSES

    def test_dismissed_is_not_a_contact_status(self):
        assert "dismissed" not in CONTACT_STATUSES

    def test_migration_allows_contacted(self):
        sql = (_REPO / "supabase/migrations/024_contacted_status.sql").read_text()
        assert "'contacted'" in sql and "interaction_type" in sql


# ---------------------------------------------------------------------------
# Outbound-capability tripwire: this product PREPARES mail, it never sends it
# ---------------------------------------------------------------------------

class TestNoOutboundSending:
    _FORBIDDEN = ("import smtplib", "googleapiclient", "google.oauth2",
                  "msgraph", "import resend", "from resend")

    def test_cold_email_modules_cannot_send(self):
        # The per-email approval flow is structural: the user sends from their
        # own client. If someone wires an outbound provider into the cold-email
        # path, this trips and the W12 approval requirements apply.
        for path in ("backend/routes/cold_email.py", "src/recommender/cold_email.py"):
            src = (_REPO / path).read_text()
            for needle in self._FORBIDDEN:
                assert needle not in src, f"{path} gained outbound-send capability ({needle})"

    def test_no_send_route_exists_for_cold_email(self):
        src = (_REPO / "backend/routes/cold_email.py").read_text()
        assert "/cold-email/send" not in src
