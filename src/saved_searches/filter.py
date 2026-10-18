"""The saved-search refresh's filter: the match view's predicates, in Python.

Used by the cron route (backend/routes/saved_searches.py) to compute,
server-side, the set of opportunities currently matching each saved
search's filters_json. The match-set is diff'd against the prior cron
run to populate saved_searches.new_match_ids.

The results page filters on the server: POST /matches/view applies
``_apply_match_view_rows`` in backend/routes/matches.py. This module follows
that function across these dimensions:
  - filters.paid in {'', 'yes', 'no'}
  - filters.intl in {'', 'yes', 'no'}
  - filters.source in {'', '<source-name>'}
  - filters.onCampus in {'', 'yes', 'no'}
  - filters.deadline in {'', 'rolling', '7', '14', '30', 'passed'}
  - filters.scope in {'', 'campus', 'open'}, through the view's own
    ``_in_view_scope`` and view rows, against the student's home school
  - query text search across title/organization/keywords/description,
    read as the card serves them (after the public contact boundary), with
    web addresses in the description left out as the results page does

Not applied: filters.minScore. The score is the match view's ranking of the
profile the browser sends, with or without the AI pass, and repeating it here
would mean a full ranking per saved search on the API's one match thread.
The route excludes what the student's stored profile rules out
(hard_exclusion), and the match view applies the minimum score when the
results open; the New badge and the digest say so.

Filter input shape (from saved_searches.filters_json):
  {
    "paid": "" | "yes" | "no",
    "intl": "" | "yes" | "no",
    "source": str,
    "onCampus": "" | "yes" | "no",
    "deadline": "" | "rolling" | "7" | "14" | "30" | "passed",
    "scope": "" | "campus" | "open"   (absent on rows saved before it),
    "minScore": int   (not applied here)
  }
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime

from backend.lib.public_projection import redact_embedded_emails
from backend.routes.matches import _in_view_scope, _match_view_row
from src.evidence import faculty_contact_claims_unverified
from src.matcher.ranker import _word_re, expand_search_aliases, without_web_addresses


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


def _matches_scope(opp: dict, want: str, home_school: str, view_rows: Mapping | None) -> bool:
    """The match view's scope rule over the view's own row for ``opp``.

    The row, not the record: a faculty profile's card says audience
    'unknown' and an unreviewed record's card carries no audience, whatever
    the stored record holds. ``view_rows`` maps an id to its row as the view
    keys them; a record it lacks gets its row built here.
    """
    if not want:
        return True
    row = view_rows.get(opp.get("id")) if view_rows is not None else None
    if row is None:
        row = _match_view_row(opp)
    return _in_view_scope(row, want, home_school)


_WORD_BOUNDARY_TERM_MAX_LEN = 3


def _served_query_fields(opp: dict) -> tuple:
    """The fields a query reads, as the record's card serves them.

    The card passes each of them through the public contact boundary, so the
    query reads what that boundary returns rather than the stored text. The
    description's web addresses are left out, as on the results page (M104).
    """
    fields = [
        opp.get("title") or "",
        opp.get("organization") or "",
        opp.get("department") or "",
        opp.get("description_clean") or opp.get("description_raw") or "",
    ]
    fields.extend(kw for kw in opp.get("keywords") or [] if isinstance(kw, str))
    served = [redact_embedded_emails(field) for field in fields]
    served[3] = without_web_addresses(served[3])
    return tuple(served)


def _query_fields(opp: dict, served: dict | None) -> tuple:
    """``_served_query_fields(opp)``, kept in ``served`` across calls if given.

    The cron checks every saved search against the same records, and the
    boundary costs about 7 s over the committed corpus, so it keeps one
    ``served`` for the whole run: each record is read through it at most once.
    """
    if served is None:
        return _served_query_fields(opp)
    entry = served.get(id(opp))
    # The record is kept with its fields, so an id reused by another object
    # can never answer for it.
    if entry is None or entry[0] is not opp:
        entry = served[id(opp)] = (opp, _served_query_fields(opp))
    return entry[1]


def _matches_query(opp: dict, query_lower: str, served: dict | None = None) -> bool:
    if not query_lower:
        return True
    haystacks = [field.lower() for field in _query_fields(opp, served)]
    # A term short enough to live inside ordinary English must match a whole
    # word. Every faculty description ends "...opportunities are currently
    # available", which contains av-AI-lable, re-SE-arch and depart-ME-nt, so
    # a saved search for "ai" was mailing the student 92% of the corpus. Same
    # rule and same threshold as the /matches/view predicate.
    #
    # Aliases come from the same place the route gets them. The results page
    # tells the student their search is "(also matching: machine learning)",
    # and this digest was then mailing them the bare token: a saved "nlp"
    # matched 37 records here against 324 on the site.
    for term in expand_search_aliases(query_lower):
        if len(term) <= _WORD_BOUNDARY_TERM_MAX_LEN:
            pattern = _word_re(term)
            if any(pattern.search(h) for h in haystacks):
                return True
        elif any(term in h for h in haystacks):
            return True
    return False


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
    *,
    served: dict | None = None,
    home_school: str = "uiuc",
    view_rows: Mapping | None = None,
) -> list[dict]:
    """Return opportunities matching ``filters`` + ``query`` text search.

    Order is preserved from the input iterable. The cron only cares about
    the set of matched IDs, but downstream callers may want the full row
    (e.g. a future "show me what's in this saved search right now" route).
    ``served``: an empty dict shared by calls over the same records, so each
    record's served fields are read once (see ``_query_fields``).
    ``home_school``: the student's school, as the match view reads it, for
    filters.scope; ``view_rows``: the match view's rows by id, if built.
    """
    q = (query or "").strip().lower()
    scope = filters.get("scope") or ""
    return [
        o for o in opportunities
        if match_filter(o, filters)
        and _matches_scope(o, scope, home_school, view_rows)
        and _matches_query(o, q, served)
    ]


def matching_ids(
    opportunities: Iterable[dict],
    filters: dict,
    query: str = "",
    *,
    served: dict | None = None,
    home_school: str = "uiuc",
    view_rows: Mapping | None = None,
) -> list[str]:
    """Same as filter_opportunities but returns just the opportunity IDs.

    Stable insertion order. Used by the cron to compute the result set
    that gets diff'd against last_result_ids.
    """
    return [
        str(o["id"])
        for o in filter_opportunities(
            opportunities, filters, query,
            served=served, home_school=home_school, view_rows=view_rows,
        )
        if o.get("id")
    ]
