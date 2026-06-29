"""School-agnostic faculty-directory engine (curated-seed first, scrape-optional).

Generalizes the UC Berkeley department faculty collectors (``ucb_common`` +
the ``ucb_*_faculty`` configs) into a reusable engine so a new school's faculty
coverage is a config module under ``schools/`` — not a fresh collector.

Why curated-seed-first (unlike the Berkeley collectors, which scrape live):
some schools' department directories sit behind a bot wall (e.g. University of
Michigan's lsa/engin pages return Cloudflare 403 to ``requests``). A stdlib
scraper lands zero records there. So this engine inverts the Berkeley model:

  1. **Curated seed layer (always on, offline-safe, stdlib only).** Each
     department config carries a hand-verified list of real professors
     (name, title, profile URL, research areas, optional public email). These
     normalize into ``faculty_research`` records unconditionally — no network,
     so the data exists even when the directory blocks scrapers.

  2. **Best-effort scrape layer (deep mode, opt-in per department).** If a
     department config supplies a ``scrape`` block (url + CSS selectors), deep
     mode fetches and parses it to *discover* additional faculty on top of the
     curated set. Lazy-imports requests/bs4; any failure (403, timeout, markup
     drift) degrades silently to the curated seeds. Schools whose directories
     aren't walled get breadth for free; walled schools omit ``scrape`` and
     ship the curated set.

Records match the exact schema the Berkeley faculty collectors emit
(``source_type="faculty_research"``, pi_name/contact_email, eligibility +
metadata dicts) so they pass the same data-quality gate. The engine reuses
``ucb_common``'s school-agnostic helpers (person-name guard, nav-furniture
strip, funding detection, skill inference) rather than duplicating them.

A school config (see ``schools/umich_faculty.py``) is a dict:

    {
      "school_slug": "umich",
      "source": "umich_faculty",            # single source, dept in `department`
      "organization": "University of Michigan",
      "location": "Ann Arbor, MI",
      "id_prefix": "umich",
      "audience": "unknown",                # faculty = per-prof openness
      "work_auth_notes": "...",
      "departments": [
        {
          "short": "CSE",
          "name": "Computer Science & Engineering",
          "majors": ["Computer Science", ...],
          "directory_url": "https://cse.umich.edu/people/faculty/",
          "faculty": [ faculty(...), ... ],
          # optional: "scrape": {"url": ..., "selectors": {...}}
        },
        ...
      ],
    }
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urljoin

from .ucb_common import (
    _RETIRED_TITLE_RE,
    _detect_funding,
    _is_person_name,
    _strip_nav_furniture,
    infer_skills_from_research,
)

logger = logging.getLogger(__name__)

_DESC_CAP = 1500

# Per-profile research enrichment fetches every faculty member's own profile page
# (one HTTP request each), so it is gated behind an env flag: OFF in CI / the
# weekly refresh (richer-dedup keeps the already-enriched records, so the cost is
# paid once), ON for the deliberate one-shot enrichment run that generates the
# data. Set OFE_ENRICH_PROFILES=1 to enable the per-profile pass.
_PROFILE_ENRICH = os.environ.get("OFE_ENRICH_PROFILES") == "1"


def faculty(
    name: str,
    *,
    title: str = "Professor",
    url: str = "",
    email: str | None = None,
    research_areas: str = "",
    keywords: list[str] | None = None,
) -> dict:
    """Build one curated faculty spec.

    ``research_areas`` is free text (shown in the description + stored raw).
    ``keywords`` is the clean topical list that drives the title parenthetical
    and the matcher — keep it tidy (no page furniture / fragments) so it passes
    the faculty data-quality gate. If omitted it falls back to research_areas.
    """
    return {
        "name": name,
        "title": title,
        "url": url,
        "email": email,
        "research_areas": research_areas,
        "keywords": keywords or [],
    }


def validate(school: dict) -> list[str]:
    """Structural problems with a faculty school config (empty = healthy)."""
    errors: list[str] = []
    for field in ("school_slug", "source", "organization", "location", "id_prefix"):
        if not school.get(field):
            errors.append(f"missing {field}")
    seen_short: set[str] = set()
    for dept in school.get("departments", []):
        short = dept.get("short")
        if not short:
            errors.append("department missing 'short'")
        elif short in seen_short:
            errors.append(f"duplicate department short {short!r}")
        seen_short.add(short)
        if not dept.get("name"):
            errors.append(f"{short}: missing department name")
        if not any(dept.get(k) for k in ("faculty", "scrape", "api", "ajax", "algolia", "faculty180", "cola", "json_dir")):
            errors.append(f"{short}: no curated faculty, scrape, api, ajax, algolia, faculty180, cola, or json_dir config")
        for person in dept.get("faculty", []):
            if not person.get("name"):
                errors.append(f"{short}: faculty entry missing name")
    return errors


# ---------------------------------------------------------------------------
# Normalization (stdlib only)
# ---------------------------------------------------------------------------

def _clean_keywords(person: dict) -> list[str]:
    """Curated keywords win; otherwise derive a couple from research areas.

    Curated lists are trusted (the config author keeps them clean); the derived
    fallback splits research_areas on separators and trims, so even a config
    that only fills research_areas yields something the title can show.
    """
    kws = [k.strip() for k in person.get("keywords", []) if k and k.strip()]
    if kws:
        # A keyword is an atomic term; an internal comma (e.g. the taxonomy term
        # "Plants, Soil and Algae") would break the title-parenthetical subset
        # invariant (the DQ gate splits the parenthetical on commas), so fold it.
        kws = [re.sub(r"\s*,\s*", " / ", k) for k in kws]
        # de-dupe preserving order
        return list(dict.fromkeys(kws))[:8]
    raw = _strip_nav_furniture(person.get("research_areas", ""))
    parts = [p.strip() for chunk in raw.split(";") for p in chunk.split(",")]
    # Oxford-comma tails ("X, Y, and Wireless power transfer") split into a
    # clause led by a connective — strip it so the real topic stands alone and
    # the keyword clears the DQ junk filter.
    parts = [re.sub(r"^(?:and|or|&)\s+", "", p, flags=re.I).strip() for p in parts]
    # Directories often prefix the research block with a section label
    # ("Research Interests: semantics, syntax") that splitting leaves stuck to
    # the first term — drop the label so the term stands alone.
    parts = [_RESEARCH_LABEL_RE.sub("", p).strip() for p in parts]
    # A comma-split of prose interests leaves continuation clauses ("history,
    # especially in India" -> "especially in India") — drop any part led by a
    # qualifier connective (it is a sub-clause, not a standalone research area).
    parts = [p for p in parts if not _FRAGMENT_LEADIN_RE.match(p)]
    # Trim stray edge punctuation a comma/semicolon split leaves ("...in STEM." ->
    # "STEM"), then drop a part with unbalanced parentheses — a "(species
    # interactions" tail left dangling when a parenthetical itself got comma-split.
    parts = [p.strip(" .,:;") for p in parts]
    parts = [p for p in parts if p.count("(") == p.count(")")]
    # A research-area keyword is a short noun phrase; a part that runs long or to
    # many words is a prose bio fragment (some directories put free text in the
    # interests field) — drop it rather than ship a sentence as a keyword. Also
    # honour the same junk definition the DQ gate enforces, so a derived keyword
    # never ships something the gate would reject.
    try:
        from .uiuc_faculty import _is_junk_keyword
    except Exception:  # noqa: BLE001
        def _is_junk_keyword(_k):  # pragma: no cover
            return False
    return list(dict.fromkeys(
        p for p in parts
        if 3 <= len(p) <= 60 and len(p.split()) <= 6 and not _is_junk_keyword(p)
    ))[:8]


_RESEARCH_LABEL_RE = re.compile(
    r"^\s*(?:research\s+(?:interests?|areas?|focus|topics?)"
    r"|areas?\s+of\s+(?:interest|expertise|research|specialization|study)"
    r"|fields?\s+of\s+(?:interest|study|research)"
    r"|specializations?|expertise|interests?|keywords?)\s*[:：\-–—]\s*",
    re.I,
)

# A research-area keyword led by a qualifier connective is a prose continuation
# clause, not a standalone topic — the DQ gate rejects these, so we drop them at
# the source. (Mirrors test_faculty_keywords_have_no_fragment_leadins.)
_FRAGMENT_LEADIN_RE = re.compile(
    r"^(?:such as|particularly|especially|including|namely|e\.g\.?)\b", re.I)


_PRONOUN_RE = re.compile(
    r"\s*[-–—(]*\s*\b(?:she|he|they|ze|sie|xe|fae|per|ey)\b\s*[,/]\s*"
    r"\b(?:her|hers|him|his|them|theirs|hir|zir|xem|faer|per|em)\b\s*\)?\s*$",
    re.I,
)


def _strip_pronouns(name: str) -> str:
    """Drop a trailing pronoun clause some directories append to the name
    (e.g. "Laura E Frantz she,her" / "Jonika Hash - she, her" / "X (they/them)")."""
    return _PRONOUN_RE.sub("", name).strip()


# Post-nominal degree/credential suffixes some directories append (medical and
# professional schools especially): "Frank Alber, PhD" / "Jane Doe, MD, MPH".
_CREDENTIAL = (r"Ph\.?\s?D|M\.?\s?D|M\.?\s?S|M\.?\s?A|M\.?\s?P\.?H|D\.?\s?M\.?A"
               r"|Pharm\.?\s?D|Dr\.?\s?P\.?H|Sc\.?\s?D|D\.?\s?V\.?M|J\.?\s?D"
               r"|Ed\.?\s?D|D\.?\s?O|R\.?\s?N|D\.?\s?D\.?S|D\.?Phil|Psy\.?\s?D|FAIA")
# A trailing comma-run of post-nominals: each item is a known degree
# (case-insensitively) OR an all-caps professional fellowship/licensure acronym
# (FAACP, FAPhA, FAASLD, BCPS, LMSW, FAAN, …). The acronym branch is
# case-SENSITIVE (≥2 leading capitals) so it never eats an ordinary name word.
_CREDENTIAL_RE = re.compile(
    r"(?:\s*,\s*(?:(?i:" + _CREDENTIAL + r")|[A-Z]{2,}[A-Za-z.()-]*)\.?)+\s*$")


def _strip_credentials(name: str) -> str:
    """Drop trailing post-nominal degree/credential suffixes
    ("Jane Doe, PhD, MPH" / "Jamie Barner, Ph.D., FAACP, FAPhA")."""
    return _CREDENTIAL_RE.sub("", name).strip()


# A name carrying a (birth–death) year range is an in-memoriam directory entry,
# not active faculty — drop it ("Alberto Apostolico (1948-2015)"). Matched on the
# name only: a year range in a research title/area is legitimate (a historian of
# a 1500-1600 figure), so this never keys off the description.
_IN_MEMORIAM_RE = re.compile(r"\(\s*\d{4}\s*[-–—]\s*\d{4}\s*\)")


def _normalize(school: dict, dept: dict, person: dict) -> dict | None:
    """Convert one faculty spec into the normalized opportunity schema."""
    name = _strip_credentials(_strip_pronouns((person.get("name") or "").strip()))
    if not _is_person_name(name):
        return None
    if _IN_MEMORIAM_RE.search(name):
        return None  # "Name (1948-2015)" — an in-memoriam entry, not active faculty
    title = person.get("title") or "Professor"
    if _RETIRED_TITLE_RE.search(title):
        return None

    short = dept["short"]
    dept_name = dept["name"]
    profile_url = person.get("url", "")
    email = person.get("email") or None
    research_areas = _strip_nav_furniture(person.get("research_areas", ""))
    keywords = _clean_keywords(person)
    skills = infer_skills_from_research(person)

    now = datetime.now(UTC).replace(tzinfo=None).isoformat()
    name_hash = hashlib.md5(f"{short}-{name}".encode()).hexdigest()[:8]
    opp_id = f"faculty-{school['id_prefix']}-{short.lower()}-{name_hash}"

    desc_parts = [
        f"Research opportunity with {title} {name} in the {dept_name} "
        f"at {school['organization']}."
    ]
    if research_areas:
        desc_parts.append(f"Research areas: {research_areas[:200]}")
    desc_parts.append(
        "Contact the professor directly to inquire about undergraduate "
        "research positions in their lab."
    )
    description = " ".join(desc_parts)
    # Defensive second pass on the fully assembled description (mirrors
    # ucb_common.normalize_faculty): the DQ gate checks nav-furniture phrases in
    # description_clean, so stripping the final string makes a leak impossible
    # regardless of entry path — matters once a school enables the scrape layer.
    description = _strip_nav_furniture(description)

    research_summary = f" ({', '.join(keywords[:3])})" if keywords else ""
    opp_title = f"Research with Prof. {name} — {short}{research_summary}"
    paid, compensation_details = _detect_funding(f"{research_areas} {description} {title}")

    return {
        "id": opp_id,
        "source": school["source"],
        "source_url": profile_url,
        "source_type": "faculty_research",
        "title": opp_title,
        "organization": school["organization"],
        "department": dept_name,
        "lab_or_program": f"Prof. {name}'s Research Group",
        "pi_name": name,
        "contact_email": email,
        "url": profile_url,
        "location": school["location"],
        # External to this product's home users (matches the ucb_* convention);
        # multi-school scoping rides on school/audience, not on_campus.
        "on_campus": False,
        "remote_option": "unknown",
        "opportunity_type": "research",
        "paid": paid,
        "compensation_details": compensation_details,
        "deadline": None,
        "is_rolling": True,
        "posted_date": None,
        "start_date": None,
        "duration": "Semester or academic year",
        "eligibility": {
            "preferred_year": ["sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": dept.get("majors", []),
            "skills_required": skills[:3],
            "skills_preferred": skills[3:],
            "citizenship_required": False,
            "international_friendly": "unknown",
            "work_auth_notes": school.get("work_auth_notes", ""),
            "eligibility_text_raw": description[:500],
        },
        "application": {
            "contact_method": "email",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "low",
            "application_url": profile_url,
        },
        "description_raw": description,
        "description_clean": description[:_DESC_CAP],
        "keywords": keywords,
        "school": school["school_slug"],
        "audience": school.get("audience", "unknown"),
        "metadata": {
            "confidence_score": 0.7 if email else 0.5,
            "last_verified": now,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": f"Curated from {dept_name} faculty directory ({school['organization']})",
            "faculty_title": title,
            "research_areas_raw": research_areas[:300] if research_areas else "",
            "curated": True,
        },
    }


# ---------------------------------------------------------------------------
# Best-effort scrape layer (deep mode, lazy HTTP deps)
# ---------------------------------------------------------------------------

def _passes_ladder(title: str, lf: dict | None) -> bool:
    """Title-based ladder gate for static directories that mix ranks.

    Most non-UCB peer directories list emeriti / adjunct / teaching / research
    professors alongside ladder faculty. ``ladder_filter`` keeps only titles
    matching ``require`` (if given) and not matching ``drop`` — so a research-
    opportunity matcher surfaces PIs who actually take undergraduates.
    """
    if not lf:
        return True
    t = title or ""
    if lf.get("require") and not re.search(lf["require"], t, re.I):
        return False
    return not (lf.get("drop") and re.search(lf["drop"], t, re.I))


def _card_section(card, heading: str) -> str:
    """Nearest preceding heading text for a card (its role group)."""
    h = card.find_previous(heading)
    return h.get_text(" ", strip=True) if h else ""


def _passes_section(card, sf: dict | None) -> bool:
    """Section gate for single-page directories that group people by role heading.

    Some departments list Faculty, Teaching Faculty, Affiliate, and Emeritus on
    one page under sibling headings, with no per-card class or title that cleanly
    separates them (an Affiliate may carry a real "Professor, <other dept>"
    title). ``section_filter`` keeps only cards whose nearest preceding heading
    matches ``include`` (and not ``exclude``) — so a flat card selector can still
    land just the home-department ladder faculty.
    """
    if not sf:
        return True
    sec = _card_section(card, sf.get("heading", "h2"))
    if sf.get("include") and not re.search(sf["include"], sec, re.I):
        return False
    return not (sf.get("exclude") and re.search(sf["exclude"], sec, re.I))


def _passes_field(card, ff: dict | None) -> bool:
    """Per-card gate on the text of an arbitrary field selector.

    Some flat directories list home-department ladder faculty and cross-listed
    affiliates (whose primary appointment is at another department or institution)
    in one undifferentiated card grid, with no role heading and a clean
    "Professor" title on everyone — so neither ``section_filter`` nor
    ``ladder_filter`` can separate them. But the card often carries a primary-
    department / affiliation field (e.g. UW Microbiology's per-card
    "Department" cell, "Microbiology" for home faculty vs "Harvard University" /
    "Department of Pediatrics" for affiliates). ``field_filter`` reads that field
    via ``selector`` and keeps only cards whose text matches ``include`` (and not
    ``exclude``). An absent/empty field counts as a match for ``include`` (the
    home-department default leaves the field blank), and never matches
    ``exclude``.
    """
    if not ff:
        return True
    el = card.select_one(ff["selector"]) if ff.get("selector") else None
    text = el.get_text(" ", strip=True) if el else ""
    if ff.get("include") and text and not re.search(ff["include"], text, re.I):
        return False
    return not (ff.get("exclude") and text and re.search(ff["exclude"], text, re.I))


def _parse_cards(soup, sel: dict, base_url: str, ladder_filter: dict | None = None,
                 name_flip: bool = False, link_filter: str | None = None,
                 section_filter: dict | None = None,
                 field_filter: dict | None = None) -> list[dict]:
    """Parse one rendered directory page into faculty specs via CSS selectors.

    Optional selectors beyond card/name/link/title: ``research`` (interests text)
    and ``email`` (a mailto) let rich cards (e.g. UW ECE) land keyworded, emailed
    faculty in one pass rather than name-only stubs. ``ladder_filter`` drops
    non-ladder ranks by title; ``name_flip`` un-inverts "Last, First" listings;
    ``link_filter`` keeps only cards whose profile href matches (e.g. "/Faculty/"
    on directories that list faculty and staff together); ``section_filter`` keeps
    only cards under a matching role heading (single-page role-grouped directories).
    """
    people: list[dict] = []
    for card in soup.select(sel.get("card", "")):
        if not _passes_section(card, section_filter):
            continue
        if not _passes_field(card, field_filter):
            continue
        # ":self" = the card element itself is the name link (link-list
        # directories where each faculty is a bare <a>, no inner name node).
        if sel.get("name") == ":self":
            name_el = card
        else:
            name_el = card.select_one(sel["name"]) if sel.get("name") else None
        if not name_el:
            continue
        name = name_el.get_text(" ", strip=True)
        if sel.get("name_strip"):
            # Some directories prefix the name link with boilerplate ("Learn more
            # about <Name>"); strip it to recover the clean, properly-cased name.
            name = re.sub(sel["name_strip"], "", name).strip()
        if name_flip:
            name = _flip_name(name)
        if sel.get("link") == ":self":
            link_el = card
        elif sel.get("link"):
            link_el = card.select_one(sel["link"])
        else:
            link_el = name_el
        href = link_el.get("href") if link_el and link_el.has_attr("href") else ""
        if link_filter and not re.search(link_filter, href):
            continue
        href = urljoin(base_url, href) if href else base_url
        title_el = card.select_one(sel["title"]) if sel.get("title") else None
        title = title_el.get_text(" ", strip=True) if title_el else "Professor"
        if sel.get("title_strip_after"):
            # Some directories cram rank + office + phone into one cell; keep only
            # the text before the first contact marker (e.g. "Office"/"Phone").
            title = re.split(sel["title_strip_after"], title)[0].strip() or "Professor"
        if not _passes_ladder(title, ladder_filter):
            continue
        research = ""
        keywords: list[str] = []
        if sel.get("research_items"):
            # Each research area is its own element (e.g. Stanford's taxonomy
            # links, UW's Drupal "Fields of Interest" rendered on the listing
            # card) — collect them as clean atomic keywords (deduped, junk-gated,
            # capped) rather than one flattened blob.
            keywords = _clean_selector_items(card, sel["research_items"])
        if sel.get("research"):
            r_el = card.select_one(sel["research"])
            research = r_el.get_text(" ", strip=True) if r_el else ""
        email = None
        if sel.get("email"):
            e_el = card.select_one(sel["email"])
            if e_el is not None:
                raw = e_el.get("href") if e_el.has_attr("href") else e_el.get_text(" ", strip=True)
                email = raw.replace("mailto:", "").split("?")[0].strip() or None
        if _is_person_name(name):
            people.append(faculty(name, title=title, url=href, email=email,
                                  research_areas=research, keywords=keywords))
    return people


def _paginated_url(base: str, page: int, param: str) -> str:
    """Insert WordPress/Elementor ``/<param>/N/`` path pagination into a URL.

    Some list widgets (e.g. UW School of Social Work's Elementor directory)
    paginate via the *path* — ``/directory/page/2/?team_roles=professor`` — and
    ignore a ``?page=2`` query param (it just re-serves page 1). Splitting on the
    query string and rebuilding ``<path>/<param>/N/?<query>`` reaches later pages
    that the query-param paginator can't.
    """
    head, sep, query = base.partition("?")
    head = head.rstrip("/")
    paged = f"{head}/{param}/{page}/"
    return f"{paged}{sep}{query}" if query else paged


def _scrape_directory(dept: dict) -> list[dict]:
    """Best-effort parse of a department directory into faculty specs.

    Opt-in: only runs when the department config has a ``scrape`` block. Lazy-
    imports requests/bs4 and degrades to ``[]`` on any failure (a 403 bot wall,
    timeout, or markup drift) so deep mode never breaks the curated layer.

    When the directory paginates (``scrape["paginate"]``), follow ``?<param>=N``
    until a page surfaces no new (name, url) pair or the page cap is hit — so a
    100-professor school isn't truncated to its first page.
    """
    cfg = dept.get("scrape")
    if not cfg:
        return []
    try:
        from .ucb_common import fetch_soup
    except Exception:  # noqa: BLE001
        return []
    base = cfg["url"]
    sel = cfg.get("selectors", {})
    lf = cfg.get("ladder_filter")
    flip = cfg.get("name_flip", False)
    link_f = cfg.get("link_filter")
    sf = cfg.get("section_filter")
    ff = cfg.get("field_filter")
    soup = fetch_soup(base)
    if soup is None:
        logger.info("faculty_graph: directory unreachable for %s (curated only)", dept.get("short"))
        return []
    try:
        people = _parse_cards(soup, sel, base, lf, flip, link_f, sf, ff)
        pag = cfg.get("paginate")
        if pag:
            param = pag.get("param", "page")
            path_mode = pag.get("mode") == "path"
            seen = {(p["name"], p["url"]) for p in people}
            for pg in range(pag.get("start", 1), pag.get("max", 12) + 1):
                next_url = _paginated_url(base, pg, param) if path_mode else (
                    f"{base}{'&' if '?' in base else '?'}{param}={pg}")
                s2 = fetch_soup(next_url)
                if s2 is None:
                    break
                fresh = [p for p in _parse_cards(s2, sel, base, lf, flip, link_f, sf, ff)
                         if (p["name"], p["url"]) not in seen]
                if not fresh:
                    break
                seen.update((p["name"], p["url"]) for p in fresh)
                people.extend(fresh)
        # Per-profile research enrichment (gated): follow each broad faculty's own
        # profile page to recover a "Research Areas" block the directory listing
        # omits. Only the records still missing research_areas are fetched, so a
        # re-run (or a listing that already carries research) costs nothing extra.
        enr = cfg.get("profile_enrich")
        if enr and _PROFILE_ENRICH:
            import time
            throttle = enr.get("throttle", 0.0)
            for p in people:
                if not p.get("url") or p.get("research_areas") or p.get("keywords"):
                    continue
                pos, research, items = _enrich_profile(p["url"], enr)
                if items:
                    p["keywords"] = items
                elif research:
                    p["research_areas"] = research
                if pos and enr.get("use_position_title"):
                    p["title"] = pos
                if throttle:
                    time.sleep(throttle)
    except Exception as e:  # noqa: BLE001
        logger.warning("faculty_graph: scrape parse failed for %s: %s", dept.get("short"), e)
        return []
    return people


# ---------------------------------------------------------------------------
# WordPress REST API source (deep mode, lazy HTTP deps)
# ---------------------------------------------------------------------------
#
# Many university department sites run WordPress and expose faculty as a custom
# post type over ``/wp-json/wp/v2/<rest_base>`` — clean structured JSON, far more
# reliable than CSS-scraping a JS-rendered card grid. A department config opts in
# with an ``api`` block instead of (or alongside) ``scrape``:
#
#     "api": {
#       "type": "wp",
#       "base": "https://www.chemistry.ucla.edu",
#       "post_type": "directory",                  # the rest_base
#       "category_include": {"directory-category": [88]},  # only Faculty term
#       "keyword_tax": ["specialties"],            # taxonomies → clean keywords
#       "keyword_drop": ["instructional"],         # non-research terms to omit
#       "name_flip": True,                         # "Last, First" → "First Last"
#       "profile_enrich": {                        # optional per-profile pass
#         "position_re": r"...Professor|Lecturer...",  # sets title (emeriti auto-drop)
#         "research_re": r"Primary Area:?\s*([...]{4,40}?)\s*(?:Home|Email|$)",
#         "require_professor": True,               # drop known non-professor ranks
#       },
#     }
#
# Taxonomy-derived keywords are controlled vocabulary (no nav-furniture junk),
# so the api source lands keyworded faculty without the fragility of per-profile
# free-text scraping. ``profile_enrich`` is the escape hatch for sites that keep
# rank/research only on the individual profile page.

_HTML_TAG_RE = re.compile(r"<[^>]+>")

# A research-area taxonomy is usually short (a handful of controlled terms); cap
# the per-profile selector harvest so an over-broad selector that accidentally
# grabs a nav list or publication feed can't dump dozens of items per faculty.
_RESEARCH_ITEMS_CAP = 12


def _clean_selector_items(soup, selector: str) -> list[str]:
    """Harvest a profile's research areas from a CSS selector that yields one
    element per area (Drupal "Fields of Interest" taxonomy links and friends).

    Each element's text is an atomic keyword — unlike the labelled-text-block
    path, these must NOT be re-split on commas (a term like "Astrophysics,
    Cosmology & Gravitation" is one area). Returns a deduped, junk-filtered,
    capped list so the caller can set ``keywords`` directly (the curated path,
    which keeps each term whole). Defends against a slightly-imperfect selector
    by running every item through the same DQ junk gate the tests enforce.
    """
    try:
        from .uiuc_faculty import _is_junk_keyword
    except Exception:  # noqa: BLE001
        def _is_junk_keyword(_k):  # pragma: no cover
            return False
    out: list[str] = []
    seen: set[str] = set()
    for el in soup.select(selector):
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip(" .,:;")
        if not (t and 2 <= len(t) <= 70 and len(t.split()) <= 8):
            continue
        if _is_junk_keyword(t):
            continue
        low = t.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(t)
        if len(out) >= _RESEARCH_ITEMS_CAP:
            break
    return out


def _wp_text(raw: str) -> str:
    """Strip tags, decode HTML entities (WP returns "Theory &amp; Computation"),
    and collapse whitespace — so names/keywords clear the DQ junk filter."""
    import html
    return re.sub(r"\s+", " ", html.unescape(_HTML_TAG_RE.sub("", raw or ""))).strip()


_NAME_SUFFIX_RE = re.compile(r"^(jr|sr|ii|iii|iv|v)\.?$", re.I)


def _flip_name(name: str) -> str:
    """"Last, First M." → "First M. Last" (WP directory titles often invert).

    Handles a generational suffix listed as its own comma field
    ("Little, Jr., Arthur L." → "Arthur L. Little Jr.").
    """
    if name.count(",") == 1:
        last, first = (p.strip() for p in name.split(",", 1))
        if last and first:
            return f"{first} {last}"
    elif name.count(",") == 2:
        a, b, c = (p.strip() for p in name.split(","))
        if _NAME_SUFFIX_RE.match(b):  # "Last, Jr., First" → "First Last Jr."
            return f"{c} {a} {b}"
        if _NAME_SUFFIX_RE.match(c):  # "Last, First, Jr." → "First Last Jr."
            return f"{b} {a} {c}"
    return name


def _wp_get_json(url: str):
    try:
        import requests
    except Exception:  # noqa: BLE001
        return None
    from .ucb_common import HEADERS
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception:  # noqa: BLE001 — degrade to None like fetch_soup
        return None


def _wp_term_map(base: str, tax: str) -> dict[int, str]:
    """Resolve a WordPress taxonomy's term ids → display names."""
    out: dict[int, str] = {}
    for pg in range(1, 6):
        data = _wp_get_json(f"{base}/wp-json/wp/v2/{tax}?per_page=100&page={pg}")
        if not isinstance(data, list) or not data:
            break
        for term in data:
            if isinstance(term, dict) and "id" in term:
                out[term["id"]] = _wp_text(term.get("name", ""))
        if len(data) < 100:
            break
    return out


def _enrich_profile(url: str, enrich: dict) -> tuple[str, str, list[str]]:
    """Fetch one profile page; extract (position, research-text, research-items).

    ``research-items`` is a clean atomic keyword list from a CSS
    ``research_items_selector`` (taxonomy-links markup); ``research-text`` is a
    labelled HTML block to be comma/semicolon-split downstream. A config uses one
    or the other depending on how the site stores research areas.
    """
    if not url:
        return ("", "", [])
    try:
        from .ucb_common import fetch_soup
    except Exception:  # noqa: BLE001
        return ("", "", [])
    soup = fetch_soup(url)
    if soup is None:
        return ("", "", [])
    body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    pos = ""
    if enrich.get("position_re"):
        m = re.search(enrich["position_re"], body, re.I)
        pos = m.group(0).strip() if m else ""
    items: list[str] = []
    if enrich.get("research_items_selector"):
        items = _clean_selector_items(soup, enrich["research_items_selector"])
    kw = ""
    if enrich.get("research_html_re"):
        # Sites that keep research areas in a labelled HTML block (e.g. GT's
        # "<strong>Research Areas:</strong> A; B; C</p>") need the markup, not the
        # flattened text, to bound the capture — match on the serialized soup,
        # then strip tags so the raw labelled text lands in research_areas (the
        # derived-keyword path cleans + splits it through the same DQ gate).
        m = re.search(enrich["research_html_re"], str(soup), re.I | re.S)
        if m:
            kw = re.sub(r"\s+", " ", _HTML_TAG_RE.sub(" ", m.group(1))).strip().rstrip(".").strip()
    if not kw and enrich.get("research_re"):
        m = re.search(enrich["research_re"], body, re.I)
        if m:
            kw = m.group(1).strip()
    return (pos, kw, items)


def _fetch_wp_api(dept: dict) -> list[dict]:
    """Best-effort WordPress-REST faculty fetch (opt-in via dept ``api`` block).

    Lazy-imports requests; any failure degrades to ``[]`` so deep mode never
    breaks the curated layer. Filters to faculty via ``category_include``,
    derives keywords from taxonomies, and (optionally) enriches per profile.
    """
    cfg = dept.get("api")
    if not cfg or cfg.get("type") != "wp":
        return []
    base = cfg["base"].rstrip("/")
    kw_taxes = cfg.get("keyword_tax", [])
    term_maps = {t: _wp_term_map(base, t) for t in kw_taxes}
    kw_drop = {k.lower() for k in cfg.get("keyword_drop", [])}
    cat_inc = cfg.get("category_include") or {}
    cat_exc = cfg.get("category_exclude") or {}
    name_flip = cfg.get("name_flip", False)
    default_title = cfg.get("title", "Professor")
    enrich = cfg.get("profile_enrich")
    # Some person post types keep the rank + public email on the WP "meta box"
    # (e.g. UW COM's `person` type: meta_box.job_title / meta_box.email_address)
    # rather than in taxonomies — read them so faculty land titled + emailed.
    meta_title_field = cfg.get("meta_title_field")
    meta_email_field = cfg.get("meta_email_field")

    records: list[dict] = []
    for pg in range(1, 13):
        data = _wp_get_json(
            f"{base}/wp-json/wp/v2/{cfg['post_type']}?per_page=100&page={pg}"
        )
        if not isinstance(data, list) or not data:
            break
        records.extend(data)
        if len(data) < 100:
            break

    specs: list[dict] = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        if any(
            not (isinstance(rec.get(tax), list) and any(v in ids for v in rec[tax]))
            for tax, ids in cat_inc.items()
        ):
            continue
        # Exclude wins over include (a person double-tagged Faculty + Emeritus, or
        # Faculty + Affiliate-elsewhere, is dropped) — so the include set can be a
        # broad role union while exclude prunes the non-home-department ranks.
        if any(
            isinstance(rec.get(tax), list) and any(v in ids for v in rec[tax])
            for tax, ids in cat_exc.items()
        ):
            continue
        title_field = rec.get("title")
        name = _wp_text(
            title_field.get("rendered", "") if isinstance(title_field, dict) else title_field
        )
        if name_flip:
            name = _flip_name(name)
        if not name:
            continue
        url = rec.get("link", "")
        keywords: list[str] = []
        for tax in kw_taxes:
            tmap = term_maps.get(tax, {})
            for tid in rec.get(tax, []) or []:
                nm = tmap.get(tid, "")
                if nm and nm.lower() not in kw_drop:
                    keywords.append(nm)
        title = default_title
        email = None
        meta = rec.get("meta_box") if isinstance(rec.get("meta_box"), dict) else {}
        if meta_title_field:
            mt = _wp_text(str(meta.get(meta_title_field, "") or ""))
            if mt:
                title = mt
        if meta_email_field:
            email = (str(meta.get(meta_email_field, "") or "").strip() or None)
        if enrich:
            pos, extra_kw, extra_items = _enrich_profile(url, enrich)
            if pos:
                title = pos
            if enrich.get("require_professor") and pos and not re.search(r"profess", pos, re.I):
                continue
            if extra_items:
                keywords = extra_items + keywords
            elif extra_kw:
                keywords.insert(0, extra_kw)
        specs.append(
            faculty(name, title=title, url=url, email=email,
                    keywords=list(dict.fromkeys(keywords)))
        )
    return specs


# ---------------------------------------------------------------------------
# UCLA Samueli (seas-people) AJAX source (deep mode, lazy HTTP deps)
# ---------------------------------------------------------------------------
#
# UCLA's engineering school (Samueli) serves all seven departments' directories
# from one ``admin-ajax.php`` endpoint (the ``seas-people`` plugin), returning
# role-grouped HTML. The role grouping is the accuracy win: ladder faculty land
# in ``core / chair / vice-chair / ieo / in-residence`` containers, cleanly
# separated from ``emeriti / lecturer / adjunct / affiliate / joint``. A dept
# opts in with an ``ajax`` block:
#
#     "ajax": {
#       "type": "seas",
#       "department": "cs",                  # be|cbe|cee|cs|ece|mae|mse
#       "research_enrich": True,             # per-profile RESEARCH AND INTERESTS
#     }
#
# Per-profile enrich reads the "RESEARCH AND INTERESTS" toggle (clean one-line
# keyword phrases for most profs; prose lines are dropped) so CS/ECE/MAE faculty
# land keyworded, at UIUC parity.

_SEAS_ENDPOINT = "https://samueli.ucla.edu/wp-admin/admin-ajax.php"
_SEAS_ALL_ROLES = (
    "chair", "vice-chair", "ieo", "core", "in-residence",
    "joint", "affiliate", "adjunct", "emeriti", "lecturer",
)
_SEAS_LADDER_ROLES = frozenset({"chair", "vice-chair", "ieo", "core", "in-residence"})


def _seas_research_kw(soup) -> list[str]:
    """Extract clean research keywords from a Samueli profile's toggle.

    Each keyword is its own line; a prose paragraph (a sentence, not a topic) is
    dropped so only matchable topical phrases survive.
    """
    for toggle in soup.select(".et_pb_toggle"):
        head = toggle.select_one(".et_pb_toggle_title")
        if not head or "RESEARCH AND INTEREST" not in head.get_text(strip=True).upper():
            continue
        content = toggle.select_one(".et_pb_toggle_content")
        if not content:
            return []
        try:
            from .uiuc_faculty import _is_junk_keyword
        except Exception:  # noqa: BLE001
            def _is_junk_keyword(_k):  # pragma: no cover
                return False
        items: list[str] = []
        for el in content.find_all(["p", "li"]):
            for chunk in el.get_text("\n", strip=True).split("\n"):
                c = chunk.strip(" ,;")
                # Keep tidy topical phrases; drop prose sentences and any item the
                # DQ junk filter would reject (a leaked news/symposium title, a
                # "Using …" sentence fragment) so seas keywords clear the gate.
                if c and len(c.split()) <= 7 and c not in items and not _is_junk_keyword(c):
                    items.append(c)
        return items[:8]
    return []


def _fetch_seas_ajax(dept: dict) -> list[dict]:
    """Best-effort UCLA Samueli faculty fetch (opt-in via dept ``ajax`` block).

    Lazy-imports requests; degrades to ``[]`` on any failure. Keeps only ladder
    role containers; enriches research keywords per profile when requested.
    """
    cfg = dept.get("ajax")
    if not cfg or cfg.get("type") != "seas":
        return []
    try:
        import requests

        from .ucb_common import HEADERS, fetch_soup
    except Exception:  # noqa: BLE001
        return []
    from bs4 import BeautifulSoup

    code = cfg["department"]
    category = ",".join(f"{role}-{code}" for role in _SEAS_ALL_ROLES)
    headers = {**HEADERS, "X-Requested-With": "XMLHttpRequest",
               "Referer": "https://samueli.ucla.edu/search-faculty/"}
    try:
        resp = requests.post(
            _SEAS_ENDPOINT,
            headers=headers,
            data={"action": "load_seas_search_results", "category": category,
                  "search_key": "", "department": code},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception:  # noqa: BLE001
        return []
    soup = BeautifulSoup(resp.text, "html.parser")
    enrich = cfg.get("research_enrich")

    specs: list[dict] = []
    seen_urls: set[str] = set()
    for container in soup.select(".seas-people-container"):
        classes = [c for c in container.get("class", []) if c != "seas-people-container"]
        role = classes[0].rsplit("-", 1)[0] if classes else ""
        if role not in _SEAS_LADDER_ROLES:
            continue
        for card in container.select(".card"):
            a = card.select_one(".people-title a")
            if not a:
                continue
            name = a.get_text(strip=True)
            url = a.get("href", "")
            if not _is_person_name(name) or (url and url in seen_urls):
                continue
            if url:
                seen_urls.add(url)
            ti = card.select_one(".card_description p i")
            title = ti.get_text(strip=True) if ti else "Professor"
            mail = card.select_one("a.mailto-link, a[href^='mailto:']")
            email = None
            if mail and mail.has_attr("href"):
                email = mail["href"].replace("mailto:", "").split("?")[0].strip() or None
            keywords: list[str] = []
            if enrich and url:
                psoup = fetch_soup(url)
                if psoup is not None:
                    keywords = _seas_research_kw(psoup)
            specs.append(
                faculty(name, title=title, url=url, email=email, keywords=keywords)
            )
    return specs


# ---------------------------------------------------------------------------
# Algolia directory source (deep mode, lazy HTTP deps)
# ---------------------------------------------------------------------------
#
# Some directories are JS clients over a public Algolia search index (e.g. UT
# Austin's College of Natural Sciences ``directory_LIVE``). Hitting the index
# directly is exact and complete. A department opts in with an ``algolia`` block:
#
#     "algolia": {
#       "app_id": "R1M3WN6NBD",
#       "api_key": "<public search key>",
#       "index": "directory_LIVE",
#       "filters": 'department:"Physics" AND position_type:"1-Tenure-Track/Tenured Faculty"',
#       "drop_title_re": r"emerit",            # position_type keeps emeriti tagged TT
#     }

def _fetch_algolia(dept: dict) -> list[dict]:
    """Best-effort faculty fetch from a public Algolia index (opt-in via block)."""
    cfg = dept.get("algolia")
    if not cfg:
        return []
    try:
        import requests
    except Exception:  # noqa: BLE001
        return []
    url = f"https://{cfg['app_id'].lower()}-dsn.algolia.net/1/indexes/{cfg['index']}/query"
    headers = {
        "X-Algolia-Application-Id": cfg["app_id"],
        "X-Algolia-API-Key": cfg["api_key"],
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            url, headers=headers,
            json={"query": "", "hitsPerPage": cfg.get("hits", 1000),
                  "filters": cfg.get("filters", "")},
            timeout=25,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", [])
    except Exception:  # noqa: BLE001
        return []
    drop_re = cfg.get("drop_title_re")
    specs: list[dict] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        name = " ".join(
            str(hit.get(f, "")).strip()
            for f in cfg.get("name_fields", ["name_first", "name_last"])
        ).strip()
        if not _is_person_name(name):
            continue
        title = str(hit.get(cfg.get("title_field", "titles_general"), "") or "Professor")
        if drop_re and re.search(drop_re, title, re.I):
            continue
        research_raw = hit.get(cfg.get("research_field", "areas_of_research"), "")
        research = ", ".join(research_raw) if isinstance(research_raw, list) else str(research_raw or "")
        email = (hit.get(cfg.get("email_field", "email")) or "").strip() or None
        url_v = (hit.get(cfg.get("url_field", "profile_link")) or "").strip()
        specs.append(faculty(name, title=title, url=url_v, email=email, research_areas=research))
    return specs


# ---------------------------------------------------------------------------
# UT Austin College of Liberal Arts JSON:API source (deep mode, lazy HTTP deps)
# ---------------------------------------------------------------------------
#
# Every Liberal Arts department's public faculty page is a Vue single-page app
# (a static scrape lands zero people) backed by one shared JSON:API at
# ``webeditor.la.utexas.edu/api/v2/persons``. A department opts in with a
# ``cola`` block; we query the persons endpoint filtered to the division (and an
# optional core-faculty ``categoryitem_id`` for interdisciplinary programs whose
# bare roster is mostly cross-listed affiliates), ladder-filter on the display
# title, and build a profile URL from the person's EID.
#
#     "cola": {
#         "base": "https://webeditor.la.utexas.edu/api/v2",
#         "division": "philosophy",
#         "role_name": "faculty",                     # optional, default "faculty"
#         "profile_base": "https://liberalarts.utexas.edu/philosophy/faculty",
#         "ladder_filter": {"require": "profess", "drop": "emerit|lecturer|..."},
#         "categoryitem_id": 2015,                    # optional core-faculty filter
#     }
def _fetch_cola(dept: dict) -> list[dict]:
    """Best-effort faculty fetch from the UT Liberal Arts JSON:API (opt-in)."""
    cfg = dept.get("cola")
    if not cfg:
        return []
    try:
        import requests
    except Exception:  # noqa: BLE001
        return []
    from .ucb_common import HEADERS
    base = cfg["base"].rstrip("/")
    params = {"filter[division]": cfg["division"],
              "filter[role_name]": cfg.get("role_name", "faculty")}
    if cfg.get("categoryitem_id"):
        params["filter[categoryitem]"] = cfg["categoryitem_id"]
    try:
        resp = requests.get(f"{base}/persons", params=params,
                            headers=HEADERS, timeout=25)
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception:  # noqa: BLE001
        return []
    lf = cfg.get("ladder_filter") or {}
    require_re, drop_re = lf.get("require"), lf.get("drop")
    profile_base = (cfg.get("profile_base") or "").rstrip("/")
    specs: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes") or {}
        name = f"{(attrs.get('first') or '').strip()} {(attrs.get('last') or '').strip()}".strip()
        if not _is_person_name(name):
            continue
        title = (attrs.get("display_title") or "").strip() or "Professor"
        if require_re and not re.search(require_re, title, re.I):
            continue
        if drop_re and re.search(drop_re, title, re.I):
            continue
        eid = (attrs.get("eid") or "").strip()
        url_v = f"{profile_base}/{eid}" if (profile_base and eid) else ""
        email = (attrs.get("email") or "").strip() or None
        research = (attrs.get("interests") or "").strip()
        specs.append(faculty(name, title=title, url=url_v, email=email, research_areas=research))
    return specs


# ---------------------------------------------------------------------------
# Generic JSON directory source (deep mode, lazy HTTP deps)
# ---------------------------------------------------------------------------
#
# Some directories ship the whole roster as one authoritative JSON file (a
# static-site export or a headless CMS feed). A department opts in with a
# ``json_dir`` block: fetch the array, keep records whose ``filter_field`` (a
# string or list) contains ``filter_value`` (the department's area) and whose
# optional ``status_field`` carries ``status_value`` (drops PhD students/staff),
# ladder-filter on the title, and map name/title/email/link by field name.
#
#     "json_dir": {
#         "url": "https://www.scheller.gatech.edu/directory/index.json",
#         "name_fields": ["firstName", "lastName"],   # joined with a space
#         "filter_field": "academic", "filter_value": "Finance",
#         "status_field": "status", "status_value": "Faculty",  # optional
#         "ladder_filter": {"drop": "emerit|lecturer|of the practice"},
#     }
def _fetch_json_dir(dept: dict) -> list[dict]:
    """Best-effort faculty fetch from an authoritative JSON directory (opt-in)."""
    cfg = dept.get("json_dir")
    if not cfg:
        return []
    try:
        import requests
    except Exception:  # noqa: BLE001
        return []
    from .ucb_common import HEADERS
    try:
        resp = requests.get(cfg["url"], headers=HEADERS, timeout=25)
        resp.raise_for_status()
        recs = resp.json()
    except Exception:  # noqa: BLE001
        return []
    if isinstance(recs, dict):
        recs = (recs.get(cfg.get("records_key", "")) if cfg.get("records_key")
                else next((v for v in recs.values() if isinstance(v, list)), []))
    lf = cfg.get("ladder_filter") or {}
    require_re, drop_re = lf.get("require"), lf.get("drop")
    name_fields = cfg.get("name_fields", ["firstName", "lastName"])
    filt_field, filt_value = cfg.get("filter_field"), cfg.get("filter_value")
    status_field, status_value = cfg.get("status_field"), cfg.get("status_value")
    specs: list[dict] = []
    for x in recs:
        if not isinstance(x, dict):
            continue
        if filt_field is not None:
            fv = x.get(filt_field)
            if filt_value not in (fv if isinstance(fv, list) else [fv]):
                continue
        if status_field is not None:
            sv = x.get(status_field)
            if status_value not in (sv if isinstance(sv, list) else [sv]):
                continue
        name = " ".join(str(x.get(f) or "").strip() for f in name_fields).strip()
        if not _is_person_name(name):
            continue
        title = x.get(cfg.get("title_field", "title")) or "Professor"
        if isinstance(title, list):
            title = ", ".join(str(t) for t in title)
        title = title.strip() or "Professor"
        if require_re and not re.search(require_re, title, re.I):
            continue
        if drop_re and re.search(drop_re, title, re.I):
            continue
        email = (x.get(cfg.get("email_field", "email")) or "").strip() or None
        url_v = (x.get(cfg.get("link_field", "link")) or "").strip()
        specs.append(faculty(name, title=title, url=url_v, email=email))
    return specs


# ---------------------------------------------------------------------------
# Interfolio Faculty180 admin-ajax source (deep mode, lazy HTTP deps)
# ---------------------------------------------------------------------------
#
# Interfolio's Faculty180 product ships a WordPress plugin that renders a
# department's faculty directory client-side, fetching the people list as JSON
# from ``wp-admin/admin-ajax.php`` (action ``faculty_search_ajax``). The raw page
# is just a filter shell ("Search Please wait …"), so a static scrape lands zero
# people — but the AJAX call returns clean structured records (firstname,
# lastname, position/rank, email, slug). A department opts in with a
# ``faculty180`` block:
#
#     "faculty180": {
#       "base": "https://nursing.uw.edu",      # site root (admin-ajax under it)
#       "profile_base": "https://nursing.uw.edu/person/",  # {pid}-{slug} appended
#       "per_page": 100,
#       "ladder_filter": {"require": r"profess|lecturer",
#                         "drop": r"emerit|affiliate|postdoc|visiting|..."},
#     }
#
# The ranks the directory mixes (Affiliate / Clinical-Non-Salaried / Emeritus /
# Postdoctoral / Teaching Associate / Visiting) are filtered out by the
# title-based ``ladder_filter`` (same require/drop semantics as the scrape
# layer) so only current ladder + teaching + lecturer faculty land.

def _fetch_faculty180(dept: dict) -> list[dict]:
    """Best-effort faculty fetch from an Interfolio Faculty180 admin-ajax feed.

    Lazy-imports requests; degrades to ``[]`` on any failure. Paginates the
    ``faculty_search_ajax`` action until the page is short, de-dupes by ``pid``,
    and applies the title ``ladder_filter`` so non-ladder ranks are dropped.
    """
    cfg = dept.get("faculty180")
    if not cfg:
        return []
    try:
        import requests
    except Exception:  # noqa: BLE001
        return []
    from .ucb_common import HEADERS

    base = cfg["base"].rstrip("/")
    endpoint = f"{base}/wp-admin/admin-ajax.php"
    profile_base = cfg.get("profile_base", f"{base}/person/").rstrip("/") + "/"
    per_page = cfg.get("per_page", 100)
    lf = cfg.get("ladder_filter")
    headers = {**HEADERS, "X-Requested-With": "XMLHttpRequest",
               "Content-Type": "application/x-www-form-urlencoded"}

    specs: list[dict] = []
    seen_pids: set = set()
    for page in range(1, cfg.get("max_pages", 20) + 1):
        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                data={"action": "faculty_search_ajax", "searchpage": str(page),
                      "args[per_page]": str(per_page)},
                timeout=30,
            )
            resp.raise_for_status()
            users = resp.json().get("users", [])
        except Exception:  # noqa: BLE001
            break
        if not users:
            break
        fresh = 0
        for u in users:
            if not isinstance(u, dict):
                continue
            pid = u.get("pid")
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            fresh += 1
            # ``rank`` is the clean academic rank ("Associate Professor");
            # ``position`` carries payroll/admin cruft ("Physician Asst-Adv Rn
            # Pract<br />Teaching Professor", "Health Services Manager (E S 10)")
            # so the ladder filter — and the stored title — key on rank.
            title = (u.get("rank") or u.get("position") or "Professor").strip()
            if not _passes_ladder(title, lf):
                continue
            name = " ".join(p for p in (u.get("firstname"), u.get("lastname")) if p).strip()
            if not _is_person_name(name):
                continue
            email = (u.get("email") or "").strip() or None
            slug = (u.get("slug") or "").strip()
            url = f"{profile_base}{pid}-{slug}/" if pid and slug else base
            specs.append(faculty(name, title=title, url=url, email=email))
        if len(users) < per_page or fresh == 0:
            break
    return specs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _key_email(rec: dict) -> str:
    return (rec.get("contact_email") or "").strip().lower()


def _key_url(rec: dict) -> str:
    return (rec.get("url") or "").strip().lower()


def _listing_urls(school: dict) -> set[str]:
    """Directory/listing URLs — shared by everyone in a department, so never a
    person de-dup key. A linkless card stores its department's listing URL (so
    the record still has a usable ``url``); the joint-appointment de-dup, which
    is meant to catch one person's *profile* URL appearing under two departments,
    must ignore these or it would collapse a whole linkless directory to one row.
    """
    urls: set[str] = set()
    for dept in school.get("departments", []):
        for block in ("scrape", "api", "ajax", "algolia", "faculty180", "cola", "json_dir"):
            cfg = dept.get(block)
            if isinstance(cfg, dict):
                for k in ("url", "base"):
                    v = (cfg.get(k) or "").strip().lower()
                    if v:
                        urls.add(v)
    return urls


def fetch_and_normalize(school: dict, deep: bool = False) -> list[dict]:
    """Normalize a school's curated faculty (+ best-effort scrape in deep mode).

    Joint-appointment de-dup keys on contact_email and profile URL — the things
    a single person shares when listed under two departments — NOT on bare name.
    Two genuinely different professors can share a name (e.g. Michigan has two
    "Wei Lu", one in ECE doing memristors and one in ME doing batteries, with
    different emails); a name-based key would wrongly merge them.
    """
    errors = validate(school)
    if errors:
        raise ValueError(f"{school.get('school_slug')} faculty config invalid: " + "; ".join(errors))

    records: list[dict] = []
    seen_emails: set[str] = set()
    seen_urls: set[str] = set()
    seen_ids: set[str] = set()
    listing_urls = _listing_urls(school)
    for dept in school.get("departments", []):
        specs = list(dept.get("faculty", []))
        if deep:
            seen_urls_local = {u for p in specs
                               if (u := (p.get("url") or "").strip().lower())
                               and u not in listing_urls}
            for discovered in (_scrape_directory(dept) + _fetch_wp_api(dept)
                               + _fetch_seas_ajax(dept) + _fetch_algolia(dept)
                               + _fetch_faculty180(dept) + _fetch_cola(dept)
                               + _fetch_json_dir(dept)):
                key = (discovered.get("url") or "").strip().lower()
                if key and key not in listing_urls and key in seen_urls_local:
                    continue
                if key and key not in listing_urls:
                    seen_urls_local.add(key)
                specs.append(discovered)
        for person in specs:
            rec = _normalize(school, dept, person)
            if rec is None:
                continue
            ek, uk = _key_email(rec), _key_url(rec)
            if uk in listing_urls:
                uk = ""
            if rec["id"] in seen_ids:
                continue
            if ek and ek in seen_emails:
                continue
            if uk and uk in seen_urls:
                continue
            seen_ids.add(rec["id"])
            if ek:
                seen_emails.add(ek)
            if uk:
                seen_urls.add(uk)
            records.append(rec)
    return records


def merge_into_processed(new_opps: list[dict]):
    """Upsert faculty records into processed/opportunities.json by id.

    School-scoped (unlike ucb_common.merge_into_processed, which is hard-wired
    to the ucb_ prefix): intra-batch dedup already happened in
    fetch_and_normalize, and ids are stable (dept+name hash), so a re-run
    upserts cleanly. We deliberately do NOT cross-dedup against other schools'
    faculty by name — two schools can have a professor with the same name.
    """
    import json

    from .ucb_common import PROCESSED_FILE

    if not PROCESSED_FILE.exists() or not new_opps:
        return (0, 0)
    with PROCESSED_FILE.open("r", encoding="utf-8") as f:
        existing = json.load(f)
    index = {o.get("id"): o for o in existing if o.get("id")}
    added = updated = 0
    for opp in new_opps:
        if opp["id"] in index:
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get(
                "metadata", {}).get("first_seen_at", opp["metadata"]["first_seen_at"])
            index[opp["id"]].update(opp)
            updated += 1
        else:
            existing.append(opp)
            index[opp["id"]] = opp
            added += 1
    with PROCESSED_FILE.open("w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False, default=str)
    return (added, updated)


def source_breakdown(opps: list[dict]) -> dict:
    return {
        "total": len(opps),
        "by_department": dict(Counter(o.get("department") for o in opps)),
        "with_email": sum(1 for o in opps if o.get("contact_email")),
    }
