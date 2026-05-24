"""Robust deadline string normalization.

Deadline strings collected from scrapers are gloriously inconsistent. Each
source has its own conventions — and on top of that, individual records leak
garbage (e.g. uiuc_sro briefly stored ``"?Yes"`` and ``"?No"`` checkbox
values in the deadline column because of a CSS-selector misalignment, see
git history). This module is the single normalization layer for every
inbound deadline string.

The pipeline runs four stages, in order, and short-circuits at the first hit:

  1. Sentinel regex  — ``"Rolling"``, ``"TBD"``, ``"ASAP"``, ``"Open until filled"``…
  2. Seasonal regex  — ``"Spring 2026"``, ``"Fall 2025 - Spring 2026"``, ``"Mid-February 2026"``…
  3. ``dateutil``    — every other recognizable date format including ``MM/DD/YY``
  4. UNPARSEABLE     — explicit sentinel; **never** silently becomes today's date

The cardinal rule: a string we cannot confidently parse must NOT become a
silent ``date.today()``. Downstream filters (``/api/opportunities/upcoming``,
``deactivate_past``, daily-reminders cron) all depend on knowing the difference
between "this opportunity has no deadline" and "we don't know the deadline".

API
---
:func:`normalize_deadline` is the main entry point. It always returns a
:class:`ParsedDeadline` — never raises, never returns ``None``.

:func:`to_legacy` converts the rich result to the historical
``(deadline_iso_str, is_rolling_bool)`` tuple still used by the opportunity
schema. Use it at write-time; new code should consume :class:`ParsedDeadline`
directly so we don't conflate ``ROLLING`` with ``UNKNOWN``.

:func:`reclassify_opportunity` mutates an opportunity dict in-place; used by
``scripts/backfill_deadlines.py`` and could be called from collectors at
write-time to fail-closed on garbage like ``"?Yes"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional

from dateutil.parser import ParserError
from dateutil.parser import parse as _dateutil_parse


class DeadlineType(str, Enum):
    """The seven flavors of deadline a string can resolve to.

    Stored as plain strings so JSON serialization is trivial and so the
    enum values are stable across schema changes.
    """

    EXACT = "exact"               # A specific date with confidence (date_start set)
    APPROXIMATE = "approximate"   # Season or fuzzy month (date_start + maybe date_end)
    RANGE = "range"               # Academic-year style range (date_start + date_end)
    ROLLING = "rolling"           # "Rolling", "Open until filled", etc.
    UNKNOWN = "unknown"           # "TBD", "TBA", "Coming Soon"
    ASAP = "asap"                 # "ASAP", "Immediately" — treat as highest urgency
    UNPARSEABLE = "unparseable"   # We tried; the string is garbage or unsupported


@dataclass(frozen=True)
class ParsedDeadline:
    """The result of running a raw deadline string through the pipeline.

    ``raw`` is always preserved verbatim so consumers can re-parse with a
    newer pipeline version, surface the original to the user, or debug
    misclassifications.
    """

    raw: str
    type: DeadlineType
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    confidence: float = 1.0
    notes: str = ""


# ── Sentinel patterns ──────────────────────────────────────────────────────
# Order matters: ASAP first so "asap" doesn't get swallowed by anything else,
# then ROLLING (broadest matches), then UNKNOWN (narrowest, mostly initialisms).

_ASAP_RE = re.compile(
    r"\b(?:asap|as\s+soon\s+as\s+possible|immediately|urgent)\b",
    re.IGNORECASE,
)

_ROLLING_RE = re.compile(
    r"""(?ix)
    \b(?:
        rolling(?:\s+(?:admissions?|basis|deadline|review))?
      | open\s+until\s+filled
      | open\s+enrollment
      | continuous(?:ly)?
      | ongoing
      | no\s+(?:fixed\s+)?deadline
      | applications?\s+accepted\s+(?:on\s+a\s+)?rolling
    )\b
    """,
)

_UNKNOWN_RE = re.compile(
    r"""(?ix)
    \b(?:
        t\.?\s?b\.?\s?d\.?
      | t\.?\s?b\.?\s?a\.?
      | coming\s+soon
      | to\s+be\s+(?:determined|announced|confirmed|posted|released|updated)
      | check\s+(?:back|website|site)
      | see\s+website
      | n\s?/\s?a
      | not\s+(?:yet\s+)?available
      | pending
    )\b
    """,
)

# ── Seasonal / range patterns ───────────────────────────────────────────────
# Northern-hemisphere academic calendar. These are deliberately wide windows
# so /opportunities/upcoming surfaces a season-deadline opp throughout that
# season rather than only on the date_start day.

_SEASON_BOUNDS = {
    "spring": (1, 31, 5, 31),   # Jan 31  →  May 31
    "summer": (5, 1, 8, 31),    # May  1  →  Aug 31
    "fall":   (8, 1, 12, 31),   # Aug  1  →  Dec 31
    "autumn": (8, 1, 12, 31),
    "winter": (12, 1, 2, 28),   # Dec  1  →  Feb 28 (wraps the year)
}

_RANGE_RE = re.compile(
    r"""(?ix)
    \b(?P<s1>spring|summer|fall|autumn|winter)\s+(?P<y1>20\d{2})
    \s*(?:-|–|—|to|through|thru)\s*
    (?P<s2>spring|summer|fall|autumn|winter)\s+(?P<y2>20\d{2})\b
    """,
)

_SEASON_RE = re.compile(
    r"""(?ix)
    \b(?P<season>spring|summer|fall|autumn|winter)\s+(?P<year>20\d{2})\b
    """,
)

# "End of January", "Mid-February 2026", "Late Spring 2026", "Early March"
_FUZZY_MONTH_RE = re.compile(
    r"""(?ix)
    (?:
        (?P<qual>early|mid|late|beginning\s+of|middle\s+of|end\s+of)
        [\s\-]*
    )?
    (?P<month>january|february|march|april|may|june|july|august|
              september|october|november|december|
              jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)
    (?:\s+(?P<year>20\d{2}))?
    """,
)

_MONTH_NUM = {
    "january": 1, "jan": 1, "february": 2, "feb": 2,
    "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_QUAL_TO_DAY = {
    None: 1, "early": 7, "beginning of": 5,
    "mid": 15, "middle of": 15,
    "late": 25, "end of": 28,
}


# ── Common SRO/Drupal field-label prefixes to strip ─────────────────────────
# Existing collectors (uiuc_sro) used to leave field labels like "Deadline:"
# or "Anticipated Deadline:" attached. Trim these before parsing so we don't
# waste a dateutil attempt on prose noise.

_LABEL_PREFIX_RE = re.compile(
    r"^(?:anticipated\s*)?(?:application\s+)?deadline\s*[:\-–—]?\s*",
    re.IGNORECASE,
)


def _strip_labels(s: str) -> str:
    return _LABEL_PREFIX_RE.sub("", s).strip()


def _season_to_dates(season: str, year: int) -> tuple[date, date]:
    s = season.lower()
    m1, d1, m2, d2 = _SEASON_BOUNDS[s]
    if s == "winter":
        return date(year, m1, d1), date(year + 1, m2, d2)
    return date(year, m1, d1), date(year, m2, d2)


def _infer_year(month_num: int, ref_year: int) -> int:
    """When a deadline has a month but no year, assume "next occurrence".

    e.g. on 2025-11-01 the string "March 15" most likely means 2026-03-15.
    """
    today = date.today()
    candidate = date(ref_year, month_num, 1)
    return ref_year + 1 if candidate < today else ref_year


# ── Garbage-token early exit ────────────────────────────────────────────────
# Strings like "?Yes", "?No" (the SRO bug), pure punctuation, or single
# alphabetic tokens that aren't a recognized sentinel can't possibly be a
# deadline. Reject them up front so dateutil(fuzzy=True) doesn't trip on
# them and "helpfully" return today's date based on the default.

_GARBAGE_RE = re.compile(r"^[\s\?\.\-–—_/\\|*•·]*$")  # only whitespace/punct
_MIN_USEFUL_LEN = 3


def _looks_like_garbage(s: str) -> bool:
    if not s or len(s.strip()) < _MIN_USEFUL_LEN:
        return True
    if _GARBAGE_RE.match(s):
        return True
    # "?Yes" / "?No" pattern (the SRO leak): leading punctuation + short word
    # with no digits and no recognized date keyword. Cheaper than running the
    # full pipeline and failing.
    if re.match(r"^[\?\.\-–—]+\s*[A-Za-z]{2,4}$", s.strip()):
        return True
    return False


def normalize_deadline(
    raw: Optional[str],
    *,
    reference_year: Optional[int] = None,
) -> ParsedDeadline:
    """Resolve a raw deadline string to a :class:`ParsedDeadline`.

    Never raises. Returns ``ParsedDeadline(type=UNPARSEABLE)`` for anything
    we can't classify with reasonable confidence.

    ``reference_year`` lets tests pin the "current year" used when a date
    string has no year. Defaults to ``date.today().year``.
    """
    if raw is None:
        return ParsedDeadline(raw="", type=DeadlineType.UNPARSEABLE)

    raw_str = str(raw)
    text = _strip_labels(raw_str).strip()
    if not text:
        return ParsedDeadline(raw=raw_str, type=DeadlineType.UNPARSEABLE)

    # 0. Garbage early exit (e.g., "?Yes" from the SRO selector bug)
    if _looks_like_garbage(text):
        return ParsedDeadline(
            raw=raw_str,
            type=DeadlineType.UNPARSEABLE,
            notes="filtered as non-date noise",
        )

    ref_year = reference_year or date.today().year

    # 1. Sentinels — order matters (ASAP wins over ROLLING wins over UNKNOWN)
    if _ASAP_RE.search(text):
        return ParsedDeadline(raw=raw_str, type=DeadlineType.ASAP, confidence=0.95)
    if _ROLLING_RE.search(text):
        return ParsedDeadline(raw=raw_str, type=DeadlineType.ROLLING, confidence=0.95)
    if _UNKNOWN_RE.search(text):
        return ParsedDeadline(raw=raw_str, type=DeadlineType.UNKNOWN, confidence=0.95)

    # 2a. Academic-year range
    m = _RANGE_RE.search(text)
    if m:
        start, _ = _season_to_dates(m["s1"], int(m["y1"]))
        _, end = _season_to_dates(m["s2"], int(m["y2"]))
        return ParsedDeadline(
            raw=raw_str,
            type=DeadlineType.RANGE,
            date_start=start,
            date_end=end,
            confidence=0.9,
            notes=f"{m['s1']} {m['y1']} → {m['s2']} {m['y2']}",
        )

    # 2b. Single season
    m = _SEASON_RE.search(text)
    if m:
        start, end = _season_to_dates(m["season"], int(m["year"]))
        return ParsedDeadline(
            raw=raw_str,
            type=DeadlineType.APPROXIMATE,
            date_start=start,
            date_end=end,
            confidence=0.85,
            notes=f"season approx: {m['season']} {m['year']}",
        )

    # 2c. Fuzzy month qualifier — "End of January", "Mid-February 2026"
    # Only treat as approximate when a qualifier is present; bare "January"
    # without qualifier falls through to dateutil so it parses to Jan 1 EXACT.
    m = _FUZZY_MONTH_RE.search(text)
    if m and m["qual"]:
        month_num = _MONTH_NUM[m["month"].lower()]
        qual = (m["qual"] or "").lower().strip() or None
        day = _QUAL_TO_DAY.get(qual, 1)
        year = int(m["year"]) if m["year"] else _infer_year(month_num, ref_year)
        try:
            # Clamp the day so "end of February" doesn't blow up on non-leap years
            d = date(year, month_num, min(day, 28))
            return ParsedDeadline(
                raw=raw_str,
                type=DeadlineType.APPROXIMATE,
                date_start=d,
                confidence=0.75,
                notes=f"qualifier '{qual}' → day {day}",
            )
        except ValueError:
            pass

    # 3. dateutil exact parse — handles ISO, MM/DD/YY, "March 15 2026",
    # "Friday, March 15", etc. Use fuzzy=False to avoid integer-in-prose
    # false positives. The label-stripping above already removes most prose.
    try:
        dt = _dateutil_parse(
            text,
            fuzzy=False,
            default=datetime(ref_year, 1, 1),
            dayfirst=False,
        )
        # Confidence drops a notch if year was inferred from the default
        has_explicit_year = bool(re.search(r"\b(?:20)?\d{2}\b", text))
        return ParsedDeadline(
            raw=raw_str,
            type=DeadlineType.EXACT,
            date_start=dt.date(),
            confidence=0.95 if has_explicit_year else 0.7,
            notes="" if has_explicit_year else "year inferred from default",
        )
    except (ParserError, OverflowError, ValueError):
        pass

    # 4. Truly unparseable. Don't guess.
    return ParsedDeadline(raw=raw_str, type=DeadlineType.UNPARSEABLE)


def to_legacy(parsed: ParsedDeadline) -> tuple[Optional[str], bool]:
    """Convert a :class:`ParsedDeadline` to the existing ``(deadline, is_rolling)``
    fields on the opportunity schema.

    - ``EXACT`` / ``APPROXIMATE`` / ``RANGE`` → ``(YYYY-MM-DD, False)`` using ``date_start``
    - ``ROLLING`` → ``(None, True)``
    - ``UNKNOWN`` / ``ASAP`` / ``UNPARSEABLE`` → ``(None, False)``  (surfaces as "missing")

    The legacy schema can't distinguish ``UNKNOWN`` from ``UNPARSEABLE``; that
    information is preserved on :class:`ParsedDeadline` for callers that want
    it (admin dashboard, future schema fields).
    """
    if parsed.type in (DeadlineType.EXACT, DeadlineType.APPROXIMATE, DeadlineType.RANGE):
        return (parsed.date_start.isoformat() if parsed.date_start else None, False)
    if parsed.type == DeadlineType.ROLLING:
        return (None, True)
    return (None, False)


def _iso_dates_equivalent(old: Optional[str], new: Optional[str]) -> bool:
    """True when ``old`` and ``new`` both resolve to the same ``YYYY-MM-DD``.

    Used to avoid churning records where the stored string is a fuller ISO
    datetime (e.g. handshake's ``"2026-04-17T23:59:59.999-05:00"``) and the
    new value is just the date (``"2026-04-17"``). Downstream consumers all
    slice ``[:10]`` so the difference is cosmetic — keep the richer string.
    """
    if not (isinstance(old, str) and isinstance(new, str)):
        return False
    if len(old) < 10 or len(new) < 10:
        return False
    return old[:10] == new[:10]


def reclassify_opportunity(
    opp: dict,
    *,
    reference_year: Optional[int] = None,
) -> dict:
    """Re-normalize an opportunity's deadline in place. Returns a change report.

    The opportunity dict is mutated only if the new values differ
    *meaningfully* from the existing ones — records with already-equivalent
    ISO strings (just with extra time/timezone precision) are left alone so
    backfills don't pollute the git diff with cosmetic changes.

    Returned report shape::

        {
            "raw":            original deadline string,
            "parsed_type":    ParsedDeadline.type value,
            "old_deadline":   what was there before,
            "new_deadline":   what we wrote (or kept),
            "old_is_rolling": prior is_rolling,
            "new_is_rolling": current is_rolling after our pass,
            "changed":        True iff opp dict was actually mutated,
        }
    """
    raw = opp.get("deadline")
    parsed = normalize_deadline(raw, reference_year=reference_year)
    new_dl, _new_rolling = to_legacy(parsed)

    old_dl = opp.get("deadline")
    old_rolling = bool(opp.get("is_rolling", False))

    changed = False

    if _iso_dates_equivalent(old_dl, new_dl):
        new_dl = old_dl
    elif old_dl != new_dl:
        opp["deadline"] = new_dl
        changed = True

    if parsed.type == DeadlineType.ROLLING and not old_rolling:
        opp["is_rolling"] = True
        changed = True

    return {
        "raw": raw,
        "parsed_type": parsed.type.value,
        "old_deadline": old_dl,
        "new_deadline": new_dl,
        "old_is_rolling": old_rolling,
        "new_is_rolling": opp.get("is_rolling", False),
        "changed": changed,
    }


# ── Backwards-compat shim ───────────────────────────────────────────────────
# A handful of legacy call sites import ``_parse_deadline`` directly.
# Provide an exact drop-in: returns ``date | None``. New code should call
# :func:`normalize_deadline` and switch on :class:`DeadlineType`.

def parse_to_date(value) -> Optional[date]:
    """Parse a raw deadline string to a single :class:`date`, or ``None``.

    Returns ``None`` for ``ROLLING``, ``UNKNOWN``, ``ASAP``, ``UNPARSEABLE``,
    or anything missing. ``RANGE`` returns its ``date_start``.
    """
    parsed = normalize_deadline(value)
    return parsed.date_start
