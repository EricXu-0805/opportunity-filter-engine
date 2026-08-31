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
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata

import requests

from ..evidence import stamp_inferred
from ..publication_trust import (
    NAME_MATCH as ATTRIBUTION_NAME_MATCH,
)
from ..publication_trust import (
    VERIFIED_AUTHOR_ID as ATTRIBUTION_VERIFIED,
)
from ..publication_trust import (
    works_are_verified,
)
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

# school slug -> OpenAlex institution id (resolved once via /institutions). The
# id is matched against each candidate author's full affiliation history, so a
# professor who has since moved is still matched while a same-name person at a
# different school is rejected.
SCHOOL_INST = {
    "uiuc": "I157725225",
    "uw": "I201448701",
    "ucla": "I161318765",
    "utexas": "I86519309",
    "stanford": "I97018004",
    "gatech": "I130701444",
    "wisc": "I135310074",
    # Verified 2026-07-05 via GET /institutions?search=… (display_name + ROR):
    "ucb": "I95457486",        # University of California, Berkeley (ror 01an7q238)
    "umich": "I27837315",      # University of Michigan [Ann Arbor] (ror 00jmfr291)
    "princeton": "I20089843",  # Princeton University (ror 00hx57361)
    "ucsd": "I36258959",       # University of California San Diego (ror 0168r3w48)
    "uchicago": "I40347166",   # University of Chicago (ror 024mw5h28)
    "ucd": "I84218800",        # University of California, Davis (API-verified 2026-07-21)
    "uci": "I204250578",       # University of California, Irvine (ror 04gyf1771)
    "ucsb": "I154570441",      # University of California, Santa Barbara (ror 02t274463)
    "boulder": "I188538660",   # University of Colorado Boulder (ror 02ttsq026)
    "purdue": "I219193219",    # Purdue University West Lafayette (ror 02dqehb95)
    "duke": "I170897317",      # Duke University (ror 00py81415)
    "jhu": "I145311948",       # Johns Hopkins University (OpenAlex-API verified)
    "northwestern": "I111979921",  # Northwestern University (OpenAlex-API verified)
    "upenn": "I79576946",      # University of Pennsylvania (OpenAlex-API verified)
    "caltech": "I122411786",   # California Institute of Technology (OpenAlex-API verified)
    # LAC ranks 11-25 (2026-07-23)
    "grinnell": "I173288447",  # Grinnell College
    "colby": "I27504731",  # Colby College
    "hamilton": "I188592606",  # Hamilton College
    "vassar": "I126820664",  # Vassar College
    "smith": "I202524275",  # Smith College
    "wlu": "I184889055",  # Washington and Lee University
    "colgate": "I39660569",  # Colgate University
    "wesleyan": "I100538780",  # Wesleyan University
    "haverford": "I155707491",  # Haverford College
    "bates": "I37415318",  # Bates College
    "barnard": "I98540497",  # Barnard College
    "coloradocollege": "I189774192",  # Colorado College
    "macalester": "I5444425",  # Macalester College
    "kenyon": "I166972335",  # Kenyon College
    "brynmawr": "I102373834",  # Bryn Mawr College
    # Top-10 liberal arts colleges (2026-07-21)
    "amherst": "I177605424",  # Amherst College
    "swarthmore": "I118020396",  # Swarthmore College
    "pomona": "I177881444",  # Pomona College
    "wellesley": "I189731429",  # Wellesley College
    "bowdoin": "I135474949",  # Bowdoin College
    "carleton": "I188497080",  # Carleton College
    "cmc": "I106107269",  # Claremont McKenna College
    "middlebury": "I195575238",  # Middlebury College
    "davidson": "I141720752",  # Davidson College
    # Wave-3 batch 1 (2026-07-20)
    "bc": "I103531236",  # Boston College
    "emory": "I150468666",  # Emory University
    "georgetown": "I184565670",  # Georgetown University
    "nyu": "I57206974",  # New York University
    "tufts": "I121934306",  # Tufts University
    "uva": "I51556381",  # University of Virginia
    "cornell": "I205783295",   # Cornell University (ror 05bnh6r87, OpenAlex-API verified)
    "rice": "I74775410",       # Rice University (ror 008zs3103, OpenAlex-API verified)
    "vanderbilt": "I200719446",  # Vanderbilt University (ror 02vm5rt34, OpenAlex-API verified)
    "brown": "I27804330",      # Brown University (ror 05gq02987, OpenAlex-API verified)
    "dartmouth": "I107672454",  # Dartmouth College (ror 049s0rh22, OpenAlex-API verified)
    "columbia": "I78577930",
    "mit": "I63966007",        # Massachusetts Institute of Technology (ror 042nb2s44, OpenAlex-API verified)
    "harvard": "I136199984",   # Harvard University (ror 03vek6s52, OpenAlex-API verified)
    "yale": "I32971472",       # Yale University (ror 03v76x132, OpenAlex-API verified)
    "cmu": "I74973139",        # Carnegie Mellon University (ror 05x2bcf33, OpenAlex-API verified)
    # Verified 2026-07-17 via GET /institutions?search=… (Wave-1 final seven):
    "usc": "I1174212",         # University of Southern California
    "umn": "I130238516",       # University of Minnesota [Twin Cities]
    "osu": "I52357470",        # The Ohio State University
    "nd": "I107639228",        # University of Notre Dame
    "rochester": "I5388228",   # University of Rochester
    "uf": "I33213144",         # University of Florida
    "umass": "I24603500",      # University of Massachusetts Amherst
    # Verified 2026-07-18 via GET /institutions?search=… (Wave-2 batch 1):
    "vt": "I859038795",        # Virginia Tech
    "tamu": "I91045830",       # Texas A&M University
    "umd": "I66946132",        # University of Maryland, College Park
    "neu": "I12912129",        # Northeastern University (US — NOT the CN homonym I9224756)
    "sbu": "I59553526",        # Stony Brook University
    "bu": "I111088046",        # Boston University
    "washu": "I204465549",     # Washington University in St. Louis
    "rutgers": "I102322142",   # Rutgers, The State University of New Jersey
    "ncsu": "I137902535",      # North Carolina State University
    "psu": "I130769515",       # Pennsylvania State University
    "ucsc": "I185103710",      # University of California, Santa Cruz
    "arizona": "I138006243",   # University of Arizona
    "ucr": "I103635307",       # University of California, Riverside
    "asu": "I55732556",        # Arizona State University
    "pitt": "I170201317",      # University of Pittsburgh
    "msu": "I87216513",        # Michigan State University
    "buffalo": "I63190737",
    "fsu": "I103163165",
    "usf": "I2613432",
    "utk": "I75027704",
    "clemson": "I8078737",
    "colostate": "I92446798",
    "oregonstate": "I131249849",
    "drexel": "I72816309",
    # Wave-5 batch 1 (2026-07-20)
    "stevens": "I108468826",  # Stevens Institute of Technology
    "njit": "I118118575",  # New Jersey Institute of Technology
    "wpi": "I107077323",  # Worcester Polytechnic Institute
    "uky": "I143302722",  # University of Kentucky
    "lehigh": "I186143895",  # Lehigh University
    "syracuse": "I70983195",  # Syracuse University
    "cincinnati": "I63135867",  # University of Cincinnati
    "unl": "I114395901",  # University of Nebraska-Lincoln
    "unc": "I114027177",  # University of North Carolina at Chapel Hill (API-verified 2026-07-26)
    "lsu": "I121820613",  # Louisiana State University
    "utdallas": "I162577319",  # University of Texas at Dallas
    "casewestern": "I58956616",
    "houston": "I44461941",
    "iastate": "I173911158",
    "indiana": "I4210119109",
    "miami": "I145608581",
    "rpi": "I165799507",
    "ucf": "I106165777",
    "uconn": "I140172145",
    "udel": "I86501945",
    "uiowa": "I126307644",
    "utah": "I223532165",
    # Verified 2026-07-18 via GET /institutions?search=University of Georgia:
    "uga": "I165733156",       # University of Georgia (US, ~141k works)
}
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


def _usable_works(raw: list[dict], dept: str = "",
                  max_works: int = _MAX_WORKS,
                  author_fields: list[str] | set[str] | None = None) -> list[dict]:
    """The citable subset of one author's works, newest first: title + year
    only, title capped at ``_TITLE_CAP`` chars (corpus lives in a 2GB backend).

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
    out: list[dict] = []
    seen: set[str] = set()
    for w in raw:
        if allowed is not None:
            field = ((w.get("primary_topic") or {}).get("field") or {}).get("display_name", "")
            if field not in allowed:
                continue
        title = re.sub(r"\s+", " ", (w.get("display_name") or "")).strip()[:_TITLE_CAP]
        year = w.get("publication_year")
        # preprint + published version of one paper share a display_name
        if title and isinstance(year, int) and _title_key(title) not in seen:
            seen.add(_title_key(title))
            out.append({"title": title, "year": year})
        if len(out) >= max_works:
            break
    return out


def author_recent_works(author_id: str, dept: str = "", max_works: int = _MAX_WORKS,
                        author_fields: list[str] | set[str] | None = None) -> list[dict]:
    """``_usable_works`` for one author, bought one request per person."""
    j = _get({
        "filter": f"author.id:{author_id}",
        "sort": "publication_date:desc",
        "per-page": _WORKS_FETCH,
        "select": "display_name,publication_year,primary_topic",
    }, url=_WORKS_API)
    return _usable_works(j.get("results") or [], dept, max_works, author_fields)


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


def index_roster(roster: list[dict]) -> dict[tuple[str, str], list[dict]]:
    idx: dict[tuple[str, str], list[dict]] = {}
    for a in roster:
        k = _match_name_key(a.get("name", ""))
        if k is not None:
            idx.setdefault(k, []).append(a)
    return idx


def _match_in_roster(name: str, dept: str,
                     idx: dict[tuple[str, str], list[dict]]) -> tuple[dict | None, str]:
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
    cands = [a for a in idx.get(k, []) if a.get("works", 0) >= _MIN_WORKS]
    if not cands:
        return None, "absent"
    allowed = _dept_fields(dept)
    if allowed is not None:
        kept = []
        for a in cands:
            fields = [f for f in (a.get("fields") or []) if f]
            n = len(fields)
            comp = sum(1 for f in fields if f in allowed)
            ok = (comp * 2 >= n) if n >= 3 else (n > 0 and comp == n)
            if ok:
                kept.append(a)
        cands = kept
        if not cands:
            return None, "field_reject"
    named = [a for a in cands if _given_names_can_be_one_person(name, a.get("name", ""))]
    if not named:
        return None, "given_name_reject"
    cands = named
    exact = [a for a in cands if _given_name(a["name"]) == _given_name(name)]
    if exact:
        cands = exact
    if len(cands) > 1:
        return None, "ambiguous"
    return cands[0], "ok"


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
        cache = os.path.join(roster_dir, f"{slug}.json") if roster_dir else None
        state = json.load(open(cache)) if cache and os.path.exists(cache) else None
        if state is None or not state.get("complete"):
            if progress:
                have = len(state["authors"]) if state else 0
                print(f"{slug}: fetching roster for {len(people)} fieldless faculty"
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
        cache = os.path.join(roster_dir, f"{slug}.json") if roster_dir else None
        state = json.load(open(cache)) if cache and os.path.exists(cache) else None
        if state is None:
            reasons["no_roster"] = reasons.get("no_roster", 0) + 1
            if progress:
                print(f"{slug}: no cached roster — skipped", flush=True)
            continue
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
            for key, aid, dept, own_fields in batch:
                works = _usable_works(raw.get(aid) or [], dept, author_fields=own_fields)
                if works:
                    mapping[key] = {"author_id": aid, "works": works}
                else:
                    reasons["no_usable_work"] = reasons.get("no_usable_work", 0) + 1
            if progress:
                print(f"  {slug}: {min(i + _WORKS_BATCH, len(resolved))}/{len(resolved)} "
                      f"-> {len(mapping)} with papers", flush=True)
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
        if works_are_verified(o):
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
        works = (author_recent_works(best["id"], dept, author_fields=_author_own_fields(best))
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
        entry = mapping.get(_person_key(o))
        if not entry and counts.get(_record_url(o), 0) == 1:
            entry = mapping.get(_record_url(o))
        works, status = _entry_works_and_status(entry)
        clean: list[dict] = []
        seen: set[str] = set()
        for w in works:
            title = str(w.get("title", ""))[:_TITLE_CAP]
            if not title or not isinstance(w.get("year"), int):
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
        if clean and _is_an_upgrade(clean, status, existing, o):
            md = o.setdefault("metadata", {})
            md["recent_works"] = clean
            md["publication_attribution_status"] = status
            n += 1
    return n


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


def _cli(argv: list[str]) -> int:
    _load_dotenv()
    if not argv or argv[0] not in ("harvest", "roster", "apply", "works",
                                   "works-roster", "apply-works"):
        print(__doc__)
        return 2
    mode, rest = argv[0], argv[1:]
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
