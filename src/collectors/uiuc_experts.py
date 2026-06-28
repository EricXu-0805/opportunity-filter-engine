"""Enrich broad-field-only UIUC faculty with research concepts from Illinois
Experts (the campus Elsevier Pure portal).

The portal's person *listing* (403) and Pure web-service API (401) are both
blocked, but each individual person page is server-rendered with publication-
derived "fingerprint" concepts in ``<span class="concept">``. So a broad-only,
research-active professor — ACES (Animal/Crop/Food/Natural-Resources), the
geosciences, the veterinary research departments, whose own campus directory
exposes no per-faculty research areas — can be lifted off the bare department
field that otherwise makes a whole department rank identically.

Conservative by construction: the slug is ``first-last``; concepts are taken
only when the person page's own ``<h1>`` confirms the same person (last name a
token of it AND a shared first initial), so a same-name stranger never leaks
third-party research areas into the corpus. Clinical/performance faculty (no
publications) simply 404 and stay honestly broad.

Run periodically / on demand, NOT in the weekly refresh: Pure fingerprints
change slowly, and the keyword-richer dedup keeps these concepts in place when
the weekly faculty scrape re-fetches the same person with only the broad field.
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata

import requests
from bs4 import BeautifulSoup

from .uiuc_faculty import HEADERS, _faculty_specific_keywords

logger = logging.getLogger(__name__)

EXPERTS_URL = "https://experts.illinois.edu/en/persons/{slug}"
TIMEOUT = 15
DELAY = 1.0

# Strip from the first title word onward — "Andrea Aguiar Research Associate
# Professor" carries two title modifiers, so a single optional prefix isn't
# enough. These words never appear as given/family names.
_TITLE_TAIL = re.compile(
    r"\b(research|teaching|clinical|adjunct|associate|assistant|visiting"
    r"|professor|instructor|lecturer|scientist|emerit)\b.*",
    re.I,
)


def _deaccent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _name_parts(pi_name: str) -> tuple[str | None, str | None]:
    """(first, last) with title noise stripped and deaccented — for the slug and
    the name-confirmation check."""
    n = _TITLE_TAIL.sub("", _deaccent(pi_name or "")).strip()
    toks = re.sub(r"[^A-Za-z\s-]", "", n).split()
    return (toks[0], toks[-1]) if len(toks) >= 2 else (None, None)


def _concepts(soup: BeautifulSoup) -> list[str]:
    """Fingerprint concept names (the clean ``<span class="concept">`` inside each
    badge, dropping the thesaurus category + relevance %), top-ranked first."""
    out: list[str] = []
    for c in soup.select("button.concept-badge-large span.concept"):
        t = c.get_text(" ", strip=True)
        if t and t not in out:
            out.append(t)
    return out[:8]


def _name_confirms(soup: BeautifulSoup, first: str, last: str) -> bool:
    """The person page's own name must carry this last name AND share the first
    initial — a slug collision with a different person is not enriched."""
    h1 = soup.select_one("h1")
    if not h1:
        return False
    page = _deaccent(h1.get_text(" ", strip=True)).lower().split()
    return bool(page) and last.lower() in page and page[0][:1] == first[:1].lower()


def experts_concepts(pi_name: str, fetch=None) -> list[str]:
    """Verified Illinois Experts concepts for one professor, or [] if not found /
    not confidently the same person. ``fetch`` is injectable for tests."""
    first, last = _name_parts(pi_name)
    if not first:
        return []
    soup = (fetch or _fetch)(f"{first}-{last}".lower())
    if soup is None or not _name_confirms(soup, first, last):
        return []
    return _concepts(soup)


def _fetch(slug: str) -> BeautifulSoup | None:
    try:
        r = requests.get(EXPERTS_URL.format(slug=slug), headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    return BeautifulSoup(r.text, "html.parser")


def enrich(records: list[dict], departments: set[str], fetch=None) -> list[dict]:
    """For each broad-field-only faculty record in ``departments``, return an
    enriched copy (same identity, Experts concepts as keywords). Records that
    don't resolve/verify are skipped — they stay honestly broad. The copies merge
    back through ``merge_into_processed`` where the keyword-richer dedup replaces
    the broad originals and rebuilds their titles."""
    targets = [o for o in records
               if o.get("department") in departments and not _faculty_specific_keywords(o)]
    out: list[dict] = []
    for i, o in enumerate(targets):
        concepts = experts_concepts(o.get("pi_name") or "", fetch=fetch)
        if concepts:
            rec = dict(o)
            rec["keywords"] = concepts
            rec["research_areas"] = "; ".join(concepts)
            out.append(rec)
        if fetch is None and i < len(targets) - 1:
            time.sleep(DELAY)
    logger.info(f"Illinois Experts: enriched {len(out)}/{len(targets)} broad-only faculty")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    import sys
    for name in sys.argv[1:] or ["Klara Nahrstedt"]:
        print(f"{name}: {experts_concepts(name)}")
