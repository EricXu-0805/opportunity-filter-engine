"""Enrich broad-field-only UIUC faculty with research concepts from Illinois
Experts (the campus Elsevier Pure portal).

The portal's person *listing* (403) and Pure web-service API (401) are both
blocked, but each individual person page is server-rendered with publication-
derived "fingerprint" concepts in ``<span class="concept">``. So a broad-only,
research-active professor — ACES (Animal/Crop/Food/Natural-Resources), the
geosciences, the veterinary research departments, whose own campus directory
exposes no per-faculty research areas — can be lifted off the bare department
field that otherwise makes a whole department rank identically.

Only UIUC rows are looked up, and a page counts only when it agrees with the
row: on the address when both have one, else on the unit and the full name. The
slug is ``first-last`` and Pure redirects a bare slug to whichever namesake
holds it as an alias, so a name match alone gave a NRES professor a business
professor's concepts, and a department-only target list gave a University of
Chicago physicist those of a UIUC animal scientist (M161). Clinical/performance
faculty (no publications) simply 404 and stay honestly broad.

The concepts are Elsevier's reading of a person's publications, not words the
person wrote, so they are stamped ``CONCEPTS_METHOD`` and every reader shows
them as inferred (``src.evidence.keywords_are_source_topics``).

Run periodically / on demand, NOT in the weekly refresh: Pure fingerprints
change slowly, and the keyword-richer dedup keeps these concepts in place when
the weekly faculty scrape re-fetches the same person with only the broad field.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import re
import time
import unicodedata
from copy import deepcopy
from datetime import UTC, datetime

import requests
from bs4 import BeautifulSoup

from ..evidence import stamp_inferred
from .uiuc_faculty import HEADERS, _faculty_specific_keywords, _is_junk_keyword

logger = logging.getLogger(__name__)

# The trailing slash is the canonical form; without it every lookup costs a 301.
EXPERTS_URL = "https://experts.illinois.edu/en/persons/{slug}/"
TIMEOUT = 15
# experts.illinois.edu/robots.txt asks for a 5-second crawl delay.
DELAY = 5.0
CONCEPTS_METHOD = "derived:illinois_experts_concepts"

# Research-active departments whose own campus directory exposes no per-faculty
# research areas, so their faculty otherwise carry only the department broad
# field. Performance/professional units (Music, Art, Architecture) are left out —
# their faculty don't publish into Pure, so they'd only 404. The set is a knob:
# add a department here to fold it into the monthly Experts pass.
TARGET_DEPARTMENTS = frozenset({
    # ACES + geosciences + veterinary research (the first cohort)
    "Department of Animal Sciences", "Department of Crop Sciences",
    "Food Science & Human Nutrition", "Natural Resources & Environmental Sciences",
    "Department of Climate, Meteorology & Atmospheric Sciences",
    "Department of Earth Science & Environmental Change",
    "Department of Veterinary Clinical Medicine", "Department of Pathobiology",
    "Department of Comparative Biosciences",
    # research-active STEM / social-science departments with broad-only faculty
    "Department of Economics", "Department of Physics", "Department of Statistics",
    "Department of Mathematics", "Department of Political Science",
    "School of Information Sciences", "Siebel School of Computing and Data Science",
    "School of Integrative Biology", "School of Molecular & Cellular Biology",
    "Department of Chemistry", "Department of Astronomy",
})

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
    badge, dropping the thesaurus category + relevance %), top-ranked first.
    Pure lists one concept from several thesauri ("Direct Numerical Simulation",
    "Direct numerical Simulation"); a repeat in another case, a name the corpus
    gate reads as junk (_is_junk_keyword) and a name with a comma, which every
    comma-joined list of keywords would read as two, are left out."""
    out: list[str] = []
    seen: set[str] = set()
    for c in soup.select("button.concept-badge-large span.concept"):
        t = c.get_text(" ", strip=True)
        if t and "," not in t and t.lower() not in seen and not _is_junk_keyword(t):
            seen.add(t.lower())
            out.append(t)
    return out[:8]


def _page_emails(soup: BeautifulSoup) -> set[str]:
    """The page's own addresses. Pure renders each as base64("mailto:<address>")
    in ``data-md5`` and splits the visible text with scripts."""
    out: set[str] = set()
    for a in soup.select("div.rendering_personorganisationcontactrendererportal li.emails a.email"):
        try:
            text = base64.b64decode(a.get("data-md5") or "", validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            continue
        if text.lower().startswith("mailto:"):
            out.add(text[len("mailto:"):].strip().lower())
    return out


def _unit_key(name: str) -> str:
    """"Department of Animal Sciences" and Pure's "Animal Sciences", "Food
    Science & Human Nutrition" and "Food Science and Human Nutrition", alike."""
    n = _deaccent(name).lower().replace("&", " and ").strip()
    n = re.sub(r"^department of ", "", n)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", n).split())


def _page_units(soup: BeautifulSoup) -> set[str]:
    """The units the page lists the person's positions in."""
    return {_unit_key(a.get_text(" ", strip=True)) for a in soup.select(
        "div.rendering_personorganisationlistrendererportal a[rel=Organisation]")}


def _same_person(soup: BeautifulSoup, record: dict) -> bool:
    """Whether the page is this row's person: the same address when both state
    one; otherwise the row's unit among the page's positions and the row's full
    first and last name in the page's own name."""
    email = (record.get("contact_email") or "").strip().lower()
    emails = _page_emails(soup)
    if email and emails:
        return email in emails
    first, last = _name_parts(record.get("pi_name") or "")
    h1 = soup.select_one("h1")
    page = _deaccent(h1.get_text(" ", strip=True)).lower().split() if h1 else []
    return (bool(first) and first.lower() in page and last.lower() in page
            and _unit_key(record.get("department") or "") in _page_units(soup))


def experts_concepts(record: dict, fetch=None) -> list[str]:
    """Illinois Experts concepts for one faculty row, or [] if not found / not
    this row's person. ``fetch`` is injectable for tests."""
    first, last = _name_parts(record.get("pi_name") or "")
    if not first:
        return []
    soup = (fetch or _fetch)(f"{first}-{last}".lower())
    if soup is None or not _same_person(soup, record):
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


def enrich(records: list[dict], departments: set[str], fetch=None,
           deadline: float | None = None, order_key: str = "") -> list[dict]:
    """For each listed, broad-field-only UIUC faculty record in ``departments``,
    return an enriched copy (same identity, Experts concepts as stamped
    keywords). Records that don't resolve/verify are skipped — they stay
    honestly broad. The copies merge back through ``merge_into_processed`` where
    the keyword-richer dedup replaces the broad originals and rebuilds their
    titles.

    Other schools' departments share these names (6,748 of 7,030 targets on
    2026-10-26) and the Experts pages are UIUC people's, so only UIUC rows are
    targets; a scheduled pass also publishes only the shards it refreshed.

    ``deadline`` (a ``time.monotonic()`` instant) stops the pass early. Pages
    that 404 leave their record broad, so a fixed order would spend every
    month's budget on the same unresolvable names; ``order_key`` shuffles the
    targets deterministically per key (refresh passes the month)."""
    targets = [o for o in records
               if o.get("source") == "uiuc_faculty"
               and (o.get("metadata") or {}).get("is_active") is not False
               and o.get("department") in departments and not _faculty_specific_keywords(o)]
    if order_key:
        targets.sort(key=lambda o: hashlib.sha256(
            f"{order_key}:{o.get('id') or o.get('pi_name') or ''}".encode()).hexdigest())
    out: list[dict] = []
    for i, o in enumerate(targets):
        if deadline is not None and time.monotonic() >= deadline:
            logger.info(f"Illinois Experts: time budget spent after {i}/{len(targets)} faculty")
            break
        concepts = experts_concepts(o, fetch=fetch)
        if concepts:
            # Not research text: the detail page would show any research text
            # as the profile's own words.
            rec = {**o, "keywords": concepts, "metadata": deepcopy(o.get("metadata") or {})}
            stamp_inferred(rec["metadata"], "keywords", CONCEPTS_METHOD)
            out.append(rec)
        if fetch is None and i < len(targets) - 1:
            time.sleep(DELAY)
    logger.info(f"Illinois Experts: enriched {len(out)}/{len(targets)} broad-only faculty")
    return out


def refresh(path: str = "data/processed/opportunities.json",
            time_budget_minutes: float | None = None) -> int:
    """Monthly/on-demand pass: enrich every broad-field-only faculty record in
    :data:`TARGET_DEPARTMENTS` from Illinois Experts and write the corpus back.
    Idempotent — already-specific records are skipped, and the keyword-richer
    dedup keeps prior concepts, so re-running only fills gaps (newly hired faculty,
    profiles that gained publications). Returns the number enriched this pass."""
    import json

    from ..normalizers.school_audience import apply_school_audience
    from .uiuc_faculty import merge_into_processed

    deadline = (time.monotonic() + time_budget_minutes * 60
                if time_budget_minutes is not None else None)
    corpus = json.load(open(path))
    enriched = enrich(corpus, set(TARGET_DEPARTMENTS), deadline=deadline,
                      order_key=datetime.now(UTC).strftime("%Y-%m"))
    if enriched:
        merge_into_processed(enriched, path)
        corpus = json.load(open(path))
        apply_school_audience(corpus)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(corpus, f, indent=2, ensure_ascii=False, default=str)
    logger.info(f"Illinois Experts refresh: {len(enriched)} faculty enriched")
    return len(enriched)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    import sys

    if "--refresh" in sys.argv:
        budget = None
        if "--time-budget-minutes" in sys.argv:
            budget = float(sys.argv[sys.argv.index("--time-budget-minutes") + 1])
        refresh(time_budget_minutes=budget)
    else:
        # A name alone has no row to check the page against: unverified.
        for name in [a for a in sys.argv[1:] if not a.startswith("-")] or ["Klara Nahrstedt"]:
            first, last = _name_parts(name)
            soup = _fetch(f"{first}-{last}".lower()) if first else None
            print(f"{name}: {_concepts(soup) if soup else []}")
