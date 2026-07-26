"""University of Notre Dame faculty config (via the faculty_graph engine).

Notre Dame's directories are all server-rendered (no WAF, no JS grids) across
seven markup families, verified live 2026-07-17:

* College of Engineering WordPress multisite (cse/ame/cbe/ee/ceees.nd.edu):
  ``article.type-profile`` cards, 10 per page, ``/faculty/page/N/`` path
  pagination. Every card carries ``position-faculty`` (including emeriti and
  administrative-only titles like "Director, Civic Innovation Lab"), so the
  ladder gate is a strict title REQUIRE + drop. Profiles keep the person's
  mailto first and the department inbox (cse@nd.edu) second; "Areas of
  Interest" is prose, so no research enrich (OpenAlex backfills).

* ND Conductor CMS ``/people/faculty/`` card pages (most Arts & Letters depts
  + ACMS + Architecture): ``li.card`` with a linked ``.card-title`` and a
  plain-text ``.person-title`` (ACMS uses ``.person-item__title``). The URL
  facet pre-drops staff/grads/emeriti; a title drop-gate prunes the adjuncts
  mixed in (Music lists 30 of 76, Architecture is adjunct-practitioner-heavy —
  the require gate there is the point, 27 of 44 kept).

* Conductor data-groups variant: Chemistry lists all 358 people (200 grad
  students) on one page — the card selector keys on the ``data-groups`` facet
  attribute to keep tenure-track/teaching/research faculty (65). Biology's
  pre-filtered page carries the mailto and the title on the card itself.

* Conductor results-list variant (Physics, Math): plain-text ``.card-title``,
  "View full bio" button link, ``em`` rank (Math has none). Physics appends
  "Visiting, Guest, & Adjunct Faculty" and "Faculty Emeriti" ``h2`` sections
  below the 77 regular cards — a section EXCLUDE cuts them (regular cards have
  no preceding ``h2``, which an include-gate would wrongly reject).

* Whole-card-anchor people-list (History ``people-list``, American Studies
  ``faculty-list`` — same markup, different class prefix).

* Philosophy's one-off ``div.faculty-item`` grid (h5 name + sibling p title).

* Mendoza College of Business: one WordPress page, 377 ``div.directory-content``
  entries mixing faculty, staff, and PhD students, mailto on every card. The
  rank is a bare TEXT NODE (no element), so ``title_re`` extracts it from the
  card text; the pattern also matches "PhD Student"/"… Manager" so the ladder
  gate can drop them (they would otherwise pass on the "Professor" default).
  Staff units are structurally excluded via ``:has(a[data-department])`` —
  only academic-department cards carry the linked department tag.

* Keough School of Global Affairs: ``li.card.card-person`` with a
  ``data-faculty_staff`` role facet — the card selector keeps ``core-faculty``
  (89), dropping staff/PhD/concurrent/postdoc/emeriti; profiles carry a clean
  semicolon-separated "Expertise" paragraph (research enrich).

Engine limitation hit: several listings carry CLEAN research slugs in card
data-attributes (Biology ``data-research``, Philosophy ``data-areas``, Keough
``data-research_areas``/``data-disciplines``), but ``_parse_cards`` reads
element text only — attributes are unreachable from config. Keough recovers
research from its profile "Expertise" block; Biology and Philosophy ship
keyword-less (profile bodies are prose bios; the OpenAlex pass backfills).

Single source ("nd_faculty"); department rides each record, ids namespaced by
department short-code.

Deferred (from the recon pass):
* Law School (law.nd.edu) — professional/graduate school, out of
  undergrad-research scope.
* German and Russian Languages and Literatures — site not located (guessed
  hostnames german/germanandrussian/grll.nd.edu all NXDOMAIN); needs a
  search-engine pass for the real hostname.
* Program of Liberal Studies (pls.nd.edu/people/) — 18 title-less ``li.card``
  mixing faculty and staff; /people/faculty/ is 404; needs a section-heading
  parse before it can be trusted.
* Preprofessional Studies — no standalone dept site (redirects to www.nd.edu).
* Medieval Institute / Gender Studies / Irish Language & Literature —
  institutes/programs whose rosters are mostly concurrent appointments
  already covered by home departments.
* Kellogg Institute faculty fellows — roster overlaps home departments;
  covered via its undergraduate programs in ``nd.py`` instead.
"""

from __future__ import annotations

from .. import faculty_graph

# Drop non-ladder ranks; the engine's _RETIRED_TITLE_RE catches emeriti again
# at normalize time, but gating here keeps the parse honest per directory.
_LADDER = {"drop": r"emerit|adjunct|visiting|postdoc"}

# Strict require-gate for rosters that mix administrative/staff titles into
# the same card grid (Engineering WP "Director, …" cards; Architecture's
# practitioner directory; Mendoza's all-of-college page).
_LADDER_STRICT = {
    "require": r"\bprofessor\b|\blecturer\b|\binstructor\b",
    "drop": r"emerit|adjunct|visiting|postdoc",
}

# Profile pages across all ND families put the person's own mailto first and
# the department inbox second — keep the first, but drop a department-style
# alias in case a profile carries only the shared inbox (one alias on many
# professors would also make the school-wide email dedupe collapse them).
_EMAIL_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": (
        r"^[^@]*$|^(?:cse|ame|cbe|ee|ceees|engineering|chemistry|physics|"
        r"biology|math|acms|econ|economics|english|history|sociology|"
        r"anthropology|psychology|politicalscience|polisci|theology|"
        r"philosophy|music|ftt|art|artdept|classics|africana|americanstudies|"
        r"eastasian|keough|kellogg|mendoza|architecture|info|contact|"
        r"webmaster|admissions?)@"
    ),
    "throttle": 0.2,
}

# Research capture for the two research-bearing markup families that share the
# email-only profile pass: Engineering WP prose (div.research-area) and
# Conductor CMS (div.person-research — scoped to the first <p> after the
# "Research Interests" h2 so the sibling "Selected Publications" section can't
# leak). research_selector is comma/semicolon-split downstream; depts with
# neither container (Econ/Soc/ACMS bio-only, Math's directory URL) no-op safely.
_RESEARCH_ENRICH = {
    **_EMAIL_ENRICH,
    "research_selector": "div.person-research > p:nth-of-type(1), div.research-area",
    "timeout": 8,
    "max_retries": 1,
    "throttle": 0.3,
}

# ---- College of Engineering WordPress multisite -----------------------------
_WP_SELECTORS = {
    "card": "article.type-profile",
    "name": "h2 a",
    "link": "h2 a",
    "title": "h3.is-style-plain",
}


def _wp(short: str, name: str, majors: list[str], subdomain: str) -> dict:
    """An Engineering department on the WP profile-card theme (10/page)."""
    url = f"https://{subdomain}.nd.edu/faculty/"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _WP_SELECTORS,
                       "paginate": {"mode": "path", "param": "page", "start": 2, "max": 10},
                       "ladder_filter": _LADDER_STRICT,
                       "profile_enrich": _RESEARCH_ENRICH}}


# ---- Conductor CMS /people/faculty/ card pages ------------------------------
_CARD_SELECTORS = {
    "card": "li.card",
    "name": ".card-title a",
    "link": ".card-title a",
    "title": ".person-title, .person-item__title",
}


def _cc(short: str, name: str, majors: list[str], subdomain: str,
        path: str = "/people/faculty/", strict: bool = False) -> dict:
    """A Conductor-theme department on a pre-filtered faculty page."""
    url = f"https://{subdomain}.nd.edu{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CARD_SELECTORS,
                       "ladder_filter": _LADDER_STRICT if strict else _LADDER,
                       "profile_enrich": _RESEARCH_ENRICH}}


# ---- Conductor results-list variant (Physics, Math) -------------------------
_RL_SELECTORS = {
    "card": "li.card.results-list__item",
    "name": ".card-title",
    "link": "a.btn",
    "title": "em",
}

# ---- History / American Studies whole-card-anchor lists ---------------------
_HIST_SELECTORS = {
    "card": "li.people-list-item",
    "name": "h3.person-item-name",
    "link": "a.person-item",
    "title": "p.person-item-title",
}
_AMST_SELECTORS = {
    "card": "li.faculty-list-item",
    "name": "h3.faculty-item-name",
    "link": "a.faculty-item",
    "title": "p.faculty-item-title",
}

# ---- Mendoza: rank is a bare text node → title_re over the card text --------
# Also matches PhD Student / Postdoctoral / "… Manager" so those cards get a
# real (droppable) title instead of passing on the "Professor" default.
_MENDOZA_TITLE_RE = (
    r"((?:(?:Adjunct|Visiting|Emeritus|Emerita|Assistant|Associate|Teaching|"
    r"Research|Clinical|Executive)\s+)*"
    r"(?:Professor|Lecturer|Instructor)[a-z]*(?:\s+Emerit(?:us|a|i))?"
    r"|Ph\.?D\.? Student|Postdoctoral \w+|Visiting Scholar|Research Fellow"
    r"|\w+ Manager)"
)


SCHOOL: dict = {
    "school_slug": "nd",
    "source": "nd_faculty",
    "organization": "University of Notre Dame",
    "location": "Notre Dame, IN",
    "id_prefix": "nd",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Notre Dame) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering (WP multisite) ------------------------
        _wp("CSE", "Department of Computer Science and Engineering",
            ["Computer Science", "Computer Engineering"], "cse"),
        _wp("AME", "Department of Aerospace and Mechanical Engineering",
            ["Aerospace Engineering", "Mechanical Engineering"], "ame"),
        _wp("CBE", "Department of Chemical and Biomolecular Engineering",
            ["Chemical Engineering"], "cbe"),
        _wp("EE", "Department of Electrical Engineering",
            ["Electrical Engineering", "Computer Engineering"], "ee"),
        _wp("CEEES", "Department of Civil and Environmental Engineering and Earth Sciences",
            ["Civil Engineering", "Environmental Earth Sciences"], "ceees"),
        # ---- College of Science -------------------------------------------
        {
            # One page lists all 358 people incl. 200 grad students — the
            # data-groups facet attribute on each card is the only role
            # signal, so the CARD selector does the gating (35 tenure-track +
            # 12 teaching + 12 research; emeriti/concurrent/adjunct excluded).
            # No title/email/research on the listing: the profile pass reads
            # the real rank (.person-title), the personal mailto, and the
            # clean "Research Areas"/"Research Specialties" <ul> lists.
            "short": "Chem", "name": "Department of Chemistry and Biochemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://chemistry.nd.edu/people/",
            "scrape": {
                "url": "https://chemistry.nd.edu/people/",
                "selectors": {
                    "card": ("li.card[data-groups*='tenured-and-tenure-track-faculty'],"
                             "li.card[data-groups*='teaching-faculty'],"
                             "li.card[data-groups*='research-faculty']"),
                    "name": ".card-title a",
                    "link": "a.card-link",
                },
                "profile_enrich": {
                    **_EMAIL_ENRICH,
                    "title_selector": ".person-title",
                    "research_items_selector": (
                        "h2:-soup-contains('Research Areas') + ul li, "
                        "h2:-soup-contains('Research Specialties') + ul li"),
                    "ladder_recheck": _LADDER,
                },
            },
        },
        {
            # 77 regular-faculty cards sit ABOVE the "Visiting, Guest, &
            # Adjunct Faculty" / "Faculty Emeriti" h2 sections — exclude-only
            # section gate (regular cards have no preceding h2 at all, so an
            # include gate would reject everything).
            "short": "Phys", "name": "Department of Physics and Astronomy",
            "majors": ["Physics", "Astronomy"],
            "directory_url": "https://physics.nd.edu/people/faculty/",
            "scrape": {
                "url": "https://physics.nd.edu/people/faculty/",
                "selectors": _RL_SELECTORS,
                "section_filter": {"heading": "h2",
                                   "exclude": r"visiting|guest|adjunct|emerit"},
                "ladder_filter": _LADDER,
                "profile_enrich": _RESEARCH_ENRICH,
            },
        },
        {
            # Pre-filtered faculty page carries the personal mailto AND the
            # title right on the card (the only Conductor dept that does) —
            # no profile pass needed. Its clean data-research slugs are in a
            # card attribute the engine can't read; profile "Research
            # Interests" is prose, so keywords come from the OpenAlex pass.
            "short": "Bio", "name": "Department of Biological Sciences",
            "majors": ["Biological Sciences", "Biology", "Neuroscience and Behavior"],
            "directory_url": "https://biology.nd.edu/people/faculty/",
            "scrape": {
                "url": "https://biology.nd.edu/people/faculty/",
                "selectors": {
                    "card": "li.card",
                    "name": ".card-title",
                    "link": "a.btn",
                    "title": ".person-title",
                    "email": ".person-meta a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        },
        {
            # /people/regular-faculty/ is pre-filtered; cards carry no title
            # element at all ("Professor" default is honest for this roster).
            "short": "Math", "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": "https://math.nd.edu/people/regular-faculty/",
            "scrape": {
                "url": "https://math.nd.edu/people/regular-faculty/",
                "selectors": _RL_SELECTORS,
                "ladder_filter": _LADDER,
                "profile_enrich": _EMAIL_ENRICH,
            },
        },
        _cc("ACMS", "Department of Applied and Computational Mathematics and Statistics",
            ["Applied and Computational Mathematics and Statistics", "Statistics",
             "Data Science"], "acms"),
        # ---- College of Arts and Letters ----------------------------------
        _cc("Econ", "Department of Economics", ["Economics"], "economics"),
        _cc("Psych", "Department of Psychology",
            ["Psychology", "Neuroscience and Behavior"], "psychology"),
        _cc("PoliSci", "Department of Political Science", ["Political Science"],
            "politicalscience"),
        _cc("Engl", "Department of English", ["English", "Creative Writing"], "english"),
        _cc("Soc", "Department of Sociology", ["Sociology"], "sociology"),
        _cc("Anth", "Department of Anthropology", ["Anthropology"], "anthropology"),
        {
            # One-off grid; its clean data-areas research slugs sit in a card
            # attribute the engine can't read (profile bodies are prose).
            "short": "Phil", "name": "Department of Philosophy",
            "majors": ["Philosophy"],
            "directory_url": "https://philosophy.nd.edu/people/faculty/",
            "scrape": {
                "url": "https://philosophy.nd.edu/people/faculty/",
                "selectors": {"card": "div.faculty-item", "name": "h5 a",
                              "link": "h5 a", "title": "p"},
                "ladder_filter": _LADDER,
                "profile_enrich": _RESEARCH_ENRICH,
            },
        },
        {
            "short": "Hist", "name": "Department of History", "majors": ["History"],
            "directory_url": "https://history.nd.edu/faculty/",
            "scrape": {
                "url": "https://history.nd.edu/faculty/",
                "selectors": _HIST_SELECTORS,
                "ladder_filter": _LADDER,
                "profile_enrich": _RESEARCH_ENRICH,
            },
        },
        _cc("Theo", "Department of Theology", ["Theology"], "theology"),
        _cc("Rom", "Department of Romance Languages and Literatures",
            ["Romance Languages", "Spanish", "French", "Italian"], "romancelanguages"),
        _cc("FTT", "Department of Film, Television, and Theatre",
            ["Film, Television, and Theatre"], "ftt"),
        # Music's faculty page mixes 30 adjuncts into 76 cards — _LADDER drops.
        _cc("Music", "Department of Music", ["Music"], "music"),
        _cc("Art", "Department of Art, Art History and Design",
            ["Art History", "Studio Art", "Design"], "artdept"),
        _cc("Afri", "Department of Africana Studies", ["Africana Studies"], "africana"),
        _cc("Clas", "Department of Classics", ["Classics"], "classics"),
        _cc("EAL", "Department of East Asian Languages and Cultures",
            ["East Asian Languages and Cultures", "Chinese", "Japanese"],
            "eastasian", path="/faculty-staff/faculty/"),
        {
            "short": "AmSt", "name": "Department of American Studies",
            "majors": ["American Studies"],
            "directory_url": "https://americanstudies.nd.edu/faculty/",
            "scrape": {
                "url": "https://americanstudies.nd.edu/faculty/",
                "selectors": _AMST_SELECTORS,
                "ladder_filter": _LADDER,
                "profile_enrich": _RESEARCH_ENRICH,
            },
        },
        # ---- Mendoza College of Business ----------------------------------
        {
            # 377 entries on one page (faculty + staff + PhD students). Staff
            # units are excluded structurally (:has on the linked academic
            # data-department tag — staff carry an unlinked <b> instead);
            # title_re + the strict gate prune PhD students, adjuncts (15),
            # and emeriti (46), keeping the 168 professorial entries. Mailto
            # rides every card, so no profile pass (profile tabs are prose).
            "short": "Mendoza", "name": "Mendoza College of Business",
            "majors": ["Finance", "Accountancy", "Marketing", "Business Analytics",
                       "Management Consulting", "IT Management"],
            "directory_url": "https://mendoza.nd.edu/mendoza-directory/",
            "scrape": {
                "url": "https://mendoza.nd.edu/mendoza-directory/",
                "selectors": {
                    "card": "div.directory-content:has(a.a-profile[data-department])",
                    "name": "div.directory-namecoach a.a-profile",
                    "link": "div.directory-namecoach a.a-profile",
                    "title_re": _MENDOZA_TITLE_RE,
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": {
                    "require": r"professor|lecturer|instructor",
                    "drop": r"emerit|adjunct|visiting|student|postdoc|fellow|manager",
                },
            },
        },
        # ---- School of Architecture (adjunct-practitioner-heavy) ----------
        {
            # Practitioner names carry alumni years / licensure tails on the
            # card ("John Mellor AIA, LEED AP, '95 and '10") — strip from the
            # first credential or class-year token.
            "short": "Arch", "name": "School of Architecture",
            "majors": ["Architecture"],
            "directory_url": "https://architecture.nd.edu/about/directory/",
            "scrape": {
                "url": "https://architecture.nd.edu/about/directory/",
                "selectors": {
                    **_CARD_SELECTORS,
                    "name_strip": r"\s*,?\s*(?:AIA|NCARB|LEED\b|PhD|\(?['’]\d{2}).*$",
                },
                "ladder_filter": _LADDER_STRICT,
                "profile_enrich": _RESEARCH_ENRICH,
            },
        },
        # ---- Keough School of Global Affairs ------------------------------
        {
            # data-faculty_staff facet keeps core-faculty (89 of 185); the
            # ladder drop prunes its visiting-professor-of-the-practice and
            # emeritus stragglers (84 kept). Profiles carry a clean
            # semicolon-separated "Expertise" paragraph.
            "short": "Keough", "name": "Keough School of Global Affairs",
            "majors": ["Global Affairs"],
            "directory_url": "https://keough.nd.edu/about/faculty-staff-directory/",
            "scrape": {
                "url": "https://keough.nd.edu/about/faculty-staff-directory/",
                "selectors": {
                    "card": "li.card.card-person[data-faculty_staff*='core-faculty']",
                    "name": ".card-title a",
                    "link": ".card-title a",
                    "title": ".person-title",
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    **_EMAIL_ENRICH,
                    "research_html_re": r">Expertise</h2>\s*<p[^>]*>(.*?)</p>",
                },
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
