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
surname. Among accepted candidates the most-published one wins; if the search
returns no institution-affiliated match, the faculty member stays broad
("better broad than a different person's research").

Run ONCE like the other enrichment passes; updates-only apply, richer-dedup
protects it on refresh -> zero weekly cost.

    python -m src.collectors.openalex_enrich harvest uw,ucla,... --out oa.json
    python -m src.collectors.openalex_enrich apply oa.json

A second pass fetches each matched author's most recent publications (title +
year only) into ``metadata.recent_works`` so cold emails can cite a real,
current paper. Same institution/surname/field gating; run-once, carried
forward on re-scrape by ``_carry_forward_enrichment``:

    python -m src.collectors.openalex_enrich works princeton,stanford --out works.json
    python -m src.collectors.openalex_enrich apply-works works.json
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time

import requests

from .ucb_common import PROCESSED_FILE

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "ofe-research/1.0 (mailto:eric.guoyi.xu@gmail.com)"}
_API = "https://api.openalex.org/authors"
_WORKS_API = "https://api.openalex.org/works"
# 86MB corpus in a 2GB-RAM backend: hard-cap what apply may store per faculty.
_MAX_WORKS = 3
_TITLE_CAP = 200

# The committed "works library": the durable url -> [{title, year}] master record
# of every OpenAlex paper we ever paid the metered API to harvest. recent_works is
# the ONE faculty field no directory scrape reproduces, so this store is how we
# re-derive it for free after any full corpus rebuild — and where future harvests
# accumulate. Kept out of the corpus so the metered data survives independently.
WORKS_STORE = os.path.join(os.path.dirname(PROCESSED_FILE), "faculty_works.json")
# Over-fetch so the per-work field filter (drops OpenAlex same-name conflation
# outliers) still leaves _MAX_WORKS survivors in the common case.
_WORKS_FETCH = 10

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
    "uci": "I204250578",       # University of California, Irvine (ror 04gyf1771)
    "ucsb": "I154570441",      # University of California, Santa Barbara (ror 02t274463)
    "boulder": "I188538660",   # University of Colorado Boulder (ror 02ttsq026)
    "purdue": "I219193219",    # Purdue University West Lafayette (ror 02dqehb95)
    "duke": "I170897317",      # Duke University (ror 00py81415)
    "jhu": "I145311948",       # Johns Hopkins University (OpenAlex-API verified)
    "northwestern": "I111979921",  # Northwestern University (OpenAlex-API verified)
    "upenn": "I79576946",      # University of Pennsylvania (OpenAlex-API verified)
    "caltech": "I122411786",   # California Institute of Technology (OpenAlex-API verified)
    "cornell": "I205783295",   # Cornell University (ror 05bnh6r87, OpenAlex-API verified)
    "rice": "I74775410",       # Rice University (ror 008zs3103, OpenAlex-API verified)
    "vanderbilt": "I200719446",  # Vanderbilt University (ror 02vm5rt34, OpenAlex-API verified)
    "brown": "I27804330",      # Brown University (ror 05gq02987, OpenAlex-API verified)
    "dartmouth": "I107672454",  # Dartmouth College (ror 049s0rh22, OpenAlex-API verified)
    "columbia": "I78577930",
    "mit": "I63966007",        # Massachusetts Institute of Technology (ror 042nb2s44, OpenAlex-API verified)
    "harvard": "I136199984",   # Harvard University (ror 03vek6s52, OpenAlex-API verified)
    "yale": "I32971472",       # Yale University (ror 03v76x132, OpenAlex-API verified)
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
    # Wave-3 batch 1 (2026-07-19, OpenAlex-API verified).
    "bc": "I103531236",          # Boston College
    "uga": "I165733156",         # University of Georgia
    "emory": "I150468666",       # Emory University
    "georgetown": "I184565670",  # Georgetown University
    "nyu": "I57206974",          # New York University
    "tufts": "I121934306",       # Tufts University
    "uva": "I51556381",          # University of Virginia
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
)


def _dept_fields(dept: str) -> set[str] | None:
    d = (dept or "").lower()
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


def _get(params: dict, url: str = _API) -> dict:
    # OpenAlex metered its API in 2026 (every call costs credits, $0 free/day);
    # the prepaid key authorizes the request via the api_key query param. Absent
    # a key the call returns a 429 budget error (no "results") -> stays broad.
    global _warned_429
    key = os.environ.get("OPENALEX_API_KEY")
    if key:
        params = {**params, "api_key": key}
    seen_429 = False
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=20)
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


def _match_author_query(query: str, surname: str, inst_id: str, dept: str) -> dict | None:
    j = _get({"search": query, "per_page": 10,
              "select": "id,display_name,works_count,affiliations,topics"})
    best, best_works = None, -1
    for a in j.get("results", []):
        if surname not in (a.get("display_name") or "").lower():
            continue
        aff_ids = {
            (aff.get("institution") or {}).get("id", "").rsplit("/", 1)[-1]
            for aff in (a.get("affiliations") or [])
        }
        if inst_id not in aff_ids:
            continue
        if (a.get("works_count") or 0) > best_works:
            best, best_works = a, a.get("works_count") or 0
    if best is None or best_works < _MIN_WORKS:
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


def author_topics(name: str, inst_id: str, dept: str = "", max_topics: int = 5) -> list[str]:
    """Top research topics for the institution-affiliated author named ``name``,
    or [] when no confident match exists (gating in ``_match_author``)."""
    best = _match_author(name, inst_id, dept)
    if best is None:
        return []
    out: list[str] = []
    for t in best.get("topics") or []:
        c = _clean_topic(t.get("display_name", ""))
        if c and c not in out and len(c.split()) <= 7:
            out.append(c)
        if len(out) >= max_topics:
            break
    return out


def author_recent_works(author_id: str, dept: str = "", max_works: int = _MAX_WORKS) -> list[dict]:
    """Up to ``max_works`` most recent works for a matched author: title + year
    only, title capped at ``_TITLE_CAP`` chars (corpus lives in a 2GB backend).

    OpenAlex author-name disambiguation conflates distinct same-name people
    under one author id, and the recency sort surfaces the mis-attributed
    outliers first (a CS/NLP professor gets a myocardial-cell-injury paper). So
    when the department maps to a field family, a work whose ``primary_topic``
    field is incompatible with it is dropped — the same wrong-field guard the
    author-topics pass applies, at the per-work level. Better to cite no paper
    than the wrong person's."""
    allowed = _dept_fields(dept)
    j = _get({
        "filter": f"author.id:{author_id}",
        "sort": "publication_date:desc",
        "per-page": _WORKS_FETCH,
        "select": "display_name,publication_year,primary_topic",
    }, url=_WORKS_API)
    out: list[dict] = []
    seen: set[str] = set()
    for w in j.get("results", []) or []:
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
            n += 1
    return n


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
        if (o.get("metadata") or {}).get("recent_works"):
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
    """Pure harvest: ``{url#name: [{title, year}, ...]}`` for faculty with a confident
    OpenAlex author match (same institution/surname/field gates as topics).

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
        works = author_recent_works(best["id"], dept) if best and best.get("id") else []
        if best and best.get("id"):
            time.sleep(throttle)
        if _warned_429:
            # Don't record this target as a miss — the lookup never really ran.
            print(f"  aborting at {i + 1}/{len(targets)} — OpenAlex budget exhausted "
                  f"(confirmed 429); {len(mapping)} matched", flush=True)
            break
        if works:
            mapping[_person_key(o)] = works
        else:
            misses.add(_person_key(o))
        if checkpoint_path and (i + 1) % checkpoint_every == 0:
            _flush_checkpoint(checkpoint_path, mapping, misses)
        if progress and (i + 1) % 100 == 0:
            print(f"  ...{i + 1}/{len(targets)}, {len(mapping)} matched", flush=True)
    _flush_checkpoint(checkpoint_path, mapping, misses)
    return mapping


def apply_works(opps: list[dict], mapping: dict[str, list[dict]]) -> int:
    """Set ``metadata.recent_works`` on faculty keyed in mapping (composite
    ``url#name`` first; bare-URL fallback only for a URL owned by exactly one
    faculty — see ``apply_openalex``), whenever
    the mapping carries MORE papers than the record already has. Upgrade-when-
    richer (not skip-if-present): re-applying the fuller ``WORKS_STORE`` promotes a
    1-paper record to the full ``_MAX_WORKS`` set, while never downgrading a record
    that already has more. Idempotent; never touches any other field."""
    counts = _shared_url_counts(opps)
    n = 0
    for o in opps:
        if not _is_faculty(o):
            continue
        works = mapping.get(_person_key(o))
        if not works and counts.get(_record_url(o), 0) == 1:
            works = mapping.get(_record_url(o))
        works = works or []
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
        if clean and len(clean) > len(existing):
            o.setdefault("metadata", {})["recent_works"] = clean
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
    if not argv or argv[0] not in ("harvest", "apply", "works", "apply-works"):
        print(__doc__)
        return 2
    mode, rest = argv[0], argv[1:]
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
