"""Truthfulness W11 — evidence model, unknown semantics, no optimistic completion.

Covers the cross-cutting invariants:

    verified evidence            -> value may be presented as verified
    missing/inferred/conflicting -> value stays unknown/unverified/conflicting

and the category-specific rules introduced by the W11 close-out: position
rank honesty, citizenship tri-state, inference stamping, source priority,
conflict recording, estimated-deadline lifecycle, and the serving-side
honorific rewrite. Publication trust and grounding already have their own
suites (test_publication_trust.py, test_grounding.py).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from backend.lib.contact_visibility import contact_email_status, verified_send_target
from backend.lib.position_truth import displayed_title, stated_rank
from src.collectors.faculty_graph import _normalize as fg_normalize
from src.collectors.nsf_reu import _detect_international, _is_reu_site
from src.evidence import (
    can_override,
    harvested_contact_email,
    inferred_method,
    is_inferred,
    is_professor_rank,
    is_synthesized_email_source,
    record_conflict,
    source_rank,
    stamp_inferred,
)
from src.matcher.ranker import _evidence_rank, _is_actionable
from src.normalizers.deactivate_past import deactivate_past
from src.parsers.llm_tagger import (
    _detect_intl_from_org,
    _detect_intl_from_text,
    _detect_paid_from_text,
    apply_updates,
)

SCHOOL = {
    "id_prefix": "test", "source": "test_faculty", "organization": "Test University",
    "location": "Testville, TS", "school_slug": "uiuc", "audience": "open",
}
DEPT = {"short": "CS", "name": "Department of Computer Science", "directory_url": "https://cs.test.edu/people"}


def _person(**kw):
    base = {"name": "Jane Doe", "url": "https://cs.test.edu/jane-doe"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Position: missing rank stays unknown, never "Professor"
# ---------------------------------------------------------------------------

class TestPositionUnknown:
    def test_missing_title_is_not_professor(self):
        rec = fg_normalize(SCHOOL, DEPT, _person())
        assert rec["metadata"]["faculty_title"] == ""
        assert "Prof." not in rec["title"]
        assert "Professor" not in rec["description_clean"]

    def test_stated_professor_rank_keeps_honorific(self):
        rec = fg_normalize(SCHOOL, DEPT, _person(title="Associate Professor"))
        assert rec["metadata"]["faculty_title"] == "Associate Professor"
        assert rec["title"].startswith("Prof. Jane Doe")
        assert "Research with" not in rec["title"]

    def test_stated_non_professor_rank_is_preserved_not_upgraded(self):
        rec = fg_normalize(SCHOOL, DEPT, _person(title="Senior Lecturer"))
        assert rec["metadata"]["faculty_title"] == "Senior Lecturer"
        assert "Prof." not in rec["title"]
        assert "Senior Lecturer Jane Doe" in rec["description_clean"]

    def test_no_fabricated_lab_entity(self):
        rec = fg_normalize(SCHOOL, DEPT, _person())
        assert rec["lab_or_program"] == ""

    def test_professor_rank_predicate(self):
        assert is_professor_rank("Assistant Professor")
        assert is_professor_rank("Prof.")
        assert is_professor_rank("Adjunct Professor of Chemistry")
        assert not is_professor_rank("Professional Specialist")
        assert not is_professor_rank("Senior Lecturer")
        assert not is_professor_rank("")
        assert not is_professor_rank(None)

    def test_emeritus_is_dropped_not_relabeled(self):
        # A retired-status rank never ships as an active contact at all.
        assert fg_normalize(SCHOOL, DEPT, _person(title="Professor Emeritus")) is None


# ---------------------------------------------------------------------------
# Serving: legacy "Prof." titles are rewritten only against a stated rank
# ---------------------------------------------------------------------------

class TestServingPositionTruth:
    def test_stated_non_professor_rank_strips_honorific(self):
        opp = {"title": "Research with Prof. R. Levin — BIOL",
               "metadata": {"faculty_title": "Senior Lecturer"}}
        assert displayed_title(opp) == "Research with R. Levin — BIOL"

    def test_professor_rank_keeps_title(self):
        opp = {"title": "Research with Prof. J. Doe — CS",
               "metadata": {"faculty_title": "Professor"}}
        assert displayed_title(opp) == "Research with Prof. J. Doe — CS"

    def test_unknown_rank_leaves_legacy_title_untouched(self):
        # Legacy records with no stated rank are indistinguishable — documented
        # residual; the rewrite must not fire without contradicting evidence.
        opp = {"title": "Research with Prof. J. Doe — CS", "metadata": {}}
        assert displayed_title(opp) == "Research with Prof. J. Doe — CS"
        assert stated_rank(opp) == ""


# ---------------------------------------------------------------------------
# International / citizenship: unknown never becomes an optimistic value
# ---------------------------------------------------------------------------

class TestCitizenshipTriState:
    def test_faculty_normalize_keeps_intl_unknown(self):
        rec = fg_normalize(SCHOOL, DEPT, _person())
        assert rec["eligibility"]["international_friendly"] == "unknown"

    def test_no_mention_is_unknown_not_yes(self):
        assert _detect_intl_from_text("A great summer research program.") == "unknown"

    def test_explicit_restriction_is_no(self):
        assert _detect_intl_from_text("Applicants must be U.S. citizens.") == "no"

    def test_explicit_welcome_is_yes(self):
        assert _detect_intl_from_text("International students are eligible to apply.") == "yes"

    def test_negated_welcome_is_not_yes(self):
        text = "This program is not open to international students."
        assert _detect_intl_from_text(text) != "yes"

    def test_condition_bearing_phrase_is_not_yes(self):
        # "international applicants" + a work-auth condition used to flip to
        # "yes" on bare substring match.
        text = "International applicants must already hold US work authorization."
        assert _detect_intl_from_text(text) == "unknown"

    def test_federal_org_match_is_word_bounded(self):
        opp = {"organization": "Transfer Student Center", "title": "Transfer Student Research Program", "source": "x"}
        assert _detect_intl_from_org(opp) == "unknown"
        opp2 = {"organization": "NSF", "title": "Summer Research", "source": "x"}
        assert _detect_intl_from_org(opp2) == "no"

    def test_inference_never_writes_citizenship_false(self):
        opp = {"paid": "unknown", "eligibility": {"international_friendly": "unknown"}}
        apply_updates(opp, {"international_friendly": "yes"})
        assert "citizenship_required" not in opp["eligibility"]

    def test_inferred_restriction_is_stamped(self):
        opp = {"paid": "unknown", "eligibility": {"international_friendly": "unknown"}}
        apply_updates(opp, {"international_friendly": "no", "citizenship_required": True})
        assert opp["eligibility"]["citizenship_required"] is True
        assert is_inferred(opp, "eligibility.international_friendly")
        assert is_inferred(opp, "eligibility.citizenship_required")

    def test_stated_value_is_never_overwritten_by_inference(self):
        opp = {"paid": "unknown", "eligibility": {"international_friendly": "yes"}}
        apply_updates(opp, {"international_friendly": "no", "citizenship_required": True})
        assert opp["eligibility"]["international_friendly"] == "yes"
        assert not is_inferred(opp, "eligibility.international_friendly")

    def test_nsf_reu_no_mention_is_policy_no(self):
        # The REU solicitation's citizenship bar is program-family policy —
        # kept, but as "no", never converted to an optimistic yes.
        assert _detect_international("We study rivers.") == "no"
        assert _detect_international("International students are eligible.") == "yes"


# ---------------------------------------------------------------------------
# Paid: absence of compensation text stays unknown
# ---------------------------------------------------------------------------

class TestPaidDetection:
    def test_unfunded_is_not_paid(self):
        assert _detect_paid_from_text("This is an unfunded volunteer position.") == "no"

    def test_bare_dollar_sign_is_not_evidence(self):
        assert _detect_paid_from_text("A $50 application fee applies.") == "unknown"

    def test_explicit_stipend_is_paid(self):
        assert _detect_paid_from_text("Participants receive a stipend.") == "yes"


# ---------------------------------------------------------------------------
# Deadline: estimates are labeled guesses, not lifecycle facts
# ---------------------------------------------------------------------------

class TestDeadlineEstimates:
    def test_estimated_deadline_never_deactivates(self):
        opps = [{"deadline": "2020-03-01", "deadline_is_estimate": True,
                 "is_rolling": False, "metadata": {"is_active": True}}]
        counts = deactivate_past(opps, today=date(2026, 7, 31))
        assert counts["skipped_estimate"] == 1
        assert opps[0]["metadata"]["is_active"] is True

    def test_real_past_deadline_still_deactivates(self):
        opps = [{"deadline": "2020-03-01", "is_rolling": False, "metadata": {"is_active": True}}]
        counts = deactivate_past(opps, today=date(2026, 7, 31))
        assert counts["newly_deactivated"] == 1

    def test_missing_deadline_stays_unknown_not_expired(self):
        opps = [{"deadline": None, "is_rolling": False, "metadata": {"is_active": True}}]
        counts = deactivate_past(opps, today=date(2026, 7, 31))
        assert counts["skipped_no_deadline"] == 1
        assert opps[0]["metadata"]["is_active"] is True


# ---------------------------------------------------------------------------
# NSF REU: only genuine REU Sites carry REU-specific claims
# ---------------------------------------------------------------------------

class TestReuSiteFilter:
    def test_reu_site_passes(self):
        assert _is_reu_site({"title": "REU Site: Coastal Ecology"})

    def test_supplement_fails(self):
        assert not _is_reu_site({"title": "REU Supplement: Coastal Ecology"})

    def test_unrelated_award_fails(self):
        # The old boolean admitted every non-supplement award, shipping REU
        # stipend/eligibility boilerplate on unrelated grants.
        assert not _is_reu_site({"title": "Collaborative Research: Deep Learning for Materials"})


# ---------------------------------------------------------------------------
# Email: synthesized provenance never ranks, reveals, or actions
# ---------------------------------------------------------------------------

_BOUND_URL = "https://cs.example.edu/people/jane-doe"


def _bound_metadata(email: str, *, source: str = "bound_profile_container") -> dict:
    """A complete, fresh identity-bound evidence tuple for `email`."""
    return {
        "identity_bound": True,
        "email_source": source,
        "contact_verified_email": email,
        "contact_source_url": _BOUND_URL,
        "contact_verified_at": datetime.now(UTC).isoformat(),
    }


def _bound_opp(email: str) -> dict:
    """A complete opp: identity-bound evidence + matching url/source_url/
    application_url — a bound_profile_* source additionally requires every
    profile-identity projection to agree with the evidence's source URL."""
    return {
        "contact_email": email,
        "url": _BOUND_URL,
        "source_url": _BOUND_URL,
        "metadata": _bound_metadata(email),
        "application": {"contact_method": "email", "application_url": _BOUND_URL},
    }


class TestEmailProvenance:
    def test_synthesized_prefixes(self):
        assert is_synthesized_email_source("constructed_netid")
        assert is_synthesized_email_source("pattern_guess")
        assert not is_synthesized_email_source("profile_page")
        assert not is_synthesized_email_source("")
        assert not is_synthesized_email_source(None)

    def test_harvested_contact_email_is_a_loose_observed_helper_not_the_actionability_bar(self):
        # harvested_contact_email only screens out synthesized provenance —
        # it is NOT the send/reveal/actionability predicate (that's
        # verified_send_target). profile_page and bare-legacy (unstamped)
        # sources both pass here even though neither is actionable or
        # revealable without a full identity-bound evidence tuple.
        assert harvested_contact_email(
            {"contact_email": "jdoe@test.edu", "metadata": {"email_source": "profile_page"}}
        ) == "jdoe@test.edu"
        assert harvested_contact_email(
            {"contact_email": "jdoe@test.edu", "metadata": {}}
        ) == "jdoe@test.edu"
        assert harvested_contact_email(
            {"contact_email": "jdoe@test.edu", "metadata": {"email_source": "constructed_netid"}}
        ) == ""

    def test_actionable_requires_verified_send_target_evidence(self):
        synth = {"contact_email": "jdoe@test.edu",
                 "metadata": {"email_source": "constructed_netid"},
                 "application": {"contact_method": "email"}}
        assert not _is_actionable(synth)
        # profile_page / bare-legacy / wayback sources are OBSERVED
        # (non-synthesized) and carry no binding fields at all — the W7a
        # legacy rule (W12 merge reconciliation): they ARE actionable, since
        # the product reveals and sends them; the evidence LADDER (not this
        # boolean) is what keeps fully-bound proof above them in a tie.
        profile_page = {"contact_email": "jdoe@test.edu",
                         "metadata": {"email_source": "profile_page"},
                         "application": {"contact_method": "email"}}
        assert _is_actionable(profile_page)
        assert _evidence_rank(profile_page) == 1
        legacy = {"contact_email": "jdoe@test.edu", "metadata": {},
                  "application": {"contact_method": "email"}}
        assert _is_actionable(legacy)
        assert _evidence_rank(legacy) == 1
        wayback = {"contact_email": "jdoe@test.edu",
                   "metadata": {"email_source": "wayback"},
                   "application": {"contact_method": "email"}}
        assert _is_actionable(wayback)
        assert _evidence_rank(wayback) == 1
        # A PARTIAL binding stamp is not legacy — it fails closed entirely.
        partial = {"contact_email": "jdoe@test.edu",
                   "metadata": {"email_source": "profile_page", "identity_bound": False},
                   "application": {"contact_method": "email"}}
        assert not _is_actionable(partial)
        assert _evidence_rank(partial) == 0
        complete = _bound_opp("jdoe@test.edu")
        assert _is_actionable(complete)
        assert _evidence_rank(complete) == 2

    def test_ranker_and_reveal_bars_agree(self):
        # The real invariant: _is_actionable (ranker tie-break) and
        # verified_send_target (reveal/send) must return the same
        # truthy/falsy verdict for every contact_method='email' record — a
        # record the product won't reveal must never win a ranking tie as
        # actionable. harvested_contact_email is deliberately excluded from
        # this comparison; it's a looser, unrelated provenance helper (see
        # the dedicated test above).
        stale = _bound_opp("jdoe@test.edu")
        stale["metadata"] = dict(stale["metadata"])
        stale["metadata"]["contact_verified_at"] = (
            datetime.now(UTC) - timedelta(days=61)
        ).isoformat()
        mismatched = _bound_opp("jdoe@test.edu")
        mismatched["metadata"] = dict(mismatched["metadata"])
        mismatched["metadata"]["contact_verified_email"] = "someoneelse@test.edu"
        cases = [
            {"contact_email": "jdoe@test.edu", "metadata": {"email_source": "constructed_netid"},
             "application": {"contact_method": "email"}},
            {"contact_email": "jdoe@test.edu", "metadata": {"email_source": "profile_page"},
             "application": {"contact_method": "email"}},
            {"contact_email": "jdoe@test.edu", "metadata": {},
             "application": {"contact_method": "email"}},
            {"contact_email": "jdoe@test.edu", "metadata": {"email_source": "wayback"},
             "application": {"contact_method": "email"}},
            _bound_opp("jdoe@test.edu"),
            stale,  # past the 60-day TTL
            mismatched,  # verified-email mismatch
        ]
        for opp in cases:
            assert bool(_is_actionable(opp)) == bool(verified_send_target(opp)), opp

    def test_missing_email_is_unavailable_not_guessed(self):
        status, email = contact_email_status({"contact_email": None, "metadata": {}}, authenticated=True)
        assert status == "unavailable" and email == ""


# ---------------------------------------------------------------------------
# Evidence model: stamps, priority, conflicts
# ---------------------------------------------------------------------------

class TestEvidenceModel:
    def test_stamp_and_read_inference(self):
        rec = {"metadata": {}}
        stamp_inferred(rec["metadata"], "keywords", "llm:bio_extraction")
        assert is_inferred(rec, "keywords")
        assert inferred_method(rec, "keywords") == "llm:bio_extraction"
        assert not is_inferred(rec, "deadline")

    def test_legacy_records_have_no_inference_stamps(self):
        assert not is_inferred({"metadata": {}}, "keywords")
        assert not is_inferred({}, "keywords")

    def test_source_priority_ordering(self):
        assert source_rank("official_page") < source_rank("academic_identity")
        assert source_rank("academic_identity") < source_rank("approved_third_party")
        assert source_rank("approved_third_party") < source_rank("llm_inference")
        assert source_rank("llm_inference") < source_rank("constructed")
        assert source_rank("discovery") > source_rank("constructed")

    def test_lower_priority_cannot_override(self):
        assert not can_override("llm_inference", "official_page")
        assert not can_override("approved_third_party", "official_page")
        assert can_override("official_page", "llm_inference")
        assert can_override("official_page", "official_page")
        assert can_override("llm_inference", None)  # empty field may be filled

    def test_unknown_source_kind_ranks_last(self):
        assert source_rank("something_new") > source_rank("discovery")

    def test_conflict_is_recorded_not_silently_dropped(self):
        meta = {}
        record_conflict(meta, "deadline", kept="2026-02-01", rejected="2026-03-01",
                        kept_source="official_page", rejected_source="approved_third_party")
        assert len(meta["conflicts"]) == 1
        c = meta["conflicts"][0]
        assert c["kept"] == "2026-02-01" and c["rejected"] == "2026-03-01"

    def test_conflicts_dedupe_and_cap(self):
        meta = {}
        for _ in range(3):
            record_conflict(meta, "deadline", kept="a", rejected="b",
                            kept_source="official_page", rejected_source="discovery")
        assert len(meta["conflicts"]) == 1
        for i in range(30):
            record_conflict(meta, "deadline", kept="a", rejected=f"r{i}",
                            kept_source="official_page", rejected_source="discovery")
        assert len(meta["conflicts"]) <= 10


# ---------------------------------------------------------------------------
# Derived keywords are labeled at rest; generated content renders unknowns
# ---------------------------------------------------------------------------

class TestDerivedContentLabels:
    def test_llm_keywords_are_stamped_at_write(self):
        from src.collectors.llm_enrich import apply_llm_keywords
        opp = {"source_type": "faculty_research", "keywords": [],
               "url": "https://x.edu/p", "metadata": {}}
        n = apply_llm_keywords([opp], {"https://x.edu/p": ["fluid dynamics"]})
        assert n == 1 and opp["keywords"] == ["fluid dynamics"]
        assert inferred_method(opp, "keywords") == "llm:bio_extraction"

    def test_openalex_keywords_are_stamped_at_write(self):
        from src.collectors.openalex_enrich import _person_key, apply_openalex
        opp = {"source_type": "faculty_research", "keywords": [],
               "url": "https://x.edu/p", "pi_name": "Jane Doe", "metadata": {}}
        n = apply_openalex([opp], {_person_key(opp): ["topology"]})
        assert n == 1 and opp["keywords"] == ["topology"]
        assert inferred_method(opp, "keywords") == "derived:openalex_topics"

    def test_scraped_keywords_carry_no_inference_stamp(self):
        rec = fg_normalize(SCHOOL, DEPT, _person(keywords=["robotics"]))
        assert rec["keywords"] == ["robotics"]
        assert not is_inferred(rec, "keywords")

    def test_chat_prompt_renders_missing_citizenship_as_unknown(self):
        from backend.routes.opportunities import _build_chat_system_prompt, _tri_state
        opp = {"title": "T", "eligibility": {}, "application": {}, "metadata": {}}
        prompt = _build_chat_system_prompt(opp, None)
        assert "Citizenship required: unknown" in prompt
        assert "Citizenship required: False" not in prompt
        assert _tri_state(True) == "yes" and _tri_state(False) == "no"
        assert _tri_state(None) == "unknown" and _tri_state(0) == "unknown"
