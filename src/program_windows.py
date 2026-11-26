"""Application windows read on each configured program's own pages.

A window belongs to one campus program spec (its school, collector key and
row URL) and holds only what the cited page states, in its words. A page that
refused us (HTTP 403, a bot check) gets no window: Johns Hopkins' academic-year
PURA page did on 2026-11-05.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ProgramWindow:
    url: str
    page: str
    reviewed_on: date
    closes_on: date
    closes_quote: str
    opens_on: date | None = None
    opens_quote: str = ""
    zone: str = ""
    opens_text: str = ""  # the opening date as the page writes it
    preserve_other_deadlines: bool = False

    @property
    def opens_at(self) -> datetime | None:
        """When the stated opening day begins on the campus, or None."""
        if self.opens_on is None:
            return None
        return datetime.combine(self.opens_on, time.min, ZoneInfo(self.zone)).astimezone(UTC)


_REVIEWED = date(2026, 11, 5)
_NCSA = "https://reu.ncsa.illinois.edu/"
_SUPERB = "https://eecs.berkeley.edu/resources/undergrads/undergraduate-research/superb/"
_SULI = "https://science.osti.gov/wdts/suli/How-to-Apply"
_HAAS = "https://research.berkeley.edu/haas-scholars/"
_SROP = "https://www.tgs.northwestern.edu/success/thoughtful-recruitment/summer-research-opportunity-program/"
_SFP = "https://sfp.caltech.edu/undergraduate-research/programs/"
_GRG = "https://undergradresearch.northwestern.edu/funding/grg/"

# A page that writes its dates without a year ("March 1: Application
# deadline.") names the cycle elsewhere on the same page ("View the 2027
# program flyer!", "SURF 2027 application portal"); that is the year here.
WINDOWS: dict[tuple[str, str], ProgramWindow] = {
    ("manual", "ext-uiuc-ncsa-reu"): ProgramWindow(
        _NCSA, _NCSA, date(2026, 11, 26), date(2027, 2, 15),
        "Online application: December 15, 2026 – February 15, 2027",
        date(2026, 12, 15), "Online application: December 15, 2026 – February 15, 2027",
        "America/Chicago", "December 15, 2026",
    ),
    ("ucb", "eecs_sure"): ProgramWindow(
        _SUPERB, _SUPERB, date(2026, 11, 25), date(2025, 1, 25),
        "Application deadline: January 25th 2025, 11:59 PM ET",
    ),
    ("ucb", "lbl_suli"): ProgramWindow(
        _SULI, _SULI, date(2026, 11, 25), date(2027, 1, 6),
        "Applications are due January 6, 2027 at 5:00 PM ET.",
    ),
    ("ucb", "haas_scholars"): ProgramWindow(
        _HAAS, _HAAS + "how-to-apply/", date(2026, 11, 25), date(2026, 3, 13),
        "Application deadline: Friday, March 13, 2026 at 12:00 PM Noon Pacific Time.",
    ),
    ("northwestern", "nu_tgs_srop"): ProgramWindow(
        _SROP, _SROP + "srop-faq.html", _REVIEWED, date(2027, 2, 10),
        "The official BTAA application opens November 1, 2026 and closes Tuesday, February 10, 2027.",
        date(2026, 11, 1),
        "The official BTAA application opens November 1, 2026 and closes Tuesday, February 10, 2027.",
        "America/Chicago", "November 1, 2026",
    ),
    ("northwestern", "nu_circumnavigator_grant"): ProgramWindow(
        _GRG, _GRG, date(2026, 11, 16), date(2026, 11, 19),
        "DEADLINE Thursday, November 19, 2026 (11:59 PM CST)",
    ),
    ("unl", "unl_summer_research_program"): ProgramWindow(
        "https://summerprogram.unl.edu/", "https://summerprogram.unl.edu/", _REVIEWED, date(2027, 3, 1),
        "March 1: Application deadline.",
        date(2026, 11, 15), "November 15: Online application opens.", "America/Chicago", "November 15",
    ),
    ("jhu", "summer_pura"): ProgramWindow(
        "https://hour.jhu.edu/opportunities/summerpura/", "https://hour.jhu.edu/opportunities/summerpura/",
        _REVIEWED, date(2027, 2, 1),
        "The Summer PURA program is accepting applications for summer 2027 projects starting 11/1/2026 "
        "through 2/1/2027.",
        date(2026, 11, 1),
        "The Summer PURA program is accepting applications for summer 2027 projects starting 11/1/2026 "
        "through 2/1/2027.",
        "America/New_York", "11/1/2026",
    ),
    ("caltech", "surf"): ProgramWindow(
        _SFP + "surf", _SFP + "surf/application_information", _REVIEWED, date(2027, 2, 22),
        "SURF applications are due on February 22.",
    ),
    ("caltech", "off_campus_surf"): ProgramWindow(
        _SFP + "off-campus-surf", _SFP + "surf/application_information", date(2026, 11, 26), date(2027, 2, 22),
        "SURF applications are due on February 22.", preserve_other_deadlines=True,
    ),
    ("caltech", "surf_exchange_iceland"): ProgramWindow(
        _SFP + "exchange_programs", _SFP + "exchange_programs", date(2026, 11, 26), date(2027, 3, 1),
        "due by March 1, 2027, 5:00 pm.", preserve_other_deadlines=True,
    ),
    ("caltech", "surf_jpl"): ProgramWindow(
        _SFP + "surfjpl", _SFP + "surfjpl/application-information", _REVIEWED, date(2027, 2, 22),
        "SURF@JPL applications are due on February 22.",
    ),
    ("caltech", "wave_fellows"): ProgramWindow(
        _SFP + "wavefellows", _SFP + "wavefellows/application_information", _REVIEWED, date(2027, 1, 8),
        "Applications are due on or before January 8.",
    ),
}


# Aggregator IDs can outlive the cohort their source pages described. Keep the
# exact incoming estimate with the host window so it cannot migrate to another
# year, a replaced program, or a newly confirmed date.
_WISCONSIN_DIRECTORY = "https://researchops.web.illinois.edu/opportunity/cellular-and-molecular-biology-stress-summer-research-program"
_WISCONSIN_HOST = "https://wiscience.wisc.edu/research/summer_research_program/"
_UND_AWARD = "https://www.nsf.gov/awardsearch/showAward?AWD_ID=2447669"
_AGGREGATOR_WINDOWS = {
    ("uiuc_sro", "sro-3c378261"): ("2027-02-15", ProgramWindow(
        _WISCONSIN_DIRECTORY, _WISCONSIN_HOST, date(2026, 11, 26), date(2027, 2, 10),
        "Apply by February 10, 2027.",
    )),
    ("nsf_reu", "nsf-reu-2447669"): ("2026-02-15", ProgramWindow(
        _UND_AWARD, "https://med.und.edu/education-training/biomedical-sciences/reu/index.html",
        date(2026, 11, 26), date(2026, 3, 15), "Applications will be accepted through March 15, 2026.",
    )),
}


def _aggregator_window(record: dict, original_estimate: str, window: ProgramWindow) -> ProgramWindow | None:
    if record.get("url") != window.url:
        return None
    deadline = record.get("deadline")
    if deadline != window.closes_on.isoformat() and not (
        deadline == original_estimate and record.get("deadline_is_estimate") is True
    ):
        return None
    source_url = record.get("source_url")
    if record["source"] == "nsf_reu":
        if source_url != window.url or str(record["metadata"].get("nsf_award_id")) != "2447669":
            return None
    else:
        # SRO records the pagination URL as source_url. The stable detail URL
        # identifies the entry; the deep page supplies its external host link.
        if not isinstance(source_url, str) or source_url.split("?", 1)[0] != "https://researchops.web.illinois.edu/":
            return None
        application = record.get("application")
        if not isinstance(application, dict) or application.get("application_url") not in (
            window.url, _WISCONSIN_HOST, "https://wiscience.wisc.edu/research/srp/",
        ):
            return None
    return window


def reviewed_window(record: object) -> ProgramWindow | None:
    """The window of the configured program ``record`` is, or None.

    None for a discovered page, and for a row whose URL is not the one we
    read the window for: a config that moved the program to a new page has
    not had the new page read.
    """
    metadata = record.get("metadata") if isinstance(record, dict) else None
    if not isinstance(metadata, dict) or metadata.get("discovered"):
        return None
    if record.get("source") in ("nsf_reu", "uiuc_sro"):
        identifier = record.get("id")
        if not isinstance(identifier, str):
            return None
        entry = _AGGREGATOR_WINDOWS.get((record["source"], identifier))
        return _aggregator_window(record, *entry) if entry else None
    school, key = metadata.get("collector_school"), metadata.get("collector_key")
    # A manual entry has a stable ID instead of collector coordinates. Its
    # two stored source URLs must still match the reviewed page below.
    if record.get("source") == "manual":
        school, key = "manual", record.get("id")
    # Berkeley's dedicated registry encodes its owner in its emitted source.
    # Both the old national row and its campus replacement carry the same key.
    if school is None and record.get("source") in {"ucb_external_research", "ucb_research_programs"}:
        school = "ucb"
    if not isinstance(school, str) or not isinstance(key, str):
        return None
    window = WINDOWS.get((school, key))
    if window is None or record.get("url") != window.url or record.get("source_url") != window.url:
        return None
    if window.preserve_other_deadlines and record.get("deadline") not in (None, "", window.closes_on.isoformat()):
        return None
    return window


def apply_program_window(record: dict) -> None:
    """Make the window's stated close the row's deadline, in place.

    The deadline is then a stated one (`src.evidence.stated_listing_deadline`):
    the row is offered until it passes and closed after. A row with a stated
    close is not rolling, so "No deadline listed" does not return it.
    """
    window = reviewed_window(record)
    if window is not None:
        record["deadline"] = window.closes_on.isoformat()
        record["deadline_is_estimate"] = False
        record["is_rolling"] = False
        if record.get("source") in ("nsf_reu", "uiuc_sro"):
            metadata = record["metadata"]
            metadata.pop("deadline_note", None)
            stamps = metadata.get("inferred_fields")
            if isinstance(stamps, dict):
                stamps.pop("deadline", None)


def read_before_opening(record: dict) -> bool:
    """Whether the row's page was last read before its window's stated opening.

    A status read then ("Apply now" left up from the last cycle) cannot say
    this cycle opened. A row with no readable read time counts as read
    before.
    """
    window = reviewed_window(record)
    opens_at = window.opens_at if window is not None else None
    if opens_at is None:
        return False
    try:
        read_at = datetime.fromisoformat(record["metadata"]["last_verified"])
    except (KeyError, TypeError, ValueError):
        return True
    if read_at.tzinfo is None:
        read_at = read_at.replace(tzinfo=UTC)  # the collectors write naive UTC
    return read_at < opens_at


def public_opening(record: dict) -> dict | None:
    """The stated opening a client shows until it passes, or None.

    ``at`` is when the opening day begins on the campus; a client compares it
    with its own clock, so a served payload never goes stale at the boundary.
    """
    window = reviewed_window(record)
    if window is None or window.opens_at is None:
        return None
    return {
        "on": window.opens_on.isoformat(),
        "at": window.opens_at.isoformat(),
        "text": window.opens_text,
        "quote": window.opens_quote,
        "source_url": window.page,
    }
