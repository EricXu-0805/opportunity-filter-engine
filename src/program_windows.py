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

    @property
    def opens_at(self) -> datetime | None:
        """When the stated opening day begins on the campus, or None."""
        if self.opens_on is None:
            return None
        return datetime.combine(self.opens_on, time.min, ZoneInfo(self.zone)).astimezone(UTC)


_REVIEWED = date(2026, 11, 5)
_SROP = "https://www.tgs.northwestern.edu/success/thoughtful-recruitment/summer-research-opportunity-program/"
_SFP = "https://sfp.caltech.edu/undergraduate-research/programs/"

# A page that writes its dates without a year ("March 1: Application
# deadline.") names the cycle elsewhere on the same page ("View the 2027
# program flyer!", "SURF 2027 application portal"); that is the year here.
WINDOWS: dict[tuple[str, str], ProgramWindow] = {
    ("northwestern", "nu_tgs_srop"): ProgramWindow(
        _SROP, _SROP + "srop-faq.html", _REVIEWED, date(2027, 2, 10),
        "The official BTAA application opens November 1, 2026 and closes Tuesday, February 10, 2027.",
        date(2026, 11, 1),
        "The official BTAA application opens November 1, 2026 and closes Tuesday, February 10, 2027.",
        "America/Chicago",
    ),
    ("unl", "unl_summer_research_program"): ProgramWindow(
        "https://summerprogram.unl.edu/", "https://summerprogram.unl.edu/", _REVIEWED, date(2027, 3, 1),
        "March 1: Application deadline.",
        date(2026, 11, 15), "November 15: Online application opens.", "America/Chicago",
    ),
    ("jhu", "summer_pura"): ProgramWindow(
        "https://hour.jhu.edu/opportunities/summerpura/", "https://hour.jhu.edu/opportunities/summerpura/",
        _REVIEWED, date(2027, 2, 1),
        "The Summer PURA program is accepting applications for summer 2027 projects starting 11/1/2026 "
        "through 2/1/2027.",
        date(2026, 11, 1),
        "The Summer PURA program is accepting applications for summer 2027 projects starting 11/1/2026 "
        "through 2/1/2027.",
        "America/New_York",
    ),
    ("caltech", "surf"): ProgramWindow(
        _SFP + "surf", _SFP + "surf/application_information", _REVIEWED, date(2027, 2, 22),
        "SURF applications are due on February 22.",
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


def reviewed_window(record: object) -> ProgramWindow | None:
    """The window of the configured program ``record`` is, or None.

    None for a discovered page, and for a row whose URL is not the one we
    read the window for: a config that moved the program to a new page has
    not had the new page read.
    """
    metadata = record.get("metadata") if isinstance(record, dict) else None
    if not isinstance(metadata, dict) or metadata.get("discovered"):
        return None
    school, key = metadata.get("collector_school"), metadata.get("collector_key")
    if not isinstance(school, str) or not isinstance(key, str):
        return None
    window = WINDOWS.get((school, key))
    if window is None or record.get("url") != window.url or record.get("source_url") != window.url:
        return None
    return window


def apply_program_window(record: dict) -> None:
    """Make the window's stated close the row's deadline, in place.

    The deadline is then a stated one (`src.evidence.stated_listing_deadline`):
    the row is offered until it passes and closed after.
    """
    window = reviewed_window(record)
    if window is not None:
        record["deadline"] = window.closes_on.isoformat()
        record["deadline_is_estimate"] = False


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
