"""Accuracy tests for the 2-hop faculty-email backfill, built from the real
profile-page shapes probed on UT Austin / Princeton / Wisconsin / UCLA / GT."""
from bs4 import BeautifulSoup

from src.collectors.profile_email import (
    _pick_personal_email,
    apply_emails,
    drop_shared_inboxes,
    email_for_profile,
    harvest_emails,
)


def _soup(mailtos, text=""):
    anchors = "".join(f'<a href="mailto:{m}">{m}</a>' for m in mailtos)
    return BeautifulSoup(f"<html><body>{anchors}<p>{text}</p></body></html>", "html.parser")


class TestDropSharedInboxes:
    def test_drops_dept_inbox_keeps_unique_and_name_matched(self):
        mapping = {
            "u/a": "studentinfo@atmos.ucla.edu",  # shared, matches nobody → drop
            "u/b": "studentinfo@atmos.ucla.edu",
            "u/c": "studentinfo@atmos.ucla.edu",
            "u/d": "lykpi@math.wisc.edu",         # unique → keep
            "u/e": "grauman@cs.utexas.edu",       # shared but name-matches → keep
            "u/f": "grauman@cs.utexas.edu",       # same professor, two listings
        }
        names = {
            "u/a": "Alice Atmos", "u/b": "Bob Breeze", "u/c": "Cara Cloud",
            "u/d": "Yingkun Li",
            "u/e": "Kristen Grauman", "u/f": "Kristen Grauman",
        }
        clean = drop_shared_inboxes(mapping, names)
        assert set(clean) == {"u/d", "u/e", "u/f"}
        assert clean["u/d"] == "lykpi@math.wisc.edu"
        assert clean["u/e"] == "grauman@cs.utexas.edu"


class TestPickPersonalEmail:
    def test_picks_named_person_over_dept_admin(self):
        # Scott Aaronson's page also lists undergrad/admissions/help inboxes.
        emails = ["aaronson@cs.utexas.edu", "under-info@cs.utexas.edu",
                  "csadmis@cs.utexas.edu", "help@cs.utexas.edu"]
        assert _pick_personal_email(emails, "Scott Aaronson") == "aaronson@cs.utexas.edu"

    def test_first_initial_plus_last(self):
        # Noga Alon -> nalon@; the department webmaster (web@) must lose.
        emails = ["nalon@math.princeton.edu", "web@math.princeton.edu"]
        assert _pick_personal_email(emails, "Noga Alon") == "nalon@math.princeton.edu"

    def test_dot_separated_name(self):
        assert _pick_personal_email(["hong.zhou@ucla.edu"], "Hong Zhou") == "hong.zhou@ucla.edu"
        assert (
            _pick_personal_email(["mustaque.ahamad@cc.gatech.edu"], "Mustaque Ahamad")
            == "mustaque.ahamad@cc.gatech.edu"
        )

    def test_single_nonadmin_wins_even_without_name_match(self):
        # Yingkun Li -> cryptic "lykpi@"; no name match, but it's the only real
        # address once the front desk / webmaster are dropped.
        emails = ["lykpi@math.wisc.edu", "mathfrontdesk@math.wisc.edu",
                  "webmaster@math.wisc.edu"]
        assert _pick_personal_email(emails, "Yingkun Li") == "lykpi@math.wisc.edu"

    def test_placeholder_prof_at_is_rejected(self):
        # Some GT pages carry a bare prof@gatech.edu placeholder — not a person.
        assert _pick_personal_email(["prof@gatech.edu"], "Jacob Abernethy") is None

    def test_ambiguous_multiple_nonmatching_returns_none(self):
        # Two plausible non-admin addresses, neither matching the name → don't guess.
        emails = ["xkcd@dept.edu", "qzpm@dept.edu"]
        assert _pick_personal_email(emails, "Jane Doe") is None

    def test_non_edu_domain_ignored(self):
        # A personal gmail on the page is not the institutional contact.
        assert _pick_personal_email(["janedoe@gmail.com"], "Jane Doe") is None

    def test_no_emails(self):
        assert _pick_personal_email([], "Jane Doe") is None


class TestEmailForProfile:
    def test_extracts_mailto_and_picks_person(self):
        soup = _soup(["nalon@math.princeton.edu", "web@math.princeton.edu"])
        assert email_for_profile("x", "Noga Alon", fetch=lambda u: soup) == "nalon@math.princeton.edu"

    def test_falls_back_to_text_when_no_mailto(self):
        soup = BeautifulSoup(
            "<html><body><p>Email: hong.zhou@ucla.edu</p></body></html>", "html.parser"
        )
        assert email_for_profile("x", "Hong Zhou", fetch=lambda u: soup) == "hong.zhou@ucla.edu"

    def test_missing_page_returns_none(self):
        assert email_for_profile("x", "Nobody", fetch=lambda u: None) is None


class TestHarvestApply:
    def _corpus(self):
        return [
            {"source_type": "faculty_research", "pi_name": "Noga Alon", "school": "princeton",
             "source_url": "https://p/alon", "application": {}},
            {"source_type": "faculty_research", "pi_name": "Hong Zhou", "school": "ucla",
             "source_url": "https://u/zhou", "contact_email": "already@ucla.edu",
             "application": {}},  # already has email → skipped
            {"source_type": "faculty_research", "pi_name": "No Page", "school": "ucla",
             "source_url": "https://u/none", "application": {}},
        ]

    def test_harvest_then_apply_updates_only(self):
        pages = {
            "https://p/alon": _soup(["nalon@math.princeton.edu", "web@math.princeton.edu"]),
            "https://u/none": None,
        }
        opps = self._corpus()
        mapping = harvest_emails(opps, fetch=lambda u: pages.get(u))
        assert mapping == {"https://p/alon": "nalon@math.princeton.edu"}

        n = apply_emails(opps, mapping)
        assert n == 1
        assert opps[0]["contact_email"] == "nalon@math.princeton.edu"
        assert opps[0]["application"]["contact_method"] == "email"
        assert opps[1]["contact_email"] == "already@ucla.edu"  # untouched
        assert "contact_email" not in opps[2]

    def test_school_filter(self):
        opps = self._corpus()
        # Only princeton targeted → ucla's email-less record is not fetched.
        fetched = []

        def fetch(u):
            fetched.append(u)
            return _soup(["nalon@math.princeton.edu"])

        harvest_emails(opps, schools=["princeton"], fetch=fetch)
        assert fetched == ["https://p/alon"]
