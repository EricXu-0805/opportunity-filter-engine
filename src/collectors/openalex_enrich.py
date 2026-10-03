"""Run-once scholarly-record enrichment of fieldless faculty via OpenAlex.

For faculty whose university directory exposes no research field (and whose
profile prose the LLM pass could not mine), recover research areas from their
*publication record* using the free OpenAlex API (author -> topics). This is the
scalable, no-block equivalent of "check their Google Scholar" — Google Scholar
itself bot-blocks at scale; OpenAlex is an open API with the same publication
signal.

Accuracy is institution-gated to avoid wrong-person matches: a candidate author
is accepted ONLY if the target school's OpenAlex institution id appears in the
author's affiliation history AND the author's name shares the faculty member's
surname. Among accepted candidates the one whose publishing history is most AT
that school wins (see ``_institution_share`` — "most works wins" handed a
conflated record's more prolific stranger to the wrong person); if the search
returns no institution-affiliated match, the faculty member stays broad
("better broad than a different person's research").

Run ONCE like the other enrichment passes; updates-only apply, richer-dedup
protects it on refresh -> zero weekly cost.

    python -m src.collectors.openalex_enrich harvest uw,ucla,... --out oa.json
    python -m src.collectors.openalex_enrich apply oa.json

``harvest`` buys one name search per professor (10 credits each, ~85 people a
day on the free tier). ``roster`` buys the school's whole author list by the
page instead (1 credit per 100 authors) and matches locally, which is the same
answer roughly 200x cheaper — a school a minute rather than a school a month:

    python -m src.collectors.openalex_enrich roster jhu,cincinnati --out oa.json
    python -m src.collectors.openalex_enrich apply oa.json

A second pass fetches each matched author's most recent publications (title +
year only) into ``metadata.recent_works`` so cold emails can cite a real,
current paper. Same institution/surname/field gating; run-once, carried
forward on re-scrape by ``_carry_forward_enrichment``:

    python -m src.collectors.openalex_enrich works princeton,stanford --out works.json
    python -m src.collectors.openalex_enrich apply-works works.json

``works`` buys one request per professor and resolves each author through the
12-credit search, which is why it never ran at corpus scale and 15,903 faculty
hold papers no serving path may cite. ``works-roster`` takes the author id from
the cached institution roster (free) and buys the papers ``_WORKS_BATCH`` people
to a request:

    python -m src.collectors.openalex_enrich works-roster jhu,cincinnati \
        --roster-dir data/openalex_rosters --out works.json
    python -m src.collectors.openalex_enrich apply-works works.json

Both works harvests (``works`` and ``works-roster``, through ``_usable_works``)
keep a paper only when the author's own authorship on it places them at the
school, or names no affiliation at all, which on a measured sample was mostly
their own work (``_affiliation_admits``). The research-snapshot path
(``refresh-research``) does not run this check yet.

``recheck-works`` runs the check over the papers verified records already
hold. It prints its credit estimate before the first request, stops at
``--max-requests`` or when x-ratelimit-remaining drops below
``--min-remaining``, and writes only a report. ``apply-recheck`` writes a
reviewed report into the corpus and makes no request. Start from a work file
assembled from the current main, because ``split`` rewrites each touched
school's shard from whatever the work file holds:

    python scripts/shard_corpus.py assemble --force
    python -m src.collectors.openalex_enrich recheck-works --schools uiuc \
        --max-requests 200 --report recheck-uiuc.json
    python -m src.collectors.openalex_enrich apply-recheck recheck-uiuc.json
    python scripts/shard_corpus.py split --only-shards uiuc
"""
from __future__ import annotations

import collections
import json
import logging
import math
import os
import re
import sys
import time
import unicodedata
from email.utils import parsedate_to_datetime
from typing import NamedTuple

import requests

from ..evidence import stamp_inferred
from ..publication_trust import (
    CURRENT_WORKS_GATE as _WORKS_GATE,
)
from ..publication_trust import (
    NAME_MATCH as ATTRIBUTION_NAME_MATCH,
)
from ..publication_trust import (
    VERIFIED_AUTHOR_ID as ATTRIBUTION_VERIFIED,
)
from ..publication_trust import (
    is_pending_remediation,
    record_works_gate,
    works_are_current_gate,
    works_are_verified,
)
from ..research_context import (
    MAX_RESEARCH_ABSTRACT,
    MAX_RESEARCH_TITLE,
    SCHOOL_INST,
    canonical_doi,
    normalized_openalex_id,
    normalized_source_url,
    validate_research_snapshot,
)
from .atomic_json import atomic_write_json
from .ucb_common import PROCESSED_FILE

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "ofe-research/1.0 (mailto:eric.guoyi.xu@gmail.com)"}
_API = "https://api.openalex.org/authors"
_WORKS_API = "https://api.openalex.org/works"
# 86MB corpus in a 2GB-RAM backend: hard-cap what apply may store per faculty.
_MAX_WORKS = 3
_TITLE_CAP = 200

# metadata.publication_attribution_status — stamped by apply_works WITH the
# works it describes, never retro-labeled onto works some other pass stored.
# verified_author_id: the mapping entry carries the OpenAlex author id the
# works were fetched through (the gated _match_author resolution). name_match:
# the entry is a bare title list (the pre-provenance WORKS_STORE format) whose
# only person linkage is the name-derived key. Records enriched before this
# stamp existed simply lack the field. The value literals live in
# src.publication_trust (the shared fail-closed gate every serving path uses,
# imported above as ATTRIBUTION_VERIFIED / ATTRIBUTION_NAME_MATCH); downstream
# treats anything but verified_author_id as unverified and excludes it from
# professor-specific output.

# A book's front matter is indexed as a work with the section as its title, so
# OpenAlex hands back "Introduction", "Preface", "Index" among a humanities
# professor's recent publications and a cold email offers to discuss them.
# Measured on the corpus: 63 of 18,699 citable papers, across 57 professors.
#
# Only unambiguous section names. "Methods", "Results", "Discussion",
# "Summary" and "Abstract" are deliberately absent: they name real papers in
# some fields, and dropping a real one is the worse error here.
_FRONT_MATTER = frozenset({
    "introduction", "conclusion", "conclusions", "preface", "foreword",
    "afterword", "epilogue", "prologue", "dedication", "index", "author index",
    "subject index", "contents", "table of contents", "acknowledgements",
    "acknowledgments", "bibliography", "references", "appendix", "glossary",
    "abbreviations", "notes", "editorial", "book review", "book reviews",
    "reviews", "comment", "erratum", "errata", "corrigendum", "front matter",
    "back matter", "frontmatter", "title page", "copyright", "contributors",
    "list of contributors", "credits", "terms", "toolkits", "case studies",
    "about",
})


# A correction notice IS the professor's own work, but a letter opening "your
# recent paper 'Corrigendum to ...'" reads as a machine that cannot tell a paper
# from its erratum. The whole-title check below catches a bare "Erratum" and
# missed every real one, because a real one carries the corrected paper's title
# after it. 421 records hold one; exactly 1 has nothing else to cite.
_CORRECTION_NOTICE_RE = re.compile(
    r"^\s*(?:retracted(?:\s+article)?|withdrawn|corrigend(?:um|a)|errat(?:um|a)|"
    r"(?:author|publisher)?\s*correction|editorial expression of concern)"
    r"\s*(?:[:.\u2014-]|\bto\b)",
    re.IGNORECASE,
)


def _is_front_matter(title: str) -> bool:
    if _CORRECTION_NOTICE_RE.match(title or ""):
        return True
    return " ".join(re.sub(r"[^a-z ]", " ", (title or "").lower()).split()) in _FRONT_MATTER


def _given_name_variant(a: str, b: str) -> bool:
    """Whether two scraped names are the same person under a different spelling.

    A nickname or a fuller given name is the same human — Dan/Daniel
    Rubenstein, Badri/Badrinath Roysam, Edward J./Edward Joseph Bernacki — and
    a directory that lists someone twice across a joint appointment is not a
    collision. Requires the surname to match and one given name to be a prefix
    of the other.
    """
    def parts(name: str) -> list[str]:
        return [w.lower() for w in re.split(r"\W+", re.sub(r"\([^)]*\)", " ", name or "")) if w]

    pa, pb = parts(a), parts(b)
    if not pa or not pb or pa[-1] != pb[-1]:
        return False
    return pa[0].startswith(pb[0]) or pb[0].startswith(pa[0])


def ambiguous_author_ids(records: list[dict]) -> set[str]:
    """OpenAlex author ids stamped on people who are not the same person.

    OpenAlex returns one author entity for names it could not separate, and the
    result is three different Smiths in three departments each told the same
    papers are theirs. We cannot tell which one is right, so every record in
    such a group must lose its attribution — fail closed.
    """
    by_id: dict[str, list[str]] = {}
    for record in records:
        author_id = (record.get("metadata") or {}).get("publication_author_id")
        if author_id:
            by_id.setdefault(author_id, []).append(record.get("pi_name") or "")
    return {
        author_id
        for author_id, names in by_id.items()
        if any(not _given_name_variant(names[0], other) for other in names[1:])
    }


# The committed "works library": the durable url -> [{title, year}] master record
# of every OpenAlex paper we ever paid the metered API to harvest. recent_works is
# the ONE faculty field no directory scrape reproduces, so this store is how we
# re-derive it for free after any full corpus rebuild — and where future harvests
# accumulate. Kept out of the corpus so the metered data survives independently.
WORKS_STORE = os.path.join(os.path.dirname(PROCESSED_FILE), "faculty_works.json")
# Over-fetch so the per-work field filter (drops OpenAlex same-name conflation
# outliers) still leaves _MAX_WORKS survivors in the common case.
_WORKS_FETCH = 10
# One /works request serves a whole batch of authors (see ``works_for_authors``).
# 25 keeps the OR filter well inside OpenAlex's length limits, and two pages of
# 200 leave room for a prolific co-author to crowd the newest-first ordering.
_WORKS_BATCH = 25
_WORKS_PAGE_SIZE = 200
# Rounds per batch, each dropping the authors already served. Four covers the
# observed skew (one UCSC author took 201 of a 200-work page on his own) while
# capping a pathological batch at four credits instead of twenty-five.
_WORKS_ROUNDS = 4
# Raw works to collect per author before calling them served: the per-work
# field gate discards some, so asking for exactly `want` would under-serve.
_WORKS_SLACK = 4

_MIN_WORKS = 5
_TRAIL = re.compile(r"\s+(research|studies|techniques|applications|methods)$", re.I)

# Wrong-person guard: a same-name author at the SAME institution but in a
# different field (e.g. "Michael West" the EE prof vs the seismologist) passes
# the institution+surname check. So also require at least one of the matched
# author's topic FIELDS (OpenAlex level-1 field) to be compatible with the
# faculty member's department. Each entry: a department-name substring -> the set
# of acceptable OpenAlex field display_names. Generous (adjacent fields included)
# to avoid rejecting interdisciplinary faculty; a department that matches nothing
# here is left ungated (accepted) since we cannot judge compatibility.
_ENG = {"Engineering", "Computer Science", "Materials Science", "Physics and Astronomy",
        "Mathematics", "Chemistry", "Chemical Engineering", "Energy", "Environmental Science"}
_LIFE = {"Biochemistry, Genetics and Molecular Biology", "Agricultural and Biological Sciences",
         "Immunology and Microbiology", "Neuroscience", "Medicine", "Environmental Science",
         "Pharmacology, Toxicology and Pharmaceutics", "Health Professions", "Chemistry"}
_HEALTH = {"Medicine", "Nursing", "Pharmacology, Toxicology and Pharmaceutics", "Health Professions",
           "Biochemistry, Genetics and Molecular Biology", "Immunology and Microbiology", "Neuroscience",
           "Psychology"}
_SOC = {"Social Sciences", "Arts and Humanities", "Psychology", "Economics, Econometrics and Finance",
        "Business, Management and Accounting", "Decision Sciences"}
_DEPT_FIELDS: tuple[tuple[str, set[str]], ...] = (
    ("electric", _ENG), ("computer", _ENG), ("computing", _ENG), ("software", _ENG),
    ("mechanic", _ENG), ("aero", _ENG), ("civil", _ENG | {"Earth and Planetary Sciences"}),
    ("industrial", _ENG | {"Business, Management and Accounting", "Decision Sciences"}),
    ("material", _ENG), ("nuclear", _ENG), ("bioeng", _ENG | _LIFE), ("biomedical", _ENG | _LIFE),
    ("chemical eng", _ENG), ("math", {"Mathematics", "Computer Science", "Decision Sciences",
                                      "Economics, Econometrics and Finance", "Physics and Astronomy"}),
    ("statistic", {"Mathematics", "Computer Science", "Decision Sciences",
                   "Economics, Econometrics and Finance"}),
    ("physic", {"Physics and Astronomy", "Materials Science", "Mathematics", "Engineering"}),
    ("astro", {"Physics and Astronomy", "Earth and Planetary Sciences", "Mathematics"}),
    ("chemistr", {"Chemistry", "Materials Science", "Chemical Engineering",
                  "Biochemistry, Genetics and Molecular Biology"}),
    ("biochem", _LIFE), ("molecular", _LIFE), ("microbio", _LIFE), ("immuno", _LIFE),
    ("neuro", _LIFE | {"Psychology"}), ("ecolog", _LIFE), ("genetic", _LIFE), ("plant", _LIFE),
    ("biolog", _LIFE), ("zoolog", _LIFE), ("wildlife", _LIFE), ("forest", _LIFE),
    ("earth", {"Earth and Planetary Sciences", "Environmental Science", "Physics and Astronomy"}),
    ("planet", {"Earth and Planetary Sciences", "Physics and Astronomy"}),
    ("atmospher", {"Earth and Planetary Sciences", "Environmental Science", "Physics and Astronomy"}),
    ("ocean", {"Earth and Planetary Sciences", "Environmental Science"}),
    ("geo", {"Earth and Planetary Sciences", "Environmental Science", "Social Sciences"}),
    ("econ", {"Economics, Econometrics and Finance", "Social Sciences",
              "Business, Management and Accounting", "Mathematics", "Decision Sciences"}),
    ("business", _SOC), ("management", _SOC), ("marketing", _SOC), ("finance", _SOC),
    ("account", _SOC), ("nursing", _HEALTH), ("medic", _HEALTH), ("pharm", _HEALTH),
    ("health", _HEALTH), ("clinical", _HEALTH), ("psycholog", {"Psychology", "Neuroscience",
                                                               "Social Sciences", "Medicine"}),
    ("socio", _SOC), ("politic", _SOC), ("anthropo", _SOC), ("communicat", _SOC),
    ("education", _SOC), ("law", _SOC), ("public", _SOC | {"Medicine"}), ("urban", _SOC | {"Engineering"}),
    # Added once the "department" collision above stopped answering for them,
    # each carrying enough faculty to deserve a real family rather than none:
    # linguistics 615, animal science 368, government 318, entomology 249,
    # kinesiology 181, pathology 124.
    ("entomol", _LIFE), ("animal", _LIFE), ("kinesio", _HEALTH | {"Psychology"}),
    ("patholog", _HEALTH), ("government", _SOC),
    ("linguist", {"Arts and Humanities", "Social Sciences", "Psychology",
                  "Computer Science"}),
    ("english", {"Arts and Humanities", "Social Sciences"}),
    ("history", {"Arts and Humanities", "Social Sciences"}),
    ("philosoph", {"Arts and Humanities", "Social Sciences"}),
    ("art", {"Arts and Humanities", "Social Sciences"}),
    ("music", {"Arts and Humanities", "Social Sciences"}),
    ("language", {"Arts and Humanities", "Social Sciences"}),
    ("literatur", {"Arts and Humanities", "Social Sciences"}),
    ("classic", {"Arts and Humanities"}), ("religio", {"Arts and Humanities", "Social Sciences"}),
    ("theatre", {"Arts and Humanities"}), ("drama", {"Arts and Humanities"}),
    ("dance", {"Arts and Humanities"}), ("media", {"Arts and Humanities", "Social Sciences"}),
    ("journalism", {"Arts and Humanities", "Social Sciences"}),
    ("architect", {"Arts and Humanities", "Engineering", "Social Sciences"}),
    # The names below matched no key above, so the wrong-person check was
    # skipped entirely for 8,583 of 70,631 enrichment targets (12.2%) — the
    # gate reads as a guard but abstains for one target in eight. None of them
    # is exotic: the single largest was "School of Engineering" (400 people),
    # because every engineering key here is a SUB-discipline and plain
    # "engineer" was never one. Ordered against the real corpus, most specific
    # first: "engineer" precedes "environment" so a school of sustainable
    # engineering is judged as engineering, and "studies" is last because it is
    # a catch-all that must not answer for Environmental Studies.
    #
    # A wrong mapping here costs coverage, never truth: too narrow a family
    # rejects the correct author and the professor stays unenriched, which is
    # this module's stated preference ("better broad than a different person's
    # research"). So each is the generous union of the fields its faculty
    # plausibly publish in.
    ("engineer", _ENG),
    ("optic", {"Physics and Astronomy", "Engineering", "Materials Science",
               "Computer Science"}),
    ("agricultur", _LIFE), ("agronom", _LIFE), ("horticultur", _LIFE),
    ("crop", _LIFE), ("soil", _LIFE | {"Earth and Planetary Sciences"}),
    ("poultry", _LIFE), ("veterinar", _LIFE | _HEALTH), ("fisheries", _LIFE),
    ("food", _LIFE | {"Chemistry"}), ("nutrition", _LIFE | _HEALTH),
    ("life scien", _LIFE),
    ("physiolog", _LIFE | _HEALTH), ("optometr", _HEALTH),
    ("epidemiolog", _HEALTH | {"Social Sciences"}), ("infectious", _LIFE | _HEALTH),
    ("therapy", _HEALTH), ("gerontolog", _HEALTH | _SOC),
    ("cognitive", {"Psychology", "Neuroscience", "Computer Science",
                   "Social Sciences", "Medicine", "Arts and Humanities"}),
    ("neural", _LIFE | {"Psychology", "Computer Science"}),
    ("informatic", _ENG | {"Decision Sciences"}),
    ("data scien", _ENG | {"Decision Sciences"}),
    # iSchools genuinely straddle computing and the social study of it, so the
    # union is wide on purpose; it still excludes a chemist or a physiologist.
    ("information", _ENG | _SOC),
    ("environment", {"Environmental Science", "Earth and Planetary Sciences",
                     "Agricultural and Biological Sciences", "Engineering",
                     "Social Sciences", "Chemistry"}),
    ("sustainab", {"Environmental Science", "Earth and Planetary Sciences",
                   "Agricultural and Biological Sciences", "Engineering",
                   "Social Sciences", "Energy"}),
    ("natural resource", _LIFE | {"Earth and Planetary Sciences", "Social Sciences"}),
    ("marine", {"Earth and Planetary Sciences", "Environmental Science",
                "Agricultural and Biological Sciences"}),
    ("design", {"Arts and Humanities", "Engineering", "Computer Science",
                "Social Sciences", "Materials Science"}),
    ("construction", _ENG | {"Social Sciences"}),
    ("planning", _SOC | {"Engineering", "Environmental Science"}),
    ("spanish", {"Arts and Humanities", "Social Sciences"}),
    ("portuguese", {"Arts and Humanities", "Social Sciences"}),
    ("french", {"Arts and Humanities", "Social Sciences"}),
    ("italian", {"Arts and Humanities", "Social Sciences"}),
    ("german", {"Arts and Humanities", "Social Sciences"}),
    ("romance", {"Arts and Humanities", "Social Sciences"}),
    ("hispanic", {"Arts and Humanities", "Social Sciences"}),
    ("theolog", {"Arts and Humanities", "Social Sciences"}),
    ("divinity", {"Arts and Humanities", "Social Sciences"}),
    ("writing", {"Arts and Humanities", "Social Sciences"}),
    ("rhetoric", {"Arts and Humanities", "Social Sciences"}),
    ("theater", {"Arts and Humanities"}),
    ("archaeolog", {"Arts and Humanities", "Social Sciences",
                    "Earth and Planetary Sciences"}),
    # Social work, human development, and global/international studies are
    # health-facing social science: measured against the cached rosters, _SOC
    # alone rejected Bridget Freisthler (182 works, Health Professions /
    # Psychology / Medicine) and six more correct people, because the majority
    # of their topics are clinical. Adding the health fields costs almost no
    # discriminating power — the wrong-person matches this gate exists to stop
    # were STEM twins (Ashleigh Jones -> "Alex K. Jones", 302 Computer Science
    # works), and Engineering, CS, Chemistry, Physics and Mathematics are still
    # out.
    ("social work", _SOC | _HEALTH),
    ("human development", _SOC | _HEALTH),
    ("global", _SOC | {"Environmental Science", "Medicine", "Health Professions"}),
    ("international", _SOC | {"Environmental Science", "Medicine", "Health Professions"}),
    ("criminolog", _SOC), ("social", _SOC), ("humanities", _SOC),
    ("teaching", _SOC), ("curriculum", _SOC),
    ("studies", _SOC | {"Medicine", "Health Professions"}),
)


# "dep-ART-ment". The table is scanned as substrings and "art" is one of its
# keys, so every department whose name missed every earlier key fell through to
# Arts and Humanities on the strength of the word "Department" alone — 13,755
# faculty corpus-wide. Music and Classics landed there by accident and were
# fine; Entomology, Animal Science, Kinesiology and Pathology were handed a
# field family none of their real topics belong to, so the majority-compatible
# gate in _match_author_query rejected the correct author every time and those
# faculty were silently never enriched. The word names the unit, never the
# discipline, so it cannot be evidence of either.
_DEPT_WORD_RE = re.compile(r"\bdepartments?\b")


def _dept_fields(dept: str) -> set[str] | None:
    d = _DEPT_WORD_RE.sub(" ", (dept or "").lower())
    for key, fields in _DEPT_FIELDS:
        if key in d:
            return fields
    return None


def _record_url(o: dict) -> str | None:
    return o.get("url") or o.get("source_url")


def _is_faculty(o: dict) -> bool:
    return bool(o.get("source_type") == "faculty_research" or o.get("pi_name"))


def _surname(name: str) -> str:
    toks = [t for t in re.split(r"\W+", (name or "").lower()) if len(t) > 1]
    return toks[-1] if toks else ""


def _title_key(title: str) -> str:
    """Dedup key for work titles. Journals republish preprints with punctuation
    and casing drift ("Older-Onset" vs "older onset"), so a lowercase-only key
    lets the same paper into a record twice; compare on alphanumerics only."""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _person_key(o: dict) -> str:
    """Harvest-store key for one faculty member. The URL alone is NOT unique:
    departments whose directories have no per-person pages give every professor
    the listing URL (430 JHU Krieger faculty share one), and a url-keyed store
    stamped a single person's papers onto all of them. Suffix the normalized
    name so each person keys their own harvest."""
    name = re.sub(r"[^a-z0-9]+", " ", (o.get("pi_name") or "").lower()).strip()
    return f"{_record_url(o)}#{name}"


def _shared_url_counts(opps: list[dict]) -> dict[str, int]:
    """How many faculty share each URL — bare-URL store entries (pre-composite-
    key harvests) are only safe to apply when exactly one faculty owns the URL."""
    counts: dict[str, int] = {}
    for o in opps:
        if _is_faculty(o) and o.get("pi_name"):
            u = _record_url(o)
            if u:
                counts[u] = counts.get(u, 0) + 1
    return counts


def _clean_topic(t: str) -> str:
    t = re.sub(r"\s+", " ", (t or "").strip())
    t = _TRAIL.sub("", t)  # drop a trailing generic noun ("... Research")
    # OpenAlex topic labels are sometimes comma/colon-joined compounds
    # ("galaxies: formation, evolution, phenomena"). A keyword must be a single
    # delimiter-free phrase — the faculty title renders keywords as a
    # comma-joined parenthetical, so an internal comma would shatter one area
    # into several false ones. Flatten separators to a single phrase.
    t = re.sub(r"\s*[,:;]\s*", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.lower()


_warned_429 = False


# Seconds to wait before confirming a 429 is budget exhaustion rather than a
# transient per-second rate limit. One retry after this pause distinguishes
# the two: a burst clears, an empty budget doesn't.
_RETRY_429_WAIT = 15.0


def _get(params: dict, url: str = _API, timeout: int = 20) -> dict:
    # OpenAlex metered its API in 2026, but the free tier is not zero: measured
    # 2026-08-27 with NO key, the response carries x-ratelimit-limit: 1000 and a
    # remaining counter that resets daily. A prepaid key (api_key query param)
    # only raises that ceiling.
    #
    # What the credits buy is NOT uniform, and the difference decides which
    # harvest is affordable:
    #
    #   /authors with `search=` (or a `display_name.search` filter)  10 credits
    #   /authors with pure filters + cursor paging (100 per page)     1 credit
    #   /works with a filter                                          1 credit
    #
    # So the per-person search path costs ~12 credits (~85 people/day), while
    # paging a whole institution's author roster costs 1 credit per 100 authors.
    # See ``harvest_openalex_roster``.
    global _warned_429
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        params = {**params, "api_key": key}
    seen_429 = False
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=timeout)
            if resp.status_code == 429:
                if not seen_429:
                    # Could be a transient per-second burst limit — pause once
                    # and retry before declaring the budget dead.
                    seen_429 = True
                    time.sleep(_RETRY_429_WAIT)
                    continue
                # Second 429 after the pause = budget exhaustion; it won't
                # clear within a retry loop. Set the flag the harvest loops
                # abort on, and warn once per process.
                if not _warned_429:
                    _warned_429 = True
                    logger.warning(
                        "OpenAlex returned 429 twice %ss apart (daily budget exhausted) — "
                        "harvest loops abort on this. Top up the prepaid key or retry "
                        "after the budget resets.", _RETRY_429_WAIT)
                return {}
            return resp.json()
        except Exception:
            time.sleep(1.2 * (attempt + 1))
    return {}


def _name_variants(name: str) -> list[str]:
    """Search queries to try in order: the directory name as-is, then a
    first+last simplification. Directories that print full legal names
    ("Iain Douglas Boyd") defeat OpenAlex full-text author search — the
    indexed form is "Iain D. Boyd", and the full form returns zero results —
    so a miss on the directory form retries without the middle tokens. Every
    candidate from the looser query still passes the same institution/surname/
    works/field gates, so it cannot admit a person the strict query would have
    rejected."""
    toks = (name or "").split()
    variants = [name]
    if len(toks) >= 3:
        simplified = f"{toks[0]} {toks[-1]}"
        if simplified.lower() != name.lower():
            variants.append(simplified)
    return variants


def _match_author(name: str, inst_id: str, dept: str = "") -> dict | None:
    """The confidently-matched OpenAlex author record for ``name`` at the
    institution, or None. Requires: surname match, the school's institution id
    in the author's affiliation history, works_count >= _MIN_WORKS, and — when
    the department maps to a field family — a majority of top topic fields
    compatible with it (rejects same-name same-institution wrong-field people).
    Tries the directory name first, then a first+last fallback (middle names
    break OpenAlex search); the gates apply identically to both."""
    surname = _surname(name)
    if not surname:
        return None
    for query in _name_variants(name):
        best = _match_author_query(query, surname, inst_id, dept)
        if best is not None:
            return best
    return None


def _institution_share(author: dict, inst_id: str) -> float:
    """How much of this author's publishing life carries the school, by year.

    Two OpenAlex authors named Elizabeth Rodrigues both list Grinnell College:
    one has Grinnell for a single year against three at Universidade Federal do
    Pará, the other two of its three years at Grinnell. The first is the more
    published, so "most works wins" chose it and offered a Grinnell
    digital-humanities scholar a materials chemist's research areas — and her
    department, "Digital Studies Concentration", mapped to no field family at
    the time, so the wrong-field gate never ran. It maps now, and would refuse
    him on its own; this rule still has to hold, because two candidates in the
    SAME field are exactly the case fields cannot decide. Being the more
    prolific author is not evidence of being this school's.

    A ratio rather than a count, so a new hire whose only listed institution is
    the school scores 1.0 instead of losing to a long conflated history.
    """
    school_years: set[int] = set()
    all_years: set[int] = set()
    for aff in author.get("affiliations") or []:
        years = {y for y in (aff.get("years") or []) if isinstance(y, int)}
        all_years |= years
        if (aff.get("institution") or {}).get("id", "").rsplit("/", 1)[-1] == inst_id:
            school_years |= years
    if not all_years:
        return 0.0
    return len(school_years) / len(all_years)


def _match_author_query(query: str, surname: str, inst_id: str, dept: str) -> dict | None:
    j = _get({"search": query, "per_page": 10,
              "select": "id,display_name,works_count,affiliations,topics"})
    best, best_rank = None, (-1.0, -1)
    for a in j.get("results", []):
        if surname not in (a.get("display_name") or "").lower():
            continue
        # The surname alone was the whole name test on this path, which is
        # weaker than the roster path's surname + initial and admits the same
        # wrong people.
        if not _given_names_can_be_one_person(query, a.get("display_name") or ""):
            continue
        aff_ids = {
            (aff.get("institution") or {}).get("id", "").rsplit("/", 1)[-1]
            for aff in (a.get("affiliations") or [])
        }
        if inst_id not in aff_ids:
            continue
        rank = (_institution_share(a, inst_id), a.get("works_count") or 0)
        if rank > best_rank:
            best, best_rank = a, rank
    if best is None or best_rank[1] < _MIN_WORKS:
        return None
    topics = best.get("topics") or []
    allowed = _dept_fields(dept)
    if allowed is not None:
        # OpenAlex topic->field labels are noisy (one topic can be mis-fielded),
        # so require a MAJORITY of the top topics to be field-compatible rather
        # than just one — a same-name wrong-field person (e.g. a seismologist
        # vs. the EE professor) is a minority match and gets rejected.
        consider = topics[:6]
        comp = sum(1 for t in consider if (t.get("field") or {}).get("display_name", "") in allowed)
        n = len(consider)
        ok = (comp * 2 >= n) if n >= 3 else (n > 0 and comp == n)
        if not ok:
            return None
    return best


def usable_topics(names, max_topics: int = 5) -> list[str]:
    """Clean OpenAlex topic labels into at most ``max_topics`` distinct keywords.

    Distinct after cleaning, not before: `_clean_topic` flattens delimiters and
    drops a trailing generic noun, so "Advanced Battery Technologies" and
    "Advanced battery technologies, materials" collapse to the same string — and
    a record carrying it twice fails the corpus duplicate-keyword gate and
    doubles the word up in the faculty title. Scanning past a duplicate rather
    than slicing first also means a professor still gets ``max_topics`` areas.
    """
    out: list[str] = []
    for raw in names:
        c = _clean_topic(raw or "")
        if c and c not in out and len(c.split()) <= 7:
            out.append(c)
        if len(out) >= max_topics:
            break
    return out


def author_topics(name: str, inst_id: str, dept: str = "", max_topics: int = 5) -> list[str]:
    """Top research topics for the institution-affiliated author named ``name``,
    or [] when no confident match exists (gating in ``_match_author``)."""
    best = _match_author(name, inst_id, dept)
    if best is None:
        return []
    return usable_topics(
        (t.get("display_name", "") for t in best.get("topics") or []), max_topics)


def _author_own_fields(author: dict | None) -> set[str]:
    """The fields this author actually publishes in, from their topic profile.

    Roster entries carry ``fields`` directly; a search-path author carries
    ``topics``. Either way this is a majority signal over the author's whole
    record, which is what makes it a better answer than the department to
    "could this paper be theirs" — the department is a proxy for exactly this,
    used when the real thing is unavailable.
    """
    if not author:
        return set()
    fields = {f for f in (author.get("fields") or []) if f}
    if fields:
        return fields
    return {
        name for t in (author.get("topics") or [])
        if (name := ((t.get("field") or {}).get("display_name") or ""))
    }


def _own_authorship(work: dict, author_id: str) -> dict | None:
    """This author's authorship on the work, or None when they are not on it.

    Only this entry says where THEY were when they wrote it. The work's other
    authors' institutions say nothing about who this author is.
    """
    for a in work.get("authorships") or []:
        if not isinstance(a, dict):
            continue
        if str((a.get("author") or {}).get("id") or "").rsplit("/", 1)[-1] == author_id:
            return a
    return None


def _paper_affiliation(work: dict, author_id: str, inst_id: str) -> str:
    """Where this author's own authorship on the paper places them.

    ``school``         an institution on it is the record's school, or sits
                       under it (the school is in that institution's lineage,
                       so a campus's institute or law school counts).
    ``elsewhere``      it lists institutions and none of them is the school.
    ``unresolved``     it lists none, but carries a raw affiliation string
                       OpenAlex could not resolve to any institution.
    ``unlisted``       it lists nothing at all.
    ``not_an_author``  the author is not among the work's authorships.

    The author id alone cannot answer this. OpenAlex merges same-name people
    into one author entity, and UIUC's Hua Li (A5113920217, 54 works across
    about 25 institutions) was holding a GE HealthCare engineer's diffusion-MRI
    paper and a Nanjing control theorist's paper beside her own. Both were
    stamped verified and one opened a student's cold email. On each of those
    papers the Hua Li authorship names its own employer, which is the evidence
    the field gate never looked at.
    """
    own = _own_authorship(work, author_id)
    if own is None:
        return "not_an_author"
    institutions = [i for i in own.get("institutions") or [] if isinstance(i, dict)]
    if not institutions:
        raw = [s for s in own.get("raw_affiliation_strings") or [] if isinstance(s, str) and s.strip()]
        return "unresolved" if raw else "unlisted"
    for inst in institutions:
        ids = {str(inst.get("id") or "").rsplit("/", 1)[-1]}
        ids |= {str(x or "").rsplit("/", 1)[-1] for x in inst.get("lineage") or []}
        if inst_id in ids:
            return "school"
    return "elsewhere"


def _strongest_affiliation(verdicts) -> str:
    """One paper's verdict across its versions (a preprint and its journal
    version share a title). Evidence for the school wins; evidence against it
    beats a version that lists nothing, so an affiliation-less preprint cannot
    outvote the journal version that names another employer.

    That last rule has a measured cost. It decided 2 papers in the 200-author
    sample, and both were the professor's own from a previous post: a version
    naming WPI, and one naming Princeton, each beside a copy listing nothing.
    It caught no namesake there."""
    for verdict in ("school", "elsewhere", "unresolved", "unlisted"):
        if verdict in verdicts:
            return verdict
    return "not_an_author"


def _version_key(title: str) -> str:
    """The key that groups one paper's versions: a preprint and its journal
    version share a title up to case, punctuation and accents.

    ``_title_key`` keeps only a-z and 0-9, which is fine for deduplicating
    English titles and wrong for grouping. Every Cyrillic, Korean or Chinese
    title keys to "" there (or to the Latin acronym inside it, "ct"), so all
    of one author's such papers fell into one group with one verdict: a single
    school-placed paper vouched for a namesake's, and a single paper from
    elsewhere took the professor's own with it. Letters of every script are
    kept here; the title is capped first, exactly as ``_usable_works`` stores
    it, so a stored title and the work it came from key alike.
    """
    folded = unicodedata.normalize("NFKD", re.sub(r"\s+", " ", title).strip()[:_TITLE_CAP])
    folded = "".join(c for c in folded if not unicodedata.combining(c)).casefold()
    return " ".join(re.findall(r"[^\W_]+", folded))


def _work_version_key(work: dict) -> str:
    return _version_key(str(work.get("display_name") or ""))


def _affiliation_admits(verdict: str) -> bool:
    """Whether a paper with this verdict may be cited as the professor's.

    ``unlisted`` is admitted on measurement, not by default. On a 200-author
    sample of verified records (2026-10-02), 67 of 592 stored papers had an
    authorship with no institution and no affiliation string, and OpenAlex
    listed no institution for ANY author on most of them: book chapters,
    reviews, conference abstracts, preprints. Read by hand, 64 were the
    professor's own, 2 were unclear and 1 was a namesake's peer-review
    "Author response" document. Dropping them would have cost one paper in
    nine to remove that one.

    ``unresolved`` is not admitted, and that costs the professor's own papers
    too. 7 sampled papers had only an unresolved string. 2 were namesakes':
    "Application Engineering GE HealthCare" on Hua Li's diffusion-MRI paper,
    the paper that opened a student's cold email, and a Qingdao institute on a
    Syracuse professor's radar paper. 4 were the professor's own: an
    editorial signed "Associate Professor of Finance", a clipped "Divisions of
    Pediatric Neurosurgery and", a previous veterinary practice, and the
    school itself misspelled ("The Pennsylvania University, University
    Park"). 1 was unclear. A stated affiliation that resolves to nothing is
    not evidence of the school; matching the school's name inside the string
    would have recovered none of the 4, the misspelled one included.
    """
    return verdict in ("school", "unlisted")


def _usable_works(raw: list[dict], dept: str = "",
                  max_works: int = _MAX_WORKS,
                  author_fields: list[str] | set[str] | None = None,
                  *, author_id: str, inst_id: str) -> list[dict]:
    """The citable subset of one author's works, newest first: title + year
    only, title capped at ``_TITLE_CAP`` chars (corpus lives in a 2GB backend).

    A paper is kept only when this author's own authorship on it places them
    at the record's school, or lists no affiliation at all
    (``_paper_affiliation``; ``_affiliation_admits`` says why the second is
    admitted). That is the per-paper identity check; the field gate below is a
    coarser proxy that predates it.

    OpenAlex author-name disambiguation conflates distinct same-name people
    under one author id, and the recency sort surfaces the mis-attributed
    outliers first (a CS/NLP professor gets a myocardial-cell-injury paper). So
    a work whose ``primary_topic`` field is incompatible with the author is
    dropped. Better to cite no paper than the wrong person's.

    "Incompatible with the author" is answered by the author's OWN field
    profile when we have it, and only otherwise by their department's field
    family. The department is the weaker proxy in both directions, and a real
    professor showed both: UIUC ECE maps to nine fields including Computer
    Science and Environmental Science, so an MRI professor's conflated
    search-agent and geochemistry papers all passed — while his own imaging
    papers, filed under Medicine, which ECE does not map to, were dropped.
    """
    allowed = set(author_fields) if author_fields else _dept_fields(dept)
    aid = str(author_id or "").rsplit("/", 1)[-1]
    verdicts: dict[str, set[str]] = {}
    for w in raw:
        verdicts.setdefault(_work_version_key(w), set()).add(_paper_affiliation(w, aid, inst_id))
    out: list[dict] = []
    seen: set[str] = set()
    for w in raw:
        if not _affiliation_admits(_strongest_affiliation(verdicts[_work_version_key(w)])):
            continue
        if allowed is not None:
            field = ((w.get("primary_topic") or {}).get("field") or {}).get("display_name", "")
            if field not in allowed:
                continue
        title = re.sub(r"\s+", " ", (w.get("display_name") or "")).strip()[:_TITLE_CAP]
        if _is_front_matter(title):
            continue
        year = w.get("publication_year")
        # preprint + published version of one paper share a display_name
        if title and isinstance(year, int) and _title_key(title) not in seen:
            seen.add(_title_key(title))
            out.append({"title": title, "year": year})
        if len(out) >= max_works:
            break
    return out


def author_recent_works(author_id: str, dept: str = "", max_works: int = _MAX_WORKS,
                        author_fields: list[str] | set[str] | None = None,
                        *, inst_id: str) -> list[dict]:
    """``_usable_works`` for one author, bought one request per person."""
    j = _get({
        "filter": f"author.id:{author_id}",
        "sort": "publication_date:desc",
        "per-page": _WORKS_FETCH,
        "select": "display_name,publication_year,primary_topic,authorships",
    }, url=_WORKS_API)
    return _usable_works(j.get("results") or [], dept, max_works, author_fields,
                         author_id=author_id, inst_id=inst_id)


def works_for_authors(author_ids: list[str], *, want: int = _MAX_WORKS,
                      rounds: int = _WORKS_ROUNDS) -> dict[str, list[dict]]:
    """Recent works for up to ``_WORKS_BATCH`` authors, a request at a time.

    ``/works`` costs a credit per REQUEST, not per author, and its author.id
    filter takes an OR list — so the same credit that buys one professor's
    papers can buy twenty-five. That is the difference between a pass that can
    run over the whole corpus and one that cannot: the per-person path costs
    about 12 credits a professor, which is why 15,903 faculty are holding
    papers no serving path may cite.

    The obvious version of this does not work, and asking OpenAlex proved it:
    three real UCSC authors in one newest-first request returned 201 works for
    the first, 1 for the second and 0 for the third. One prolific author
    crowds out the page, and paging deeper just buys more of the same author.

    So each round drops the authors it has already served and re-asks for the
    rest. The prolific ones are satisfied first and stop competing, which is
    what makes the next page belong to the quiet ones. A few extra requests
    per batch is still far cheaper than one request per person.
    """
    pending = {a.rsplit("/", 1)[-1] for a in author_ids if a}
    if not pending:
        return {}
    enough = max(1, want) * _WORKS_SLACK    # room for the per-work field gate
    out: dict[str, list[dict]] = {}
    for _ in range(max(1, rounds)):
        j = _get({
            "filter": "author.id:" + "|".join(sorted(pending)),
            "sort": "publication_date:desc",
            "per-page": _WORKS_PAGE_SIZE,
            "select": "display_name,publication_year,primary_topic,authorships",
        }, url=_WORKS_API)
        results = j.get("results") or []
        for w in results:
            for a in w.get("authorships") or []:
                aid = ((a.get("author") or {}).get("id") or "").rsplit("/", 1)[-1]
                if aid in pending:
                    out.setdefault(aid, []).append(w)
        if len(results) < _WORKS_PAGE_SIZE:
            break                           # the whole filter fits in one page
        served = {aid for aid in pending if len(out.get(aid) or []) >= enough}
        if not served:
            break                           # re-asking would buy the same page
        pending -= served
        if not pending:
            break
    return out


def _targets(opps: list[dict], schools: list[str] | None) -> list[dict]:
    out = []
    for o in opps:
        if not _is_faculty(o) or o.get("keywords"):
            continue
        s = o.get("school")
        if s not in SCHOOL_INST or (schools and s not in schools):
            continue
        if not (o.get("pi_name") and _record_url(o)):
            continue
        out.append(o)
    return out


def _miss_path(checkpoint_path: str | None) -> str | None:
    return checkpoint_path + ".misses" if checkpoint_path else None


def _load_resume_state(checkpoint_path: str | None, resume: bool, targets: list[dict],
                       key=None):
    """(mapping, misses, remaining targets). The sidecar ``.misses`` file makes
    resume skip previously-*unmatched* faculty too — every miss already cost a
    metered search call, and re-scanning a long run of genuine misses is also
    what used to false-trigger the old consecutive-miss "budget exhausted"
    abort."""
    mapping: dict = {}
    misses: set[str] = set()
    if resume and checkpoint_path and os.path.exists(checkpoint_path):
        mapping = json.load(open(checkpoint_path))
    miss_path = _miss_path(checkpoint_path)
    if resume and miss_path and os.path.exists(miss_path):
        misses = set(json.load(open(miss_path)))
    if mapping or misses:
        key = key or _record_url
        done = set(mapping) | misses
        before = len(targets)
        targets = [o for o in targets if key(o) not in done]
        print(f"  resuming: {len(mapping)} matched + {len(misses)} known misses skipped, "
              f"{len(targets)}/{before} targets remain", flush=True)
    return mapping, misses, targets


def _flush_checkpoint(checkpoint_path: str | None, mapping: dict, misses: set[str]) -> None:
    if not checkpoint_path:
        return
    json.dump(mapping, open(checkpoint_path, "w"), indent=2)
    json.dump(sorted(misses), open(_miss_path(checkpoint_path), "w"))


def harvest_openalex(
    opps: list[dict],
    *,
    schools: list[str] | None = None,
    sample: int | None = None,
    throttle: float = 0.15,
    progress: bool = False,
    checkpoint_path: str | None = None,
    checkpoint_every: int = 50,
    resume: bool = False,
) -> dict[str, list[str]]:
    """Pure harvest: ``{url#name: topics}`` for fieldless faculty with a confident
    OpenAlex institution match. ``_is_junk_keyword`` gates each topic. Same
    metered-budget guards as ``harvest_works``: matches AND misses checkpoint
    every ``checkpoint_every`` targets, and the run aborts the moment ``_get``
    confirms a 429 (the definitive budget signal — a miss streak is not; whole
    teaching-heavy departments legitimately miss for 50+ people in a row)."""
    from .uiuc_faculty import _is_junk_keyword

    targets = _targets(opps, schools)
    if sample is not None:
        targets = targets[:sample]
    mapping, misses, targets = _load_resume_state(checkpoint_path, resume, targets,
                                                   key=_person_key)
    for i, o in enumerate(targets):
        tops = author_topics(o["pi_name"], SCHOOL_INST[o["school"]], o.get("department", ""))
        time.sleep(throttle)
        tops = [t for t in tops if not _is_junk_keyword(t)]
        if _warned_429:
            # Don't record this target as a miss — the lookup never really ran.
            print(f"  aborting at {i + 1}/{len(targets)} — OpenAlex budget exhausted "
                  f"(confirmed 429); {len(mapping)} matched", flush=True)
            break
        if tops:
            mapping[_person_key(o)] = tops
        else:
            misses.add(_person_key(o))
        if checkpoint_path and (i + 1) % checkpoint_every == 0:
            _flush_checkpoint(checkpoint_path, mapping, misses)
        if progress and (i + 1) % 100 == 0:
            print(f"  ...{i + 1}/{len(targets)}, {len(mapping)} matched", flush=True)
    _flush_checkpoint(checkpoint_path, mapping, misses)
    return mapping


_ROSTER_PAGE = 100
# Fields the roster needs. `affiliations` is deliberately absent: it is 96% of
# the payload (5.3MB vs 201KB per 100 authors, measured), and the filter below
# already pins the institution. What it cost us is the _institution_share
# tiebreak, which the ambiguity rule replaces — see _match_in_roster.
_ROSTER_SELECT = "id,display_name,works_count,topics"


def _roster_author(a: dict) -> dict:
    """One roster row, trimmed to what matching needs."""
    topics = a.get("topics") or []
    return {
        "id": a.get("id"),
        "name": a.get("display_name") or "",
        "works": a.get("works_count") or 0,
        "topics": [t.get("display_name") for t in topics[:8] if t.get("display_name")],
        "fields": [
            (t.get("field") or {}).get("display_name", "") for t in topics[:6]
        ],
    }


def fetch_roster(inst_id: str, *, min_works: int = _MIN_WORKS,
                 progress: bool = False, cursor: str = "*",
                 authors: list[dict] | None = None) -> dict:
    """Every OpenAlex author whose LAST KNOWN institution is ``inst_id``.

    Pure filters + cursor paging, so this costs 1 credit per 100 authors rather
    than the 10 a name search costs — 28,388 JHU authors for 284 credits, versus
    ~54,000 credits to search that school's 4,563 faculty one at a time.

    Returns ``{"authors", "cursor", "expected", "complete"}``. ``complete`` is
    the only thing a caller may trust: a page can fail to arrive (a timeout, an
    exhausted daily budget) and ``_get`` reports both as an empty dict, which is
    byte-identical to a roster that has genuinely ended. Reading that as "done"
    is how the first run of this cached 300 of Cincinnati's 6,925 authors and
    then matched 4% of the school against them. So completeness is decided by
    the count OpenAlex itself reports, not by the loop finishing.

    Pass ``cursor``/``authors`` back to resume an incomplete roster tomorrow.
    """
    out = list(authors or [])
    expected: int | None = None
    pages = 0
    while cursor:
        j = _get({
            "filter": f"last_known_institutions.id:{inst_id},works_count:>{min_works - 1}",
            "select": _ROSTER_SELECT,
            "per_page": _ROSTER_PAGE,
            "cursor": cursor,
        }, timeout=90)
        results = j.get("results")
        if results is None:
            # The page never arrived. Leave the cursor set so the caller can
            # tell this apart from a finished walk and resume from here.
            break
        if expected is None:
            expected = (j.get("meta") or {}).get("count")
        if not results:
            cursor = None
            break
        out.extend(_roster_author(a) for a in results)
        pages += 1
        if progress and pages % 25 == 0:
            print(f"  roster: {len(out)}/{expected} authors, {pages} pages", flush=True)
        cursor = (j.get("meta") or {}).get("next_cursor")
    complete = cursor is None and (
        expected is None or len(out) >= expected * 0.98
    )
    return {"authors": out, "cursor": cursor, "expected": expected,
            "complete": complete}


def _match_name_key(name: str) -> tuple[str, str] | None:
    """(surname, first initial), accent-folded. None when the name is unusable."""
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    toks = [t for t in re.sub(r"[^a-z ]", " ", folded.lower()).split() if t]
    if len(toks) < 2:
        return None
    return (toks[-1], toks[0][0])


def _given_name(name: str) -> str:
    k = _match_name_key(name)
    if k is None:
        return ""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    return re.sub(r"[^a-z ]", " ", folded.lower()).split()[0]


# Given names that can be one person. Every pair here was observed as a
# rejection this rule got wrong on the cached rosters — Mike/Michael Guidry
# (334 works), Joe/Joseph Miles (116), Charlie/Charles Kwit (71) — so the list
# is derived from evidence rather than guessed at, and it is certainly
# incomplete. It does not assert that two names ARE one person; it only stops
# the name from being grounds for refusal, leaving the institution, field and
# ambiguity gates to decide.
_DIMINUTIVES = {
    "mike": "michael", "cindi": "cynthia", "cindy": "cynthia",
    "joe": "joseph", "nick": "nicholas", "charlie": "charles",
    "katie": "katherine", "kathy": "katherine", "bill": "william",
    "bob": "robert", "dan": "daniel", "jim": "james", "tom": "thomas",
    "steve": "stephen", "dave": "david", "liz": "elizabeth",
    "beth": "elizabeth", "sue": "susan",
}


def _off_by_one(a: str, b: str) -> bool:
    """One substitution or one inserted letter apart — Oswaldo/Osvaldo.

    Only for names of five letters or more, where a single character is a
    spelling variant rather than a different name: at three letters it would
    make Jun and Jie the same person.
    """
    if min(len(a), len(b)) < 5 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) == 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long)):
        if long[:i] + long[i + 1:] == short:
            return True
    return False


def _given_names_can_be_one_person(faculty: str, author: str) -> bool:
    """Whether these two given names can belong to the same human.

    The surname and first initial are all that bind a faculty member to a
    roster author, which is why "Christy Hickman" was being handed Candice
    Hickman's research, and "Ashleigh Jones" Alex K. Jones's. Neither the
    institution nor the field gate can see the difference: both people really
    are C. Hickman at that school.

    Unknown on either side is not evidence, so it passes.
    """
    a, b = _given_name(faculty), _given_name(author)
    if not a or not b or a == b:
        return True
    if len(a) == 1 or len(b) == 1:      # "J." tells us only the initial
        return a[0] == b[0]
    if a.startswith(b) or b.startswith(a):
        return True
    if _DIMINUTIVES.get(a, a) == _DIMINUTIVES.get(b, b):
        return True
    return _off_by_one(a, b)


def _given_sequence(name: str) -> list[str]:
    """The given-name tokens, in order, accent- and punctuation-folded.

    The surname is split off on WHITESPACE before any punctuation is touched,
    because the two carry different punctuation and it means different things.
    Splitting the whole string on non-letters first made "Akih-Kumgeh" into two
    tokens and counted "akih" as one of Ben Akih-Kumgeh's given names, and
    "O’Hara" into "o" + "hara". Within the given part, a hyphen separates
    names ("Zhi-Pei" is two) while an apostrophe or a period sits inside one
    ("No’am" is one) — which is why they are folded differently.
    """
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    out: list[str] = []
    for part in folded.split()[:-1]:
        part = re.sub(r"['’.]", "", part.lower())
        out.extend(t for t in re.split(r"[^a-z]+", part) if t)
    return out


def _given_tokens(name: str) -> set[str]:
    """Every given name before the surname. "Zhi-Pei" is two, so it can be
    told apart from "Zhixiang" — which the prefix rule above cannot do."""
    return set(_given_sequence(name))


def _writes_out_given_names(faculty: str, author: str) -> bool:
    """Whether this roster row writes out every given name the directory lists."""
    want = _given_tokens(faculty)
    return bool(want) and want <= _given_tokens(author)


def _shortens_given_name(faculty: str, author: str) -> bool:
    """Whether the row gives a recognisable short form — Chris for Christopher.

    An initial does not count: "M." is a prefix of Meghan, Melissa and Mark
    alike. Three letters is where a prefix stops abbreviating one name and
    starts naming another, and the direction matters too — Zhixiang is not a
    short form of Zhi-Pei.
    """
    a, b = _given_name(faculty), _given_name(author)
    return len(b) >= 3 and (a.startswith(b) or _DIMINUTIVES.get(b) == a)


# A department whose discipline maps to exactly one unambiguous OpenAlex
# field, used only to ask whether a candidate has ever published in it.
# Ordered like _DEPT_FIELDS so "electric" answers first: Electrical & Computer
# Engineering contains the word "computer", and its faculty legitimately
# publish as Engineering, Physics and Astronomy or Materials Science with no
# Computer Science topic at all.
_DISCIPLINE_PROBE: tuple[tuple[str, str | None], ...] = (
    ("electric", None),
    ("computer", "Computer Science"),
    ("computing", "Computer Science"),
    ("software", "Computer Science"),
)
# How many people must share a surname on one institution's roster before
# surname + first initial stops identifying anybody. Measured, not guessed:
# see _match_in_roster.
_AMBIGUOUS_SURNAME_MIN = 3


def _discipline_probe(dept: str) -> str | None:
    d = _DEPT_WORD_RE.sub(" ", (dept or "").lower())
    for key, field in _DISCIPLINE_PROBE:
        if key in d:
            return field
    return None


class Roster(NamedTuple):
    """A school's authors, indexed the two ways matching needs them.

    Carrying the surname counts here rather than passing them separately is
    deliberate: _match_in_roster cannot be called without them, so the guard
    below cannot be left unwired by a caller that forgets.
    """

    by_name: dict[tuple[str, str], list[dict]]
    surnames: collections.Counter


def index_roster(roster: list[dict]) -> Roster:
    idx: dict[tuple[str, str], list[dict]] = {}
    surnames: collections.Counter = collections.Counter()
    for a in roster:
        k = _match_name_key(a.get("name", ""))
        if k is not None:
            idx.setdefault(k, []).append(a)
            surnames[k[0]] += 1
    return Roster(idx, surnames)


def _rejected_namesake(name: str, chosen: dict,
                       rejected: list[dict]) -> dict | None:
    """The field gate's own reject, when it discarded the only candidate that
    carries this faculty member's name.

    _dept_fields is a proxy for identity and a coarse one: OpenAlex fields
    follow what a person publishes, not who pays them, so Carle Illinois's
    Ravishankar K. Iyer is Computer Science + Engineering, fails a college of
    medicine's field family, and leaves an "R. Iyer" with five papers that the
    ambiguity rule is happy to return. A row that writes the name out is direct
    identity evidence and the field family is not, so when the gate has thrown
    away the one such row, take it back.

    Measured against the 18 cached rosters, 16 matches change. A blind panel
    judged 14 of them: 12 say the record being replaced is a different human,
    and 2 are one person OpenAlex had split in two, where the larger half is
    the better answer either way. Of the 2 unjudged, Syracuse's Meghan Kelly
    looks like the cost of the rule — the roster's 221-work "Meghan Kelly" is a
    design academic and the "M. Kelly" being replaced does publish on GIS. No
    name evidence separates her case from the twelve.

    Uniqueness is what keeps the rest honest: Pitt has three Jun Chens, and
    there this changes nothing.
    """
    if (_writes_out_given_names(name, chosen.get("name", ""))
            or _shortens_given_name(name, chosen.get("name", ""))):
        return None
    full = [a for a in rejected
            if _writes_out_given_names(name, a.get("name", ""))
            and a.get("works", 0) > chosen.get("works", 0)]
    return full[0] if len(full) == 1 else None


def _match_in_roster(name: str, dept: str,
                     idx: Roster) -> tuple[dict | None, str]:
    """The roster author for this faculty member, or (None, reason).

    Gates in order, all of them the search path's own:
      * surname + first initial, accent-folded;
      * works_count >= _MIN_WORKS;
      * a majority of the top topic fields compatible with the department.

    Then the rule that replaces ``_institution_share``: if more than one
    candidate is still standing, REFUSE. The old tiebreak was "most works
    wins", and that is exactly what handed a Grinnell digital-humanities
    scholar a Brazilian chemist's research areas. Without affiliation years
    there is no honest way to rank two same-named colleagues, and a wrong
    person's research is worse than none.
    """
    k = _match_name_key(name)
    if k is None:
        return None, "unusable_name"
    cands = [a for a in idx.by_name.get(k, []) if a.get("works", 0) >= _MIN_WORKS]
    if not cands:
        return None, "absent"
    allowed = _dept_fields(dept)
    rejected: list[dict] = []
    if allowed is not None:
        kept = []
        for a in cands:
            fields = [f for f in (a.get("fields") or []) if f]
            n = len(fields)
            comp = sum(1 for f in fields if f in allowed)
            ok = (comp * 2 >= n) if n >= 3 else (n > 0 and comp == n)
            (kept if ok else rejected).append(a)
        cands = kept
        if not cands:
            return None, "field_reject"
    named = [a for a in cands if _given_names_can_be_one_person(name, a.get("name", ""))]
    if not named:
        # The field gate's rejects are NOT consulted here, though one of them
        # may well carry the name. Measured on the cached rosters, reaching for
        # them recovers 26 matches and four of the first seven inspected are a
        # different human: a Journalism professor given a smart-grid
        # researcher's papers, Sociology given a protein biophysicist's, Public
        # Affairs given a geophysicist's. A department rejecting every
        # candidate is evidence, not an accident, and a shared name is not
        # enough to overrule it.
        return None, "given_name_reject"
    cands = named
    exact = [a for a in cands if _given_name(a["name"]) == _given_name(name)]
    if exact:
        cands = exact
    if len(cands) == 1:
        better = _rejected_namesake(name, cands[0], rejected)
        if better is not None:
            cands = [better]
    # When the surname is common on this roster, surname + first initial is not
    # identifying and the field family above is too wide to finish the job: a
    # School of Computing maps to a family holding Chemistry, Physics and
    # Materials Science, so a peptide chemist named Arindam Banerjee is a
    # majority-compatible match for the machine-learning professor of the same
    # name, and "T. P. Martin" (302 works, physics) for Travis Martin.
    #
    # So for a department whose discipline names one unambiguous field, ask
    # whether the candidate has ever published in it — of the match that would
    # actually be made, which is why this runs after the name preference above
    # rather than before it. Filtering first let the check RESHAPE the
    # candidate set instead of judging it: for Arindam Banerjee it dropped the
    # chemist who carries his exact name and handed the professor an
    # initials-only "A Banerjee" whose profile does list Computer Science —
    # one wrong person swapped for another. Spending the name evidence first
    # also keeps eleven correct matches the other order kept by accident. Measured on 392 matched
    # computing faculty: this rejects 12, of which a blind adversarial audit
    # confirmed 10 as different humans. Requiring the shared surname is what
    # keeps the other 380 — Deepak Vasisht (labelled Engineering, correct),
    # Colleen Josephson (Engineering/Environmental, correct) and the maths half
    # of a joint Mathematics & Computer Science department all have surnames
    # that are near-unique on their rosters and are not asked the question.
    probe = _discipline_probe(dept)
    if probe and idx.surnames.get(_surname(name), 0) >= _AMBIGUOUS_SURNAME_MIN:
        cands = [a for a in cands if probe in set(a.get("fields") or [])]
        if not cands:
            return None, "discipline_reject"
    if len(cands) > 1:
        return None, "ambiguous"
    return cands[0], "ok"


def _roster_state(slug: str, roster_dir: str | None, *, progress: bool,
                  what: str) -> dict:
    """This school's roster: the cache when it is complete, otherwise fetched
    (resuming a partial one from its cursor) and cached.

    Both passes need a roster and only one of them could get it. They select
    different people — ``_targets`` wants faculty with no research keywords,
    ``_works_targets`` wants faculty with no citable papers — so a school can
    have thousands of works targets and no keyword targets at all, and never be
    reachable by the only command that buys rosters. Berkeley is exactly that:
    0 keyword targets, 2,168 works targets, and no way to get its roster.
    """
    cache = os.path.join(roster_dir, f"{slug}.json") if roster_dir else None
    state = json.load(open(cache)) if cache and os.path.exists(cache) else None
    if state is None or not state.get("complete"):
        if progress:
            have = len(state["authors"]) if state else 0
            print(f"{slug}: fetching roster for {what}"
                  + (f" (resuming from {have})" if have else ""), flush=True)
        state = fetch_roster(
            SCHOOL_INST[slug], progress=progress,
            cursor=(state or {}).get("cursor") or "*",
            authors=(state or {}).get("authors"),
        )
        if cache:
            os.makedirs(roster_dir, exist_ok=True)
            json.dump(state, open(cache, "w"))
    elif progress:
        print(f"{slug}: {len(state['authors'])} cached roster authors", flush=True)
    return state


def harvest_openalex_roster(
    opps: list[dict],
    *,
    schools: list[str] | None = None,
    progress: bool = False,
    roster_dir: str | None = None,
    max_topics: int = 5,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """``harvest_openalex``'s result, bought by the page instead of by the person.

    Returns ``({url#name: topics}, reason_counts)``. The mapping is the same
    shape ``apply_openalex`` already consumes.

    ``roster_dir`` caches each school's roster as JSON so a re-run — after the
    daily budget resets, or to re-match with a changed gate — costs nothing.
    """
    from .uiuc_faculty import _is_junk_keyword

    targets = _targets(opps, schools)
    by_school: dict[str, list[dict]] = {}
    for o in targets:
        by_school.setdefault(o["school"], []).append(o)

    mapping: dict[str, list[str]] = {}
    reasons: dict[str, int] = {}
    for slug, people in sorted(by_school.items()):
        state = _roster_state(slug, roster_dir, progress=progress,
                              what=f"{len(people)} fieldless faculty")
        if not state["complete"]:
            # Matching a school against a roster that is missing authors invents
            # misses, and those misses are indistinguishable from real ones in
            # the output. Skip the school; tomorrow's run resumes its cursor.
            reasons["roster_incomplete"] = reasons.get("roster_incomplete", 0) + 1
            if progress:
                print(f"{slug}: roster incomplete "
                      f"({len(state['authors'])}/{state.get('expected')}) — skipped",
                      flush=True)
            continue
        idx = index_roster(state["authors"])
        for o in people:
            author, why = _match_in_roster(o["pi_name"], o.get("department", ""), idx)
            reasons[why] = reasons.get(why, 0) + 1
            if author is None:
                continue
            topics = [t for t in usable_topics(author.get("topics") or [], max_topics)
                      if not _is_junk_keyword(t)]
            if topics:
                mapping[_person_key(o)] = topics
            else:
                reasons["no_usable_topics"] = reasons.get("no_usable_topics", 0) + 1
        if progress:
            print(f"{slug}: {len(people)} targets -> {len(mapping)} matched so far",
                  flush=True)
    return mapping, reasons


def apply_openalex(opps: list[dict], mapping: dict[str, list[str]]) -> int:
    """Updates-only: set keywords on fieldless faculty keyed in mapping.
    Composite ``url#name`` keys are authoritative; bare-URL keys (pre-2026-07
    harvests) apply only when exactly one faculty owns the URL — a shared
    directory URL must never stamp one person's topics onto colleagues."""
    counts = _shared_url_counts(opps)
    n = 0
    for o in opps:
        if not _is_faculty(o) or o.get("keywords"):
            continue
        kws = mapping.get(_person_key(o))
        if not kws and counts.get(_record_url(o), 0) == 1:
            kws = mapping.get(_record_url(o))
        if kws:
            o["keywords"] = kws
            # W11: publication-derived topics are a derivation from the
            # author-matched OpenAlex record, not text scraped off the
            # professor's page — stamp the producer so serving/audits can
            # tell the difference at rest.
            stamp_inferred(o.setdefault("metadata", {}), "keywords", "derived:openalex_topics")
            n += 1
    return n


def harvest_works_by_roster(
    opps: list[dict],
    *,
    schools: list[str] | None = None,
    roster_dir: str | None = None,
    progress: bool = False,
) -> tuple[dict[str, dict], dict[str, int]]:
    """``harvest_works``'s result, bought the way #821 buys research areas.

    Returns ``({url#name: {"author_id":..., "works":[...]}}, reason_counts)``,
    the dict form ``apply_works`` stamps as verified attribution — which is the
    whole point. 15,903 faculty are holding real paper titles that no serving
    path may cite, because they were harvested before provenance existed and
    the committed store keeps only a name-keyed association. A cold email may
    say "your recent paper" only of a paper it can prove is theirs, so those
    15,903 records cite nothing.

    The two costs that made re-harvesting them unaffordable are both gone here.
    Resolving the author was 12 credits a professor through the search API; the
    cached institution roster already holds the answer and costs nothing to
    match against. Fetching the papers was one request a professor; a single
    ``/works`` request serves ``_WORKS_BATCH`` of them.

    Only faculty whose works are not already verified are targeted, and a
    school whose cached roster is incomplete is skipped rather than matched
    against a partial list — the same rule ``harvest_openalex_roster`` follows,
    for the same reason: a miss against a partial roster is indistinguishable
    from a real one.
    """
    targets = _works_targets(opps, schools)
    by_school: dict[str, list[dict]] = {}
    for o in targets:
        by_school.setdefault(o["school"], []).append(o)

    mapping: dict[str, dict] = {}
    reasons: dict[str, int] = {}
    for slug, people in sorted(by_school.items()):
        state = _roster_state(slug, roster_dir, progress=progress,
                              what=f"{len(people)} faculty with nothing citable")
        if _warned_429 and not state.get("complete"):
            # The budget died buying this roster. Every school after it would
            # spend a request confirming the same thing.
            if progress:
                print(f"{slug}: budget exhausted while fetching the roster — stopping",
                      flush=True)
            return mapping, reasons
        if not state.get("complete"):
            reasons["roster_incomplete"] = reasons.get("roster_incomplete", 0) + 1
            if progress:
                print(f"{slug}: roster incomplete "
                      f"({len(state.get('authors') or [])}/{state.get('expected')}) — skipped",
                      flush=True)
            continue
        idx = index_roster(state["authors"])
        # (key, author_id, dept, the author's own fields)
        resolved: list[tuple[str, str, str, set[str]]] = []
        for o in people:
            author, why = _match_in_roster(o["pi_name"], o.get("department", ""), idx)
            reasons[why] = reasons.get(why, 0) + 1
            if author is None:
                continue
            aid = str(author.get("id") or "").rsplit("/", 1)[-1]
            if aid:
                resolved.append((_person_key(o), aid, o.get("department", ""),
                                 _author_own_fields(author)))
        if progress:
            print(f"{slug}: {len(people)} targets, {len(resolved)} authors resolved "
                  f"({-(-len(resolved) // _WORKS_BATCH)} requests)", flush=True)
        affiliations: collections.Counter = collections.Counter()
        for i in range(0, len(resolved), _WORKS_BATCH):
            batch = resolved[i:i + _WORKS_BATCH]
            raw = works_for_authors([aid for _, aid, _, _ in batch])
            if _warned_429:
                # Don't record this batch as misses — the lookup never really
                # ran. An empty answer from an exhausted budget is not the same
                # claim as "this professor has no citable paper", and writing
                # the second one would make tomorrow's run skip them.
                if progress:
                    print(f"  {slug}: aborting at {i}/{len(resolved)} — OpenAlex "
                          f"budget exhausted (confirmed 429); {len(mapping)} with papers",
                          flush=True)
                return mapping, reasons
            # Whether the request itself worked. If NO author in the batch came
            # back with anything, that is a failure to ask, not twenty-five
            # people with nothing to cite — and writing the second one down
            # would clear their records below.
            batch_answered = bool(raw)
            for key, aid, dept, own_fields in batch:
                affiliations.update(_paper_affiliation(w, aid, SCHOOL_INST[slug])
                                    for w in raw.get(aid) or [])
                works = _usable_works(raw.get(aid) or [], dept, author_fields=own_fields,
                                      author_id=aid, inst_id=SCHOOL_INST[slug])
                if works:
                    mapping[key] = {"author_id": aid, "works": works}
                elif batch_answered:
                    # An answer about this author: their recent work is not
                    # theirs to cite. apply_works needs this written down —
                    # absent from the mapping is indistinguishable from never
                    # harvested, and a record that keeps its old papers because
                    # the newer gate rejected all of them is the worst outcome
                    # available.
                    mapping[key] = {"author_id": aid, "works": []}
                    reasons["no_usable_work"] = reasons.get("no_usable_work", 0) + 1
                else:
                    reasons["batch_unanswered"] = reasons.get("batch_unanswered", 0) + 1
            if progress:
                print(f"  {slug}: {min(i + _WORKS_BATCH, len(resolved))}/{len(resolved)} "
                      f"-> {len(mapping)} with papers", flush=True)
        if progress and affiliations:
            # "unlisted" papers pass with no affiliation evidence at all
            # (_affiliation_admits); the count is how much of a run leans on that.
            print(f"  {slug}: fetched papers by the author's listed affiliation: "
                  + ", ".join(f"{k} {v}" for k, v in sorted(affiliations.items())), flush=True)
    return mapping, reasons


def _works_targets(opps: list[dict], schools: list[str] | None) -> list[dict]:
    # Unlike the topics pass, keyworded faculty ARE targets — a recent paper
    # title gives the cold email substance regardless of keyword source.
    out = []
    for o in opps:
        if not _is_faculty(o):
            continue
        s = o.get("school")
        if s not in SCHOOL_INST or (schools and s not in schools):
            continue
        if not (o.get("pi_name") and _record_url(o)):
            continue
        # Having works is not being done. Works no serving path may cite are
        # worth exactly what an empty list is worth, and skipping their records
        # here is what locked 15,917 faculty out of the only pass that could
        # ever stamp them: harvested before the stamp existed, then never
        # selected again because they looked harvested.
        #
        # Nor is being verified being done, if an older gate verified it: a
        # record whose papers were chosen by the department's field family is
        # holding whatever that family let through, and #846 exists because
        # that included other people's work. Re-target it once; the stamp it
        # gets back stops it being selected again.
        #
        # A record the remediation has withdrawn (``pending_remediation``) is
        # not verified, so it lands here by the same rule that selects the
        # never-stamped: withdrawing trust is what puts it back in the queue.
        if works_are_verified(o) and works_are_current_gate(o):
            continue
        out.append(o)
    return out


def harvest_works(
    opps: list[dict],
    *,
    schools: list[str] | None = None,
    sample: int | None = None,
    throttle: float = 0.2,
    progress: bool = False,
    checkpoint_path: str | None = None,
    checkpoint_every: int = 50,
    resume: bool = False,
) -> dict[str, list[dict]]:
    """Pure harvest: ``{url#name: {"author_id": ..., "works": [{title, year}, ...]}}``
    for faculty with a confident OpenAlex author match (same institution/
    surname/field gates as topics). Carrying the resolved author id is what
    lets apply_works stamp these works ``verified_author_id`` instead of the
    bare-list legacy form's ``name_match``.

    OpenAlex is metered (paid per call), so two guards protect the budget:
    with ``checkpoint_path`` set, matches AND misses are flushed every
    ``checkpoint_every`` targets (a ``.misses`` sidecar), so neither a crash
    nor a resume ever re-pays for a lookup; and the run aborts the moment
    ``_get`` confirms a 429 — the definitive budget signal, unlike a miss
    streak (whole teaching-heavy departments legitimately miss 50+ in a row,
    which used to false-abort resumed runs)."""
    targets = _works_targets(opps, schools)
    if sample is not None:
        targets = targets[:sample]
    mapping, misses, targets = _load_resume_state(checkpoint_path, resume, targets,
                                                   key=_person_key)
    for i, o in enumerate(targets):
        dept = o.get("department", "")
        best = _match_author(o["pi_name"], SCHOOL_INST[o["school"]], dept)
        time.sleep(throttle)
        works = (author_recent_works(best["id"], dept, author_fields=_author_own_fields(best),
                                     inst_id=SCHOOL_INST[o["school"]])
                 if best and best.get("id") else [])
        if best and best.get("id"):
            time.sleep(throttle)
        if _warned_429:
            # Don't record this target as a miss — the lookup never really ran.
            print(f"  aborting at {i + 1}/{len(targets)} — OpenAlex budget exhausted "
                  f"(confirmed 429); {len(mapping)} matched", flush=True)
            break
        if works:
            mapping[_person_key(o)] = {"author_id": best["id"], "works": works}
        else:
            misses.add(_person_key(o))
        if checkpoint_path and (i + 1) % checkpoint_every == 0:
            _flush_checkpoint(checkpoint_path, mapping, misses)
        if progress and (i + 1) % 100 == 0:
            print(f"  ...{i + 1}/{len(targets)}, {len(mapping)} matched", flush=True)
    _flush_checkpoint(checkpoint_path, mapping, misses)
    return mapping


def _entry_works_and_status(entry) -> tuple[list[dict], str]:
    """A mapping entry's works + the attribution status they earn. The dict
    form (current harvests) proves the works came through a resolved author id;
    the bare-list form (the committed pre-provenance WORKS_STORE) retains only
    the name-keyed association, so its works are honestly ``name_match``."""
    if isinstance(entry, dict):
        status = ATTRIBUTION_VERIFIED if entry.get("author_id") else ATTRIBUTION_NAME_MATCH
        return entry.get("works") or [], status
    return entry or [], ATTRIBUTION_NAME_MATCH


# The gate version and its reader now live in the trust boundary, not here.
# "Verified" is a claim a specific rule version made, and everything that has
# to know WHICH version — the serving gate, the remediation population query,
# the ledger's idempotency key — must read the same answer. The catalogue of
# what each version means stays with the code that implements it:
#
#   1  the department's field family alone. A proxy for the author and a poor
#      one in both directions: Electrical & Computer Engineering spans nine
#      fields including Computer Science and Environmental Science, so a
#      conflated entity's search-agent and geochemistry papers all passed,
#      while the professor's own imaging papers, filed under Medicine, did not.
#   2  the author's own published fields, falling back to the family only when
#      we don't have them (#846), with the roster's direct name evidence
#      allowed to reclaim a record the field gate discarded (#853).
#   3  the same, minus a book's front matter: "Introduction" and "Preface" are
#      indexed as works and were being offered as recent publications (#857).
#
# Stamped on every write. A record made by an older gate is a target again and
# its replacement supersedes at any paper count — under a stricter gate, fewer
# papers is the correction, not a regression.
_record_gate = record_works_gate


def _is_a_retraction(entry, record: dict) -> bool:
    """Whether an answer that yields NO citable paper should clear this record.

    Only for an explicit answer — a dict entry carrying the resolved author id,
    which ``harvest_works_by_roster`` writes only when the request that
    produced it demonstrably worked. A missing entry means the person was never
    asked about and must never clear anything.

    The caller decides emptiness, not this function: an answer can arrive with
    works and still leave nothing citable once they are cleaned, which is what
    happens to a record whose every paper is a book's front matter. "Answered,
    and none of it may be cited" is the same conclusion either way.

    And only against papers an OLDER gate chose. A record already at the
    current gate holding papers this run happened not to return is a transient
    difference, not a correction.

    ``pending_remediation`` counts alongside ``verified`` here. It is what the
    historical remediation writes over a record an older gate had trusted: the
    papers are still sitting on the record awaiting judgement, and an explicit
    "none of these are theirs" is exactly the judgement the remediation asked
    for. Reading only ``works_are_verified`` would have left every withdrawn
    record holding its stranger's papers forever, because withdrawing the trust
    is what stopped it qualifying.
    """
    if not (isinstance(entry, dict) and entry.get("author_id")):
        return False
    if not (record.get("metadata") or {}).get("recent_works"):
        return False
    if works_are_current_gate(record):
        return False
    return works_are_verified(record) or is_pending_remediation(record)


def _is_an_upgrade(clean: list[dict], status: str, existing: list[dict],
                   record: dict) -> bool:
    """Whether writing ``clean`` over ``existing`` makes the record better.

    Count alone answers this only WITHIN a trust level. Across levels it gives
    the wrong answer, and did: 15,327 of the 15,917 records holding papers hold
    exactly ``_MAX_WORKS`` of them, so a re-harvest returning the same three
    papers now carrying an author id failed ``3 > 3`` and the stamp never
    landed. Unverified works are unusable by every serving path, so one citable
    paper beats three uncitable ones — and a verified record is never traded
    back for an unverified one at any count.
    """
    was_verified = works_are_verified(record)
    now_verified = status == ATTRIBUTION_VERIFIED
    if now_verified != was_verified:
        return now_verified
    if now_verified and not works_are_current_gate(record):
        # Re-harvested under a stricter gate. Count cannot answer here either:
        # the whole point of the newer gate is that some of what the record
        # holds should never have been cited, so a shorter list is the
        # correction. Measured on 800 rechecked records, this is what a
        # re-harvest usually returns — one of the professor's own papers in
        # place of a stranger's, not a shorter list.
        return True
    return len(clean) > len(existing)


def apply_works(opps: list[dict], mapping: dict[str, list | dict]) -> int:
    """Set ``metadata.recent_works`` on faculty keyed in mapping (composite
    ``url#name`` first; bare-URL fallback only for a URL owned by exactly one
    faculty — see ``apply_openalex``), whenever the mapping entry is an upgrade
    (``_is_an_upgrade``: better attribution first, more papers as the tiebreak
    within a trust level). Upgrade-when-richer, not skip-if-present:
    re-applying the fuller ``WORKS_STORE`` promotes a 1-paper record to the
    full ``_MAX_WORKS`` set, while never downgrading a record that already has
    more — or that already has better provenance. Every write also stamps
    ``metadata.publication_attribution_status`` for the works it stores (see
    ``_entry_works_and_status``); records it doesn't touch keep whatever they
    had. Idempotent; never touches any other field."""
    counts = _shared_url_counts(opps)
    n = 0
    for o in opps:
        if not _is_faculty(o):
            continue
        current_metadata = o.get("metadata") or {}
        refresh = current_metadata.get("research_refresh")
        if "research_snapshot" in current_metadata or (
            isinstance(refresh, dict) and refresh.get("reason") == "identity_revoked"
        ):
            # The title-only library has neither a fresh author check nor the
            # source content/time of the newer snapshot. It cannot replace a
            # successful empty snapshot or restore a deliberately revoked ID.
            continue
        entry = mapping.get(_person_key(o))
        if not entry and counts.get(_record_url(o), 0) == 1:
            entry = mapping.get(_record_url(o))
        works, status = _entry_works_and_status(entry)
        author_id = entry.get("author_id") if isinstance(entry, dict) else None
        clean: list[dict] = []
        seen: set[str] = set()
        for w in works:
            title = str(w.get("title", ""))[:_TITLE_CAP]
            if not title or not isinstance(w.get("year"), int):
                continue
            if _is_front_matter(title):
                continue
            # the committed store predates the _title_key dedup and can carry
            # punctuation-variant duplicates of one paper
            if _title_key(title) in seen:
                continue
            seen.add(_title_key(title))
            clean.append({"title": title, "year": w["year"]})
            if len(clean) >= _MAX_WORKS:
                break
        existing = (o.get("metadata") or {}).get("recent_works") or []
        if not clean and _is_a_retraction(entry, o):
            # The newer gate was asked about this author and rejected every
            # paper the record holds. Keeping them because the replacement is
            # empty is the worst outcome available: these are the records most
            # likely to be citing a stranger.
            md = o.setdefault("metadata", {})
            md.pop("recent_works", None)
            md.pop("publication_attribution_status", None)
            md.pop("publication_author_id", None)
            md["works_gate"] = _WORKS_GATE
            n += 1
            continue
        if clean and _is_an_upgrade(clean, status, existing, o):
            md = o.setdefault("metadata", {})
            md["recent_works"] = clean
            md["publication_attribution_status"] = status
            md["works_gate"] = _WORKS_GATE
            # The status asserts that an author id resolved these papers; keep
            # the id itself, because "which author was this?" is the only
            # question that settles a wrong-person report and re-deriving the
            # answer from today's matcher gives yesterday's records the wrong
            # one. Diagnosing Zhi-Pei Liang's three misattributed 2026 papers
            # took two tries and got it wrong the first time for exactly this
            # reason.
            if author_id:
                md["publication_author_id"] = author_id
            else:
                md.pop("publication_author_id", None)
            n += 1
    n -= _strip_ambiguous_attributions(opps)
    return n


def _strip_ambiguous_attributions(opps: list[dict]) -> int:
    """Drop the citation from every record in an id group that spans two people.

    Runs over the WHOLE corpus after an apply, not over the batch, because the
    second professor sharing an id may have been stamped by an earlier harvest.
    Fail closed: we cannot tell which of them the papers belong to, so none of
    them may cite.
    """
    ambiguous = ambiguous_author_ids(opps)
    if not ambiguous:
        return 0
    stripped = 0
    for record in opps:
        md = record.get("metadata") or {}
        if md.get("publication_author_id") in ambiguous:
            md.pop("publication_author_id", None)
            md.pop("publication_attribution_status", None)
            md.pop("works_gate", None)
            md.pop("recent_works", None)
            stripped += 1
    return stripped


def _load_dotenv() -> None:
    """Load backend/.env so ``python -m`` runs pick up OPENALEX_API_KEY; the
    importable functions never touch the environment beyond os.environ.get."""
    from pathlib import Path

    p = Path("backend/.env")
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# New snapshots use a separate bounded refresh path. Legacy title caches retain
# their original semantics; they are never promoted into abstract provenance.
_RESEARCH_PAGE_SIZE = 100
_RESEARCH_RECORD_LIMIT = 25
_RESEARCH_ROUNDS = 4
_RESEARCH_RESPONSE_BYTES = 8 * 1024 * 1024
_RESEARCH_SELECT = ('id,display_name,publication_year,publication_date,doi,'
                    'abstract_inverted_index,updated_date,primary_topic,authorships')


def _research_get(params: dict, *, url: str) -> tuple[dict | None, str | None]:
    """One metered read, with an explicit failure. Never replay or call it empty."""
    request_params = dict(params)
    api_key = os.environ.get('OPENALEX_API_KEY')
    if api_key:
        request_params['api_key'] = api_key
    try:
        response = requests.get(url, params=request_params, headers=_HEADERS, timeout=20)
        if response.status_code != 200:
            return None, 'rate_limited' if response.status_code == 429 else 'http_error'
        data = response.json()
        return (data, None) if type(data) is dict else (None, 'invalid_response')
    except (requests.RequestException, ValueError, TypeError):
        return None, 'request_failed'


def _research_header_number(value) -> float | None:
    """Keep only finite, nonnegative header numbers, never header text."""
    if type(value) not in (str, int, float) or type(value) is str and len(value) > 100:
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and 0 <= number <= 2**53 - 1 else None


def _research_retry_after(value) -> float | None:
    number = _research_header_number(value)
    if number is not None:
        return number
    if type(value) is not str or len(value) > 100:
        return None
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None:
            return None
        return _research_header_number(max(0, date.timestamp() - time.time()))
    except (ValueError, TypeError, OverflowError):
        return None


def research_http_read(params: dict, *, url: str, timeout=20, session=None) -> tuple[dict | None, str | None, dict]:
    """One bounded OpenAlex GET for the durable runner, with safe numeric receipts.

    This new transport does not alter legacy ``_research_get`` callers. A real
    injected Session must also have retries disabled; mock sessions can expose
    only ``get``. Redirects are always disabled, including same-host redirects.
    Responses are capped at eight MiB after decoding. Deadline checks stop
    further reads; they cannot interrupt a currently blocked socket read.
    Invalid local configuration raises before any request; remote failure is a
    sanitized reason, and absent accounting headers remain explicitly unknown.
    """
    if type(url) is not str or re.fullmatch(r'https://api\.openalex\.org/(?:works|authors/A[1-9][0-9]*)', url) is None:
        raise ValueError('invalid_research_url')
    if type(timeout) not in (int, float) or not 0 < timeout <= 20 or not math.isfinite(timeout):
        raise ValueError('invalid_research_timeout')
    if type(params) is not dict or any(type(key) is not str or key.lower() == 'api_key' for key in params):
        raise ValueError('invalid_research_params')
    if isinstance(session, requests.Session):
        retries = session.get_adapter(url).max_retries
        if retries.total not in (0, False):
            raise ValueError('research_transport_retries')
    headers = dict(_HEADERS)
    api_key = os.environ.get('OPENALEX_API_KEY')
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    telemetry = dict.fromkeys(('http_status', 'retry_after_seconds', 'credits_used', 'remaining', 'reset_seconds'))
    get = requests.get if session is None else session.get
    response = None
    deadline = time.monotonic() + timeout
    try:
        response = get(url, params=dict(params), headers=headers, timeout=timeout, allow_redirects=False, stream=True)
        status = response.status_code
        if type(status) is not int or not 100 <= status <= 599:
            return None, 'invalid_response', telemetry
        telemetry['http_status'] = status
        response_headers = requests.structures.CaseInsensitiveDict(response.headers)
        telemetry.update(
            retry_after_seconds=_research_retry_after(response_headers.get('Retry-After')),
            credits_used=_research_header_number(response_headers.get('X-RateLimit-Credits-Used')),
            remaining=_research_header_number(response_headers.get('X-RateLimit-Remaining')),
            reset_seconds=_research_header_number(response_headers.get('X-RateLimit-Reset')),
        )
        if status != 200:
            error = 'rate_limited' if status == 429 else 'server_error' if status >= 500 else 'client_error'
            return None, error, telemetry
        # Count decoded bytes, including compressed responses. Do not trust an
        # absent or incorrect Content-Length, and never read an error body.
        body = bytearray()
        chunks = iter(response.iter_content(chunk_size=8192))
        while True:
            if time.monotonic() >= deadline:
                return None, 'request_failed', telemetry
            try:
                chunk = next(chunks)
            except StopIteration:
                break
            if time.monotonic() >= deadline:
                return None, 'request_failed', telemetry
            if type(chunk) is not bytes or len(body) + len(chunk) > _RESEARCH_RESPONSE_BYTES:
                return None, 'invalid_response', telemetry
            body.extend(chunk)
        try:
            data = json.loads(body)
        except (ValueError, TypeError, RecursionError):
            return None, 'invalid_response', telemetry
        return (data, None, telemetry) if type(data) is dict else (None, 'invalid_response', telemetry)
    except requests.RequestException:
        return None, 'request_failed', telemetry
    finally:
        if response is not None:
            response.close()


def reconstruct_research_abstract(value) -> tuple[str | None, str]:
    """Invert every position, or preserve an explicit absence/error; no prefix."""
    if value is None:
        return None, 'missing'
    if type(value) is not dict or not value:
        return None, 'invalid'
    # At most 12,000 characters can be useful, hence more tokens cannot fit.
    positions: dict[int, str] = {}
    if len(value) > MAX_RESEARCH_ABSTRACT:
        return None, 'too_long'
    for token, indexes in value.items():
        if type(token) is not str or not token.strip() or '\x00' in token:
            return None, 'invalid'
        try:
            token.encode('utf-8')
        except UnicodeEncodeError:
            return None, 'invalid'
        if type(indexes) is not list or not indexes:
            return None, 'invalid'
        if len(token) > MAX_RESEARCH_ABSTRACT or len(indexes) > MAX_RESEARCH_ABSTRACT:
            return None, 'too_long'
        for index in indexes:
            if type(index) is not int or index < 0:
                return None, 'invalid'
            if index >= MAX_RESEARCH_ABSTRACT:
                return None, 'too_long'
            if index in positions:
                return None, 'invalid'
            positions[index] = token
        if len(positions) > MAX_RESEARCH_ABSTRACT:
            return None, 'too_long'
    if set(positions) != set(range(len(positions))):
        return None, 'invalid'
    result = ' '.join(positions[i] for i in range(len(positions)))
    if len(result) > MAX_RESEARCH_ABSTRACT:
        return None, 'too_long'
    return result, 'present'


def _research_author_matches(author: dict, record: dict, author_id: str) -> bool | None:
    """Recheck the previously resolved ID; do not search for a replacement."""
    raw_id = author.get('id')
    if raw_id in ('https://openalex.org/A9999999999', 'https://openalex.org/A5317838346'):
        return False
    if normalized_openalex_id(raw_id, 'A') is None:
        return None
    if normalized_openalex_id(raw_id, 'A') != author_id:
        return False
    if (type(author.get('display_name')) is not str or not author['display_name'].strip()
            or type(author.get('affiliations')) is not list or not author['affiliations']
            or type(author.get('topics')) is not list or not author['topics']):
        return None
    if any(type(a) is not dict or type(a.get('institution')) is not dict
           or normalized_openalex_id(a['institution'].get('id'), 'I') is None
           for a in author['affiliations']):
        return None
    if any(type(t) is not dict or type(t.get('field')) is not dict
           or type(t['field'].get('display_name')) is not str for t in author['topics']):
        return None
    name = record.get('pi_name') or ''
    other_name = author.get('display_name') or ''
    if not isinstance(other_name, str) or _surname(name) != _surname(other_name):
        return False
    if not _given_names_can_be_one_person(name, other_name):
        return False
    inst = normalized_openalex_id(SCHOOL_INST.get(record.get('school')), 'I')
    affiliations = author.get('affiliations')
    if type(affiliations) is not list or not any(
        type(a) is dict and type(a.get('institution')) is dict
        and normalized_openalex_id(a['institution'].get('id'), 'I') == inst
        for a in affiliations
    ):
        return False
    topics = author.get('topics')
    if type(topics) is not list or any(type(t) is not dict or type(t.get('field')) is not dict for t in topics):
        return False
    allowed = _dept_fields(record.get('department') or '')
    if allowed is not None:
        considered = topics[:6]
        count = sum(t['field'].get('display_name') in allowed for t in considered)
        if not (count * 2 >= len(considered) if len(considered) >= 3 else bool(considered) and count == len(considered)):
            return False
    return bool(_author_own_fields(author))


def _research_work(raw: dict, author_id: str, fields: set[str]) -> dict | None:
    authorships = raw.get('authorships')
    if type(authorships) is not list or not any(
        type(a) is dict and type(a.get('author')) is dict
        and normalized_openalex_id(a['author'].get('id'), 'A') == author_id
        for a in authorships
    ):
        return None
    topic = raw.get('primary_topic')
    field = topic.get('field') if type(topic) is dict else None
    if type(field) is not dict or field.get('display_name') not in fields:
        return None
    title = raw.get('display_name')
    if type(title) is str:
        title = re.sub(r'\s+', ' ', title).strip()
    if type(title) is not str or not title.strip() or len(title) > MAX_RESEARCH_TITLE or _is_front_matter(title):
        return None
    work_id = normalized_openalex_id(raw.get('id'), 'W')
    if work_id is None:
        return None
    abstract, status = reconstruct_research_abstract(raw.get('abstract_inverted_index'))
    doi = canonical_doi(raw.get('doi'))
    return {'work_id': work_id, 'title': title, 'year': raw.get('publication_year'),
            'publication_date': raw.get('publication_date'), 'source_url': doi or work_id, 'doi': doi,
            'abstract': abstract, 'abstract_status': status, 'updated_date': raw.get('updated_date')}


def research_works_for_authors(author_fields: dict[str, set[str]], *, rounds: int = _RESEARCH_ROUNDS, request=None) -> dict:
    """Each author gets success only after three usable works or proven exhaustion.

    A full page with no progress, malformed response, absent/truncated authorships
    or round exhaustion is incomplete, not a successful empty list. A new query
    drops served authors; it never pretends one crowded page covers every author.
    """
    if not 1 <= rounds <= _RESEARCH_ROUNDS or len(author_fields) > _RESEARCH_RECORD_LIMIT:
        raise ValueError('research_refresh_limit')
    if any(normalized_openalex_id(a, 'A') != a or not fields for a, fields in author_fields.items()):
        raise ValueError('invalid_research_author')
    read = _research_get if request is None else request
    if not callable(read):
        raise ValueError('invalid_research_request')
    pending = set(author_fields)
    results = {a: {'status': 'incomplete', 'reason': 'round_limit', 'works': []} for a in pending}
    for _ in range(rounds):
        if not pending:
            break
        payload, error = read({
            'filter': 'author.id:' + '|'.join(sorted(a.rsplit('/', 1)[-1] for a in pending)),
            'sort': 'publication_date:desc', 'per_page': _RESEARCH_PAGE_SIZE,
            'select': _RESEARCH_SELECT,
        }, url=_WORKS_API)
        if error:
            for a in pending:
                results[a].update(status='failed', reason=error)
            break
        raw_works = payload.get('results') if type(payload) is dict else None
        meta = payload.get('meta') if type(payload) is dict else None
        count = meta.get('count') if type(meta) is dict else None
        if type(raw_works) is not list or len(raw_works) > _RESEARCH_PAGE_SIZE or any(type(w) is not dict for w in raw_works) or type(count) is not int or count < len(raw_works):
            for a in pending:
                results[a].update(status='failed', reason='invalid_response')
            break
        unsafe_authorships = any(
            type(w.get('authorships')) is not list or not w['authorships'] or len(w['authorships']) >= 100
            or any(type(a) is not dict or type(a.get('author')) is not dict
                   or normalized_openalex_id(a['author'].get('id'), 'A') is None for a in w['authorships'])
            for w in raw_works
        )
        complete = count == len(raw_works) and not unsafe_authorships
        served = set()
        for a in pending:
            works = []
            seen_ids = set()
            for raw in raw_works:
                work = _research_work(raw, a, author_fields[a])
                if work and work['work_id'] not in seen_ids:
                    works.append(work)
                    seen_ids.add(work['work_id'])
                if len(works) == _MAX_WORKS:
                    break
            results[a]['works'] = works
            if len(works) == _MAX_WORKS or complete:
                results[a].update(status='success', reason=None)
                served.add(a)
        if not served:
            for a in pending:
                results[a]['reason'] = 'incomplete_page'
            break
        pending -= served
    return results


def _research_binding(record: dict) -> dict:
    md = record.get('metadata') or {}
    return {'record_source_url': _record_url(record), 'identity_name': record.get('pi_name'),
            'institution_id': normalized_openalex_id(SCHOOL_INST.get(record.get('school')), 'I'),
            'author_id': normalized_openalex_id(md.get('publication_author_id'), 'A'),
            'gate_version': md.get('works_gate')}


def _validate_research_corpus(opps: list[dict]) -> None:
    if type(opps) is not list or any(type(o) is not dict or type(o.get('metadata', {})) is not dict for o in opps):
        raise ValueError('invalid_research_corpus')
    seen_ids = set()
    for record in opps:
        rid = record.get('id')
        if rid is not None:
            if type(rid) is not str or not rid:
                raise ValueError('invalid_research_record_id')
            if rid in seen_ids:
                raise ValueError('duplicate_research_record_id')
            seen_ids.add(rid)


def _iter_research_targets(opps: list[dict], *, schools: list[str] | None = None):
    _validate_research_corpus(opps)
    for record in opps:
        school = record.get('school')
        # Normal national programs have nullable school/pi_name. They are not
        # malformed faculty, and an unrelated school's identity is not this
        # explicitly selected batch's authority decision.
        if type(school) is not str or school not in SCHOOL_INST or (schools and school not in schools):
            continue
        if not _is_faculty(record) or (record.get('metadata') or {}).get('publication_attribution_status') != ATTRIBUTION_VERIFIED:
            continue
        name = record.get('pi_name')
        if type(name) is not str or not name.strip() or len(name) > 200 or normalized_source_url(_record_url(record)) is None:
            raise ValueError('invalid_research_target')
        try:
            name.encode('utf-8')
        except UnicodeEncodeError:
            raise ValueError('invalid_research_target') from None
        if '\x00' in name:
            raise ValueError('invalid_research_target')
        yield record


def research_targets(opps: list[dict], *, schools: list[str] | None = None) -> list[dict]:
    """All eligible faculty for due-time planning, without a first-page cap."""
    return list(_iter_research_targets(opps, schools=schools))


def _research_targets(opps: list[dict], *, limit: int, schools: list[str] | None = None) -> list[dict]:
    """Keep the legacy bounded selector, including its validation boundary."""
    if type(limit) is not int or not 1 <= limit <= _RESEARCH_RECORD_LIMIT:
        raise ValueError('research_refresh_limit')
    selected = []
    for record in _iter_research_targets(opps, schools=schools):
        selected.append(record)
        if len(selected) == limit:
            break
    return selected


def harvest_research_snapshots(opps: list[dict], *, limit: int = 10, schools: list[str] | None = None,
                               now=None, selected_ids: list[str] | None = None, request=None) -> dict:
    """Explicit small refresh, independent from old permanent misses/run-once gate."""
    from datetime import UTC, datetime

    if selected_ids is None:
        targets = _research_targets(opps, limit=limit, schools=schools)
    else:
        if (type(selected_ids) is not list or len(selected_ids) > _RESEARCH_RECORD_LIMIT
                or any(type(rid) is not str or not rid.strip() for rid in selected_ids)
                or len(set(selected_ids)) != len(selected_ids)):
            raise ValueError('invalid_research_selected_ids')
        _validate_research_corpus(opps)
        records_by_id = {record.get('id'): record for record in opps}
        if any(rid not in records_by_id for rid in selected_ids):
            raise ValueError('unavailable_research_selected_id')
        # Validate only the explicitly authorized target identities. Unselected
        # legacy source errors belong to the queue's visible review outcomes;
        # full-corpus duplicate IDs and author collisions still fail closed.
        selected_records = [records_by_id[rid] for rid in selected_ids]
        targets = research_targets(selected_records, schools=schools)
        if len(targets) != len(selected_ids):
            raise ValueError('unavailable_research_selected_id')
        # Explicit queue order is authoritative. Never silently fall back to the
        # corpus prefix or truncate it with the legacy default limit of ten.
    read = _research_get if request is None else request
    if not callable(read):
        raise ValueError('invalid_research_request')
    current = datetime.now(UTC) if now is None else now
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError('invalid_research_time')
    stamp = current.astimezone(UTC).isoformat().replace('+00:00', 'Z')
    # Known cross-person ID collisions are checked across the corpus, including
    # other schools, without allowing an unrelated malformed identity to crash
    # this batch. Such a malformed row is never an eligible source itself.
    ambiguous = ambiguous_author_ids([
        o for o in opps if type(o.get('pi_name')) is str
        and type((o.get('metadata') or {}).get('publication_author_id')) is str
    ])
    output = {}
    author_fields = {}
    for record in targets:
        binding = _research_binding(record)
        aid = binding['author_id']
        entry = {'binding': binding, 'research_refresh': {'checked_at': stamp, 'status': 'failed', 'reason': 'identity_unavailable'}}
        output[_person_key(record)] = entry
        gate = binding['gate_version']
        if aid is None or aid in ambiguous or type(gate) is not int or gate < _WORKS_GATE:
            if aid in ambiguous or binding['author_id'] is None:
                entry['research_refresh']['reason'] = 'identity_revoked'
            continue
        author, error = read({'select': 'id,display_name,affiliations,topics'}, url=_API + '/' + aid.rsplit('/', 1)[-1])
        if error:
            entry['research_refresh']['reason'] = error
            continue
        matched = _research_author_matches(author, record, aid) if type(author) is dict else None
        if matched is not True:
            entry['research_refresh']['reason'] = 'identity_revoked' if matched is False else 'invalid_response'
            continue
        author_fields[aid] = _author_own_fields(author)
        entry['_eligible'] = True
    fetched = research_works_for_authors(author_fields, request=read) if author_fields else {}
    for record in targets:
        entry = output[_person_key(record)]
        binding = entry['binding']
        result = fetched.get(binding['author_id'])
        # An author shared by equivalent records still has to pass this record's
        # own identity check. Failure must never borrow another record's success.
        if entry['research_refresh']['reason'] != 'identity_unavailable' or result is None:
            continue
        # Rejected identity and eligible entries are tracked separately below.
        if not entry.pop('_eligible', False):
            continue
        entry['research_refresh'].update(status=result['status'], reason=result['reason'])
        if result['status'] == 'success':
            snapshot = {'version': 1, 'source': 'openalex', **binding, 'checked_at': stamp, 'works': result['works']}
            valid = validate_research_snapshot(snapshot, record, now=current)
            if valid is not None:
                entry['research_snapshot'] = valid
            else:
                entry['research_refresh'].update(status='failed', reason='invalid_work')
    return output


def apply_research_refresh(opps: list[dict], mapping: dict, *, now=None) -> int:
    """Apply an explicit refresh patch in memory; failures retain last success."""
    from datetime import UTC, datetime

    _validate_research_corpus(opps)
    if type(mapping) is not dict or len(mapping) > _RESEARCH_RECORD_LIMIT:
        raise ValueError('research_refresh_limit')
    current = datetime.now(UTC) if now is None else now
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError('invalid_research_time')
    changed = 0
    for record in opps:
        entry = mapping.get(_person_key(record))
        if type(entry) is not dict or entry.get('binding') != _research_binding(record):
            continue
        md = record.get('metadata') or {}
        if md.get('publication_attribution_status') != ATTRIBUTION_VERIFIED:
            continue
        refresh = entry.get('research_refresh')
        if type(refresh) is not dict or set(refresh) != {'checked_at', 'status', 'reason'}:
            continue
        try:
            stamp = refresh['checked_at']
            if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', stamp):
                continue
            refreshed_at = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if refreshed_at > current:
                continue
            last_stamp = (md.get('research_refresh') or {}).get('checked_at')
            if last_stamp and datetime.fromisoformat(last_stamp.replace('Z', '+00:00')) > refreshed_at:
                continue
            # Every outcome is ordered against the last success too. Private
            # attempt metadata may legitimately be absent after an import; an
            # older failure must not revoke or relabel a newer successful read.
            previous = md.get('research_snapshot')
            if type(previous) is dict:
                if datetime.fromisoformat(previous['checked_at'].replace('Z', '+00:00')) > refreshed_at:
                    continue
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        reasons = {'rate_limited', 'http_error', 'server_error', 'client_error', 'invalid_response', 'request_failed', 'identity_unavailable',
                   'identity_revoked', 'incomplete_page', 'round_limit', 'invalid_work'}
        if type(refresh['status']) is not str or (refresh['reason'] is not None and type(refresh['reason']) is not str):
            continue
        if ((refresh['status'] == 'success' and refresh['reason'] is not None)
                or (refresh['status'] != 'success' and refresh['reason'] not in reasons)):
            continue
        snapshot = validate_research_snapshot(entry.get('research_snapshot'), record, now=current)
        if refresh.get('status') == 'success':
            if snapshot is None or snapshot['checked_at'] != refresh['checked_at']:
                continue
            md['research_snapshot'] = snapshot
            md['recent_works'] = [{'title': w['title'], 'year': w['year']} for w in snapshot['works']]
        elif refresh.get('status') not in ('failed', 'incomplete'):
            continue
        if refresh['reason'] == 'identity_revoked':
            md.pop('publication_attribution_status', None)
        # This is private operational state, never a new success timestamp.
        md['research_refresh'] = dict(refresh)
        record['metadata'] = md
        changed += 1
    return changed


def _research_cli(argv: list[str]) -> int:
    """No implicit corpus rewrite: refresh produces an explicit bounded patch."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(prog='openalex_enrich refresh-research')
    parser.add_argument('--input', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--limit', required=True, type=int, choices=range(1, _RESEARCH_RECORD_LIMIT + 1))
    parser.add_argument('--schools')
    args = parser.parse_args(argv)
    source, dest = Path(args.input), Path(args.out)
    if dest.exists():
        parser.error('--out already exists; choose a new patch file')
    if source.resolve() == dest.resolve():
        parser.error('--out must differ from --input')
    records = json.loads(source.read_text())
    if type(records) is not list or any(type(record) is not dict for record in records):
        parser.error('--input must be a corpus array')
    result = harvest_research_snapshots(records, limit=args.limit, schools=args.schools.split(',') if args.schools else None)
    # Exclusive create: never erase an earlier diagnostic/success artifact.
    with dest.open('x') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'Refreshed {len(result)} records into {dest}; input corpus unchanged.')
    return 0


def _apply_research_cli(argv: list[str]) -> int:
    """Explicit local candidate apply; never overwrite the input or an earlier output."""
    import argparse
    import tempfile
    from pathlib import Path

    parser = argparse.ArgumentParser(prog='openalex_enrich apply-research')
    parser.add_argument('--input', required=True)
    parser.add_argument('--patch', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    source, patch = Path(args.input), Path(args.patch)
    dest = Path(args.out)
    if patch.resolve() == source.resolve() or patch.resolve() == dest.resolve():
        parser.error('patch and corpus paths must differ')
    if dest.resolve() == source.resolve() or dest.exists():
        parser.error('--out must be a new file distinct from --input')
    if patch.stat().st_size > 2 * 1024 * 1024:
        parser.error('patch exceeds 2 MiB')
    original = source.read_bytes()
    records, mapping = json.loads(original), json.loads(patch.read_text())
    if type(records) is not list or any(type(o) is not dict for o in records):
        parser.error('--input must be a corpus array')
    try:
        applied = apply_research_refresh(records, mapping)
    except ValueError as error:
        parser.error(str(error))
    encoded = json.dumps(records, ensure_ascii=False, indent=2).encode('utf-8')
    with tempfile.NamedTemporaryFile(dir=dest.parent, prefix='.research-apply-', delete=False) as f:
        temp = Path(f.name)
        f.write(encoded)
        f.flush()
        os.fsync(f.fileno())
    try:
        # A separate reviewable candidate, not an in-place CAS. Other corpus
        # writers need not cooperate with a new lock or lose their latest work.
        os.link(temp, dest)
    finally:
        temp.unlink(missing_ok=True)
    print(f'Applied {applied} bounded refresh entries into {dest}.')
    return 0


# --- re-checking the papers a verified record already holds -----------------
#
# The per-paper affiliation check binds future harvests only. A record stamped
# verified at the current gate is never a works target again, and what it
# stores is a title and a year, nothing the check can be run against. So its
# papers are fetched again and judged where they stand. CURRENT_WORKS_GATE
# stays put (tests on in-flight branches pin it), which is why this is an
# explicit command over the stamped population rather than a gate bump that
# would withdraw every record's trust first.
#
# Judging and writing are two commands, as refresh-research and apply-research
# are. recheck-works spends the credits and writes its outcomes to a report,
# never to the corpus; apply-recheck writes a reviewed report and makes no
# request. What lands is then exactly what was reviewed, and the credits are
# spent once, not again on a second fetch that could answer differently.

_RECHECK_SELECT = "id,display_name,publication_year,primary_topic,authorships"
_RECHECK_PAGE_SIZE = 200
# Requests one batch of authors may spend finding its stored papers before the
# rest are reported as not found.
_RECHECK_BATCH_PAGES = 6
_RECHECK_MIN_REMAINING = 100


class _RecheckBudget:
    """The run's request accounting, consulted before every request."""

    def __init__(self, max_requests: int, min_remaining: int):
        self.max_requests = max_requests
        self.min_remaining = min_remaining
        self.requests = 0
        self.first_remaining: float | None = None
        self.remaining: float | None = None
        self.stopped: str | None = None

    def allows(self) -> bool:
        if self.stopped is None and self.requests >= self.max_requests:
            self.stopped = "max_requests"
        # x-ratelimit-remaining from the previous page. An absent header is no
        # reading at all; the 429 below still stops the run.
        if (self.stopped is None and self.remaining is not None
                and self.remaining < self.min_remaining):
            self.stopped = "remaining_below_floor"
        return self.stopped is None

    def spent(self, error: str | None, telemetry: dict) -> None:
        self.requests += 1
        self.remaining = telemetry.get("remaining")
        if self.first_remaining is None:
            self.first_remaining = self.remaining
        if error == "rate_limited":
            self.stopped = "rate_limited"


def _recheck_batch(wanted: dict[str, set[str]], *, read, budget: _RecheckBudget,
                   page_size: int = _RECHECK_PAGE_SIZE) -> dict[str, dict]:
    """Find each author's stored papers among the works OpenAlex lists for them.

    ``wanted`` maps an author id to the version keys of the titles its records
    hold. Per author, returns the works routed to them and how the search
    ended: ``located`` (every title found), ``exhausted`` (every work listed
    for them was read and a title is still missing), ``page_cap`` (stopped
    looking), ``failed`` (a request failed) or ``not_run`` (the budget stopped
    first).

    Rounds work as in ``works_for_authors``: authors whose titles are all found
    leave the filter and page 1 is asked again, so a prolific author stops
    crowding out the rest. Only when a full page settles nobody does it page
    deeper into the same filter.
    """
    out = {aid: {"works": [], "status": "not_run", "reason": None} for aid in wanted}
    unfound = {aid: set(keys) for aid, keys in wanted.items()}
    pending = set(wanted)
    page = spent = 0
    while pending:
        if spent >= _RECHECK_BATCH_PAGES:
            for aid in pending:
                out[aid]["status"] = "page_cap"
            break
        if not budget.allows():
            for aid in pending:
                out[aid]["reason"] = budget.stopped
            break
        page += 1
        data, error, telemetry = read({
            "filter": "author.id:" + "|".join(sorted(pending)),
            "sort": "publication_date:desc",
            "per_page": page_size,
            "page": page,
            "select": _RECHECK_SELECT,
        }, url=_WORKS_API)
        budget.spent(error, telemetry or {})
        spent += 1
        results = data.get("results") if isinstance(data, dict) else None
        meta = data.get("meta") if isinstance(data, dict) else None
        count = meta.get("count") if isinstance(meta, dict) else None
        if (error or not isinstance(results, list) or not isinstance(count, int)
                or any(not isinstance(w, dict) for w in results)):
            for aid in pending:
                out[aid].update(status="failed", reason=error or "invalid_response")
            break
        for w in results:
            key = _work_version_key(w)
            for a in w.get("authorships") or []:
                if not isinstance(a, dict):
                    continue
                aid = str((a.get("author") or {}).get("id") or "").rsplit("/", 1)[-1]
                if aid in pending:
                    out[aid]["works"].append(w)
                    unfound[aid].discard(key)
        if page * page_size >= count:
            for aid in pending:
                out[aid]["status"] = "exhausted" if unfound[aid] else "located"
            break
        served = {aid for aid in pending if not unfound[aid]}
        for aid in served:
            out[aid]["status"] = "located"
        if served:
            pending -= served
            page = 0
    return out


def _recheck_record(record: dict, found: dict) -> dict:
    """What the per-paper affiliation check says about each paper this record holds.

    A paper is removed only on evidence: it was found, and no version of it
    (a preprint and its journal version share a title) is admitted. A paper
    that could not be found keeps its place and is reported, because not
    finding it is not a verdict. Nothing is added or reordered.
    """
    md = record.get("metadata") or {}
    aid = str(md.get("publication_author_id") or "").rsplit("/", 1)[-1]
    inst = SCHOOL_INST[record["school"]]
    before = list(md.get("recent_works") or [])
    outcome = {
        "id": record.get("id"), "pi_name": record.get("pi_name"),
        "school": record.get("school"), "author_id": aid,
        "status": "not_run", "search": found["status"], "reason": found["reason"],
        "before": before, "after": before,
        "removed": [], "kept_unlisted": [], "unfound": [],
    }
    if found["status"] in ("failed", "not_run"):
        return outcome
    versions: dict[str, list[dict]] = {}
    for w in found["works"]:
        versions.setdefault(_work_version_key(w), []).append(w)
    kept: list[dict] = []
    for paper in before:
        candidates = versions.get(_version_key(str(paper.get("title") or "")))
        if not candidates:
            outcome["unfound"].append(paper)
            kept.append(paper)
            continue
        verdict = _strongest_affiliation({_paper_affiliation(w, aid, inst) for w in candidates})
        if verdict == "school":
            kept.append(paper)
        elif _affiliation_admits(verdict):
            outcome["kept_unlisted"].append(paper)
            kept.append(paper)
        else:
            own = [_own_authorship(w, aid) or {} for w in candidates]
            outcome["removed"].append({
                **paper,
                "verdict": verdict,
                "institutions": sorted({
                    i.get("display_name") or i.get("id") or ""
                    for a in own for i in a.get("institutions") or [] if isinstance(i, dict)}),
                "raw_affiliations": sorted({
                    s for a in own for s in a.get("raw_affiliation_strings") or [] if isinstance(s, str)}),
                "work_ids": [w.get("id") for w in candidates],
            })
    outcome["after"] = kept
    outcome["status"] = "partial" if outcome["unfound"] else "checked"
    return outcome


def recheck_targets(opps: list[dict], *, schools: list[str] | None = None) -> list[dict]:
    """Faculty whose papers are stamped verified through an author id."""
    out = []
    for o in opps:
        md = o.get("metadata") or {}
        if not _is_faculty(o) or not works_are_verified(o):
            continue
        if o.get("school") not in SCHOOL_INST or (schools and o.get("school") not in schools):
            continue
        # A research snapshot's works were validated on their own path and the
        # title list mirrors them; apply_works leaves such records alone too.
        if "research_snapshot" in md:
            continue
        if not (o.get("id") and md.get("publication_author_id") and md.get("recent_works")):
            continue
        out.append(o)
    return out


def recheck_works(targets: list[dict], *, max_requests: int,
                  min_remaining: int = _RECHECK_MIN_REMAINING, read=None,
                  batch_size: int = _WORKS_BATCH, page_size: int = _RECHECK_PAGE_SIZE) -> dict:
    """Judge every stored paper of ``targets`` against its re-fetched authorship.

    Pure with respect to the records: returns ``{"outcomes": {id: outcome},
    "requests", "first_remaining", "remaining", "stopped"}`` and leaves the
    corpus alone. ``apply_recheck`` writes the outcomes.
    """
    read = research_http_read if read is None else read
    wanted: dict[str, set[str]] = {}
    for record in targets:
        aid = str(record["metadata"]["publication_author_id"]).rsplit("/", 1)[-1]
        wanted.setdefault(aid, set()).update(
            _version_key(str(w.get("title") or "")) for w in record["metadata"]["recent_works"])
    budget = _RecheckBudget(max_requests, min_remaining)
    found: dict[str, dict] = {}
    authors = list(wanted)
    for i in range(0, len(authors), batch_size):
        batch = {aid: wanted[aid] for aid in authors[i:i + batch_size]}
        found.update(_recheck_batch(batch, read=read, budget=budget, page_size=page_size))
    outcomes = {}
    for record in targets:
        aid = str(record["metadata"]["publication_author_id"]).rsplit("/", 1)[-1]
        outcomes[record["id"]] = _recheck_record(record, found[aid])
    return {"outcomes": outcomes, "requests": budget.requests,
            "first_remaining": budget.first_remaining, "remaining": budget.remaining,
            "stopped": budget.stopped}


def apply_recheck(opps: list[dict], outcomes: dict[str, dict]) -> dict[str, list[str]]:
    """Write each judged record's surviving papers.

    Returns the ids it ``changed`` (``retracted`` among them: left with nothing
    to cite) and the ids it left alone as ``stale``: the outcome would change
    the record, but the record no longer holds the papers that were judged, or
    is gone. An outcome the run could not judge carries ``after == before``
    and changes nothing.
    """
    result: dict[str, list[str]] = {"changed": [], "retracted": [], "stale": []}
    wanted = {rid for rid, out in outcomes.items() if out["after"] != out["before"]}
    present: set[str] = set()
    for record in opps:
        rid = record.get("id")
        if rid not in wanted:
            continue
        present.add(rid)
        out = outcomes[rid]
        md = record.get("metadata") or {}
        if (md.get("recent_works") or []) != out["before"]:
            result["stale"].append(rid)
            continue
        if out["after"]:
            md["recent_works"] = out["after"]
        else:
            # Nothing left to cite: the same retraction apply_works makes when
            # the gate rejects every paper.
            md.pop("recent_works", None)
            md.pop("publication_attribution_status", None)
            md.pop("publication_author_id", None)
            md["works_gate"] = _WORKS_GATE
            result["retracted"].append(rid)
        result["changed"].append(rid)
    result["stale"].extend(sorted(wanted - present))
    return result


def _recheck_report_outcomes(report) -> dict[str, dict]:
    """A recheck-works report's outcomes by record id, checked as input.

    apply-recheck writes what the report says, and a report is a file a person
    reviews and may edit: put a paper back into ``after`` to keep it, or delete
    a record's outcome to leave the record alone. It may never add a paper or
    reorder them, so an ``after`` that is not ``before`` with papers taken out
    refuses the whole report, as does anything that is not a report.
    """
    outcomes = report.get("outcomes") if isinstance(report, dict) else None
    if not isinstance(outcomes, list):
        raise ValueError("not a recheck-works report")
    by_id: dict[str, dict] = {}
    for out in outcomes:
        if not (isinstance(out, dict) and isinstance(out.get("id"), str)
                and isinstance(out.get("before"), list) and isinstance(out.get("after"), list)):
            raise ValueError("an outcome lacks its id, before or after")
        if out["id"] in by_id:
            raise ValueError(f"two outcomes for {out['id']}")
        remaining = iter(out["before"])
        if not all(any(paper == held for held in remaining) for paper in out["after"]):
            raise ValueError(f"the outcome for {out['id']} adds or reorders a paper")
        by_id[out["id"]] = out
    return by_id


def _recheck_cli(argv: list[str]) -> int:
    """Judge and report. The estimate is printed before any request, and the
    corpus is never written: ``apply-recheck`` writes a reviewed report."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="openalex_enrich recheck-works",
        description="Re-fetch the papers of records stamped verified_author_id and report "
                    "the ones whose authorship does not place the author at the school. "
                    "Writes only the report; apply-recheck writes it into the corpus.")
    parser.add_argument("--input", default=str(PROCESSED_FILE))
    parser.add_argument("--schools")
    parser.add_argument("--ids-file", help="only these record ids, one per line")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-requests", type=int, required=True,
                        help="hard ceiling on OpenAlex requests (1 credit each)")
    parser.add_argument("--min-remaining", type=int, default=_RECHECK_MIN_REMAINING,
                        help="stop when x-ratelimit-remaining falls below this")
    parser.add_argument("--batch-size", type=int, default=_WORKS_BATCH,
                        help=f"authors per request, 1 to {_WORKS_BATCH}")
    parser.add_argument("--page-size", type=int, default=_RECHECK_PAGE_SIZE,
                        help=f"works per page, 1 to {_RECHECK_PAGE_SIZE}. A page over the "
                             "transport's 8 MiB cap fails as invalid_response and its authors "
                             "are reported as not run; rerun those ids with smaller sizes")
    parser.add_argument("--report", required=True,
                        help="new file for every record's outcome; apply-recheck reads it")
    args = parser.parse_args(argv)
    if args.max_requests < 0:
        parser.error("--max-requests must be 0 or more")
    if not 1 <= args.batch_size <= _WORKS_BATCH:
        parser.error(f"--batch-size must be 1 to {_WORKS_BATCH}")
    if not 1 <= args.page_size <= _RECHECK_PAGE_SIZE:
        parser.error(f"--page-size must be 1 to {_RECHECK_PAGE_SIZE}")
    report = Path(args.report)
    # Checked before a credit is spent: the outcomes of a paid run land here.
    if report.exists() or not report.parent.is_dir():
        parser.error("--report must name a new file in an existing directory")

    source = Path(args.input)
    records = json.loads(source.read_text(encoding="utf-8"))
    schools = args.schools.split(",") if args.schools else None
    targets = recheck_targets(records, schools=schools)
    if args.ids_file:
        ids = {line.strip() for line in Path(args.ids_file).read_text().splitlines() if line.strip()}
        targets = [t for t in targets if t["id"] in ids]
        missing = len(ids - {t["id"] for t in targets})
        if missing:
            print(f"recheck-works: {missing} listed id(s) are not verified faculty records here")
    if args.limit is not None:
        targets = targets[:args.limit]
    n_authors = len({str(t["metadata"]["publication_author_id"]).rsplit("/", 1)[-1]
                     for t in targets})
    batches = -(-n_authors // args.batch_size)
    print(f"recheck-works: {len(targets)} records, {n_authors} authors, {batches} "
          f"batch(es) of up to {args.batch_size}. Estimated cost: {batches} to "
          f"{batches * _RECHECK_BATCH_PAGES} requests at 1 credit each; this run "
          f"stops at {args.max_requests} or when x-ratelimit-remaining < "
          f"{args.min_remaining}.", flush=True)

    result = recheck_works(targets, max_requests=args.max_requests,
                           min_remaining=args.min_remaining,
                           batch_size=args.batch_size, page_size=args.page_size)
    outcomes = result["outcomes"]
    by_status = collections.Counter(o["status"] for o in outcomes.values())
    verdicts = collections.Counter(p["verdict"] for o in outcomes.values() for p in o["removed"])
    held = sum(len(o["before"]) for o in outcomes.values() if o["status"] != "not_run")
    removed = sum(len(o["removed"]) for o in outcomes.values())
    print(f"records: {by_status.get('checked', 0)} checked, {by_status.get('partial', 0)} "
          f"with a paper not found, {by_status.get('not_run', 0)} not run"
          + (f" ({result['stopped']})" if result["stopped"] else ""))
    print(f"papers: {held} held by judged records, {removed} removed "
          f"({', '.join(f'{k} {v}' for k, v in sorted(verdicts.items())) or 'none'}), "
          f"{sum(len(o['kept_unlisted']) for o in outcomes.values())} kept with no "
          f"affiliation listed, {sum(len(o['unfound']) for o in outcomes.values())} not found")
    print(f"records losing a paper: {sum(1 for o in outcomes.values() if o['removed'])}; "
          f"losing all: {sum(1 for o in outcomes.values() if o['removed'] and not o['after'])}")
    print(f"requests: {result['requests']}; x-ratelimit-remaining: "
          f"{result['first_remaining']} -> {result['remaining']}")
    for o in outcomes.values():
        if o["status"] == "not_run":
            print(f"  not run: {o['id']} ({o['reason'] or o['search']})")
    with report.open("x", encoding="utf-8") as f:
        json.dump({**result, "outcomes": list(outcomes.values())}, f, ensure_ascii=False, indent=2)
    print(f"report -> {report}; corpus not written. Review it, then write exactly these "
          f"outcomes, with no further request: python -m src.collectors.openalex_enrich "
          f"apply-recheck {report} --input {source}")
    return 0


def _apply_recheck_cli(argv: list[str]) -> int:
    """Write a reviewed recheck-works report into the corpus. No request."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="openalex_enrich apply-recheck",
        description="Remove the papers a reviewed recheck-works report removes. Run it on "
                    "a work file just assembled from the current main "
                    "(scripts/shard_corpus.py assemble --force): split rewrites each "
                    "touched school's shard from whatever the work file holds.")
    parser.add_argument("report")
    parser.add_argument("--input", default=str(PROCESSED_FILE))
    args = parser.parse_args(argv)
    try:
        outcomes = _recheck_report_outcomes(json.loads(Path(args.report).read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        parser.error(f"{args.report}: {error}")

    source = Path(args.input)
    records = json.loads(source.read_text(encoding="utf-8"))
    result = apply_recheck(records, outcomes)
    stale = result["stale"]
    if stale:
        print(f"{len(stale)} record(s) changed or gone since the report was written, left alone: "
              + ", ".join(stale[:20]) + (f" and {len(stale) - 20} more" if len(stale) > 20 else ""))
    if not result["changed"]:
        print("applied: no record changed; corpus not written")
        return 0
    atomic_write_json(source, records, indent=None, separators=(",", ":"))
    changed = set(result["changed"])
    schools = sorted({r["school"] for r in records if r.get("id") in changed})
    print(f"applied: {len(changed)} record(s) changed, {len(result['retracted'])} of them left "
          f"with no paper and retracted -> {source}")
    print(f"publish: python scripts/shard_corpus.py split --only-shards {','.join(schools)}")
    return 0


def _cli(argv: list[str]) -> int:
    _load_dotenv()
    if not argv or argv[0] not in ("harvest", "roster", "apply", "works",
                                   "works-roster", "apply-works", "refresh-research", "apply-research",
                                   "recheck-works", "apply-recheck"):
        print(__doc__)
        return 2
    mode, rest = argv[0], argv[1:]
    if mode == "recheck-works":
        return _recheck_cli(rest)
    if mode == "apply-recheck":
        return _apply_recheck_cli(rest)
    if mode == "refresh-research":
        return _research_cli(rest)
    if mode == "apply-research":
        return _apply_research_cli(rest)
    if mode == "roster":
        schools = rest[0].split(",") if rest and not rest[0].startswith("-") else None
        out = "openalex.json"
        roster_dir = "data/openalex_rosters"
        for i, a in enumerate(rest):
            if a == "--out":
                out = rest[i + 1]
            elif a == "--roster-dir":
                roster_dir = rest[i + 1]
        opps = json.load(open(PROCESSED_FILE))
        mapping, reasons = harvest_openalex_roster(
            opps, schools=schools, progress=True, roster_dir=roster_dir,
        )
        json.dump(mapping, open(out, "w"), indent=2)
        total = sum(reasons.values())
        print(f"matched {len(mapping)} faculty -> {out}")
        for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {why:18} {n:6} ({n / max(1, total) * 100:5.1f}%)")
        return 0
    if mode == "works-roster":
        schools = rest[0].split(",") if rest and not rest[0].startswith("-") else None
        out = "works.json"
        roster_dir = "data/openalex_rosters"
        for i, a in enumerate(rest):
            if a == "--out":
                out = rest[i + 1]
            elif a == "--roster-dir":
                roster_dir = rest[i + 1]
        opps = json.load(open(PROCESSED_FILE))
        mapping, reasons = harvest_works_by_roster(
            opps, schools=schools, progress=True, roster_dir=roster_dir,
        )
        json.dump(mapping, open(out, "w"), indent=2)
        total = sum(reasons.values())
        print(f"matched {len(mapping)} faculty with citable papers -> {out}")
        for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {why:18} {n:6} ({n / max(1, total) * 100:5.1f}%)")
        return 0
    if mode in ("harvest", "works"):
        schools = rest[0].split(",") if rest and not rest[0].startswith("-") else None
        out = "openalex.json"
        sample = None
        resume = "--resume" in rest
        for i, a in enumerate(rest):
            if a == "--out":
                out = rest[i + 1]
            elif a == "--sample":
                sample = int(rest[i + 1])
        opps = json.load(open(PROCESSED_FILE))
        fn = harvest_openalex if mode == "harvest" else harvest_works
        # checkpoint_path=out makes the harvest flush partial results as it
        # goes, so a metered-budget 429 mid-run preserves paid-for records.
        # --resume reloads that checkpoint and skips already-harvested URLs, so a
        # run continued the next day never re-pays for records already collected.
        mapping = fn(
            opps, schools=schools, sample=sample, progress=True,
            checkpoint_path=out, resume=resume,
        )
        json.dump(mapping, open(out, "w"), indent=2)
        print(f"matched {len(mapping)} faculty -> {out}")
        return 0
    opps = json.load(open(PROCESSED_FILE))
    # `apply-works` with no map files restores recent_works from the committed
    # works library — the free, re-runnable path back to full coverage after a
    # rebuild. `apply` (topics) still requires explicit maps.
    files = rest or ([WORKS_STORE] if mode == "apply-works" else [])
    merged: dict = {}
    for f in files:
        merged.update(json.load(open(f)))
    n = (apply_openalex if mode == "apply" else apply_works)(opps, merged)
    json.dump(opps, open(PROCESSED_FILE, "w"), ensure_ascii=False, indent=2)
    print(f"applied {n} enrichments from {len(rest)} map(s) -> {PROCESSED_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
