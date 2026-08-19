"""Pure-Python port of the /results frontend filter logic.

Used by the cron route (backend/routes/saved_searches.py) to compute,
server-side, the set of opportunities currently matching each saved
search's filters_json. The match-set is diff'd against the prior cron
run to populate saved_searches.new_match_ids.

Mirrors frontend/src/app/results/page.tsx's `filtered = useMemo(...)`
logic across these dimensions:
  - filters.paid in {'', 'yes', 'no'}
  - filters.intl in {'', 'yes', 'no'}
  - filters.source in {'', '<source-name>'}
  - filters.onCampus in {'', 'yes', 'no'}
  - filters.deadline in {'', 'rolling', '7', '14', '30', 'passed'}
  - query text search across title/organization/keywords/description

Deliberately omitted: filters.minScore. Scoring requires the user's
profile, which the cron doesn't have access to (and we don't want to
denormalise the profile into saved_searches). minScore is enforced
client-side after the user opens the matched results page.

Filter input shape (from saved_searches.filters_json):
  {
    "paid": "" | "yes" | "no",
    "intl": "" | "yes" | "no",
    "source": str,
    "onCampus": "" | "yes" | "no",
    "deadline": "" | "rolling" | "7" | "14" | "30" | "passed",
    "minScore": int   (ignored here)
  }
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime

from src.evidence import faculty_contact_claims_unverified


def days_until(deadline: str | None) -> int | None:
    """Return calendar days from today until ``deadline`` (YYYY-MM-DD).

    Returns ``None`` when the input is missing, empty, or unparseable.
    Negative values indicate the deadline is in the past. Matches the
    frontend's daysUntil() in lib/match-utils.ts so cron-side filtering
    agrees with what the user sees on /results.
    """
    if not deadline:
        return None
    try:
        dl = datetime.strptime(deadline[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (dl - date.today()).days


def _matches_paid(opp_paid: str | None, want: str) -> bool:
    if not want:
        return True
    if want == "yes":
        return opp_paid in ("yes", "stipend")
    if want == "no":
        return opp_paid in ("no", "unknown") or opp_paid is None
    return True


def _matches_intl(eligibility: dict, want: str) -> bool:
    if not want:
        return True
    if want == "yes":
        return eligibility.get("international_friendly") == "yes"
    return True


def _matches_source(opp_source: str | None, want: str) -> bool:
    return not want or opp_source == want


def _matches_on_campus(opp_on_campus: bool | None, want: str) -> bool:
    if not want:
        return True
    if want == "yes":
        return opp_on_campus is True
    if want == "no":
        return opp_on_campus is False
    return True


def _matches_deadline(opp: dict, want: str) -> bool:
    if not want:
        return True
    if faculty_contact_claims_unverified(opp):
        return False
    # 'rolling' reads a different field, so it takes the whole record. Note the
    # fallthrough below returns True for an unrecognised value: before this
    # branch existed, a saved search carrying deadline='rolling' matched every
    # record instead of the rolling ones. Any future value must land here too.
    if want == "rolling":
        return opp.get("is_rolling") is True
    d = days_until(opp.get("deadline"))
    if want == "passed":
        return d is not None and d < 0
    try:
        cutoff = int(want)
    except ValueError:
        return True
    return d is not None and 0 <= d <= cutoff


def _matches_query(opp: dict, query_lower: str) -> bool:
    if not query_lower:
        return True
    haystacks: list[str] = [
        (opp.get("title") or "").lower(),
        (opp.get("organization") or "").lower(),
        (opp.get("department") or "").lower(),
        (opp.get("description_clean") or opp.get("description_raw") or "").lower(),
    ]
    for kw in opp.get("keywords") or []:
        if isinstance(kw, str):
            haystacks.append(kw.lower())
    return any(query_lower in h for h in haystacks)


def match_filter(opp: dict, filters: dict) -> bool:
    """True if a single opportunity passes the filter dict.

    Defensive against missing / non-dict eligibility on the opp side —
    real opportunities.json data is well-formed but cron should never
    crash on a single malformed row.
    """
    is_faculty_contact = faculty_contact_claims_unverified(opp)
    eligibility = opp.get("eligibility") or {}
    if not isinstance(eligibility, dict):
        eligibility = {}
    return (
        _matches_paid(
            "unknown" if is_faculty_contact else opp.get("paid"),
            filters.get("paid", ""),
        )
        and _matches_intl(
            {"international_friendly": "unknown"}
            if is_faculty_contact
            else eligibility,
            filters.get("intl", ""),
        )
        and _matches_source(opp.get("source"), filters.get("source", ""))
        and _matches_on_campus(
            None if is_faculty_contact else opp.get("on_campus"),
            filters.get("onCampus", ""),
        )
        and _matches_deadline(opp, filters.get("deadline", ""))
    )


def filter_opportunities(
    opportunities: Iterable[dict],
    filters: dict,
    query: str = "",
) -> list[dict]:
    """Return opportunities matching ``filters`` + ``query`` text search.

    Order is preserved from the input iterable. The cron only cares about
    the set of matched IDs, but downstream callers may want the full row
    (e.g. a future "show me what's in this saved search right now" route).
    """
    q = (query or "").strip().lower()
    return [o for o in opportunities if match_filter(o, filters) and _matches_query(o, q)]


def matching_ids(opportunities: Iterable[dict], filters: dict, query: str = "") -> list[str]:
    """Same as filter_opportunities but returns just the opportunity IDs.

    Stable insertion order. Used by the cron to compute the result set
    that gets diff'd against last_result_ids.
    """
    return [str(o["id"]) for o in filter_opportunities(opportunities, filters, query) if o.get("id")]
