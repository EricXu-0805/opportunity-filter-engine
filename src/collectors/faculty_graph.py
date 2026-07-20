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
import html
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from urllib.parse import unquote, urljoin

from .ucb_common import (
    _RETIRED_TITLE_RE,
    _detect_funding,
    _is_person_name,
    _strip_nav_furniture,
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
        if not any(dept.get(k) for k in ("faculty", "scrape", "api", "ajax", "algolia", "faculty180", "cola", "json_dir", "coa_api", "poly_api", "krieger_table", "sitemap")):
            errors.append(f"{short}: no curated faculty, scrape, api, ajax, algolia, faculty180, cola, json_dir, coa_api, poly_api, krieger_table, or sitemap config")
        for person in dept.get("faculty", []):
            if not person.get("name"):
                errors.append(f"{short}: faculty entry missing name")
    return errors


# ---------------------------------------------------------------------------
# Normalization (stdlib only)
# ---------------------------------------------------------------------------

# Bare single words that are directory/nav furniture, never a research area on
# their own — dropped from a curated keyword list. Deliberately narrow: broad-
# but-real fields ("design", "theory", "education") are NOT here, only tokens
# that carry zero topical meaning as a standalone tag chip.
_BARE_NAV_WORDS = frozenset({
    "research", "people", "overview", "directory", "news", "events",
    "resources", "resource",
})


# Prose-fragment lead-ins that scrape into a "research interest" list but are
# never a standalone topic ("with emphasis on…", "our lab studies…", "my
# research explores…", "in particular …"). Deliberately narrower than uiuc's
# _LEADING_NONTOPICAL_RE, which also rejects any "the …"/"in …" lead: a curated
# taxonomy legitimately holds determiner-led humanities areas ("the
# Enlightenment", "the Cold War", "in situ microscopy"), so only first-person /
# possessive / qualifier leads that can never name a research area are dropped.
_PROSE_FRAGMENT_LEAD_RE = re.compile(
    r"^(?:with|our|my|we|i|for example|in particular|in turn|in the|in a|in my)\b",
    re.IGNORECASE,
)

# An academic-unit name is never a research area — some directories fill the
# expertise field with the person's school/department affiliation instead
# ("USC Annenberg School for Communication and Journalism").
_UNIT_NAME_RE = re.compile(
    r"\b(?:school|college|department|institute|academy)s?\s+(?:of|for)\b",
    re.IGNORECASE,
)


def _hygiene_keyword(k: str) -> str | None:
    """Clean one keyword (curated or derived): strip wrapping quotes and edge
    punctuation, fold an internal comma to ' / ' (a comma would fragment the
    title parenthetical the DQ gate comma-splits), and drop it when it is page
    furniture, a publication venue, a room/contact residue, or a prose fragment.
    Returns the cleaned keyword or ``None`` to drop. Reuses uiuc's
    ``_is_junk_keyword`` as the shared junk gate so curated/taxonomy keywords are
    held to the same bar the derived fallback already enforces."""
    c = (k or "").strip().strip("\"'“”‘’").strip(" .,;:").strip()
    if not c:
        return None
    # A bare single nav word ("Research", "News") is zero-signal furniture and,
    # unlike the collector-time _clean_keywords path, can enter here via the
    # monthly profile-enrichment pass — which the corpus-wide hygiene must catch
    # so the DQ gate's no-bare-nav-keyword invariant holds on every refresh.
    if " " not in c and c.lower() in _BARE_NAV_WORDS:
        return None
    if _PROSE_FRAGMENT_LEAD_RE.match(c):
        return None
    # A comma-split of a prose "Research Interests" paragraph (UGA English's
    # narrative bios) strands continuation clauses led by a qualifier connective
    # ("especially as these areas intersect"). The derived-keyword path already
    # drops these; the hygiene path (curated/taxonomy/profile-enrich + the
    # corpus-wide re-clean) must enforce the SAME rule the DQ gate does, or a
    # fragment that entered via keywords survives the gate.
    if _FRAGMENT_LEADIN_RE.match(c):
        return None
    try:
        from .uiuc_faculty import _is_junk_keyword
    except Exception:  # noqa: BLE001
        def _is_junk_keyword(_k):  # pragma: no cover
            return False
    if _is_junk_keyword(c):
        return None
    if _UNIT_NAME_RE.search(c):
        return None
    return re.sub(r"\s*,\s*", " / ", c)


def _hygiene_keywords(kws: list[str]) -> list[str]:
    """Clean + de-dupe a keyword list order-preserving (case-insensitive).

    A semicolon inside a chip always delimits separate areas ("Classical
    Guitar; Composition / Theory & Analysis") — split before cleaning.
    """
    out: list[str] = []
    seen: set[str] = set()
    for k in (part for kw in kws or [] for part in (kw or "").split(";")):
        c = _hygiene_keyword(k)
        if c is None:
            continue
        low = c.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append(c)
    return out


def _clean_keywords(person: dict) -> list[str]:
    """Curated keywords win; otherwise derive a couple from research areas.

    Curated lists are trusted (the config author keeps them clean); the derived
    fallback splits research_areas on separators and trims, so even a config
    that only fills research_areas yields something the title can show.
    """
    kws = [k.strip() for k in person.get("keywords", []) if k and k.strip()]
    if kws:
        # Even a curated list can carry a bare nav-junk word ("Research",
        # "People") that scraped in alongside real areas — zero-signal noise as
        # a tag chip. Drop only these unambiguous non-areas; a broad-but-real
        # field ("Design", "Theory") is kept, and a multi-word phrase ("water
        # resources") is unaffected — only the standalone junk token is rejected.
        kws = [k for k in kws if " " in k or k.lower() not in _BARE_NAV_WORDS]
        # Hold curated/taxonomy keywords to the same hygiene the derived branch
        # applies: strip edge punctuation/quotes, fold an internal comma to
        # " / " (a comma breaks the title-parenthetical subset invariant), drop
        # page-furniture / venue / room / prose-fragment junk, and de-dupe
        # order-preserving. Previously only the derived fallback below cleaned,
        # so a curated list shipped its junk verbatim.
        return _hygiene_keywords(kws)[:8]
    raw = _strip_nav_furniture(person.get("research_areas", ""))
    # Split on ; | and , — directories delimit a research list with any of them
    # (Stanford Education uses " | " between areas; most use commas/semicolons).
    parts = [p.strip() for chunk in re.split(r"[;|]", raw) for p in chunk.split(",")]
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
        # Same bare nav-junk rule the curated branch enforces — a prose split
        # can strand a standalone "research"/"people" token too.
        and (" " in p or p.lower() not in _BARE_NAV_WORDS)
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
               r"|M\.?\s?Eng|D\.?\s?M\.?\s?Sc|P\.?\s?E|P\.?\s?Eng"
               r"|Pharm\.?\s?D|Dr\.?\s?P\.?H|Sc\.?\s?D|D\.?\s?V\.?M|J\.?\s?D"
               r"|Ed\.?\s?D|D\.?\s?O|R\.?\s?N|D\.?\s?D\.?S|D\.?Phil|Psy\.?\s?D|FAIA")
# A trailing comma-run of post-nominals: each item is a known degree
# (case-insensitively) OR an all-caps professional fellowship/licensure acronym
# (FAACP, FAPhA, FAASLD, BCPS, LMSW, FAAN, …), optionally with a space-separated
# qualifier ("LEED AP", "LEED AP BD+C"). The acronym branch is case-SENSITIVE
# (≥2 leading capitals) so it never eats an ordinary name word.
_CREDENTIAL_RE = re.compile(
    r"(?:\s*,\s*(?:(?i:" + _CREDENTIAL + r")|[A-Z]{2,}[A-Za-z.()-]*"
    r"(?:\s+[A-Z0-9][A-Za-z0-9.+()-]*)*)\.?)+\s*$")

# Leading honorific some directories prepend ("Dr. Jane Doe", "Prof. John Roe").
_HONORIFIC_RE = re.compile(r"^(?:Dr|Prof|Professor|Mr|Ms|Mrs)\.?\s+", re.IGNORECASE)

# A trailing status parenthetical ("(on leave AY 26-27)", "(sabbatical)") is not
# part of the name — but a single-word nickname parenthetical ("(Steve)") IS a
# legitimate name form, so key strictly off status keywords, never all parens.
_STATUS_PAREN_RE = re.compile(
    r"\s*\((?=[^)]*\b(?:on leave|leave|sabbatical|retir|emerit|interim|acting|"
    r"deceased|visiting|adjunct)\b)[^)]*\)\s*$", re.IGNORECASE)


def _strip_credentials(name: str) -> str:
    """Drop trailing post-nominal degree/credential suffixes
    ("Jane Doe, PhD, MPH" / "Jamie Barner, Ph.D., FAACP, FAPhA"), a leading
    honorific ("Dr. Jane Doe"), and a trailing status parenthetical
    ("Åsa Rennermalm (on leave AY 26-27)"). A nickname parenthetical
    ("Xun (Steve) Jian") is a legitimate name form and is preserved."""
    name = _HONORIFIC_RE.sub("", name)
    name = _STATUS_PAREN_RE.sub("", name)
    return _CREDENTIAL_RE.sub("", name).strip()


# A name carrying a (birth–death) year range is an in-memoriam directory entry,
# not active faculty — drop it ("Alberto Apostolico (1948-2015)"). Matched on the
# name only: a year range in a research title/area is legitimate (a historian of
# a 1500-1600 figure), so this never keys off the description.
_IN_MEMORIAM_RE = re.compile(r"\(\s*\d{4}\s*[-–—]\s*\d{4}\s*\)")


def _normalize(school: dict, dept: dict, person: dict) -> dict | None:
    """Convert one faculty spec into the normalized opportunity schema."""
    # JSON/API feeds (e.g. Texas A&M) deliver HTML-entity-encoded names
    # ("Daniel A. Jim&eacute;nez", "Anxiao &quot;Andrew&quot; Jiang"); card
    # names are already unescaped upstream, but unescaping here is idempotent
    # and covers every ingest path.
    name = _strip_credentials(_strip_pronouns(
        html.unescape((person.get("name") or "").strip())))
    # Directory footnote markers ("David Barner*", "Jane Doe†" — accepting-
    # students / area-head legends) ride the name anchor on some listings; a
    # marked and unmarked crawl of the same person must hash to the same id.
    name = re.sub(r"[\s*†‡]+$", "", name)
    if not _is_person_name(name):
        return None
    if _IN_MEMORIAM_RE.search(name):
        return None  # "Name (1948-2015)" — an in-memoriam entry, not active faculty
    # Some directory cards prefix the rank with a scraped field label
    # ("Position title: Glynn LL Isaac Professor…", "Title: …"); strip it so the
    # label doesn't leak into the description ("Research opportunity with
    # Position title: … in the Department of Anthropology…").
    title = re.sub(r"^\s*(?:position\s+title|title)\s*:\s*", "",
                   person.get("title") or "Professor", flags=re.IGNORECASE).strip() or "Professor"
    if _RETIRED_TITLE_RE.search(title):
        return None

    short = dept["short"]
    dept_name = dept["name"]
    # Some authoritative feeds (e.g. UCSD Physics' profile API) carry no
    # per-person page; point at the directory the person is listed on rather
    # than ship a record with no destination (the integrity gate requires url).
    profile_url = person.get("url", "") or dept.get("directory_url", "")
    # Final lowercase guard on every record's email (covers non-scrape sources —
    # coa_api/poly_api/WP-meta/curated/json_dir — that don't pass through
    # _clean_email); a capitalized local part trips the DQ corrupted-email gate,
    # and a truncated feed value ("timo.sprekeler", no @) is not an address.
    email = ((person.get("email") or "").strip().lower() or None)
    if email and "@" not in email:
        email = None
    research_areas = _strip_nav_furniture(person.get("research_areas", ""))
    keywords = _clean_keywords(person)
    # Faculty are cold-email research contacts, not postings with required
    # skills — inferring skills from research-topic prose is false-precise
    # and degrades their match score (mirrors the R70A DQ gate; the enricher/
    # llm_tagger backfills are already faculty-gated).
    skills: list[str] = []

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
            # Directory scrapes never state year preferences; lock freshmen out
            # only when a posting explicitly does (Eric 2026-07-16).
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
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
    if ff.get("require_present") and (el is None or not el.get_text(strip=True)):
        # Mixed listings where only role-carrying cards are wanted: the lenient
        # absent-field-passes default would ship a role-less card (a student)
        # as a "Professor" — require the field to exist before gating on it.
        return False
    text = el.get_text(" ", strip=True) if el else ""
    if ff.get("include") and text and not re.search(ff["include"], text, re.I):
        return False
    return not (ff.get("exclude") and text and re.search(ff["exclude"], text, re.I))


def _clean_email(raw: str) -> str | None:
    """Normalize a mailto/text email — hand-edited CMS anchors get creative.

    Handles percent-encoded display-name forms ("mailto:Jane%20Doe%20%3Cjd%40x
    .edu%3E"), trailing whitespace/nbsp, and "Name <addr>" text by extracting
    the first address-shaped token after URL-decoding.
    """
    raw = raw or ""
    # JS charcode obfuscation (legacy ASP directories, e.g. UVA Physics):
    # href="javascript:...String.fromCharCode(109,97,105,...)" encodes the real
    # "mailto:addr". Decode the code points first so the address-shape search
    # sees a clean string instead of the surrounding <a> markup.
    m_cc = re.search(r"fromCharCode\(([\d,\s]+)\)", raw)
    if m_cc:
        try:
            raw = "".join(chr(int(n)) for n in m_cc.group(1).split(",") if n.strip())
        except ValueError:
            pass
    # Strip zero-width / invisible formatting chars first: some CMSes (Utah's
    # Kahlert/CS people pages) splice a zero-width space into the mailto so a
    # scraper stops at the break — the address-shape regex would then bail and
    # leak the raw obfuscated string. These code points never appear in real
    # addresses, so dropping them is safe and canonicalizing.
    raw = re.sub("[\u200b\u200c\u200d\u2060\ufeff]", "", raw or "")
    addr = unquote(raw).replace("mailto:", "").split("?")[0].strip()
    # Normalize written-out obfuscation before the address-shape search: both
    # spamspan text ("x [at] umass [dot] edu") and hand-quoted forms
    # ('lane "at" cs.rochester.edu') publish a real address behind at/dot words.
    addr = re.sub(r"\s*[\[(\"']\s*at\s*[\])\"']\s*", "@", addr, flags=re.I)
    addr = re.sub(r"\s*[\[(\"']\s*dot\s*[\])\"']\s*", ".", addr, flags=re.I)
    if "@" not in addr and re.search(r"\bat\b", addr, re.I) and re.search(r"\bdot\b", addr, re.I):
        # Bare prose obfuscation without brackets ("jcumming at andrew dot cmu
        # dot edu", sometimes letter-spaced) — CMU Math publishes these inside
        # mailto: hrefs. Collapse to an address only when the result is
        # exactly address-shaped, so real prose never converts.
        cand = re.sub(r"\s+at\s+", "@", addr, count=1, flags=re.I)
        cand = re.sub(r"\s+dot\s+", ".", cand, flags=re.I)
        cand = re.sub(r"\s+", "", cand)
        if re.fullmatch(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", cand):
            addr = cand
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", addr)
    # An email MUST contain an @: a directory that puts a phone number
    # ("(301) 405-5935") in the email column, or leaves an empty ``mailto:``
    # anchor with the phone as visible text, must yield None — never the raw
    # non-address string.
    if m:
        result = m.group(0)
    elif ("@" in addr and "<" not in addr and ">" not in addr
          and re.search(r"@[\w-]+\.[\w]", addr)):
        result = addr
    else:
        # Residual JS/HTML blob or a TLD-less truncation ("user@virginia") —
        # never leak the raw non-address string.
        result = None
    # Canonicalize to lowercase: some directories carry a display-cased address
    # ("Charles.gersbach@duke.edu"), and the DQ gate flags a capitalized local
    # part as a corruption pattern. Email local parts are effectively case-
    # insensitive, so lowercasing is safe and canonical.
    return result.lower() if result else None


def _decode_cfemail(el) -> str | None:
    """Decode a Cloudflare email-protection payload on (or under) ``el``.

    Cloudflare's scrape-shield replaces published addresses with
    ``<a href="/cdn-cgi/l/email-protection#HEX"><span class="__cf_email__"
    data-cfemail="HEX">`` — the hex string XORs back to the address with its
    first byte as key. Shielded sites (all Caltech division sites) publish NO
    mailto anywhere, so without this decode their email coverage is zero.
    """
    payload = el.get("data-cfemail")
    if not payload:
        sub = el.select_one("[data-cfemail]") if hasattr(el, "select_one") else None
        if sub is not None:
            payload = sub.get("data-cfemail")
    if not payload and el.has_attr("href"):
        m = re.search(r"/cdn-cgi/l/email-protection#([0-9a-fA-F]+)", el["href"])
        if m:
            payload = m.group(1)
    if not payload:
        return None
    try:
        data = bytes.fromhex(payload)
        decoded = bytes(b ^ data[0] for b in data[1:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return _clean_email(decoded)


def _decode_b64email(el) -> str | None:
    """Decode a base64 ``data-email`` payload on (or under) ``el``.

    MIT Math's directory hides addresses as ``<a class="email-hidden"
    data-email="BASE64">`` (decoded client-side); without this decode the
    whole department lands unemailed despite publishing every address.
    """
    payload = el.get("data-email")
    if not payload and hasattr(el, "select_one"):
        sub = el.select_one("[data-email]")
        if sub is not None:
            payload = sub.get("data-email")
    if not payload:
        return None
    import base64
    try:
        decoded = base64.b64decode(payload, validate=True).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None
    return _clean_email(decoded) if "@" in decoded else None


def _decode_rot13email(el) -> str | None:
    """Decode a rot13 ``data-mail-to`` payload on (or under) ``el``.

    UMass Amherst's campus Drupal obfuscates every address as
    ``<a data-mail-to="nyunevev/ng/purz/qbg/hznff/qbg/rqh">`` — rot13 with
    ``/at/`` and ``/dot/`` separators (decoded client-side). Without this
    decode the whole campus lands unemailed despite publishing every address.
    """
    payload = el.get("data-mail-to")
    if not payload and hasattr(el, "select_one"):
        sub = el.select_one("[data-mail-to]")
        if sub is not None:
            payload = sub.get("data-mail-to")
    if not payload:
        return None
    import codecs
    decoded = codecs.decode(payload, "rot13").replace("/at/", "@").replace("/dot/", ".")
    return _clean_email(decoded) if "@" in decoded else None


def _decode_datacode_email(el) -> str | None:
    """Decode a hex-UTF16 ``data-code`` payload on (or under) ``el``.

    University of Miami's Cascade CMS renders every address as
    ``<a class="email-decode" data-code="HEX">`` where HEX is the address's
    UTF-16 big-endian code units (``00760078...`` -> "vx..."), decoded
    client-side. Without this decode Miami's A&S + Engineering department sites
    (a template shared campus-wide) land unemailed despite publishing every
    address.
    """
    payload = el.get("data-code")
    if not payload and hasattr(el, "select_one"):
        sub = el.select_one("[data-code]")
        if sub is not None:
            payload = sub.get("data-code")
    if not payload:
        return None
    hexstr = re.sub(r"[^0-9a-fA-F]", "", payload)
    if len(hexstr) < 8 or len(hexstr) % 4:
        return None
    try:
        decoded = bytes.fromhex(hexstr).decode("utf-16-be")
    except Exception:  # noqa: BLE001
        return None
    return _clean_email(decoded) if "@" in decoded else None
def _decode_reversed_email(el) -> str | None:
    """Decode a reversed ``data-user``/``data-domain`` cloak on (or under) ``el``.

    UGA's College of Education profile pages (people.coe.uga.edu) cloak every
    address as ``<span class="cloaked-e-mail" data-user="maharba.anna"
    data-domain="ude.agu">`` — both strings simply reversed and joined
    client-side. Without this decode the whole college lands unemailed.
    """
    sub = el
    if not el.get("data-user") and hasattr(el, "select_one"):
        sub = el.select_one("[data-user][data-domain]") or el
    user, domain = sub.get("data-user"), sub.get("data-domain")
    if not (user and domain):
        return None
    return _clean_email(f"{user[::-1]}@{domain[::-1]}")


def _email_from_el(e_el) -> str | None:
    """Address from a selected email element — cf-shield/base64/rot13/reversed decode, then mailto/text."""
    cf = _decode_cfemail(e_el)
    if cf:
        return cf
    b64 = _decode_b64email(e_el)
    if b64:
        return b64
    r13 = _decode_rot13email(e_el)
    if r13:
        return r13
    dc = _decode_datacode_email(e_el)
    if dc:
        return dc
    rev = _decode_reversed_email(e_el)
    if rev:
        return rev
    raw = e_el.get("href") if e_el.has_attr("href") else e_el.get_text(" ", strip=True)
    return _clean_email(raw)


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
        # Collapse internal whitespace runs — a name split across text nodes
        # by ``<br>``/nbsp (e.g. Purdue Chemistry's "Ryan&#160;\n Altman") comes
        # back from get_text with embedded newlines/double-spaces that would leak
        # into pi_name and trip the data-quality name checks.
        name = re.sub(r"\s+", " ", name_el.get_text(" ", strip=True)).strip()
        if sel.get("name_last"):
            # Directories that split the name across two cells (a first-name and
            # a last-name column, e.g. UCI Chemistry's Drupal table): the ``name``
            # selector holds the first name, ``name_last`` the surname.
            last_el = card.select_one(sel["name_last"])
            if last_el:
                name = f"{name} {last_el.get_text(' ', strip=True)}".strip()
        if sel.get("name_strip"):
            # Some directories prefix the name link with boilerplate ("Learn more
            # about <Name>"); strip it to recover the clean, properly-cased name.
            name = re.sub(sel["name_strip"], "", name).strip()
        if sel.get("name_title_case") and name.isupper():
            # SHOUTING rosters (UGA Pharmacy's "MICHAEL BARTLETT") — retitle only
            # all-caps names so mixed-case ones (McLean, DiMaggio) stay untouched.
            name = name.title()
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
        # A card whose only anchor is a tel:/mailto:/javascript: link has no real
        # profile page — fall back to the directory URL rather than ship a phone
        # number as the record's url (one such tel: URL corrupted a UCI record and
        # crashed URL canonicalization corpus-wide).
        if re.match(r"(?i)\s*(tel|mailto|javascript|fax|sms):", href or ""):
            href = ""
        href = urljoin(base_url, href) if href else base_url
        if sel.get("link_strip_query") and "?" in href:
            # Listing hrefs that append navigation state (Caltech's ?back_url=…)
            # would make the same profile a distinct URL per listing page —
            # strip the query so cross-listing dedupe and the profile-enrich
            # pass see one canonical profile URL.
            href = href.split("?", 1)[0]
        title_el = card.select_one(sel["title"]) if sel.get("title") else None
        if title_el is None and sel.get("title_sibling"):
            # Definition-list directories (MIT Sloan's A-Z <dl>) keep the rank
            # in the card's FOLLOWING sibling (<dt>name</dt><dd>title</dd>) —
            # unreachable by a descendant selector from the card.
            title_el = card.find_next_sibling(sel["title_sibling"])
        title = title_el.get_text(" ", strip=True) if title_el else "Professor"
        if sel.get("title_re"):
            # Hand-edited CMS cards sometimes keep the rank as loose text with no
            # stable element path (UCSD Communication/Urban Studies); a regex over
            # the card text extracts it where a CSS selector can't. Falls back to
            # the CSS/default title when the pattern doesn't match.
            m = re.search(sel["title_re"], card.get_text(" ", strip=True))
            if m:
                title = m.group(1).strip() or title
        if sel.get("title_strip_after"):
            # Some directories cram rank + office + phone into one cell; keep only
            # the text before the first contact marker (e.g. "Office"/"Phone").
            title = re.split(sel["title_strip_after"], title)[0].strip() or "Professor"
        if sel.get("title_html_re"):
            # Ranks that live as bare text between markup with no element of
            # their own (UGA Law's "<a>Name</a><br>Title<br><a mailto>") need
            # the serialized card, like research_re — capture group 1, strip
            # tags, and unescape ("&amp;" would otherwise land in the title).
            m = re.search(sel["title_html_re"], str(card), re.I | re.S)
            if m:
                import html as _html
                t = re.sub(r"\s+", " ",
                           _html.unescape(_HTML_TAG_RE.sub(" ", m.group(1)))).strip()
                title = t or title
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
        if not research and not keywords and sel.get("research_re"):
            # Some listing cards keep the research line as plain delimited text in
            # the card markup (no per-area element to select) — e.g. UCLA Physics'
            # "<h5>Name</h5><p>Title<br>High Energy, Astroparticle<br>Office:...".
            # A regex bounds just the research line; _clean_keywords splits it.
            m = re.search(sel["research_re"], str(card), re.I | re.S)
            if m:
                seg = _BR_RE.sub("; ", m.group(1))  # <br>-separated areas → delimiter
                research = re.sub(r"\s+", " ", _HTML_TAG_RE.sub(" ", seg)).strip()
        if not research and not keywords and sel.get("research_re_text"):
            # Same idea but over the card's rendered TEXT — for patterns whose
            # character classes ([^.]) would trip on dots inside tag attributes
            # (UCSD Sociology's "…PhD Harvard 1984. <areas>." card prose).
            m = re.search(sel["research_re_text"], card.get_text(" ", strip=True), re.S)
            if m:
                research = re.sub(r"\s+", " ", m.group(1)).strip()
        email = None
        if sel.get("email"):
            e_el = card.select_one(sel["email"])
            if e_el is not None:
                email = _email_from_el(e_el)
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


def _is_cf_interstitial(soup) -> bool:
    """True when a rendered page is still Cloudflare's challenge shell, not content.

    Cloudflare returns its interstitial with HTTP 200 and non-empty HTML ("Just a
    moment…" + a ``/cdn-cgi/challenge-platform/`` script) and only swaps in the real
    DOM after the JS challenge passes and reloads. Capturing ``page.content()`` too
    early yields this shell — zero cards, no error — so the render must be retried.
    """
    title = (soup.title.get_text() if soup.title else "").strip().lower()
    if "just a moment" in title or "attention required" in title:
        return True
    return bool(soup.select_one(
        "#challenge-running, #cf-challenge-running, "
        "script[src*='challenge-platform'], script[src*='/cdn-cgi/challenge']"))


def _render_soup(url: str, timeout_ms: int = 60000,
                 wait_until: str = "domcontentloaded", settle_ms: int = 3500,
                 expect_selector: str | None = None):
    """Fetch a URL through a headless-Chromium browser and return a BeautifulSoup.

    The escape hatch for directories a plain ``requests`` GET can't read: pages
    rendered client-side (the cards exist only after JS runs) and sites behind
    Cloudflare's bot wall (a real browser passes the JS challenge that 403s a
    bare request). Opt-in per department via ``scrape["render"] = True``; a slow
    client-rendered roster whose cards land only after its XHRs finish can opt
    into ``scrape["render_wait"] = "networkidle"`` (UCI cs.ics.uci.edu).

    Playwright is imported lazily so the module still imports where Playwright/
    Chromium isn't installed; there it returns ``None`` and the caller degrades
    to the curated layer, exactly like an unreachable ``fetch_soup``.
    """
    try:
        from bs4 import BeautifulSoup
        from playwright.sync_api import sync_playwright

        from .ucb_common import HEADERS
    except ImportError:
        logger.warning(
            "faculty_graph: playwright not installed; render fetch skipped for %s "
            "(pip install playwright && python -m playwright install chromium)", url,
        )
        return None
    # Headless navigation is flaky (transient goto timeouts, slow card grids, and
    # Cloudflare interstitials that 200 with a challenge shell before reloading the
    # real DOM), so retry up to three times, backing off the settle each round. A
    # render "succeeds" only when it yields a non-challenge page that actually has
    # the caller's ``expect_selector`` cards — capturing the interstitial or an
    # un-hydrated grid forces another attempt rather than returning empty.
    soup = None
    for attempt in (1, 2, 3):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_context(user_agent=HEADERS["User-Agent"]).new_page()
                    page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                    # Let client-side card grids / Cloudflare interstitials settle.
                    page.wait_for_timeout(settle_ms)
                    # Block until the expected cards render (CF cleared + JS done);
                    # a timeout just falls through to the interstitial check below.
                    if expect_selector:
                        try:
                            page.wait_for_selector(expect_selector, timeout=20000)
                        except Exception:  # noqa: BLE001 — handled by the retry guard
                            pass
                    html = page.content()
                finally:
                    browser.close()
            cand = BeautifulSoup(html, "html.parser") if html else None
            if cand is not None and not _is_cf_interstitial(cand) and (
                    not expect_selector or cand.select(expect_selector)):
                soup = cand
                break
            logger.info("faculty_graph: render for %s unresolved (attempt %d: "
                        "challenge shell or no '%s' cards); retrying",
                        url, attempt, expect_selector or "?")
            settle_ms = min(settle_ms + 4000, 14000)
        except Exception as e:  # noqa: BLE001 — degrade to None like fetch_soup
            logger.warning("faculty_graph: render fetch failed for %s (attempt %d): %s",
                           url, attempt, e)
    return soup


def _render_paginated_soup(url: str, param: str = "page", max_pages: int = 12,
                          card_sel: str = "", timeout_ms: int = 60000):
    """Walk a client-side hash-router directory in ONE render session.

    Some AEM "people" grids (Michigan LSA — Chemistry, Psychology, Statistics,
    MCDB) render ~12 cards per page and only advance when the URL fragment changes
    *in-page* (a hashchange event); a fresh load with ``#…page=N`` pre-set never
    bootstraps past page 1, so the normal fetch-per-URL paginator can't drive them.
    This loads the base once, then re-navigates the SAME page to ``#…&page=N`` for
    each page (a same-document navigation that fires the router), accumulating each
    page's ``card_sel`` outerHTML until a page surfaces nothing new or the cap is
    hit. Returns a soup of all pages' cards concatenated (parsed by the caller's
    normal selectors), or ``None`` where Playwright/Chromium is unavailable.
    """
    if not card_sel:
        return None
    try:
        from bs4 import BeautifulSoup
        from playwright.sync_api import sync_playwright

        from .ucb_common import HEADERS
    except ImportError:
        return None
    parts: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_context(user_agent=HEADERS["User-Agent"]).new_page()
                seen: set[str] = set()
                for pg in range(1, max_pages + 1):
                    target = url if pg == 1 else f"{url}#q=&alpha=&{param}={pg}"
                    page.goto(target, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(3500 if pg == 1 else 2500)
                    cards = page.eval_on_selector_all(
                        card_sel, "els => els.map(e => e.outerHTML)")
                    fresh = [c for c in cards if c not in seen]
                    if pg > 1 and not fresh:
                        break
                    seen.update(fresh)
                    parts.extend(fresh)
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001 — degrade to None like fetch_soup
        logger.warning("faculty_graph: paginated render failed for %s: %s", url, e)
        return None
    if not parts:
        return None
    return BeautifulSoup("<div>" + "".join(parts) + "</div>", "html.parser")


def _scrape_directory(dept: dict) -> list[dict]:
    """Best-effort parse of a department directory into faculty specs.

    Opt-in: only runs when the department config has a ``scrape`` block. Lazy-
    imports requests/bs4 and degrades to ``[]`` on any failure (a 403 bot wall,
    timeout, or markup drift) so deep mode never breaks the curated layer.

    ``scrape["render"] = True`` routes fetches through a headless browser
    (:func:`_render_soup`) instead of a plain request — for JS-rendered grids and
    Cloudflare-walled directories. All the CSS selectors below work unchanged on
    the rendered HTML.

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
    if cfg.get("ajax_html"):
        # Drupal "Show more" tabs cap the static HTML at one page; the tab's
        # /ajax/show-more endpoint returns [{"data": "<cards html>"}] in one
        # call (Harvard HWP requires XHR headers + a Referer or Akamai 403s).
        try:
            import requests
            from bs4 import BeautifulSoup

            from .ucb_common import HEADERS
            hdrs = {**HEADERS, "X-Requested-With": "XMLHttpRequest",
                    **cfg.get("ajax_headers", {})}
            resp = requests.get(cfg["url"], headers=hdrs, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            html = "".join(part.get("data", "") for part in payload
                           if isinstance(part, dict))
            soup = BeautifulSoup(html, "html.parser")
            people = _parse_cards(soup, cfg.get("selectors", {}),
                                  dept.get("directory_url") or cfg["url"],
                                  cfg.get("ladder_filter"), cfg.get("name_flip", False),
                                  cfg.get("link_filter"), cfg.get("section_filter"),
                                  cfg.get("field_filter"))
            return _apply_profile_enrich(people, cfg.get("profile_enrich"))
        except Exception as e:  # noqa: BLE001
            logger.warning("faculty_graph: ajax_html fetch failed for %s: %s",
                           dept.get("short"), e)
            return []
    if cfg.get("render"):
        # A slow client-rendered roster can request networkidle (its cards land
        # only after late XHRs); default stays domcontentloaded for speed. A
        # longer ``render_settle`` clears the tougher Cloudflare/Turnstile walls
        # that a datacenter IP (CI) hits — and it must apply to the paginated
        # follow-ups too, not just the base page, or pages 2..N collect nothing.
        rw = cfg.get("render_wait", "domcontentloaded")
        _settle = cfg.get("render_settle", 3500)
        def fetch(u, _rw=rw, _s=_settle):
            return _render_soup(u, wait_until=_rw, settle_ms=_s)
    else:
        # Pass ua/insecure only when configured — tests (and older collectors)
        # stub fetch_soup with single-arg fakes.
        _cfg_ua = cfg.get("ua")
        _cfg_insecure = cfg.get("insecure", False)
        def fetch(u, _ua=_cfg_ua, _ins=_cfg_insecure):
            if _ins:
                return fetch_soup(u, ua=_ua, insecure=True)
            return fetch_soup(u, ua=_ua) if _ua else fetch_soup(u)
    if cfg.get("pre_delay"):
        # Space out listing hits against burst-rate WAFs (Penn Medicine's
        # Imperva front 403s after ~6 rapid requests) — a terminal 403 here
        # would silently drop the whole department for the run.
        import time
        time.sleep(cfg["pre_delay"])
    base = cfg["url"]
    sel = cfg.get("selectors", {})
    lf = cfg.get("ladder_filter")
    flip = cfg.get("name_flip", False)
    link_f = cfg.get("link_filter")
    sf = cfg.get("section_filter")
    ff = cfg.get("field_filter")
    pag = cfg.get("paginate")
    if cfg.get("render") and pag and pag.get("mode") == "hash":
        # Client-side hash-router grids (AEM "Michigan LSA" people pages) render
        # only ~12 cards per page and advance solely on an in-page hashchange — a
        # fresh load with the fragment pre-set never bootstraps past page 1. Walk
        # every page inside one render session (below) instead of the fetch-per-URL
        # loop, which can't drive a same-document router.
        soup = _render_paginated_soup(base, pag.get("param", "page"),
                                      pag.get("max", 12), sel.get("card", ""))
    elif cfg.get("render"):
        # Wait for the card selector so a Cloudflare-walled dept retries past the
        # interstitial instead of parsing the challenge shell (empty result). A
        # slower CF subdomain can request a longer initial settle (``render_settle``)
        # so its challenge clears before the first card check (JHU BME's bme.jhu.edu).
        soup = _render_soup(base, wait_until=rw, expect_selector=sel.get("card"),
                            settle_ms=cfg.get("render_settle", 3500))
    else:
        soup = fetch(base)
    if soup is None:
        logger.info("faculty_graph: directory unreachable for %s (curated only)", dept.get("short"))
        return []
    try:
        people = _parse_cards(soup, sel, base, lf, flip, link_f, sf, ff)
        if pag and pag.get("mode") != "hash":
            param = pag.get("param", "page")
            path_mode = pag.get("mode") == "path"
            seen = {(p["name"], p["url"]) for p in people}
            # Drupal multi-view pagers prefix the page value ("?page=%2C3" —
            # SEAS's faculty view is the second view on the page).
            vpre = pag.get("value_prefix", "")
            for pg in range(pag.get("start", 1), pag.get("max", 12) + 1):
                next_url = _paginated_url(base, pg, param) if path_mode else (
                    f"{base}{'&' if '?' in base else '?'}{param}={vpre}{pg}")
                s2 = fetch(next_url)
                if s2 is None:
                    break
                fresh = [p for p in _parse_cards(s2, sel, base, lf, flip, link_f, sf, ff)
                         if (p["name"], p["url"]) not in seen]
                if not fresh:
                    break
                seen.update((p["name"], p["url"]) for p in fresh)
                people.extend(fresh)
        people = _apply_profile_enrich(people, cfg.get("profile_enrich"))
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
_BR_RE = re.compile(r"(?i)<br\s*/?>")

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
        t = re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip(" .,:;•·*–—-\t")
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


def _acf_path(rec: dict, path: str):
    """Walk a dotted path into a WP record's ``acf`` block ("job_titles.0.position.title").

    Numeric segments index lists; any miss returns "" so a person whose ACF
    omits the field degrades to the config default instead of raising.
    """
    cur = rec.get("acf")
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return ""
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return ""
    return cur if isinstance(cur, str | int | float) else ""


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


def _wp_get_json(url: str, ua: str | None = None):
    try:
        import requests
    except Exception:  # noqa: BLE001
        return None
    from .ucb_common import HEADERS
    headers = {**HEADERS, "User-Agent": ua} if ua else HEADERS
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception:  # noqa: BLE001 — degrade to None like fetch_soup
        return None


def _wp_term_map(base: str, tax: str, ua: str | None = None) -> dict[int, str]:
    """Resolve a WordPress taxonomy's term ids → display names."""
    out: dict[int, str] = {}
    for pg in range(1, 6):
        url = f"{base}/wp-json/wp/v2/{tax}?per_page=100&page={pg}"
        # ua only when configured — tests stub _wp_get_json single-arg.
        data = _wp_get_json(url, ua=ua) if ua else _wp_get_json(url)
        if not isinstance(data, list) or not data:
            break
        for term in data:
            if isinstance(term, dict) and "id" in term:
                out[term["id"]] = _wp_text(term.get("name", ""))
        if len(data) < 100:
            break
    return out


def _fetch_digitalmeasures(url: str, dm: dict) -> str:
    """Research-expertise text from a Digital Measures (Activity Insight) report.

    Many business schools (UT McCombs) render faculty profiles client-side from a
    public Digital Measures JSON report keyed by a campus username carried in the
    listing link (``?username=<u>``). We pull the report, find the configured
    heading ("Research Expertise"), and join the values of the records block that
    follows it into a comma/semicolon-split-ready string.
    """
    m = re.search(r"[?&]username=([A-Za-z0-9._-]+)", url)
    if not m:
        return ""
    api = (f"https://profiles.digitalmeasures.com/clients/{dm['client']}"
           f"?reportId={dm['report']}&identifierKey=username"
           f"&identifierValue={m.group(1)}")
    try:
        import requests

        from .ucb_common import HEADERS
        data = requests.get(api, headers=HEADERS, timeout=20).json()
    except Exception:  # noqa: BLE001
        return ""
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return ""
    heading = dm.get("heading", "Research Expertise")
    for i, it in enumerate(items):
        head = it.get("heading") if isinstance(it, dict) else None
        hv = head.get("value") if isinstance(head, dict) else head
        if not (hv and heading in str(hv)):
            continue
        for j in range(i, min(i + 3, len(items))):
            blk = items[j].get("data") if isinstance(items[j], dict) else None
            recs = blk.get("records") if isinstance(blk, dict) else None
            if recs:
                vals = [_HTML_TAG_RE.sub("", r.get("value", ""))
                        for r in recs if isinstance(r, dict)]
                return "; ".join(v.strip() for v in vals if v and v.strip())
        break
    return ""


def _apply_profile_enrich(people: list[dict], enr: dict | None) -> list[dict]:
    """Per-profile enrichment pass (gated): follow each faculty's own profile
    page to recover research areas / email / rank the directory listing omits.

    Only records still missing the wanted fields are fetched, so a re-run (or a
    listing that already carries them) costs nothing extra. ``always: True``
    bypasses the OFE_ENRICH_PROFILES env gate — for directories whose LISTING
    has no title/email at all (bare link-lists), the profile pass isn't
    optional depth, it's where the record's core fields live. ``url_template``
    builds the fetch URL from the person's email local-part instead of the
    stored url (roster APIs whose per-person endpoint is keyed by username,
    e.g. UCSD Physics ``/api/profile/<user>/<dept>``). ``ladder_recheck``
    re-gates on rank AFTER titles exist (the listing-time gate saw only the
    "Professor" default). ``render: True`` fetches each profile through the
    headless browser instead of a plain GET — for schools whose profile pages
    sit behind the same bot wall as the listing (Princeton dept subdomains,
    umich), where the listing omits the email/research the profile carries.
    """
    if not enr or not (_PROFILE_ENRICH or enr.get("always")):
        return people
    import time
    throttle = enr.get("throttle", 0.0)
    tpl = enr.get("url_template")
    for p in people:
        target = p.get("url") or ""
        if tpl:
            local = (p.get("email") or "").split("@")[0]
            if not local:
                continue
            target = tpl.format(email_local=local)
        if not target:
            continue
        want_research = not p.get("research_areas") and not p.get("keywords")
        want_email = bool(enr.get("email_selector")) and not p.get("email")
        want_title = bool(enr.get("title_selector"))
        if not (want_research or want_email or want_title):
            continue
        pos, research, items, email = _enrich_profile(target, enr)
        if items and want_research:
            p["keywords"] = items
        elif research and want_research:
            p["research_areas"] = research
        if email and enr.get("email_drop") and re.search(enr["email_drop"], email, re.I):
            # A profile whose first mailto is a shared departmental inbox
            # (info@english.upenn.edu) must not become anyone's personal
            # address — one alias on 36 professors would also make the
            # school-wide email dedupe collapse them into one record.
            email = None
        if email and want_email:
            p["email"] = email
        if pos and (enr.get("use_position_title") or enr.get("title_selector")):
            p["title"] = pos
        if throttle:
            time.sleep(throttle)
    lr = enr.get("ladder_recheck")
    if lr:
        people = [p for p in people if _passes_ladder(p.get("title") or "", lr)]
    return people


def _enrich_profile(url: str, enrich: dict) -> tuple[str, str, list[str], str | None]:
    """Fetch one profile page; extract (position, research-text, research-items, email).

    ``research-items`` is a clean atomic keyword list from a CSS
    ``research_items_selector`` (taxonomy-links markup); ``research-text`` is a
    labelled HTML block to be comma/semicolon-split downstream. A config uses one
    or the other depending on how the site stores research areas.
    """
    if not url:
        return ("", "", [], None)
    dm = enrich.get("digitalmeasures")
    if dm:
        return ("", _fetch_digitalmeasures(url, dm), [], None)
    if enrich.get("render"):
        # Profile pages sit behind the same bot wall as the listing (Princeton
        # dept subdomains, umich) — a plain GET 403s, so route the per-profile
        # fetch through the headless browser too. Returns None where Playwright/
        # Chromium is absent, degrading exactly like an unreachable fetch_soup.
        # ``render_wait`` mirrors the scrape block's knob: some walls (Duke's
        # Anubis proof-of-work interstitial on nicholas.duke.edu) only clear once
        # the challenge JS finishes and reloads, which "networkidle" waits for but
        # the "domcontentloaded" default fires too early on.
        soup = _render_soup(url, wait_until=enrich.get("render_wait", "domcontentloaded"))
    else:
        try:
            from .ucb_common import fetch_soup
        except Exception:  # noqa: BLE001
            return ("", "", [], None)
        _ua = enrich.get("ua")
        soup = fetch_soup(url, ua=_ua) if _ua else fetch_soup(url)
    if soup is None:
        return ("", "", [], None)
    body = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    pos = ""
    if enrich.get("title_selector"):
        # Directories whose LISTING carries no rank at all (a bare link-list,
        # e.g. UCSD Literature/Theatre) keep it on the profile page in a stable
        # element — a CSS selector beats a body-text regex there.
        t_el = soup.select_one(enrich["title_selector"])
        pos = t_el.get_text(" ", strip=True) if t_el else ""
    if not pos and enrich.get("position_re"):
        m = re.search(enrich["position_re"], body, re.I)
        pos = m.group(0).strip() if m else ""
    email = None
    if enrich.get("email_selector"):
        e_el = soup.select_one(enrich["email_selector"])
        if e_el is not None:
            email = _email_from_el(e_el)
    items: list[str] = []
    if enrich.get("research_items_selector"):
        items = _clean_selector_items(soup, enrich["research_items_selector"])
    kw = ""
    if enrich.get("research_selector"):
        # Profiles that keep research areas as a prose block in a stable
        # element (Caltech's div.field__research_summary) — a CSS selector
        # beats a serialized-HTML regex, which nested markup can truncate.
        r_el = soup.select_one(enrich["research_selector"])
        if r_el is not None:
            kw = re.sub(r"\s+", " ", r_el.get_text(" ", strip=True)).strip()
            # The block often embeds its own heading ("Research Summary
            # Geochemical investigations…") — strip the label, keep the prose.
            kw = re.sub(r"^research\s+(summary|interests?|areas?)\s*:?\s*", "", kw, flags=re.I)
    if not kw and enrich.get("research_html_re"):
        # Sites that keep research areas in a labelled HTML block (e.g. GT's
        # "<strong>Research Areas:</strong> A; B; C</p>") need the markup, not the
        # flattened text, to bound the capture — match on the serialized soup,
        # then strip tags so the raw labelled text lands in research_areas (the
        # derived-keyword path cleans + splits it through the same DQ gate).
        m = re.search(enrich["research_html_re"], str(soup), re.I | re.S)
        if m:
            seg = _BR_RE.sub("; ", m.group(1))  # <br>-separated areas → delimiter
            kw = re.sub(r"\s+", " ", _HTML_TAG_RE.sub(" ", seg)).strip().rstrip(".").strip()
    if not kw and enrich.get("research_re"):
        m = re.search(enrich["research_re"], body, re.I)
        if m:
            kw = m.group(1).strip()
    if not items and not kw and enrich.get("cap_keywords"):
        # Stanford's on-site dept profiles are prose, but each links to a central
        # CAP profile (profiles.stanford.edu/<id>) whose open JSON API exposes a
        # clean curated ``keywords`` field. Two-hop: page → CAP id → CAP JSON. Use
        # ``keywords`` only (researchInterestTopics/publicationTags are empty or
        # MeSH-noisy). Values are comma/newline-delimited → fold to the ;/,
        # separators _clean_keywords splits on.
        idm = re.search(r"profiles\.stanford\.edu/(\d+)", str(soup))
        if idm:
            cap = _wp_get_json(
                f"https://profiles.stanford.edu/proxy/api/cap/profiles/{idm.group(1)}")
            data = cap.get("data") if isinstance(cap, dict) else None
            vals = data.get("keywords") if isinstance(data, dict) else None
            if isinstance(vals, list):
                raw = "; ".join(v for v in vals if isinstance(v, str) and v.strip())
                kw = re.sub(r"[\r\n]+", "; ", raw).strip()
    return (pos, kw, items, email)


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
    ua = cfg.get("ua")
    kw_taxes = cfg.get("keyword_tax", [])
    term_maps = {t: _wp_term_map(base, t, ua=ua) for t in kw_taxes}
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
    # Others keep them on the ACF block instead (UGA Terry's `directory` type:
    # acf.email plus acf.job_titles[0].position.title) — ``acf_fields`` maps
    # {"title"|"email": dotted path} into that nested structure.
    acf_fields = cfg.get("acf_fields") or {}

    records: list[dict] = []
    query = cfg.get("query", "")
    for pg in range(1, 13):
        page_url = f"{base}/wp-json/wp/v2/{cfg['post_type']}?per_page=100&page={pg}{query}"
        data = _wp_get_json(page_url, ua=ua) if ua else _wp_get_json(page_url)
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
        if cfg.get("name_strip"):
            # Person post titles that append credentials ("Jane Doe, PhD, RN")
            # — strip so pi_name stays a clean person name.
            name = re.sub(cfg["name_strip"], "", name).strip()
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
        if acf_fields.get("title"):
            at = _wp_text(str(_acf_path(rec, acf_fields["title"]) or ""))
            if at:
                title = at
        if acf_fields.get("email") and not email:
            email = (str(_acf_path(rec, acf_fields["email"]) or "").strip() or None)
        if not _passes_ladder(title, cfg.get("ladder_filter")):
            # Same title gate as the scrape path — REST role taxonomies are often
            # too coarse (UGA Terry tags lecturers `faculty` too).
            continue
        if enrich:
            pos, extra_kw, extra_items, extra_email = _enrich_profile(url, enrich)
            if pos:
                title = pos
            if enrich.get("require_professor") and pos and not re.search(r"profess", pos, re.I):
                continue
            if extra_items:
                keywords = extra_items + keywords
            elif extra_kw:
                keywords.insert(0, extra_kw)
            if extra_email and not email:
                email = extra_email
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
                # (Deliberately newline-only: many ECE/MAE/MSE toggles are prose,
                # and comma-splitting them shatters sentences into fragments —
                # better broad than fragments; those go to the LLM-prose pass.)
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


_FUTUREVU_PATH = ("/wp-content/themes/anchordown-futurevu/library/remote/"
                  "peoplemanager-directory-remote-webcomm.php")


def _fetch_futurevu_ajax(dept: dict) -> list[dict]:
    """Vanderbilt FutureVU "People Directory" fetch (opt-in via dept ``ajax``
    block with ``type: "futurevu"``).

    The shared anchordown-futurevu widget client-side GETs a same-origin JSON
    endpoint returning ``{"data": [{full_name, titles, email, slug, ...}]}``.
    ``titles`` is HTML (``<br/>``-joined multi-line + entities); we decode it,
    take the first non-empty line as the rank, and ladder-filter on the whole
    thing. Degrades to ``[]`` on any failure so deep mode never breaks.
    """
    import html as _html

    cfg = dept.get("ajax")
    if not cfg or cfg.get("type") != "futurevu":
        return []
    try:
        import requests

        from .ucb_common import HEADERS
    except Exception:  # noqa: BLE001
        return []
    host = cfg["host"].rstrip("/")
    params = {
        "option": "choose-department", "school": cfg["school"],
        "department": cfg.get("department", "all"), "group": cfg.get("group", "all"),
        "affiliated": cfg.get("affiliated", "primary"),
        "neighborhood": "none", "showdept": "true",
    }
    headers = {**HEADERS, "X-Requested-With": "XMLHttpRequest",
               "Referer": f"https://{host}/people/"}
    try:
        resp = requests.get(f"https://{host}{_FUTUREVU_PATH}", headers=headers,
                            params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001
        return []
    records = data.get("data", []) if isinstance(data, dict) else data
    if not isinstance(records, list):
        return []

    lf = cfg.get("ladder_filter") or {}
    req_re = re.compile(lf["require"], re.I) if lf.get("require") else None
    drop_re = re.compile(lf["drop"], re.I) if lf.get("drop") else None
    profile_base = cfg.get("profile_base", f"https://{host}/bio/")

    def _clean_titles(raw: str) -> str:
        txt = _html.unescape(re.sub(r"<br\s*/?>", "\n", raw or ""))
        lines = [ln.strip() for ln in re.split(r"[\n\r]+", txt) if ln.strip()]
        return lines[0] if lines else ""

    specs: list[dict] = []
    seen: set[str] = set()
    for rec in records:
        if not isinstance(rec, dict):
            continue
        name = (rec.get("full_name")
                or f"{rec.get('first_name', '')} {rec.get('last_name', '')}").strip()
        if not name or not _is_person_name(name):
            continue
        raw_titles = f"{rec.get('titles', '')} {rec.get('other_titles', '')}"
        if req_re and not req_re.search(raw_titles):
            continue
        if drop_re and drop_re.search(raw_titles):
            continue
        slug = (rec.get("slug") or "").strip()
        if slug and slug in seen:
            continue
        if slug:
            seen.add(slug)
        email = (rec.get("email") or "").strip() or None
        url = f"{profile_base}{slug}" if slug else ""
        specs.append(faculty(name, title=_clean_titles(rec.get("titles", "")) or "Professor",
                             url=url, email=email))
    return specs


def _fetch_worx_ajax(dept: dict) -> list[dict]:
    """Yale SEAS "Worx" faculty-directory fetch (opt-in via dept ``ajax`` block
    with ``type: "worx"``).

    seas.yale.edu (concrete5, Worx theme) renders its faculty directory with a
    Vue block that POSTs form data to a ``load_faculty`` endpoint and paints the
    returned JSON — ``{"pages": {"letters": {"A": [{name, title, fullTitle,
    url}, ...], ...}}}``. Hitting the endpoint directly (department term id from
    the page's inline ``departmentsList``) is exact and complete, and one
    endpoint serves every SEAS department. Degrades to ``[]`` on any failure so
    deep mode never breaks the curated layer.
    """
    cfg = dept.get("ajax")
    if not cfg or cfg.get("type") != "worx":
        return []
    try:
        import requests

        from .ucb_common import HEADERS
    except Exception:  # noqa: BLE001
        return []
    endpoint = cfg["endpoint"]
    try:
        resp = requests.post(
            endpoint,
            data={"action": endpoint, "template": "full", "maxpages": "0",
                  "department": str(cfg.get("department", "")), "query": ""},
            headers={**HEADERS, "X-Requested-With": "XMLHttpRequest",
                     "Referer": cfg.get("referer", endpoint)},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001
        return []
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, dict):
        return []
    letters = pages.get("letters")
    groups = letters.values() if isinstance(letters, dict) else [pages.get("fullPages") or []]

    lf = cfg.get("ladder_filter") or {}
    req_re = re.compile(lf["require"], re.I) if lf.get("require") else None
    drop_re = re.compile(lf["drop"], re.I) if lf.get("drop") else None

    specs: list[dict] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for rec in group:
            if not isinstance(rec, dict):
                continue
            name = (rec.get("name") or "").strip()
            if not name or not _is_person_name(name):
                continue
            title = (rec.get("fullTitle") or rec.get("title") or "").strip() or "Professor"
            if req_re and not req_re.search(title):
                continue
            if drop_re and drop_re.search(title):
                continue
            url = (rec.get("url") or "").strip()
            key = url.lower() or name.lower()
            if key in seen:
                continue
            seen.add(key)
            specs.append(faculty(name, title=title, url=url))
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
#         "name_fields": ["firstName", "lastName"],   # joined + whitespace-collapsed
#         "filter_field": "academic", "filter_value": "Finance",
#         "status_field": "status", "status_value": "Faculty",  # optional
#         "ladder_filter": {"drop": "emerit|lecturer|of the practice"},
#     }
#
# Options for a shared cross-department roster feed (UChicago BSD / Chemistry):
#     "headers": {"Referer": "https://microbiology.uchicago.edu/"},  # same-origin gate
#     "filter_field": "department", "filter_index": 0,               # PRIMARY appt only
#     "filter_value": "Microbiology",
#     "research_field": "interests[]",                               # list -> keywords
#     "link_base": "https://chemistry.uchicago.edu",                 # join relative pathAlias
#     # or, when the microsite host isn't resolvable, pull a stable link from a list:
#     "link_list": {"field": "websites", "match_key": "name",
#                   "match_value": "Research Network Profile", "url_key": "url"},
def _dig(record: dict, path: str):
    """Read a field by name, or by dotted path for nested feeds.

    UCSD Biology keeps the rank at ``titleInfo.standardTitle``; a plain key
    (no dot) reads exactly like ``record.get(key)``, so flat configs are
    unaffected. Any missing/non-dict hop resolves to None.
    """
    cur = record
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _fetch_json_dir(dept: dict) -> list[dict]:
    """Best-effort faculty fetch from an authoritative JSON directory (opt-in).

    Field-name options (``name_fields``, ``title_field``, ``email_field``,
    ``link_field``, ``filter_field``, ``status_field``) accept dotted paths
    into nested objects.
    """
    cfg = dept.get("json_dir")
    if not cfg:
        return []
    # A committed local JSON file (``file``) instead of a live endpoint: the
    # persistence layer for mega-directories that are too large / bot-walled to
    # re-render every refresh (JHU Bloomberg Public Health, School of Medicine,
    # NU Feinberg). A one-time local harvest writes the file; the refresh loads
    # it instantly with the same field-mapping. Path is repo-root-relative.
    if cfg.get("file"):
        import json as _json
        import os as _os
        here = _os.path.dirname(__file__)
        root = _os.path.abspath(_os.path.join(here, "..", ".."))
        fpath = cfg["file"] if _os.path.isabs(cfg["file"]) else _os.path.join(root, cfg["file"])
        try:
            with open(fpath, encoding="utf-8") as fh:
                recs = _json.load(fh)
        except Exception:  # noqa: BLE001
            logger.warning("faculty_graph: json_dir file unreadable for %s: %s",
                           dept.get("short"), cfg["file"])
            return []
        return _json_dir_records(dept, cfg, recs)
    try:
        import requests
    except Exception:  # noqa: BLE001
        return []
    from .ucb_common import HEADERS
    # Some feeds gate on a same-origin Referer (UChicago's shared BSD roster
    # endpoint returns empty to a header-less request); merge any per-source
    # headers over the browser-like defaults.
    hdrs = {**HEADERS, **(cfg.get("headers") or {})}
    try:
        if str(cfg.get("method", "get")).lower() == "post":
            # Some campus HR feeds only answer form POSTs (UCSD's EAH directory
            # returns an empty body to a GET of the same URL).
            resp = requests.post(cfg["url"], data=cfg.get("data"),
                                 headers=hdrs, timeout=25)
        else:
            resp = requests.get(cfg["url"], headers=hdrs, timeout=25)
        resp.raise_for_status()
        recs = resp.json()
    except Exception:  # noqa: BLE001
        return []
    return _json_dir_records(dept, cfg, recs)


def _json_dir_records(dept: dict, cfg: dict, recs) -> list[dict]:
    """Map a JSON directory payload (from a live endpoint or a committed file)
    into faculty specs, honouring the field-name / filter / title-map options."""
    if isinstance(recs, dict):
        recs = (recs.get(cfg.get("records_key", "")) if cfg.get("records_key")
                else next((v for v in recs.values() if isinstance(v, list)), []))
    lf = cfg.get("ladder_filter") or {}
    require_re, drop_re = lf.get("require"), lf.get("drop")
    name_fields = cfg.get("name_fields", ["firstName", "lastName"])
    filt_field, filt_value = cfg.get("filter_field"), cfg.get("filter_value")
    filt_index = cfg.get("filter_index")
    status_field, status_value = cfg.get("status_field"), cfg.get("status_value")
    specs: list[dict] = []
    for x in recs:
        if not isinstance(x, dict):
            continue
        if filt_field is not None:
            fv = _dig(x, filt_field)
            if filt_index is not None:
                # Match at a fixed list position instead of membership — a shared
                # roster feed lists every joint appointment in the record's
                # department array, so keying on department[0] (the PRIMARY
                # appointment) keeps a cross-listed professor in one home dept
                # only, not once per department they touch.
                fv = fv[filt_index] if isinstance(fv, list) and len(fv) > filt_index else None
                if fv != filt_value:
                    continue
            elif filt_value not in (fv if isinstance(fv, list) else [fv]):
                continue
        if status_field is not None:
            sv = _dig(x, status_field)
            if status_value not in (sv if isinstance(sv, list) else [sv]):
                continue
        # Regex gates over arbitrary fields, for feeds that need more than the
        # single equality pair above (e.g. UCSD Math's HR feed: keep ladder
        # job codes AND employee_class "Academic: Faculty", drop Retired).
        if any(
            (ff.get("include") and not re.search(ff["include"], str(_dig(x, ff["field"]) or ""), re.I))
            or (ff.get("exclude") and re.search(ff["exclude"], str(_dig(x, ff["field"]) or ""), re.I))
            for ff in cfg.get("field_filters", [])
        ):
            continue
        name = re.sub(r"\s+", " ",
                      " ".join(str(_dig(x, f) or "").strip() for f in name_fields)).strip()
        if not _is_person_name(name):
            continue
        title = _dig(x, cfg.get("title_field", "title")) or "Professor"
        if isinstance(title, list):
            title = ", ".join(str(t) for t in title)
        title = str(title).strip() or "Professor"
        if "<" in title or "&" in title:
            # Some JSON feeds carry <br>-joined multi-role titles and HTML
            # entities (Rice MCLC / Art History / Sport Mgmt / EEPS) — flatten
            # the <br> breaks to "; ", strip any residual tags, unescape
            # entities, so raw markup never reaches the corpus.
            import html as _html
            title = _BR_RE.sub("; ", title)
            title = re.sub(r"\s+", " ", _html.unescape(_HTML_TAG_RE.sub("", title))).strip()
            title = re.sub(r"(?:\s*;\s*)+", "; ", title).strip(" ;") or "Professor"
        tm = cfg.get("title_map")
        if tm:
            # Feeds that carry a rank CODE, not a rank (HR job codes) — map it;
            # unmapped codes fall back to the map's "_default" (or "Professor").
            title = tm.get(title, tm.get("_default", "Professor"))
        if require_re and not re.search(require_re, title, re.I):
            continue
        if drop_re and re.search(drop_re, title, re.I):
            continue
        email = str(_dig(x, cfg.get("email_field", "email")) or "").strip() or None
        ll = cfg.get("link_list")
        if ll:
            # The profile URL lives in a list of {name,url} objects (a feed's
            # "websites" array) rather than a scalar field — pick the entry whose
            # match_key equals match_value (e.g. the stable "Research Network
            # Profile" link, since the per-dept microsite host isn't resolvable).
            url_v = ""
            for item in (_dig(x, ll["field"]) or []):
                if isinstance(item, dict) and item.get(ll["match_key"]) == ll["match_value"]:
                    url_v = str(item.get(ll["url_key"], "") or "").strip()
                    break
        else:
            url_v = str(_dig(x, cfg.get("link_field", "link")) or "").strip()
        if url_v.startswith("//"):
            url_v = "https:" + url_v
        elif url_v.startswith("/") and cfg.get("link_base"):
            # A feed carrying a relative pathAlias (Chemistry: "/paul-alivisatos")
            # joins onto the department site host.
            url_v = cfg["link_base"].rstrip("/") + url_v
        research = ""
        keywords: list[str] = []
        for rf in ([cfg["research_field"]] if isinstance(cfg.get("research_field"), str)
                   else cfg.get("research_field") or []):
            # Rich feeds (UCSD Biology) carry per-person research data — no
            # profile scrape needed. A "[]" path segment fans out over a list
            # (profileInfo.sections[].title → one clean area tag per section)
            # and lands as keywords; a plain path is prose research_areas.
            # First populated field wins.
            if "[]" in rf:
                head, tail = rf.split("[]", 1)
                lst = _dig(x, head.strip("."))
                vals = [str(_dig(i, tail.strip(".")) if tail.strip(".") else i or "").strip()
                        for i in (lst if isinstance(lst, list) else [])
                        if isinstance(i, dict | str)]
                keywords = [v for v in vals if v]
                if keywords:
                    break
            else:
                research = str(_dig(x, rf) or "").strip()
                if research:
                    break
        specs.append(faculty(name, title=title, url=url_v, email=email,
                             research_areas=research, keywords=keywords))
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
# Corpus-wide faculty hygiene (one-time cleanup + refresh-safe regression guard)
# ---------------------------------------------------------------------------

# A faculty title is "Research with Prof. <name> — <SHORT> (kw1, kw2, kw3)"; the
# parenthetical is a subset of the record's keywords (a DQ invariant). When the
# keyword list is cleaned/de-duped the parenthetical must be rebuilt from it. The
# short segment carries no "(", so the lazy group stops at the keyword paren.
_FAC_TITLE_PAREN_RE = re.compile(r"^(.+ — [^(]+?)(?: \(.+\))$")


def _is_active_faculty(o: dict) -> bool:
    return (o.get("source_type") == "faculty_research"
            and (o.get("metadata") or {}).get("is_active", True))


def clean_corpus_faculty_keywords(opps: list[dict]) -> int:
    """Apply keyword hygiene (edge-strip, comma-fold, junk/prose drop, order-
    preserving de-dupe) to every faculty record and rebuild the title
    parenthetical when the record has one. Idempotent, so it doubles as a
    refresh-safe guard against a future scrape reintroducing duplicate/junk
    keywords. Mutates ``opps`` in place; returns the count of records changed."""
    changed = 0
    for o in opps:
        if o.get("source_type") != "faculty_research":
            continue
        kws = o.get("keywords") or []
        new = _hygiene_keywords(kws)
        touched = False
        if new != kws:
            o["keywords"] = new
            touched = True
        title = o.get("title") or ""
        m = _FAC_TITLE_PAREN_RE.match(title)
        if m:
            rebuilt = m.group(1) + (f" ({', '.join(new[:3])})" if new else "")
            if rebuilt != title:
                o["title"] = rebuilt
                touched = True
        if touched:
            changed += 1
    return changed


# Umbrella rosters that re-list people whose home is a more specific department
# (Georgia Tech's cc.gatech.edu "College of Computing" page lists everyone in the
# Schools of Interactive Computing / Computational Science & Engineering / CS).
# Keyed by school_slug -> the umbrella department names. Used ONLY for the
# no-email same-name collapse: a record under an umbrella dept that co-occurs
# with the same person under a specific dept is the redundant one.
_UMBRELLA_DEPTS: dict[str, frozenset[str]] = {
    "gatech": frozenset({"College of Computing"}),
}


# "Scott L. Delp, Ph.D." must normalize equal to "Scott L. Delp" — credential
# suffixes made the same person on the same profile URL survive dedup twice.
_CREDENTIAL_TOKENS = frozenset({
    "ph", "phd", "dphil", "md", "dvm", "dds", "jd", "esq", "mba", "msc",
    "dr", "prof", "jr", "sr", "ii", "iii", "iv",
})


def _name_tokens(name: str) -> set[str]:
    """Lowercased alphabetic name tokens (length > 1 — drops middle initials;
    credential/honorific tokens excluded)."""
    return {
        t for t in re.findall(r"[a-z]+", (name or "").lower())
        if len(t) > 1 and t not in _CREDENTIAL_TOKENS
    }


def _norm_person_name(name: str) -> str:
    """Order-insensitive normalized full name ("Last, First" == "First Last")."""
    return " ".join(sorted(_name_tokens(name)))


def _norm_faculty_url(o: dict) -> str:
    """Trailing-slash- and case-insensitive profile URL — the identity a
    person's profile page carries across the two department directories that
    both link to it."""
    return (o.get("url") or o.get("source_url") or "").strip().rstrip("/").lower()


def _merge_faculty_fields(survivor: dict, loser: dict) -> None:
    """Fill the survivor's missing contact fields (email / profile link) from the
    dropped duplicate, so collapsing never loses a usable address or URL."""
    if not (survivor.get("contact_email") or "").strip() and (loser.get("contact_email") or "").strip():
        survivor["contact_email"] = loser["contact_email"]
    for f in ("url", "source_url"):
        if not (survivor.get(f) or "").strip() and (loser.get(f) or "").strip():
            survivor[f] = loser[f]
    app, lapp = survivor.get("application"), loser.get("application")
    if isinstance(app, dict) and isinstance(lapp, dict):
        if not (app.get("application_url") or "").strip() and (lapp.get("application_url") or "").strip():
            app["application_url"] = lapp["application_url"]


def _pick_richer(group: list[dict], umbrella: frozenset[str]) -> dict:
    """Keyword-richest record in a same-person group; on a keyword tie, prefer a
    specific (non-umbrella) department over the umbrella roster."""
    from .uiuc_faculty import _faculty_is_richer
    best = group[0]
    for o in group[1:]:
        if _faculty_is_richer(o, best):
            best = o
        elif not _faculty_is_richer(best, o) and (
            best.get("department") in umbrella and o.get("department") not in umbrella
        ):
            best = o
    return best


def collapse_same_person_faculty(opps: list[dict]) -> dict:
    """Collapse duplicate ACTIVE faculty for the same person at one school and
    prevent recreation on the next merge.

    Two passes, both school-scoped and conservative:

    * **Same contact_email.** A cross-appointed professor listed under two
      departments (different profile URLs) shares one personal address. When the
      records also share a name token (the surname), they are one person: keep
      the keyword-richer record, merge the loser's email/link, delete the loser.
      When they do NOT share a name (a scraped department/advising inbox on two
      different people, e.g. two Law professors on one assistant's address), the
      email is a mis-scraped shared inbox — null it on both rather than merge,
      so a "Dear Prof. X" cold email can never reach the wrong person.

    * **Same normalized name, both without email.** Only collapsed when one
      record sits under an umbrella roster of the other (``_UMBRELLA_DEPTS``);
      genuine joint appointments across two peer departments (Stanford Applied
      Physics + Physics) are left as two records.

    Mutates ``opps`` in place (nulls shared inboxes) and returns
    ``{"kept": [...], "removed_by_school": {...}, "nulled_by_school": {...}}``."""
    active = [o for o in opps if _is_active_faculty(o)]
    remove: set[int] = set()
    removed_by_school: Counter = Counter()
    nulled_by_school: Counter = Counter()

    # Pass 0 — same school + same profile URL + same name is ONE person,
    # regardless of email. A cross-listed professor emitted by two department
    # rosters (Cornell Physics + Applied & Engineering Physics) shares one
    # ``/<slug>`` profile URL; the email and name passes below both miss the
    # pair when the two rows carry different (or only one) scraped emails —
    # the email pass never groups them and the name pass skips any record that
    # has an email. Keying on the shared canonical URL + name is exactly the
    # data-quality invariant (no two faculty at one URL) and is conservative: a
    # genuine joint appointment across peer departments has a DIFFERENT profile
    # URL per department, so this only ever collapses true duplicates.
    by_url_name: dict[tuple, list[dict]] = defaultdict(list)
    for o in active:
        u = (o.get("url") or o.get("source_url") or "").strip().rstrip("/").lower()
        nn = _norm_person_name(o.get("pi_name"))
        if u and nn:
            by_url_name[(o.get("school"), u, nn)].append(o)
    for (school, _u, _nn), group in by_url_name.items():
        if len(group) < 2:
            continue
        survivor = _pick_richer(group, frozenset())
        for o in group:
            if o is survivor:
                continue
            _merge_faculty_fields(survivor, o)
            remove.add(id(o))
            removed_by_school[school] += 1

    # Same profile SLUG syndicated across two department sites (Caltech CMS +
    # EE both serve /people/<slug> for a cross-listed professor with the same
    # profile content — 15% of Caltech faculty duplicated this way). Runs over
    # ALL active records regardless of email state: one department's scrape
    # often captured the mailto while the other didn't, which is exactly the
    # pair every email-keyed pass misses. Distinct from a genuine joint
    # appointment with per-department profiles: those carry department-specific
    # research blurbs, so the loser's keywords must be a NON-empty subset of
    # the survivor's (identical, or a syndicated stub) — shared content is the
    # evidence of syndication; two keyword-less stubs on different hosts carry
    # no evidence and stay.
    by_tail: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for o in active:
        if id(o) in remove:
            continue
        tail = _norm_faculty_url(o).rsplit("/", 1)[-1]
        nn = _norm_person_name(o.get("pi_name"))
        if tail and nn:
            by_tail[(o.get("school"), nn, tail)].append(o)
    for (school, _nn, _tail), tgroup in by_tail.items():
        if len(tgroup) < 2:
            continue
        survivor = _pick_richer(tgroup, frozenset())
        skw = {k.lower() for k in (survivor.get("keywords") or [])}
        for o in tgroup:
            if o is survivor:
                continue
            okw = {k.lower() for k in (o.get("keywords") or [])}
            # Evidence gate: the SURVIVOR must carry content and the loser must
            # be a subset of it — identical keywords, a syndicated stub, or a
            # keyword-less stub (nothing department-specific to preserve). Two
            # keyword-less records on different hosts (Stanford ME + BioE
            # stubs) carry no evidence either way and stay.
            if skw and okw <= skw:
                _merge_faculty_fields(survivor, o)
                remove.add(id(o))
                removed_by_school[school] += 1

    by_email: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for o in active:
        if id(o) in remove:
            continue
        em = (o.get("contact_email") or "").strip().lower()
        if em:
            by_email[(o.get("school"), em)].append(o)
    for (school, _em), group in by_email.items():
        if len(group) < 2:
            continue
        common = set.intersection(*(_name_tokens(o.get("pi_name")) for o in group))
        if common:
            survivor = _pick_richer(group, frozenset())
            for o in group:
                if o is survivor:
                    continue
                _merge_faculty_fields(survivor, o)
                remove.add(id(o))
                removed_by_school[school] += 1
        else:
            for o in group:
                o["contact_email"] = None
                nulled_by_school[school] += 1

    by_name: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for o in active:
        if id(o) in remove or (o.get("contact_email") or "").strip():
            continue
        nn = _norm_person_name(o.get("pi_name"))
        if nn:
            by_name[(o.get("school"), nn)].append(o)
    for (school, _nn), group in by_name.items():
        if len(group) < 2:
            continue
        # Same person (guaranteed same normalized name by the grouping above)
        # sharing ONE profile URL is a single profile linked from several
        # department directories — a UCLA Luskin professor cross-listed under
        # Public Policy + Urban Planning + Social Welfare, or a credential-suffix
        # name variant within one department. One profile URL ⟹ one person, so
        # collapse regardless of department: a genuine joint appointment across
        # peer departments has a DIFFERENT profile URL per department and is left
        # to the umbrella pass below. Keying by name+URL (not department) is what
        # the data-quality gate requires (no two faculty at one URL).
        by_url: dict[str, list[dict]] = defaultdict(list)
        for o in group:
            u = (o.get("url") or o.get("source_url") or "").strip().rstrip("/").lower()
            if u:
                by_url[u].append(o)
        for dgroup in by_url.values():
            if len(dgroup) < 2:
                continue
            survivor = _pick_richer(dgroup, frozenset())
            for o in dgroup:
                if o is survivor:
                    continue
                _merge_faculty_fields(survivor, o)
                remove.add(id(o))
                removed_by_school[school] += 1
        group = [o for o in group if id(o) not in remove]
        if len(group) < 2:
            continue
        umbrella = _UMBRELLA_DEPTS.get(school, frozenset())
        if not umbrella:
            continue
        umbrella_recs = [o for o in group if o.get("department") in umbrella]
        specific_recs = [o for o in group if o.get("department") not in umbrella]
        # Only the umbrella listing is redundant. Genuine joint appointments
        # across peer departments (Interactive Computing + City & Regional
        # Planning) both stay — we merge the umbrella record's fields into the
        # richer specific home record and delete only the umbrella record.
        if not umbrella_recs or not specific_recs:
            continue
        survivor = _pick_richer(specific_recs, umbrella)
        for o in umbrella_recs:
            _merge_faculty_fields(survivor, o)
            remove.add(id(o))
            removed_by_school[school] += 1

    # Drop inactive tombstones that duplicate a surviving ACTIVE record. The
    # passes above only dedupe active faculty, but the DQ gate counts inactive
    # ones too (a person "shown twice" is judged on the whole corpus). When a
    # partial re-scrape deactivates one department's listing while the same
    # professor stays active under another, the stale tombstone and the live
    # record collide on the gate's (school, email) / (school, url, name) keys.
    # The tombstone is superseded — the person is live elsewhere — so it is pure
    # cruft; dropping it never removes a shown record.
    kept_active = [o for o in active if id(o) not in remove]
    live_email_keys = {
        (o.get("school"), (o.get("contact_email") or "").strip().lower())
        for o in kept_active if (o.get("contact_email") or "").strip()
    }
    live_url_name_keys = {
        (o.get("school"), _norm_faculty_url(o), _norm_person_name(o.get("pi_name")))
        for o in kept_active if _norm_faculty_url(o) and _norm_person_name(o.get("pi_name"))
    }
    for o in opps:
        if id(o) in remove or _is_active_faculty(o) or o.get("source_type") != "faculty_research":
            continue
        school = o.get("school")
        em = (o.get("contact_email") or "").strip().lower()
        url, nn = _norm_faculty_url(o), _norm_person_name(o.get("pi_name"))
        if (em and (school, em) in live_email_keys) or (
            url and nn and (school, url, nn) in live_url_name_keys
        ):
            remove.add(id(o))
            removed_by_school[school] += 1

    kept = [o for o in opps if id(o) not in remove]
    return {
        "kept": kept,
        "removed_by_school": dict(removed_by_school),
        "nulled_by_school": dict(nulled_by_school),
    }


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
        v = (dept.get("directory_url") or "").strip().lower()
        if v:
            urls.add(v)
        for block in ("scrape", "api", "ajax", "algolia", "faculty180", "cola", "json_dir"):
            cfg = dept.get(block)
            if isinstance(cfg, dict):
                for k in ("url", "base"):
                    v = (cfg.get(k) or "").strip().lower()
                    if v:
                        urls.add(v)
    return urls


def _join_slug(url: str) -> str:
    """Last non-empty path segment of a profile URL, lowercased — the join key."""
    path = re.sub(r"[?#].*$", "", (url or "").strip().lower()).rstrip("/")
    return path.rsplit("/", 1)[-1] if "/" in path else path


def _apply_research_join(dept: dict, specs: list[dict]) -> None:
    """Fill research areas from one shared page keyed by each person's slug/name.

    Some departments keep research areas only on a single aggregator page (a
    "research interests" index, or the directory listing itself when the roster
    is fetched via API) rather than on each profile. A ``research_join`` block
    fetches that page once and maps key -> areas (accumulated across repeats — a
    person may appear under several headings), then fills ``research_areas`` for
    any matching spec that has none. One fetch per department: refresh-safe, no
    per-profile crawl. ``key`` is "slug" (matched against each spec's profile
    URL) or "name"; ``item_re`` needs named groups ``key`` and ``areas``.
    """
    import html as _html

    cfg = dept.get("research_join")
    if not cfg:
        return
    try:
        import requests

        from .ucb_common import HEADERS
    except Exception:  # noqa: BLE001
        return
    key_kind = cfg.get("key", "slug")

    def _norm(raw: str) -> str:
        if key_kind == "email":
            # HR/export feeds keyed by work email — the one identifier both
            # sides carry verbatim (UCSD Math's export feed).
            return (raw or "").strip().lower()
        if key_kind != "name":
            return _join_slug(raw)
        # Order-insensitive name key: aggregators often list "Last, First"
        # while the roster spec holds "First Last" — sorting the tokens makes
        # both hash to the same key. Single-letter tokens (middle initials,
        # present on one side only) are dropped for the same reason.
        toks = [t for t in re.findall(r"[a-z]+", _html.unescape(raw or "").lower())
                if len(t) > 1]
        return "".join(sorted(toks))

    mapping: dict[str, list[str]] = {}
    url, next_re = cfg["url"], cfg.get("next_re")
    for _hop in range(cfg.get("max_pages", 12)):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            page = resp.text
        except Exception:  # noqa: BLE001
            break
        for m in re.finditer(cfg["item_re"], page, re.I | re.S):
            gd = m.groupdict()
            key = _norm(gd.get("key", ""))
            areas = _html.unescape(re.sub(
                r"\s+", " ", _HTML_TAG_RE.sub(" ", _BR_RE.sub("; ", gd.get("areas", "") or "")))).strip()
            if key and areas:
                mapping.setdefault(key, []).append(areas)
        # Paginated aggregators (Drupal JSON:API "links.next") expose the next
        # page's URL in the body; single-page joins simply have no next_re.
        if not next_re:
            break
        nm = re.search(next_re, page)
        if not nm:
            break
        url = (nm.group(1).encode().decode("unicode_escape")
               .replace("\\/", "/").replace("&amp;", "&"))
    if not mapping:
        return
    for sp in specs:
        if sp.get("research_areas") or sp.get("keywords"):
            continue
        raw = {"name": sp.get("name", ""), "email": sp.get("email", "")}.get(
            key_kind, sp.get("url", ""))
        key = _norm(raw)
        if key and key in mapping:
            sp["research_areas"] = "; ".join(mapping[key])


# ---------------------------------------------------------------------------
# Purdue College of Agriculture directory API (deep mode, lazy HTTP deps)
# ---------------------------------------------------------------------------
#
# Purdue's College of Agriculture serves every department's directory from one
# React SPA backed by a public POST endpoint that returns the whole college's
# roster as structured JSON. A department config opts in with a ``coa_api`` block:
#
#     "coa_api": {"dept_id": 10}          # department id from the ListDepartment API
#
# One POST returns all ~2100 CoA people; the roster is cached per organization
# (all nine departments share it) and filtered to the department's Faculty-
# classified members client-side — no server-side department filter exists. Names
# are pre-split (FirstName/LastName), the public email + rank ride each record, and
# the per-person profile page is ``ag.purdue.edu/directory/<alias>``. A ladder gate
# keeps professorial faculty (the "Faculty" classification also carries the odd
# extension/administrative title).

_COA_BASE = "https://ag.purdue.edu"
_COA_LADDER = {"require": r"\bprof",
               "drop": r"\bemerit|\badjunct|\bvisiting|\bcourtesy|\blecturer|\binstructor|\bpostdoc"}
_COA_ROSTER_CACHE: dict[str, list] = {}


def _coa_roster(org: str) -> list:
    """Fetch (and cache per org) the full College of Agriculture roster."""
    if org in _COA_ROSTER_CACHE:
        return _COA_ROSTER_CACHE[org]
    try:
        import requests

        from .ucb_common import HEADERS
    except Exception:  # noqa: BLE001
        return []
    rows: list = []
    try:
        resp = requests.post(
            f"{_COA_BASE}/api/pi/2021/api/Directory/ListStaffDirectory",
            # The API 500s on the default Accept: text/html — force JSON.
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            data={"organization": org, "page": 1, "pageSize": 5000}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and isinstance(data.get("Data"), list):
            rows = data["Data"]
    except Exception as e:  # noqa: BLE001 — degrade to [] like fetch_soup
        logger.warning("faculty_graph: CoA roster fetch failed for %s: %s", org, e)
    _COA_ROSTER_CACHE[org] = rows
    return rows


def _fetch_coa_api(dept: dict) -> list[dict]:
    """Best-effort Purdue College of Agriculture fetch (opt-in via ``coa_api``).

    Filters the cached college roster to this department's Faculty-classified
    members and lands them name + rank + public email + profile URL.
    """
    cfg = dept.get("coa_api")
    if not cfg:
        return []
    org = cfg.get("organization", "CoA")
    dept_id = cfg.get("dept_id")
    lf = cfg.get("ladder_filter", _COA_LADDER)
    specs: list[dict] = []
    for rec in _coa_roster(org):
        if not isinstance(rec, dict):
            continue
        # Keep only records with a Faculty-classified membership in this dept.
        if not any(isinstance(d, dict) and d.get("Id") == dept_id
                   and (d.get("ClassificationId") == 4
                        or d.get("classification") == "Faculty")
                   for d in (rec.get("DepartmentList") or [])):
            continue
        name = " ".join(p for p in ((rec.get("FirstName") or "").strip(),
                                     (rec.get("LastName") or "").strip()) if p)
        if not name:
            continue
        title = _wp_text(rec.get("Title") or "") or "Professor"
        if not _passes_ladder(title, lf):
            continue
        alias = (rec.get("stralias") or "").strip()
        url = f"{_COA_BASE}/directory/{alias}" if alias else ""
        email = (rec.get("Email") or "").strip() or None
        specs.append(faculty(name, title=title, url=url, email=email))
    return specs


# ---------------------------------------------------------------------------
# Purdue Polytechnic Institute directory (Drupal JSON:API, deep mode)
# ---------------------------------------------------------------------------
#
# Purdue Polytechnic serves every school's directory from one Drupal JSON:API
# feed: ``node--directory`` (a department page) -> field_directory_section
# (paragraphs) -> field_person (``user--user`` entities) -> field_research_interests
# (taxonomy terms). A department config opts in with a ``poly_api`` block:
#
#     "poly_api": {"node_title": "SOET Directory"}
#
# One include-expanded request returns every school; the feed is cached and the
# target department located by its node title, then its people resolved through the
# relationship chain. Users carry display_name + field_job_title + public ``mail`` +
# a ``/profile`` path + research-interest terms, so records land emailed + titled +
# keyworded. A ladder gate keeps professorial faculty.

_POLY_BASE = "https://polytechnic.purdue.edu"
_POLY_URL = (_POLY_BASE + "/jsonapi/node/directory"
             "?include=field_directory_section.field_person,"
             "field_directory_section.field_person.field_research_interests")
_POLY_LADDER = {"require": r"\bprofessor\b",
                "drop": r"\bemerit|\badjunct|\bvisiting|\blecturer|\binstructor"}
_POLY_FEED_CACHE: dict = {}


def _poly_feed() -> dict:
    """Fetch (and cache) the Polytechnic JSON:API directory feed."""
    if "d" in _POLY_FEED_CACHE:
        return _POLY_FEED_CACHE["d"]
    data: dict = {}
    try:
        import requests

        from .ucb_common import HEADERS
        resp = requests.get(_POLY_URL, headers={**HEADERS, "Accept": "application/vnd.api+json"},
                            timeout=45)
        resp.raise_for_status()
        j = resp.json()
        if isinstance(j, dict):
            data = j
    except Exception as e:  # noqa: BLE001 — degrade to {} like fetch_soup
        logger.warning("faculty_graph: Polytechnic feed fetch failed: %s", e)
    _POLY_FEED_CACHE["d"] = data
    return data


def _fetch_poly_jsonapi(dept: dict) -> list[dict]:
    """Best-effort Purdue Polytechnic fetch (opt-in via ``poly_api``).

    Locates the department's ``node--directory`` by title and resolves its people
    through field_directory_section -> field_person, landing them name + rank +
    public email + profile URL + research-interest keywords.
    """
    cfg = dept.get("poly_api")
    if not cfg:
        return []
    feed = _poly_feed()
    data = feed.get("data") or []
    if not data:
        return []
    lut = {(o.get("type"), o.get("id")): o
           for o in (feed.get("included") or []) if isinstance(o, dict)}

    def rel(obj, field):
        r = (obj.get("relationships", {}).get(field, {}) or {}).get("data")
        return (r if isinstance(r, list) else [r]) if r else []

    node = next((n for n in data if isinstance(n, dict)
                 and n.get("attributes", {}).get("title") == cfg.get("node_title")), None)
    if node is None:
        return []
    lf = cfg.get("ladder_filter", _POLY_LADDER)
    specs: list[dict] = []
    seen: set = set()
    for sec in rel(node, "field_directory_section"):
        para = lut.get((sec.get("type"), sec.get("id")))
        if not para:
            continue
        for pu in rel(para, "field_person"):
            u = lut.get((pu.get("type"), pu.get("id")))
            if not u or u.get("id") in seen:
                continue
            seen.add(u.get("id"))
            a = u.get("attributes", {})
            name = (a.get("display_name")
                    or " ".join(p for p in ((a.get("field_first_name") or "").strip(),
                                            (a.get("field_last_name") or "").strip()) if p))
            if not name:
                continue
            title = _wp_text(a.get("field_job_title") or "") or "Professor"
            if not _passes_ladder(title, lf):
                continue
            alias = (a.get("path") or {}).get("alias") or ""
            url = f"{_POLY_BASE}{alias}" if alias else ""
            email = (a.get("mail") or "").strip() or None
            kws: list[str] = []
            for t in rel(u, "field_research_interests"):
                term = lut.get((t.get("type"), t.get("id")))
                nm = term.get("attributes", {}).get("name") if term else None
                if nm:
                    kws.append(nm)
            specs.append(faculty(name, title=title, url=url, email=email,
                                 keywords=list(dict.fromkeys(kws))[:8]))
    return specs


# ---------------------------------------------------------------------------
# JHU Krieger central faculty directory (Cloudflare-walled TablePress, deep mode)
# ---------------------------------------------------------------------------
#
# Johns Hopkins' Krieger School serves its entire faculty from ONE TablePress
# table (``#tablepress-54`` at krieger.jhu.edu/people/faculty-directory/) — four
# columns: Name ("Last, First"), Department, Title, Email (public mailto), ~836
# rows all emailed. The page (and every KSAS dept subdomain) sits behind
# Cloudflare, and DataTables detaches off-page rows from the DOM, so neither a
# plain request nor the generic render+_parse_cards path can read it. A HEADLESS
# Chromium session clears the Cloudflare JS challenge (verified) and the
# DataTables JS API hands back all rows. A department config opts in with:
#
#     "krieger_table": {"department": "<exact Department-column string>",
#                       "ladder_filter": {"require": ..., "drop": ...}}
#
# The table is fetched ONCE per refresh (cached) and sliced for every KSAS dept.
# HEADLESS ONLY — never a visible/headful browser on a user machine.

_KRIEGER_URL = "https://krieger.jhu.edu/people/faculty-directory/"
_KRIEGER_CACHE: dict = {}


def _krieger_rows() -> list:
    """Fetch (and cache) all Krieger directory rows via headless Chromium + the
    DataTables JS API. Each row is a list of 4 cell-HTML strings."""
    if "rows" in _KRIEGER_CACHE:
        return _KRIEGER_CACHE["rows"]
    rows: list = []
    try:
        from playwright.sync_api import sync_playwright

        from .ucb_common import HEADERS
    except ImportError:
        _KRIEGER_CACHE["rows"] = []
        return []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)  # headless ONLY
            try:
                page = browser.new_context(user_agent=HEADERS["User-Agent"]).new_page()
                try:
                    page.goto(_KRIEGER_URL, wait_until="domcontentloaded", timeout=60000)
                except Exception:  # noqa: BLE001 — CF reload aborts the first goto
                    pass
                for _ in range(20):  # poll until the Cloudflare interstitial clears
                    title = page.title()
                    if title.strip() and "just a moment" not in title.lower():
                        break
                    page.wait_for_timeout(2000)
                rows = page.evaluate(
                    "() => (window.jQuery && jQuery('#tablepress-54').length)"
                    " ? jQuery('#tablepress-54').DataTable().rows().data().toArray() : []")
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001 — degrade to [] like fetch_soup
        logger.warning("faculty_graph: Krieger directory fetch failed: %s", e)
    _KRIEGER_CACHE["rows"] = rows if isinstance(rows, list) else []
    return _KRIEGER_CACHE["rows"]


def _fetch_krieger_table(dept: dict) -> list[dict]:
    """Best-effort JHU Krieger fetch (opt-in via ``krieger_table``): filter the
    cached central table to this department and land name + rank + email."""
    cfg = dept.get("krieger_table")
    if not cfg:
        return []
    import html as _html
    want = cfg.get("department", "")
    lf = cfg.get("ladder_filter")

    def cell(h: str) -> str:
        return _html.unescape(_HTML_TAG_RE.sub(" ", h or "")).strip()

    specs: list[dict] = []
    for row in _krieger_rows():
        if not isinstance(row, list | tuple) or len(row) < 4:
            continue
        if cell(row[1]) != want:
            continue
        name = _flip_name(re.sub(r"\s+", " ", cell(row[0])))
        title = cell(row[2]) or "Professor"
        if not _passes_ladder(title, lf):
            continue
        email = _clean_email(row[3] or "") or _clean_email(cell(row[3]))
        specs.append(faculty(name, title=title, url=_KRIEGER_URL, email=email))
    return specs


_SITEMAP_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def _sitemap_collect(cfg: dict) -> list[str]:
    """Gather page URLs from a division's sitemap(s), following nested indexes.

    Many modern faculty directories are JS/search grids with no scrapeable
    listing, but the site's sitemap enumerates every ``/faculty/<slug>`` profile
    page. This walks the configured sitemap URLs (or a ``sitemap_pages`` template
    for paginated sitemaps), following nested ``<loc>``-of-sitemaps one level, and
    returns the page URLs matching ``include`` (minus ``exclude``). Cloudflare-
    walled sitemaps set ``render: True`` to fetch through the headless browser.

    Divisions with no XML sitemap but a rendered "all faculty" listing instead set
    ``list_pages`` (or ``list_pages_template`` for pagination): each HTML page is
    fetched (``list_render`` toggles headless) and its ``<a href>`` profile links
    harvested through the same ``include``/``exclude`` filter.
    """
    render = cfg.get("render", False)

    def fetch_xml(u: str) -> str:
        if render:
            s = _render_soup(u, wait_until="domcontentloaded", settle_ms=2500)
            return str(s) if s is not None else ""
        try:
            from .ucb_common import fetch_soup
            s = fetch_soup(u)
            return str(s) if s is not None else ""
        except Exception:  # noqa: BLE001
            return ""

    maps = list(cfg.get("sitemaps", []))
    pages = cfg.get("sitemap_pages")
    if pages:
        tmpl, start, end = pages
        maps += [tmpl.format(n=n) for n in range(start, end + 1)]
    include = re.compile(cfg["include"], re.I) if cfg.get("include") else None
    exclude = re.compile(cfg["exclude"], re.I) if cfg.get("exclude") else None
    urls: list[str] = []
    # HTML listing pages: harvest <a href> profile links directly (for divisions
    # with no XML sitemap but a rendered "all faculty" page — NU Law, JHU Education).
    list_pages = cfg.get("list_pages", [])
    lp_pages = cfg.get("list_pages_template")
    if lp_pages:
        tmpl, start, end = lp_pages
        list_pages = list(list_pages) + [tmpl.format(n=n) for n in range(start, end + 1)]
    if list_pages:
        from urllib.parse import urljoin
        lp_render = cfg.get("list_render", render)
        for lp in list_pages:
            if lp_render:
                s = _render_soup(lp, wait_until="domcontentloaded", settle_ms=cfg.get("list_settle", 5000))
            else:
                try:
                    from .ucb_common import fetch_soup
                    s = fetch_soup(lp)
                except Exception:  # noqa: BLE001
                    s = None
            if s is None:
                continue
            for a in s.select("a[href]"):
                full = urljoin(lp, a.get("href", ""))
                full = full.split("#")[0]
                if include and not include.search(full):
                    continue
                if exclude and exclude.search(full):
                    continue
                urls.append(full)
    seen_maps: set[str] = set()
    queue = list(maps)
    while queue and len(seen_maps) < 60:
        m = queue.pop(0)
        if m in seen_maps:
            continue
        seen_maps.add(m)
        for loc in _SITEMAP_LOC_RE.findall(fetch_xml(m)):
            if loc.endswith((".xml", ".xml.gz")):
                # nested sitemap index — follow only obviously-relevant children
                if include and include.search(loc):
                    queue.append(loc)
                continue
            if include and not include.search(loc):
                continue
            if exclude and exclude.search(loc):
                continue
            urls.append(loc)
    # de-dupe, preserve order
    out, seen = [], set()
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _fetch_sitemap_directory(dept: dict) -> list[dict]:
    """Best-effort fetch (opt-in via ``sitemap``): enumerate profile URLs from the
    site's sitemap, then fetch each profile and extract name / rank / email.

    The escape hatch for JS/search-grid directories (Medill, JHU Carey) whose
    listing exposes no cards but whose sitemap lists every profile page. Each
    profile is fetched (curl, or headless when ``profile_render``) and parsed with
    the ``selectors`` block (``name`` / ``title`` / ``email``); ``ladder_filter``
    gates on the parsed rank. ``cap`` bounds the profile fetches (a safety valve
    for very large directories); when it truncates, the drop is logged.
    """
    cfg = dept.get("sitemap")
    if not cfg:
        return []
    try:
        from .ucb_common import fetch_soup
    except Exception:  # noqa: BLE001
        return []
    urls = _sitemap_collect(cfg)
    if not urls:
        logger.info("faculty_graph: sitemap yielded no profile URLs for %s", dept.get("short"))
        return []
    cap = cfg.get("cap")
    if cap and len(urls) > cap:
        logger.warning("faculty_graph: %s sitemap capped %d -> %d profiles (dropped %d)",
                        dept.get("short"), len(urls), cap, len(urls) - cap)
        urls = urls[:cap]
    sel = cfg.get("selectors", {})
    name_sel, title_sel, email_sel = sel.get("name"), sel.get("title"), sel.get("email")
    lf = cfg.get("ladder_filter")
    prof_render = cfg.get("profile_render", cfg.get("render", False))
    # A longer settle clears the tougher Cloudflare/Turnstile walls that a
    # datacenter IP (CI) hits — required for e.g. publichealth.jhu.edu profiles.
    settle = cfg.get("render_settle", 3500)
    import time
    throttle = cfg.get("throttle", 0.0)
    specs: list[dict] = []
    for u in urls:
        soup = (_render_soup(u, expect_selector=name_sel, settle_ms=settle)
                if prof_render else fetch_soup(u))
        if soup is None:
            continue
        n_el = soup.select_one(name_sel) if name_sel else None
        name = re.sub(r"\s+", " ", n_el.get_text(" ", strip=True)).strip() if n_el else ""
        if not name:
            continue
        title = "Professor"
        if title_sel:
            t_el = soup.select_one(title_sel)
            if t_el and t_el.get_text(strip=True):
                title = t_el.get_text(" ", strip=True)
        if not _passes_ladder(title, lf):
            continue
        email = None
        if email_sel:
            e_el = soup.select_one(email_sel)
            if e_el is not None:
                raw = e_el.get("href") if e_el.has_attr("href") else e_el.get_text(" ", strip=True)
                email = _clean_email(raw)
        specs.append(faculty(name, title=title, url=u, email=email))
        if throttle:
            time.sleep(throttle)
    return specs


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
                               + _fetch_seas_ajax(dept) + _fetch_futurevu_ajax(dept)
                               + _fetch_worx_ajax(dept)
                               + _fetch_algolia(dept)
                               + _fetch_faculty180(dept) + _fetch_cola(dept)
                               + _fetch_json_dir(dept) + _fetch_coa_api(dept)
                               + _fetch_krieger_table(dept)
                               + _fetch_poly_jsonapi(dept)
                               + _fetch_sitemap_directory(dept)):
                key = (discovered.get("url") or "").strip().lower()
                if key and key not in listing_urls and key in seen_urls_local:
                    continue
                if key and key not in listing_urls:
                    seen_urls_local.add(key)
                specs.append(discovered)
            _apply_research_join(dept, specs)
            # Dept-level profile_enrich serves the non-scrape sources too — a
            # json_dir roster (UCSD Physics) has no scrape block to hang the
            # pass on, but its people still have profile endpoints to follow.
            specs = _apply_profile_enrich(specs, dept.get("profile_enrich"))
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
    from .uiuc_faculty import _carry_forward_enrichment

    for opp in new_opps:
        if opp["id"] in index:
            cur = index[opp["id"]]
            opp["metadata"]["first_seen_at"] = cur.get(
                "metadata", {}).get("first_seen_at", opp["metadata"]["first_seen_at"])
            # Don't let a broad/empty re-scrape clobber committed OpenAlex/LLM
            # enrichment on the same stable id.
            _carry_forward_enrichment(cur, opp)
            cur.update(opp)
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
