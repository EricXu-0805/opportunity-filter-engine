"""M90: a configured program loses "(applications open)" only when its deadline
note mentions no opening or reopening, no rolling review, no TBA, TBC or TBD,
no "until filled", no "no deadline" and no recurring cycle (quarterly,
monthly, annually, year-round, ongoing...), every month name and digit in it is
part of a date written in full (month name, day and a year from 2000 to 2099),
a time of day or a year on its own, and every such date is two or more UTC
days back.

The campus collector writes the suffix whenever the program page reads as open
(USTAR's page still carries an "APPLY NOW!" button), and the served title kept
it for any actionable listing. M05's closure reads only the structured
`deadline` field, which a configured program never has: its window is prose in
`metadata.deadline_note`. So Georgia Tech Petit (note: "…with a September 15,
2026 deadline") and JHU USTAR (note: "…were due January 24, 2025") kept saying
applications are open, weeks and a year and a half after those dates.

Since 2026-11-16 the suffix also needs the page's own sentence
(TestOnlyThePagesOwnSentenceKeepsTheSuffix), so the rows here carry one.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest

from backend.lib.public_projection import neutralize_lifecycle_title, project_public_opportunity_payload
from src import evidence
from src.collectors import ucb_sources
from src.collectors.schools import SCHOOL_CONFIGS
from src.evidence import target_truth

_TODAY = date(2026, 10, 17)


@pytest.fixture
def calendar(monkeypatch):
    monkeypatch.setattr(evidence, "_today", lambda: _TODAY)
    return _TODAY


def _page(excerpt: str) -> str:
    return f"Scholars spend a year in a faculty lab.\n\nFrom the program page: {excerpt}"


def _program(note: object, *, title: str = "Petit Undergraduate Research Scholars Program (IBB) (applications open)",
             **overrides) -> dict:
    """A configured campus program the way campus_graph writes it, read off a
    page that says applications are open."""
    record = {
        "id": "gatech-b681bbe40c66",
        "source": "gatech_research_programs",
        "source_type": "campus_program",
        "campus_source_type": "program",
        "title": title,
        "url": "https://bioresearch.gatech.edu/education-and-outreach/petit-scholars",
        "description": _page("Applications are now open."),
        "deadline": None,
        "is_rolling": True,
        "metadata": {
            "is_active": True,
            "collector_key": "petit_scholars",
            "collector_source": "gatech_program",
            "status": "open",
            "deadline_note": note,
            "seed_page_verified": True,
            "last_verified": "2026-10-10T13:47:31.345369",
        },
    }
    record.update(overrides)
    return record


_PETIT = "Petit Undergraduate Research Scholars Program (IBB)"
_USTAR = "Hopkins USTAR — Undergraduate Scholars Training in Aging Research"
_PETIT_NEXT = "2027 cohort applications were due Sept. 15, 2026; dates for the next cohort are not posted yet"


class TestAPassedNoteDeadlineEndsTheOpenClaim:
    def test_petit(self, calendar):
        # What the config at b8602cb0 writes on the next refresh. The live
        # row's note says "open", which this rule leaves alone (TestWordsThatKeepTheWindowOpen).
        record = _program(_PETIT_NEXT)
        assert neutralize_lifecycle_title(record["title"], record) == _PETIT

    def test_ustar(self, calendar):
        record = _program(
            "2025 cohort applications were due January 24, 2025; no later dates are posted",
            title=f"{_USTAR} (applications open)",
            id="jhu-30cee668ca23",
            source="jhu_research_programs",
        )
        assert neutralize_lifecycle_title(record["title"], record) == _USTAR

    def test_the_public_payload_carries_the_plain_title(self, calendar):
        record = _program(_PETIT_NEXT)
        payload = project_public_opportunity_payload(deepcopy(record), record)
        assert payload["title"] == _PETIT

    @pytest.mark.parametrize("note", [
        "Application deadline for summer 2026: Sunday, March 1, 2026 at 11:59 PM",
        "Summer 2026 applications were due 11:59 PM Monday, March 2, 2026; summer 2027 dates are not posted yet",
    ], ids=["ucla-incubator", "time-before-date"])
    def test_the_other_live_shapes(self, calendar, note):
        record = _program(note)
        assert neutralize_lifecycle_title(record["title"], record) == _PETIT

    @pytest.mark.parametrize("note", [
        # The rule reads the whole note, not its deadline clauses: these were
        # left alone while a deadline clause had to carry the date.
        "Applications closed February 15, 2026 at 11:59 PM; dates for the next cycle are not posted yet.",
        "All application materials must be received by February 1, 2026",
        "Summer 2026 deadline was Feb 9, 2026; Summer 2027 deadline not posted yet",
        # "Quarterly deadlines" here would keep the suffix (a recurring cycle; see test_each_word).
        "Two deadlines; Winter deadline Friday, January 15, 2025 and Spring deadline Friday, April 9, 2025",
        "Paused due to funding; last cohort started June 1, 2025",
    ], ids=["closed-wording", "received-by", "undated-second-deadline", "undated-plural", "due-to"])
    def test_a_note_whose_dates_are_all_behind_us(self, calendar, note):
        record = _program(note)
        assert neutralize_lifecycle_title(record["title"], record) == _PETIT

    def test_only_the_open_claim_goes(self, calendar):
        """Not a closure: the row stays actionable, so Apply, Tailor and Cold
        Email still work, and every other title is untouched."""
        record = _program("2025 cohort applications were due January 24, 2025")
        assert target_truth(record).actionable is True
        assert target_truth(record).reason_code is None
        for title in ("Summer Program (applications closed)", "Open House", "  Research Assistant (Physics) "):
            assert neutralize_lifecycle_title(title, record) == title

    def test_the_real_clock_ends_a_long_past_deadline(self):
        record = _program("2025 cohort applications were due January 24, 2025; no later dates are posted")
        assert neutralize_lifecycle_title(record["title"], record) == _PETIT


class TestTheGraceIsM05s:
    """Date D has passed everywhere only from UTC D+2, the same grace the
    stated-deadline closure uses."""

    @pytest.mark.parametrize("today,kept", [
        (date(2026, 9, 15), True),
        (date(2026, 9, 16), True),
        (date(2026, 9, 17), False),
    ], ids=["deadline-day", "day-after", "two-days-after"])
    def test_petit_around_its_deadline(self, monkeypatch, today, kept):
        monkeypatch.setattr(evidence, "_today", lambda: today)
        record = _program(_PETIT_NEXT)
        assert (neutralize_lifecycle_title(record["title"], record) == record["title"]) is kept


class TestWordsThatKeepTheWindowOpen:
    """A note that mentions an opening or reopening, rolling review, TBA or
    TBD, "until filled", "no deadline" or a recurring cycle keeps the suffix
    whatever dates it gives: the page may be right that applications are open."""

    @pytest.mark.parametrize("note", [
        # Live rows: their notes mention the opening, so this rule leaves the suffix.
        "2027 cohort applications open with a September 15, 2026 deadline",
        "Applications open Oct 15, 2025; deadline Feb 15, 2026; decisions by April 1, 2026",
        "Application opened November 1, 2025; deadline February 1, 2026, 11:59pm PDT; "
        "notifications mid-March to April 11, 2026.",
    ], ids=["gatech-petit-live", "gatech-sure", "stanford-ssrp"])
    def test_live_notes_that_mention_the_opening(self, calendar, note):
        record = _program(note)
        assert neutralize_lifecycle_title(record["title"], record) == record["title"]

    @pytest.mark.parametrize("note", [
        # Review M90 (a): a date beside an opening, a reopening or an undated
        # deadline was read as the deadline.
        "Applications open September 1, 2026, deadline TBA",
        "Applications open September 1, 2026 with a rolling deadline",
        "Deadline February 15, 2026, applications reopen October 1, 2026",
        "The 2026 deadline was February 15, 2026 and the 2027 application opened October 1, 2026",
        "Deadline: March 1, 2026\nApplications reopen: October 1, 2026",
        "Priority deadline March 1, 2026; applications accepted on a rolling basis after that",
        "No fixed deadline (page updated January 5, 2026)",
        "Deadline TBA (info session January 5, 2026)",
        "Deadline: rolling, info session January 5, 2026",
        "Applications reviewed until the position is filled; no deadline, posted January 5, 2026",
        "Deadline: Sept. 15, 2026. Rolling admission thereafter.",
    ], ids=["open-tba", "open-rolling", "reopen", "opened", "reopen-newline", "rolling-after", "no-fixed-deadline",
            "tba-info-session", "rolling-info-session", "until-filled", "rolling-thereafter"])
    def test_review_probes(self, calendar, note):
        record = _program(note)
        assert neutralize_lifecycle_title(record["title"], record) == record["title"]

    @pytest.mark.parametrize("with_word,without", [
        ("2027 cohort applications open with a September 15, 2026 deadline",
         "2027 cohort applications came with a September 15, 2026 deadline"),
        ("Deadline February 15, 2026; the portal opens October 1, 2026",
         "Deadline February 15, 2026; the portal closed October 1, 2026"),
        ("Application opened November 1, 2025; deadline February 1, 2026",
         "Application posted November 1, 2025; deadline February 1, 2026"),
        ("Deadline February 15, 2026; next opening October 1, 2026",
         "Deadline February 15, 2026; next update October 1, 2026"),
        ("Deadline February 15, 2026; Reopens October 1, 2026",
         "Deadline February 15, 2026; Updated October 1, 2026"),
        ("Deadline March 1, 2026; the 2027 application cycle begins October 1, 2026",
         "Deadline March 1, 2026; the 2027 application cycle ended October 1, 2026"),
        ("Deadline March 1, 2026; the 2027 portal launches October 1, 2026",
         "Deadline March 1, 2026; the 2027 portal closed October 1, 2026"),
        ("Deadline March 1, 2026; the next round accepts applications from October 1, 2026",
         "Deadline March 1, 2026; the next round ended October 1, 2026"),
        ("Openings posted October 1, 2026; deadline March 1, 2026",
         "Positions posted October 1, 2026; deadline March 1, 2026"),
        ("Priority deadline March 1, 2026; rolling review after that",
         "Priority deadline March 1, 2026; final review after that"),
        ("2027 deadline TBA; 2026 deadline was March 1, 2026", "2026 deadline was March 1, 2026"),
        ("2027 deadline TBD; 2026 deadline was March 1, 2026", "2026 deadline was March 1, 2026"),
        ("2027 dates to be announced; 2026 deadline was March 1, 2026", "2026 deadline was March 1, 2026"),
        ("2027 deadline T.B.A.; 2026 deadline was March 1, 2026", "2026 deadline was March 1, 2026"),
        ("2027 deadline T.B.D.; 2026 deadline was March 1, 2026", "2026 deadline was March 1, 2026"),
        ("2027 deadline TBC; 2026 deadline was March 1, 2026", "2026 deadline was March 1, 2026"),
        ("2027 dates to be confirmed; 2026 deadline was March 1, 2026", "2026 deadline was March 1, 2026"),
        ("2027 dates to be determined; 2026 deadline was March 1, 2026", "2026 deadline was March 1, 2026"),
        ("Reviewed until the position is filled; posted January 5, 2026", "Reviewed; posted January 5, 2026"),
        ("No fixed deadline; page updated January 5, 2026", "Page updated January 5, 2026"),
        ("No deadline; last cohort selected March 1, 2025", "Last cohort selected March 1, 2025"),
        # A recurring cycle: the next date may already be set.
        ("Quarterly deadlines; last deadline March 1, 2026", "Deadlines; last deadline March 1, 2026"),
        ("Deadlines each quarter; last was March 1, 2026", "Deadlines; last was March 1, 2026"),
        ("Deadlines every quarter; last was March 1, 2026", "Deadlines; last was March 1, 2026"),
        ("One deadline per quarter; last was March 1, 2026", "One deadline; last was March 1, 2026"),
        ("Autumn-quarter deadline Oct 6, 2025; Winter-quarter deadline Jan 8, 2026",
         "Autumn deadline Oct 6, 2025; Winter deadline Jan 8, 2026"),
        ("Reviewed monthly; last review March 1, 2026", "Reviewed; last review March 1, 2026"),
        ("Reviewed each month; last review March 1, 2026", "Reviewed; last review March 1, 2026"),
        ("Reviewed every month; last review March 1, 2026", "Reviewed; last review March 1, 2026"),
        ("Offered annually; last deadline March 1, 2026", "Offered; last deadline March 1, 2026"),
        ("Annual cycle; last deadline March 1, 2026", "Last deadline March 1, 2026"),
        ("Offered each year; last deadline March 1, 2026", "Offered; last deadline March 1, 2026"),
        ("Offered every year; last deadline March 1, 2026", "Offered; last deadline March 1, 2026"),
        ("Deadline March 1, 2026 (one cycle per year)", "Deadline March 1, 2026"),
        ("Year-round; last cohort selected March 1, 2026", "Last cohort selected March 1, 2026"),
        ("ONGOING; last cohort selected March 1, 2026", "Last cohort selected March 1, 2026"),
    ], ids=["open", "opens", "opened", "opening", "reopens", "begins", "launches", "accepts", "openings",
            "rolling", "tba", "tbd", "to-be-announced", "t.b.a.", "t.b.d.", "tbc", "to-be-confirmed",
            "to-be-determined", "until-filled", "no-fixed-deadline", "no-deadline", "quarterly", "each-quarter",
            "every-quarter", "per-quarter", "season-quarter-deadline", "monthly", "each-month", "every-month",
            "annually", "annual-cycle", "each-year", "every-year", "one-cycle-per-year", "year-round", "ongoing"])
    def test_each_word(self, calendar, with_word, without):
        kept = _program(with_word)
        dropped = _program(without)
        assert neutralize_lifecycle_title(kept["title"], kept) == kept["title"]
        assert neutralize_lifecycle_title(dropped["title"], dropped) == _PETIT


class TestWhatItDoesNotTouch:
    """Anything short of a note that names no open window, writes every date
    in full and dates nothing within the grace or ahead of it changes
    nothing."""

    @pytest.mark.parametrize("note", [
        "Application opens Dec 14, 2026; deadline Feb 14, 2027 at 11:59 p.m.",
        "Application deadline October 31, 2026 for the academic-year cohort",
        # The later of two deadlines decides.
        "2025-26 nomination deadline Tuesday, Dec 1, 2025; student application deadline Monday, Jan 25, 2027.",
        "Application opens Monday, January 4, 2027; deadline Monday, March 1, 2027, 11:59pm PST; "
        "faculty mentor letter due March 8, 2027; project execution Summer 2027.",
    ], ids=["wisc", "northwestern", "two-deadlines", "vpue-major"])
    def test_an_upcoming_deadline(self, calendar, note):
        record = _program(note)
        assert neutralize_lifecycle_title(record["title"], record) == record["title"]

    @pytest.mark.parametrize("note", [
        "Summer 2026 applications were due Friday, February 13; annual cycle.",
        "Summer 2027 deadline: Friday, March 5 (11:59 PM CST)",
        "2026-27 deadlines: Oct 13, Nov 10, Jan 12, Feb 9 (11:59 PM CST, no extensions)",
        "Applications December 15 – February 8",
        "Mid-February annually",
        "Applications typically due in spring",
    ], ids=["day-no-year", "label-no-year", "list-no-year", "range-no-year", "month-only", "season"])
    def test_a_yearless_deadline(self, calendar, note):
        record = _program(note)
        assert neutralize_lifecycle_title(record["title"], record) == record["title"]

    @pytest.mark.parametrize("note", [
        # A deadline clause with a month we cannot place.
        "Application due early March (2026: March 2, 5pm)",
        "Summer 2026 ran May 18–July 24; deadline was early F",
        "Summer-Fall 2026 cycle deadline was 02/27/2026; annual cycle.",
        "Deadline March 1, 2026 (extended to 2027-01-15)",
        "Deadline March 1, 2026；2027年申请将于2026年10月1日开放",
        "Deadline February 30, 2025",
        "Deadline in February 2025",
        # A year from 2000 to 2099 only: this is a word count.
        "Statement due March 1, 1500 words maximum",
        # A past date in full beside a yearless one: the next round may be open.
        "Fall round deadline September 15, 2025; spring round applications close February 1",
        "Deadline September 15, 2025; apply by November 30 for the spring cohort",
        "",
        None,
        ["2025 cohort applications were due January 24, 2025"],
    ], ids=["early-month", "truncated", "numeric", "iso", "cjk", "no-such-day", "no-day", "word-count",
            "yearless-close", "yearless-apply-by", "empty", "none", "not-text"])
    def test_an_unparseable_deadline(self, calendar, note):
        record = _program(note)
        assert neutralize_lifecycle_title(record["title"], record) == record["title"]

    @pytest.mark.parametrize("note", [
        # Review M90 r2: a bare "May", a numeric date other than d/d, ISO or
        # CJK, and a TBA spelling outside the list dropped the suffix.
        "Fall round deadline September 15, 2025; spring round applications close in April",
        "Fall round deadline September 15, 2025; spring round applications close in May",
        "Deadline February 1, 2026; second round deadline late May",
        "Deadline 03-01-2027; info session March 1, 2026",
        "Deadline T.B.A. (info session January 5, 2026)",
        "Deadline to be confirmed (info session January 5, 2026)",
        # Every month name, "may" in any case included, and every digit must
        # sit in a full date, a time of day or a year on its own.
        "Deadline 1.3.2027; info session March 1, 2026",
        "Deadline 2027.03.01; info session March 1, 2026",
        "Deadline January 5, 2026; second round MAY",
        "Students may apply again; deadline was January 5, 2026",
        "Deadline was January 5, 2026; 10 more places",
    ], ids=["april-control", "close-in-may", "late-may", "dashed", "t.b.a.", "to-be-confirmed",
            "dotted", "year-first-dotted", "upper-may", "may-verb", "stray-number"])
    def test_a_month_or_digit_outside_a_full_date(self, calendar, note):
        record = _program(note)
        assert neutralize_lifecycle_title(record["title"], record) == record["title"]

    def test_may_in_a_full_date_is_read(self, calendar):
        record = _program("Applications were due May 1, 2026 at 5 p.m.")
        assert neutralize_lifecycle_title(record["title"], record) == _PETIT

    @pytest.mark.parametrize("note", [
        # northwestern-9e5d1ce486e9: the window runs to Nov 8 after the Oct 6 due date.
        "2026-27 open job search applications Oct 26 - Nov 8, 2026; pre-selected materials were due Oct 6, 2026",
        "Summer 2025 deadline was Feb 16, 2025; 2027 applications open fall 2026",
        "Deadline was Feb 1, 2026; the next cycle opened October 1, 2026",
        "Applications open; deadline was February 1, 2026",
    ], ids=["window-after-due-date", "undated-opening", "opening-after-deadline", "opening-without-date"])
    def test_a_window_the_note_opens_after_its_deadline(self, calendar, note):
        record = _program(note)
        assert neutralize_lifecycle_title(record["title"], record) == record["title"]

    def test_every_date_the_note_gives_must_be_behind_us(self, calendar):
        record = _program("Deadline Sept. 1, 2026; decisions by November 1, 2026")
        assert neutralize_lifecycle_title(record["title"], record) == record["title"]

    def test_a_discovered_page_is_not_a_configured_program(self, calendar):
        record = _program("2025 cohort applications were due January 24, 2025")
        assert evidence.configured_note_window_passed(record) is True
        record["metadata"]["discovered"] = True
        assert evidence.configured_note_window_passed(record) is False

    def test_a_note_from_another_collector_is_not_read(self, calendar):
        record = _program("Deadline: January 24, 2025", source="uiuc_sro", source_type="uiuc_research")
        assert evidence.configured_note_window_passed(record) is False

    def test_the_record_is_never_mutated(self, calendar):
        record = _program("2025 cohort applications were due January 24, 2025")
        before = deepcopy(record)
        neutralize_lifecycle_title(record["title"], record)
        assert record == before


class TestOnlyThePagesOwnSentenceKeepsTheSuffix:
    """M90, 2026-11-16: 27 served titles said "(applications open)". The
    collector's status reads the whole page: of their 26 pages that loaded, 18
    read open on an "Apply Now" link alone, 6 on a sentence about something
    else's applications and 2 no longer read open. Six of the rows held a
    status from a read weeks earlier, because their page had stopped loading.

    So the suffix stays only on a configured program whose last refresh
    loaded its page and kept, in the excerpt, a sentence that says, whole,
    that applications are open."""

    @pytest.mark.parametrize("excerpt", [
        "Applications are open.",
        "Applications are currently open!",
        "Scholars join a lab for a year. Applications are now open. Apply through the portal.",
        "Meet the scholars\nApplications are now open",
    ], ids=["plain", "currently", "among-other-sentences", "heading-line"])
    def test_a_page_that_says_so_keeps_it(self, calendar, excerpt):
        record = _program("", description=_page(excerpt))
        assert neutralize_lifecycle_title(record["title"], record) == record["title"]

    @pytest.mark.parametrize("description", [
        # Most of the 27: the excerpt has no such sentence, or there is none.
        "Scholars spend a year in a faculty lab.",
        _page("Scholars join a faculty lab for a year and present at a spring symposium."),
        # A link's label: uf-d8572cb84ea9 in the page body, purdue-8d52cd4b08e0 in the site menu.
        _page("Scholars are supported in their pursuit of a Ph.D. Apply Now!"),
        _page("Admissions Overview Undergraduate Admissions Apply Now Academics"),
        # A sentence about something else: osu-b6451f208c42, ucb-5f4f6f484f1251,
        # uchicago-6806765d5248, purdue-805818988b54, arizona-9159d1ff5d3d.
        _page("Applications are now open for the 2026 Three Minute Thesis Competition."),
        _page("Workshop and Startup Spotlight applications are now open."),
        _page("The field semester program is now accepting applications for the Fall 2027 program!"),
        _page("Spring 2027 – Now Accepting Faculty Project Applications"),
        _page("Honors Scholars Now Accepting Applications"),
        # A cycle the sentence names: tamu-f960392cf9ec, under /reu-archive/.
        _page("Applications for Summer 2026 REU are now open."),
        _page("Applications are not open."),
        _page("Applications are open to rising juniors."),
        _page("If applications are open, apply through the portal."),
        _page("Applications will open in January."),
    ], ids=["no-page-text", "nothing-said", "apply-now-button", "apply-now-menu", "another-event", "another-call",
            "another-program", "another-audience", "another-office-program", "a-named-cycle", "not-open",
            "open-to", "hedged", "later"])
    def test_a_page_that_does_not_say_so_loses_it(self, calendar, description):
        record = _program("", description=description)
        assert neutralize_lifecycle_title(record["title"], record) == _PETIT

    def test_a_sentence_the_excerpt_cut_short_is_not_read(self, calendar):
        # The words cut off may be "for the 2026 Three Minute Thesis Competition".
        tail = "Applications are now open"
        cut = "a" * (evidence.EXCERPT_LIMIT - len(tail) - 2) + ". " + tail
        assert len(cut) == evidence.EXCERPT_LIMIT
        record = _program("", description=_page(cut))
        assert neutralize_lifecycle_title(record["title"], record) == _PETIT
        whole = _program("", description=_page(cut[1:]))
        assert neutralize_lifecycle_title(whole["title"], whole) == whole["title"]

    @pytest.mark.parametrize("seed_page_verified", [False, None])
    def test_a_status_held_from_an_earlier_read(self, calendar, seed_page_verified):
        """cornell-4860da480b01 was last read on 09-17 and upenn-8063dfd66d46
        on 10-10: every run since failed to load the page, and merge kept the
        stored status and title."""
        record = _program("")
        record["metadata"]["seed_page_verified"] = seed_page_verified
        assert neutralize_lifecycle_title(record["title"], record) == _PETIT

    def test_a_passage_outlives_the_read_that_kept_it(self, calendar):
        """princeton-b07d2a507b0d: the passages of the 11-06 read stayed on
        the row after the 11-13 read failed. Only the excerpt is this read's."""
        record = _program("", description="Scholars spend a year in a faculty lab.")
        record["source_url"] = record["url"]
        record["metadata"]["contact_instruction_sources"] = [{
            "source_url": record["url"], "record_source_url": record["url"],
            "checked_at": "2026-10-03T13:47:30+00:00",
            "sections": [{"heading": "How to apply", "text": "Applications are now open."}],
        }]
        assert "Applications are now open." in evidence._captured_text(record)[0]
        assert neutralize_lifecycle_title(record["title"], record) == _PETIT

    def test_a_page_the_config_shares_or_calls_a_directory(self, calendar):
        shared = _program("")
        shared["metadata"]["shared_program_page"] = True
        assert neutralize_lifecycle_title(shared["title"], shared) == _PETIT
        directory = _program("", title="Summer Research Opportunities Directory (applications open)")
        assert neutralize_lifecycle_title(directory["title"], directory) == "Summer Research Opportunities Directory"

    def test_a_row_no_program_spec_wrote(self, calendar):
        discovered = _program("")
        discovered["metadata"]["discovered"] = True
        assert neutralize_lifecycle_title(discovered["title"], discovered) == _PETIT
        other = _program("", source="uiuc_sro", source_type="uiuc_research")
        assert neutralize_lifecycle_title(other["title"], other) == _PETIT

    def test_only_the_claim_goes(self, calendar):
        record = _program("", description="Scholars spend a year in a faculty lab.")
        before = deepcopy(record)
        payload = project_public_opportunity_payload(deepcopy(record), record)
        assert payload["title"] == _PETIT
        assert payload["target_truth"]["actionable"] is True
        assert record == before


class TestEveryConfiguredNoteTheRuleReads:
    """The wording check (dates aside) on every program note in our config.

    Its known limit: a note that says a window is open in words outside the
    list ("until further notice", "will be announced") still reads, and drops
    the suffix once its dates pass. So no note written in our config reads
    unless a person has looked at its words and listed it here. Notes already
    in the data shards, written before these commits, are not in this list:
    the measurement over the served rows counts them.
    """

    # A configured note that newly reads here fails this test until a person adds it to this list.
    _READ = {
        "caltech/surf_exchange_iceland": "Application due by March 1, 2027, 5:00 pm",
        "duke/goldwater_scholarship": "Requires campus nomination; 2026 cycle deadline Nov 6, 2026",
        "gatech/petit_scholars":
            "2027 cohort applications were due Sept. 15, 2026; dates for the next cohort are not posted yet",
        "jhu/jhu_ustar": "2025 cohort applications were due January 24, 2025; no later dates are posted",
        "northwestern/nu_circumnavigator_grant": "Deadline Thursday, November 19, 2026 (11:59 PM CST); finalist "
                                                 "interviews during week one of winter quarter",
        "northwestern/nu_iin_nanotech_reu": "Summer 2026 deadline was Feb 9, 2026; Summer 2027 deadline not posted yet",
        "northwestern/nu_lurie_cancer_summer_internship":
            "Your completed application must be received by midnight on Sunday, February 14, 2027.",
        "northwestern/nu_mccormick_summer_award":
            "2026 deadline was 5:00 PM Monday, April 6, 2026; 2027 deadline not posted yet",
        "northwestern/nu_mrsec_reu": "Deadline Feb 12, 2027 for Summer 2027",
        "northwestern/nu_mrsec_uri": "Application deadline October 31, 2026 for the academic-year cohort",
        "sbu/explorations_in_stem": "Centralized URECA summer application, deadline March 12, 2027",
        "sbu/suny_soar": "2026 applications closed (deadline was March 24, 2026); 2027 deadline not posted yet",
        "sbu/ureca_summer": "One centralized application covers URECA Summer, Explorations in STEM and the Velay "
                            "Fellowship (deadline March 12, 2027)",
        "sbu/velay_fellowship": "Centralized URECA summer application, deadline March 12, 2027",
        "stanford/biox_usrp":
            "Application deadline January 12, 2027 at 8:00 a.m. PST. Faculty mentors must complete the confirmation form within three days of submission.",
        "stanford/chappell_lougee": "Application deadline Tuesday, December 1, 2026, 11:59pm PST; faculty mentor "
                                    "letter due December 8, 2026; project execution Summer 2027.",
        "uchicago/dsi_summer_lab": "Applications close January 11, 2027 at 11:59 p.m. Central.",
        "uchicago/quad_summer_scholars": "Priority deadline January 31, 2027; final deadline March 31, 2027.",
        "uchicago/quad_year_scholars": "Academic-year deadlines: October 5, 2026 and December 18, 2026. "
                                      "Faculty letters are due with the application.",
        "uchicago/ede_plus": "Annual program; 2026 cohort application closed Feb 16, 2026; details of the EDE+ 2027 "
                             "application are not posted yet.",
        "ucla/amgen_scholars_ucla":
            "2026 application materials were due February 1, 2026; 2027 dates are not posted yet",
        "ucla/urc_sciences_summer": "Summer 2026 applications were due 11:59 PM Monday, March 2, 2026; summer 2027 "
                                    "dates are not posted yet",
        "ucla/ursp_sciences": "Application for 2026-2027 closed June 16, 2026 at 11:59 PM; the 2027-2028 application "
                              "is not posted yet",
        "uf/suirp":
            "Applications closed February 15, 2026 at 11:59 PM; dates for the next cycle are not posted yet.",
        "upenn/wharton_spur": "Application deadline is March 22, 2027",
        "utexas/ts_research_forum": "Next forum: April 16, 2027, Welch Hall Grand Concourse",
        "washu/dbbs_amgen_scholars": "2026 application deadline was February 2, 2026; the page has not posted a "
                                     "2027 Amgen Scholars application yet",
    }

    @staticmethod
    def _notes() -> dict:
        notes = {
            f"{school['school_slug']}/{spec['key']}": spec.get("deadline_note")
            for school in SCHOOL_CONFIGS
            for source in school.get("sources", [])
            for spec in source.get("programs", [])
        }
        return notes | {f"ucb/{spec['key']}": spec.get("deadline_note") for _, spec in ucb_sources.iter_programs()}

    def test_the_notes_it_reads_are_the_listed_ones(self):
        assert {key: note for key, note in self._notes().items() if evidence.configured_note_dates(note)} == self._READ

    @pytest.mark.parametrize("key", [
        "stanford/small_grant", "uchicago/quad_faculty_research_grant",
    ])
    def test_notes_without_a_specific_deadline_are_not_read(self, key):
        # A repeating cycle or a closed academic year does not establish a specific deadline.
        note = self._notes()[key]
        assert note and evidence.configured_note_dates(note) is None
