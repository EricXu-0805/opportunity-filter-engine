"""Read the application notice Berkeley publishes on an individual URAP project."""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

SOURCE = "ucb_urap_projects"
PACIFIC = ZoneInfo("America/Los_Angeles")
_TERM = re.compile(r"(Spring|Summer|Fall|Winter) (20\d{2})", re.I)
_MONTHS = {name.lower(): i for i in range(1, 13) for name in (calendar.month_name[i], calendar.month_abbr[i])}
_MONTH = r"(?P<month>" + "|".join(_MONTHS) + r")\.?"
_DAY = r"(?P<day>\d{1,2})(?:st|nd|rd|th)?"
_DATE = (r"(?:(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
         + _MONTH + r"\s+" + _DAY + r"(?:,\s*(?P<year>20\d{2}))?")
_CLOCK = (r"(?:(?P<noon>(?:12\s+)?noon)|(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*"
          r"(?P<meridiem>[ap])\.?m\.?(?:\s+(?P<qualifier>noon|midnight))?)"
          r"(?:\s+(?P<zone>PT|PST|PDT)\b)?")
_DEADLINE_LABEL = re.compile(r"\b(?:the deadline to apply is|applications are due)\s+", re.I)
# A period can terminate a sentence or the abbreviation "p.m.". Do not
# discard an unparsed time zone as if it began a new sentence.
_END = (r"(?:\.?$|\.(?=\s+(?!(?:eastern|central|mountain|pacific|atlantic|alaska|hawaii|"
        r"universal|local|greenwich|london)\b|(?-i:[A-Z]{2,6})\b)(?-i:[A-Z][a-z])))")
_DEADLINES = (
    re.compile(_DATE + r"(?:\s*,\s*(?:(?:at|by)\s+)?|\s+(?:at|by)\s+)" + _CLOCK + _END, re.I),
    re.compile(_CLOCK + r"\s+on\s+" + _DATE + _END, re.I),
)
_OPENING = re.compile(r"\bEnter your application online beginning\s+" + _MONTH + r"\s+" + _DAY
                      + r"(?=\.|\s+and the deadline\b)", re.I)
_APPLICATION_CTA = " Apply through the URAP application portal."


def _date(year: int, month: str, day: str) -> date:
    return date(year, _MONTHS[month.lower()], int(day))


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
    labels = list(_DEADLINE_LABEL.finditer(notice))
    if len(labels) != 1:
        return None
    label = labels[0]
    for pattern in _DEADLINES:
        match = pattern.match(notice, label.end())
        if match is not None:
            break
    else:
        return None
    year = int(term[-4:])
    month = _MONTHS[match["month"].lower()]
    # A spring application round in late fall belongs to the previous
    # calendar year, even if the notice omits both the weekday and year.
    if term.lower().startswith("spring") and month >= 10:
        # An undated, weekday-free December notice cannot establish the
        # calendar year of a spring round on its own.
        if not (match["year"] or match["weekday"]):
            return None
        year -= 1
    if match["year"] and int(match["year"]) != year:
        return None
    try:
        close = _date(year, match["month"], match["day"])
        if match["weekday"] and close.strftime("%A").casefold() != match["weekday"].casefold():
            return None
        hour = 12
        if not match["noon"]:
            hour = int(match["hour"])
            if not 1 <= hour <= 12:
                return None
            hour = hour % 12 + 12 * (match["meridiem"].lower() == "p")
            if match["qualifier"]:
                expected = 12 if match["qualifier"].lower() == "noon" else 0
                if hour != expected or int(match["minute"] or 0):
                    return None
        closes_at = datetime(year, month, close.day, hour, int(match["minute"] or 0), tzinfo=PACIFIC)
        if match["zone"] and match["zone"].upper() not in {"PT", closes_at.tzname()}:
            return None
        opening = _OPENING.search(notice)
        if "application online beginning" in notice.lower():
            if opening is None:
                return None
            opens_year = year
            if month <= 3 and _MONTHS[opening["month"].lower()] >= 10:
                opens_year -= 1
            opens = _date(opens_year, opening["month"], opening["day"])
            if opens > close:
                return None
            detail["opens_on"] = opens.isoformat()
    except ValueError:
        return None
    return {**detail, "status": "open", "deadline_at": closes_at.isoformat(), "deadline_quote": notice[label.start():match.end()]}


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
