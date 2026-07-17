"""University of Southern California faculty config (via the faculty_graph engine).

USC's school/department directories are server-rendered (no Cloudflare walls on
the units wired here), across eight markup families, verified live 2026-07-17:

* Viterbi School of Engineering: all 8 department sites (``cs`` /
  ``minghsiehece`` / ``ame`` / ``bme`` / ``cee`` / ``ise`` / ``chems`` /
  ``astronautics`` ``.usc.edu``) front ONE shared central directory app —
  ``div.faculty-member`` cards wrapped in the profile ``<a>``, name on
  ``h5.resultName``, and the rank as a bare text node after the h5 (no element
  of its own), so ``title_re`` extracts it from the card text. The title
  SELECTOR is deliberately ``div.faculty-text`` (name + rank concatenated): a
  card with no rank text at all (research staff ride the same directory) then
  keeps a name-shaped "title" and fails the professor require-gate instead of
  inheriting the "Professor" default. Profiles keep the email as plain text
  under "Contact Information" (``div.contactInformation`` — the address-token
  regex pulls it out) and a labeled "Research Summary" block
  (``div.research-piece``; comma keyword lists for most, prose for some — the
  keyword hygiene drops long prose fragments). Use ``chems.usc.edu`` for the
  Mork Family department — the ``mork.usc.edu`` alias is DNS-broken from some
  networks.

* Dornsife paginated "person-card" theme (physics, mcb, econ, psyc, engl,
  hist, earth, anth, poir): ``div.person-card`` grid, 12/page, ``/page/N/``
  path pagination. Titles on ``span.person-title`` include named-chair holders
  whose title omits "Professor" (Dockson Chair) — the require-gate accepts
  ``chair`` too. Profiles (``dornsife.usc.edu/profile/<slug>/``) expose a real
  mailto and a clean "Research Keywords" comma list (``research_html_re``).

* Dornsife one-page "card" variant (math, chem, phil, soci, ling, heb):
  ``div.card`` grid, rank in the first ``div.f--description p`` (HEB instead
  uses a ``div.f--eyebrow span``), listing emails as plain "Email: x@usc.edu"
  text in the description (math/ling). Math lists names "Last, First" →
  ``name_flip``. Some linguistics h3 links go to personal external sites —
  kept (working profile destinations).

* Annenberg Drupal directory: 213 profiles on one page, split first/last name
  fields (``name`` + ``name_last``), rank on ``.field-academic-title``, and a
  clean comma expertise tag list on the listing (``.field-faculty-expertise``).
  Profiles carry a ``.field-email`` mailto.

* Leonard Davis Gerontology WP list: one page, expertise tag list on the
  listing (``.expertise-keywords``); profiles have NO mailto (verified), so no
  enrich pass.

* Thornton Music + School of Dramatic Arts shared ``li.person`` WP pattern:
  one page each. SDA carries the rank in ``div.position p`` and a
  ``data-filter`` faculty token on the card; Music's cards have NO rank
  anywhere (program area only) — Music faculty ship with the engine's default
  "Professor" title and the program/expertise chips as keywords, and cannot be
  adjunct-gated (documented limitation).

* Kaufman Dance (``article.item``) and Mann Pharmacy
  (``article.faculty-list__member``, mailto on the listing) one-pagers.

* Drupal pagers: Rossier Education (``?page=N``, 0-indexed, 10/page) and
  Dworak-Peck Social Work (30/page — but its multi-pager wants ``?page=,N``,
  a query shape the engine's ``param=N`` paginator cannot emit and ``?page=1``
  re-serves page 0 (verified live), so only the first 30 of ~90 land; page-0
  yield documented, revisit if the engine grows a pager-prefix knob).

* Marshall Marketing ``li.person-list-item`` carousel: hrefs are
  RELATIVE ``personnel/<slug>`` and resolve against the dept path to a
  bounce-redirect (verified live), so the link selector accepts only absolute
  personnel URLs (today none — records fall back to the directory URL, and the
  config self-heals if Marshall ever emits absolute links). No enrich without
  per-person URLs. Roski Art & Design ``div.item-card`` grid paginates
  ``/page/N/`` keeping its ``?type=faculty`` query.

Single source ("usc_faculty"); department rides each record, ids namespaced by
department short-code.

Deferred (recon 2026-07-17): School of Cinematic Arts (ColdFusion directory
paginates by ``startRow`` in strides of 30; ``startPage`` is inert — verified
live — and the engine's +1 query paginator can't stride, so only an
alphabetically-biased first 30 of ~460 would land; directory is also very
adjunct-heavy); Keck School of Medicine (WAF 403s /faculty-search/); Price
School of Public Policy (WP admin-ajax JS grid); Iovine and Young Academy
(Next.js, names not in raw HTML); Gould Law (hub page, no server-rendered
listings); Ostrow Dentistry (no public simple directory); Chan Occupational
Science/Therapy (directory path 404); School of Architecture (23MB
server-rendered page, needs a careful streaming parse); Marshall's other 7
department pages (same CMS as Marketing but not individually live-verified);
BISC Marine & Environmental Biology + Neurobiology section sites and the
remaining Dornsife humanities departments (same Dornsife families expected,
not fetched this pass).
"""

from __future__ import annotations

from .. import faculty_graph

# Ladder gates. ``chair`` is required-in because named-chair full professors
# (Dornsife "Dockson Chair in Economics…") carry no "Professor" in their
# listing title. Arts units (SDA, Kaufman) keep full-time Lecturers — the
# working rank of much practice faculty — while research units require a
# professor-rank title.
_LADDER = {
    "require": r"\bprofessor\b|\bchair\b",
    "drop": r"emerit|adjunct|visiting|part-?time|\bpostdoc",
}
_LADDER_ARTS = {
    "require": r"\bprofessor\b|\blecturer\b|\bchair\b",
    "drop": r"emerit|adjunct|visiting|part-?time|\bpostdoc",
}

_EMAIL_DROP = r"^[^@]*$|info@|admissions@|communications@|department@|office@"

# ---- Viterbi shared central directory --------------------------------------
# The rank is a bare text node inside div.faculty-text (after the h5 name), so
# title_re lifts it out of the card text; the div.faculty-text title selector
# is the no-rank fallback that FAILS the ladder gate (see module docstring).
# No $ anchor: some ranks wrap across a raw newline ("Electrical and Computer\n
# Engineering") and `.*$` would refuse to match; `.*` captures to the break.
_VIT_TITLE_RE = (
    r"\b((?:(?:University|Distinguished|Provost|Assistant|Associate|Research|"
    r"Teaching|Adjunct|Emeritus|Emerita|Senior|Visiting|Clinical|Part-Time|"
    r"Full|WiSE)\s+)*(?:Professor|Lecturer|Instructor)\b.*)"
)

_VIT_ENRICH = {
    "email_selector": "div.contactInformation",
    "email_drop": _EMAIL_DROP,
    "research_selector": "div.research-piece",
    "throttle": 0.2,
}


def _vit(short: str, name: str, majors: list[str], host: str,
         path: str = "/directory/faculty/") -> dict:
    """A Viterbi department on the shared central directory.

    ECE mounts the app at ``/faculty-directory/`` — its ``/directory/faculty/``
    path serves a 59-card partial listing (verified live), not the full 134.
    """
    url = f"https://{host}{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": "a:has(div.faculty-member)",
                                     "name": "h5.resultName", "link": ":self",
                                     "title": "div.faculty-text",
                                     "title_re": _VIT_TITLE_RE},
                       "ladder_filter": _LADDER,
                       # All 8 dept hosts front one Viterbi directory app —
                       # space the listing hits as if they were one host.
                       "pre_delay": 0.8,
                       "profile_enrich": _VIT_ENRICH}}


# ---- Dornsife paginated person-card theme ----------------------------------
_DPC_SELECTORS = {
    "card": "div.person-card",
    "name": "h3 a",
    "link": "h3 a",
    "title": "span.person-title",
}

_DORN_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": _EMAIL_DROP,
    "research_html_re": r"Research Keywords</h4>\s*<p[^>]*>(.*?)</p>",
    "throttle": 0.2,
}


def _dpc(short: str, name: str, majors: list[str], path: str, pages: int) -> dict:
    """A Dornsife department on the paginated person-card theme (12/page)."""
    url = f"https://dornsife.usc.edu{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _DPC_SELECTORS,
                       "paginate": {"mode": "path", "param": "page",
                                    "start": 2, "max": pages},
                       "ladder_filter": _LADDER,
                       "profile_enrich": _DORN_ENRICH}}


def _dcard(short: str, name: str, majors: list[str], path: str,
           title_sel: str = "div.f--description p", flip: bool = False) -> dict:
    """A Dornsife department on the one-page card variant.

    The first description line is the rank; "Email:"/"Office:" tails are cut by
    ``title_strip_after``. Listing emails (math/ling/phil/soci) are plain
    "Email: x@usc.edu" text inside the description — the ``:-soup-contains``
    guard matches the div ONLY when an address is present, because on a miss
    the engine's ``_clean_email`` would return the element's raw text as the
    "email" (a card without the line would ship its rank as a corrupt address).
    """
    url = f"https://dornsife.usc.edu{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url,
                       "selectors": {"card": "div.card", "name": "h3",
                                     "link": "h3 a", "title": title_sel,
                                     "title_strip_after": r"\s*(?:Email|Office|Phone)\s*:",
                                     "email": "div.f--description:-soup-contains('@')"},
                       "name_flip": flip,
                       "ladder_filter": _LADDER,
                       "profile_enrich": _DORN_ENRICH}}


SCHOOL: dict = {
    "school_slug": "usc",
    "source": "usc_faculty",
    "organization": "University of Southern California",
    "location": "Los Angeles, CA",
    "id_prefix": "usc",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Southern California) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Viterbi School of Engineering --------------------------------
        _vit("CS", "Thomas Lord Department of Computer Science",
             ["Computer Science"], "www.cs.usc.edu"),
        _vit("ECE", "Ming Hsieh Department of Electrical and Computer Engineering",
             ["Electrical and Computer Engineering", "Electrical Engineering",
              "Computer Engineering"], "minghsiehece.usc.edu",
             path="/faculty-directory/"),
        _vit("AME", "Department of Aerospace and Mechanical Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"], "ame.usc.edu"),
        _vit("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "bme.usc.edu"),
        _vit("CEE", "Sonny Astani Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"], "cee.usc.edu"),
        _vit("ISE", "Daniel J. Epstein Department of Industrial and Systems Engineering",
             ["Industrial and Systems Engineering"], "ise.usc.edu"),
        _vit("CHEMS", "Mork Family Department of Chemical Engineering and Materials Science",
             ["Chemical Engineering", "Materials Science"], "chems.usc.edu"),
        _vit("ASTE", "Department of Astronautical Engineering",
             ["Astronautical Engineering", "Aerospace Engineering"],
             "astronautics.usc.edu"),
        # ---- Dornsife: paginated person-card depts ------------------------
        _dpc("PHYS", "Department of Physics and Astronomy",
             ["Physics", "Astronomy"], "/physics/faculty/", 7),
        _dpc("MCB", "Molecular and Cellular Biosciences (Biological Sciences)",
             ["Biological Sciences", "Molecular Biology"], "/mcb/mcb-faculty/", 5),
        _dpc("ECON", "Department of Economics", ["Economics"], "/econ/faculty/", 8),
        _dpc("PSYC", "Department of Psychology", ["Psychology"], "/psyc/faculty/", 13),
        _dpc("ENGL", "Department of English", ["English"], "/engl/faculty/", 8),
        _dpc("HIST", "Department of History", ["History"], "/hist/faculty/", 7),
        _dpc("EARTH", "Department of Earth Sciences",
             ["Earth Sciences", "Geology"], "/earth/people/faculty/", 5),
        _dpc("ANTH", "Department of Anthropology", ["Anthropology"],
             "/anth/people/faculty/", 4),
        _dpc("POIR", "Department of Political Science and International Relations",
             ["Political Science", "International Relations"], "/poir/people/", 8),
        # ---- Dornsife: one-page card depts --------------------------------
        _dcard("MATH", "Department of Mathematics", ["Mathematics"],
               "/mathematics/faculty-list/", flip=True),
        _dcard("CHEM", "Department of Chemistry", ["Chemistry"], "/chemistry/faculty/"),
        _dcard("PHIL", "School of Philosophy", ["Philosophy"], "/phil/faculty/"),
        _dcard("SOCI", "Department of Sociology", ["Sociology"], "/soci/faculty/"),
        _dcard("LING", "Department of Linguistics", ["Linguistics"],
               "/ling/people/faculty/"),
        _dcard("HEB", "Human and Evolutionary Biology (Biological Sciences)",
               ["Biological Sciences", "Human Biology"], "/heb/faculty/",
               title_sel="div.f--eyebrow span"),
        # ---- Annenberg School for Communication and Journalism ------------
        {
            "short": "COMM",
            "name": "Annenberg School for Communication and Journalism",
            "majors": ["Communication", "Journalism", "Public Relations"],
            "directory_url": "https://annenberg.usc.edu/faculty",
            "scrape": {
                "url": "https://annenberg.usc.edu/faculty",
                "selectors": {"card": "div.faculty-directory__item",
                              "name": ".field-first-name",
                              "name_last": ".field-last-name",
                              "link": "a.faculty-directory__item--details__name",
                              "title": ".field-academic-title",
                              "research": ".field-faculty-expertise"},
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "email_selector": ".field-email a[href^='mailto:']",
                    "email_drop": _EMAIL_DROP,
                    "throttle": 0.2,
                },
            },
        },
        # ---- Leonard Davis School of Gerontology --------------------------
        {
            "short": "GERO",
            "name": "Leonard Davis School of Gerontology",
            "majors": ["Gerontology", "Human Development and Aging", "Lifespan Health"],
            "directory_url": "https://gero.usc.edu/faculty/",
            "scrape": {
                "url": "https://gero.usc.edu/faculty/",
                "selectors": {"card": "li:has(div.post-title)",
                              "name": ".post-title a", "link": ".post-title a",
                              "title": ".faculty-position",
                              "research": ".expertise-keywords"},
                "ladder_filter": _LADDER,
            },
        },
        # ---- Alfred E. Mann School of Pharmacy ----------------------------
        {
            "short": "PHAR",
            "name": "Alfred E. Mann School of Pharmacy and Pharmaceutical Sciences",
            "majors": ["Pharmacology and Drug Development", "Biopharmaceutical Sciences"],
            "directory_url": "https://mann.usc.edu/research-faculty/faculty-directory/",
            "scrape": {
                "url": "https://mann.usc.edu/research-faculty/faculty-directory/",
                "selectors": {"card": "article.faculty-list__member",
                              "name": "h4.faculty-name",
                              "link": ".faculty-list__member--info a",
                              "title": ".faculty-list__member--info > p",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": _LADDER,
            },
        },
        # ---- Marshall School of Business: Marketing -----------------------
        # Relative personnel/ hrefs mis-resolve against the dept path (bounce
        # redirect, verified live) — accept only absolute personnel links
        # (today none), so records carry the directory URL. See docstring.
        {
            "short": "MKT",
            "name": "Department of Marketing (Marshall School of Business)",
            "majors": ["Business Administration", "Marketing"],
            "directory_url": "https://www.marshall.usc.edu/departments/marketing/faculty",
            "scrape": {
                "url": "https://www.marshall.usc.edu/departments/marketing/faculty",
                "selectors": {"card": "li.person-list-item",
                              "name": "a.person-content-btn h3",
                              "link": "a.person-content-btn[href^='https://www.marshall.usc.edu/personnel/']",
                              "title": "ul.position-list"},
                "ladder_filter": _LADDER,
            },
        },
        # ---- Rossier School of Education (Drupal ?page=N, 0-indexed) ------
        {
            "short": "EDUC",
            "name": "Rossier School of Education",
            "majors": ["Education"],
            "directory_url": "https://rossier.usc.edu/faculty-research/directory",
            "scrape": {
                "url": "https://rossier.usc.edu/faculty-research/directory",
                "selectors": {"card": "article.listing-item.profile--faculty",
                              "name": "h2", "link": "a",
                              "title": "li.profile__title"},
                "paginate": {"param": "page", "start": 1, "max": 8},
                "ladder_filter": _LADDER,
            },
        },
        # ---- Dworak-Peck School of Social Work (page 0 only — see docstring)
        {
            "short": "SOWK",
            "name": "Suzanne Dworak-Peck School of Social Work",
            "majors": ["Social Work"],
            "directory_url": "https://dworakpeck.usc.edu/about/faculty-directory",
            "scrape": {
                "url": "https://dworakpeck.usc.edu/about/faculty-directory",
                "selectors": {"card": "div.faculty__grid__item__inner",
                              "name": "a.faculty__list__info__name",
                              "link": "a.faculty__list__info__name",
                              "title": "strong"},
                "ladder_filter": _LADDER,
            },
        },
        # ---- Thornton School of Music (no rank on cards — default titles) -
        {
            "short": "MUS",
            "name": "Thornton School of Music",
            "majors": ["Music"],
            "directory_url": "https://music.usc.edu/faculty/",
            "scrape": {
                "url": "https://music.usc.edu/faculty/",
                "selectors": {"card": "li.person", "name": "h3", "link": "a",
                              "research_items": ".person-program, .person-expertise"},
            },
        },
        # ---- School of Dramatic Arts --------------------------------------
        {
            "short": "THTR",
            "name": "School of Dramatic Arts",
            "majors": ["Acting", "Theatre"],
            "directory_url": "https://dramaticarts.usc.edu/faculty-and-staff/",
            "scrape": {
                "url": "https://dramaticarts.usc.edu/faculty-and-staff/",
                "selectors": {"card": "li.person.item[data-filter*='faculty']",
                              "name": "h3", "link": "a",
                              "title": "div.position p"},
                "ladder_filter": _LADDER_ARTS,
            },
        },
        # ---- Glorya Kaufman School of Dance -------------------------------
        {
            "short": "DANC",
            "name": "Glorya Kaufman School of Dance",
            "majors": ["Dance"],
            "directory_url": "https://kaufman.usc.edu/faculty/",
            "scrape": {
                "url": "https://kaufman.usc.edu/faculty/",
                "selectors": {"card": "article.item", "name": "h2", "link": "a",
                              "title": "h3", "research": "h4"},
                "ladder_filter": _LADDER_ARTS,
            },
        },
        # ---- Roski School of Art and Design (type=faculty facet is the gate)
        {
            "short": "ART",
            "name": "Roski School of Art and Design",
            "majors": ["Art", "Design"],
            "directory_url": "https://roski.usc.edu/profile-listing/?filter-by-keyword=&area=&type=faculty",
            "scrape": {
                "url": "https://roski.usc.edu/profile-listing/?filter-by-keyword=&area=&type=faculty",
                "selectors": {"card": "div.item-card", "name": "h3", "link": "a"},
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 6},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
