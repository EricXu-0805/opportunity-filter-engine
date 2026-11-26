"""Read the application notice Berkeley publishes on an individual URAP project."""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

SOURCE = "ucb_urap_projects"
PACIFIC = ZoneInfo("America/Los_Angeles")
_TERM = re.compile(r"(Spring|Summer|Fall|Winter) (20\d{2})", re.I)
_MONTH = r"(" + "|".join(calendar.month_name[1:]) + ")"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_WEEKDAY = r"(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
_DEADLINE = re.compile(
    r"\bThe deadline to apply is\s+" + _WEEKDAY + _MONTH + r"\s+" + _DAY
    + r"(?:,\s*(20\d{2}))?\s*(?:,\s*|\s+at\s+)(\d{1,2})(?::(\d{2}))?\s*(am|pm)"
    + r"(?:\s+(?:noon|midnight))?\s*(?:\.|$)", re.I,
)
_OPENING = re.compile(r"\bEnter your application online beginning\s+" + _MONTH + r"\s+" + _DAY + r"\.", re.I)
_APPLICATION_CTA = " Apply through the URAP application portal."


def _date(year: int, month: str, day: str) -> date:
    return date(year, list(calendar.month_name).index(month.capitalize()), int(day))


def parse_project_notice(soup, title: str, url: str, observed_at: datetime) -> dict | None:
    """Only a matching project heading, term and its standalone status notice qualify."""
    if soup is None:
        return None
    headings = soup.select("h3")
    if len(headings) != 1 or " ".join(headings[0].stripped_strings).split() != title.split():
        return None
    terms = {s.get_text(" ", strip=True) for s in soup.select("h2 > span")}
    terms = {term for term in terms if _TERM.fullmatch(term)}
    notices = [
        em.get_text(" ", strip=True) for em in soup.select("p > em:only-child")
        if em.parent.get_text(" ", strip=True) == em.get_text(" ", strip=True)
        and re.match(r"^(?:Open|Closed)\.", em.get_text(" ", strip=True), re.I)
    ]
    if len(terms) != 1 or len(notices) != 1:
        return None
    term, notice = terms.pop(), notices[0]
    detail = {"term": term, "source_url": url, "observed_at": observed_at.isoformat()}
    if notice.lower().startswith("closed."):
        return {**detail, "status": "closed"}
    matches = list(_DEADLINE.finditer(notice))
    if len(matches) != 1:
        return None
    match = matches[0]
    weekday, month, day, explicit_year, hour, minute, meridiem = match.groups()
    year = int(term[-4:])
    if (explicit_year and int(explicit_year) != year) or not 1 <= int(hour) <= 12:
        return None
    try:
        close = _date(year, month, day)
        if weekday and close.strftime("%A").casefold() != weekday.casefold():
            return None
        closes_at = datetime(year, close.month, close.day, int(hour) % 12 + 12 * (meridiem.lower() == "pm"),
                             int(minute or 0), tzinfo=PACIFIC)
        opening = _OPENING.search(notice)
        if "application online beginning" in notice.lower():
            if opening is None:
                return None
            opens = _date(year, *opening.groups())
            if opens > close:
                return None
            detail["opens_on"] = opens.isoformat()
    except ValueError:
        return None
    return {**detail, "status": "open", "deadline_at": closes_at.isoformat(), "deadline_quote": match[0].strip()}


def window_phase(detail: dict, now: datetime | None = None) -> str:
    if detail.get("status") == "closed":
        return "closed"
    if detail.get("status") != "open":
        return "unknown"
    try:
        close = datetime.fromisoformat(detail["deadline_at"])
        if close.tzinfo is None:
            return "unknown"
        now = now or datetime.now(UTC)
        if now >= close:
            return "closed"
        if detail.get("opens_on") and now.astimezone(PACIFIC).date() < date.fromisoformat(detail["opens_on"]):
            return "upcoming"
    except (KeyError, TypeError, ValueError):
        return "unknown"
    return "open"


# The pre-detail collector's sole open row in the deployed shard. Bind its
# independently read notice to both official URLs and the same project ID.
_LEGACY_ID = "20152-2"
_LEGACY_URL = "https://urapprojects.berkeley.edu/detail.php?id=20152-2"
_LEGACY_WINDOW = {
    "term": "Fall 2026", "status": "open", "source_url": _LEGACY_URL,
    "observed_at": "2026-11-25T12:06:36+00:00", "opens_on": "2026-08-21",
    "deadline_at": "2026-08-31T16:00:00-07:00",
    "deadline_quote": "The deadline to apply is Monday, August 31st, 4pm.",
}


def apply_legacy_window(record: dict) -> None:
    """Bring the existing served row up to the detail read until the next collection."""
    if record.get("source") != SOURCE:
        return
    meta = record.get("metadata") or {}
    if (record.get("id") != "ucb-urap-proj-4029d15a89db"
            or meta.get("urap_status") != "open" or meta.get("urap_window") or meta.get("urap_project_id") != _LEGACY_ID
            or record.get("url") != _LEGACY_URL or record.get("source_url") != _LEGACY_URL):
        return
    meta.update(urap_window=dict(_LEGACY_WINDOW), urap_status="closed", is_active=False,
                deadline_note=_LEGACY_WINDOW["deadline_quote"])
    record.update(deadline=_LEGACY_WINDOW["deadline_at"][:10], deadline_is_estimate=False, is_rolling=False)
    if isinstance(record.get("application"), dict):
        record["application"]["application_url"] = None
    for key in ("description", "description_clean", "description_raw"):
        if isinstance(record.get(key), str):
            record[key] = record[key].removesuffix(_APPLICATION_CTA)


def project_cutoff(record: dict) -> datetime | None:
    """The exact cutoff of an actionable URAP record, if one was observed."""
    if record.get("source") != SOURCE:
        return None
    meta = record.get("metadata") or {}
    if meta.get("urap_status") != "open":
        return None
    window = meta.get("urap_window")
    if not isinstance(window, dict):
        return None
    try:
        cutoff = datetime.fromisoformat(window["deadline_at"])
        return cutoff if cutoff.tzinfo is not None else None
    except (KeyError, TypeError, ValueError):
        return None
