"""Georgetown University faculty config (via the faculty_graph engine).

Georgetown runs a single WordPress multisite ("My WordPress Site Network")
behind nginx+Varnish — clean 200s everywhere, no WAF, no render mode
(~50 recon fetches all plain HTTP). Departments each own a subdomain
(``<dept>.georgetown.edu``) and build their public people pages out of a
handful of shared Georgetown-theme "gu-block" components. The block
GENERATIONS differ across departments, so this module groups depts into four
live-verified selector families (verified 2026-07-19):

* ``gu_media`` — the modern ``div.gu-block-media-text`` "Media & Text" block
  (biology, sociology, philosophy, theology, mathstat, english). One card per
  person: an ``h2`` name, a ``<p>`` whose leading line is the rank (plain text
  or bolded), then ``Interests:`` and ``Email:`` label rows, and a
  ``a.gu-block-link-cta`` "Bio" button (points at either an on-domain
  ``/profiles/<slug>/`` page or the central gufaculty360 contact record).
  Email is an inline mailto on every dept EXCEPT english (whose cards carry
  only the gufaculty360 CTA) — english backfills email via the env-gated
  profile pass. Rank is recovered with a shared case-sensitive title_re
  (``_RANK_RE``) since the position line has no stable element; research
  interests via ``research_re_text`` on the "Interests:" row.

* ``gu_cards`` — the ``div.gu-block-profile-card`` (a.k.a. ``gu-cards-card``)
  compact card (government, psychology, linguistics, spanish&portuguese,
  german, classics, and the McDonough School of Business area rosters). Person
  cards are gated with ``:has(p.gu-block-profile-title a)`` (the block is also
  reused for seminar-series / event cards that must be excluded). Name +
  profile link live in ``p.gu-block-profile-title a``; the rank is an inline
  ``p.gu-block-profile-text`` sibling. These cards carry NO inline email — the
  env-gated profile pass recovers it from the linked ``/profiles/`` page
  (on-domain depts: classics/german/msb/gov-partial). Cards linking to
  gufaculty360 (a Salesforce Lightning SPA) cannot be enriched, so email
  coverage on those depts stays partial by design.

* ``gu_profile`` — the older ``div.wp-block-gu-profile`` block (computer
  science, chemistry). CS names sit in an ``h2.wp-block-heading a`` with a
  ``Position:``/``Email:``/``Interests:`` labelled paragraph; chemistry packs
  everything into a single ``p.wp-block-paragraph`` whose first anchor is the
  name and whose ``<br>``-separated tail carries rank + room + phone + a
  mailto. Both share the rank title_re + inline mailto.

* ``gu_deck`` — the ``div.wp-block-gu-profile-card`` card-deck block
  (economics). ``h3.card-title`` name, ``p.card-title`` rank, an inline mailto,
  and a "Research Interests:" line inside ``div.card-text``.

Single source ("georgetown_faculty"); the department rides each record, ids
namespaced by department short-code. Emails are inline georgetown.edu mailtos
on gu_media (minus english), gu_profile, and gu_deck; recovered on gu_cards
via the profile pass.

Expansion pass (verified live 2026-07-20) moved these OUT of deferral, adding
four new selector families/bespoke helpers:

* Physics (``_phys_table``) — the ``/meet-the-faculty/`` page injects its roster
  client-side (empty even after headless render), but ``physics.georgetown.edu/
  people/`` is a server-rendered ``table.gu-table``; the first ``.table-responsive``
  table is FULL-TIME faculty (the EMERITUS/ADJUNCT tables that follow carry no
  rank text and are scoped out). Inline mailto recovered via the profile pass.
* Neuroscience (``_neuro``) — the ``div.expand-content`` accordion; ``p.body-text``
  ``<strong>`` name + ``<br>`` rank + inline mailto.
* History (``_hist``) — the ``article.news-article`` list; clean ``p.title`` name,
  ``p.excerpt strong`` rank, inline mailto, gufaculty360 profile link.
* Anthropology (``_deck_gu360``) — the same wp-block-gu-profile-card DECK as
  economics but linking to gufaculty360 (no inline email).
* McCourt School of Public Policy + School of Nursing (``_guprofile``) — the newer
  ``div.gu-profile`` filtered-post-list card (``p.gu-profile-title a`` + rank
  ``p.gu-profile-text``); gufaculty360 / email-less ``/profiles/`` links.
* School of Health (``_cards``) — the standard gu-block-profile-card grid.
* MSB Operations-and-Analytics + Strategy/Economics/Ethics/Public-Policy — the
  two remaining area pages now serve the standard gu-block-profile-card template
  (previously a card-less template) and wire in via ``_cards``; the MSBA URL was
  repointed to the renamed ``/accounting-business-law/`` slug.

Still deferred (2026-07-20 recon, concrete proof):
* School of Foreign Service CORE roster (sfs.georgetown.edu/our-people/faculty/)
  — the "Our Faculty" page is a WordPress Interactivity-API ``wp-block-query``
  whose ``category-faculty`` items are faculty NEWS posts, not a people
  directory; static HTML has zero person cards and a headless render (both
  networkidle — never idles — and 12s domcontentloaded settle) still yields
  zero profile cards. SFS's PRIMARY degree faculty are reached via program
  subsites: STIA is wired above. The regional-studies centers (African/Asian/
  Latin American/Arab/Eurasian Studies) publish gu-block-profile-card rosters
  too, but they are AFFILIATED cross-appointment lists (e.g. CLAS 63, African
  41) drawn from departments already covered here — folding them in would
  double-count the same professors under different (department vs center)
  profile URLs, so they are intentionally left out.
* Physics EMERITUS/ADJUNCT tables — scoped out on purpose (retired/adjunct).
* gufaculty360-linked rosters (Anthropology, McCourt, Health, STIA, MSB
  partial) land name+rank only: gufaculty360 is a Salesforce Lightning SPA
  behind a bot wall and exposes no scrapeable email.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- shared pieces ---------------------------------------------------------

# Case-sensitive rank extractor (ranks are Title-cased; the name and research
# lines never carry these phrases). Captures the whole rank incl. "Associate/
# Assistant/Teaching/Research/Distinguished ... Professor of X" and "... of the
# Practice". Applied over each card's rendered TEXT (title_re).
_RANK_RE = (
    r"\b((?:Distinguished\s+)?(?:University\s+)?"
    r"(?:Chair\s+(?:and|&)\s+|Vice\s+Chair\s+(?:and|&)\s+|Interim\s+)?"
    r"(?:Provost[’'`]s\s+Distinguished\s+)?"
    r"(?:Associate\s+|Assistant\s+|Research\s+|Teaching\s+|Visiting\s+"
    r"|Adjunct\s+|Clinical\s+|Full\s+|Senior\s+|Distinguished\s+|Professorial\s+)*"
    r"(?:Professor|Lecturer|Instructor)"
    r"(?:\s+of\s+the\s+Practice)?"
    r"(?:\s+of\s+[A-Z][A-Za-z ,&-]{2,45})?)"
)

# "Interests:" / "Research Interests:" line → research text, over rendered
# TEXT (stops at the next labelled row).
_INTERESTS_RE = (
    r"Interests?\s*:\s*(.+?)"
    r"(?:\s+Email\b|\s+Office\s+Hours\b|\s+View\b|\s+Personal\s+Website\b"
    r"|\s+Website\b|\s+Bio\b|$)"
)

# Faculty pages already role-scope to ladder faculty; a light drop prunes any
# emeritus/adjunct/visiting/postdoc that slip in. No "require" so cards whose
# rank didn't parse (title defaults to "Professor") are kept.
_LADDER = {"drop": r"emerit|adjunct|visiting|post-?doc|affiliate\b"}

# Dept-alias inboxes the profile pass may hit first (german@, classics@,
# info@, chair@, …) — drop them so 20 professors don't collapse on a shared
# address in dedup.
_EMAIL_DROP = (
    r"^(?:info|contact|office|admin|dept\w*|department|advising|undergrad"
    r"|graduate|webmaster|chair|reception|frontdesk|classics|german"
    r"|linguistics|psychology|sociology|philosophy|theology|english"
    r"|spanport|government|econ|biology|chemistry|physics)@"
)

# Georgetown (a Jesuit university) lists many faculty with a religious-order
# post-nominal the engine's credential stripper doesn't know (", S.J." Society
# of Jesus, O.P., C.S.C., O.F.M., …). Strip it from parsed names.
_NAME_STRIP = r"\s*,\s*(?:S\.?\s?J\.?|O\.?\s?P\.?|C\.?\s?S\.?\s?C\.?|O\.?\s?F\.?\s?M\.?|R\.?\s?S\.?\s?C\.?\s?J\.?)\s*$"

# Env-gated profile pass: recover the inline mailto (and drop dept aliases).
_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": _EMAIL_DROP,
    "throttle": 0.2,
}


def _media(short: str, name: str, majors: list[str], url: str, *,
           enrich: dict | None = None) -> dict:
    """A department on the modern gu-block Media&Text component."""
    sel: dict = {
        "card": "div.gu-block-media-text",
        "name": "h2.gu-block-image-cta-text-content-heading, h2",
        "name_strip": _NAME_STRIP,
        "link": "a.gu-block-link-cta",
        "email": "a[href^='mailto:']",
        "title_re": _RANK_RE,
        "research_re_text": _INTERESTS_RE,
    }
    scrape: dict = {"url": url, "selectors": sel, "ladder_filter": _LADDER}
    if enrich:
        scrape["profile_enrich"] = enrich
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


def _cards(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the compact gu-block Profile-Card component.

    Name + profile link in ``p.gu-block-profile-title a``; inline rank in the
    ``p.gu-block-profile-text`` sibling; email recovered from the linked
    profile page by the env-gated pass.
    """
    sel: dict = {
        "card": "div.gu-block-profile-card:has(p.gu-block-profile-title a)",
        "name": "p.gu-block-profile-title a",
        "name_strip": _NAME_STRIP,
        "link": "p.gu-block-profile-title a",
        "title": "p.gu-block-profile-text",
    }
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER,
                       "profile_enrich": _ENRICH}}


def _wp(short: str, name: str, majors: list[str], url: str, name_sel: str) -> dict:
    """A department on the legacy wp-block-gu-profile block (CS/chemistry)."""
    sel: dict = {
        "card": "div.wp-block-gu-profile",
        "name": name_sel,
        "name_strip": _NAME_STRIP,
        "link": name_sel,
        "email": "a[href^='mailto:']",
        "title_re": _RANK_RE,
        "research_re_text": _INTERESTS_RE,
    }
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER}}


def _deck(short: str, name: str, majors: list[str], url: str) -> dict:
    """Economics — the wp-block-gu-profile-card card-deck block."""
    sel: dict = {
        "card": "div.wp-block-gu-profile-card",
        "name": "h3.card-title",
        "name_strip": _NAME_STRIP,
        "link": "a.btn",
        "title": "p.card-title",
        "email": "a[href^='mailto:']",
        "research_re_text": _INTERESTS_RE,
    }
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER}}


def _deck_gu360(short: str, name: str, majors: list[str], url: str) -> dict:
    """Same wp-block-gu-profile-card deck as economics, but the profile CTA
    points at the gufaculty360 Salesforce record (no on-card mailto) — the
    anthropology roster. Rank sits in the FIRST ``p.card-title`` (a second
    ``p.card-title`` may carry an administrative role like "Chair"); research
    areas ride the "Research Interests:" row inside ``div.card-text``. Email is
    unavailable (gufaculty360 is a bot-walled SPA), so these records stay
    email-less by design.
    """
    sel: dict = {
        "card": "div.wp-block-gu-profile-card",
        "name": "h3.card-title",
        "name_strip": _NAME_STRIP,
        "link": "a[href]",
        "title": "p.card-title",
        "research_re_text": _INTERESTS_RE,
    }
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER}}


def _guprofile(short: str, name: str, majors: list[str], url: str) -> dict:
    """The newer ``div.gu-profile`` (a.k.a. ``gu-block gu-container gu-profile``)
    filtered-post-list card used by the McCourt School of Public Policy and the
    School of Nursing full-time rosters. Name + profile link live in
    ``p.gu-profile-title a`` (the ``title-link``); the rank is the sibling
    ``p.gu-profile-text``. The CTA points at either the gufaculty360 Salesforce
    record (McCourt) or an on-domain ``/profiles/`` page that carries no public
    email (Nursing) — so no profile-enrich pass is wired and these records land
    name+rank only. Emeritus/adjunct pruned by the shared ladder filter.
    """
    # Nursing lists every name with a long, comma-separated credential train
    # ("Intima Alrimawi, PhD, MSN, MPH, BSN (RN), FAAN") — the engine's generic
    # credential stripper trips on the "(RN)" parenthetical, so peel the whole
    # comma tail here (also removes any ", S.J." order post-nominal). McCourt
    # names carry no comma, so this is a no-op there.
    sel: dict = {
        "card": "div.gu-profile:has(p.gu-profile-title a)",
        "name": "p.gu-profile-title a",
        "name_strip": r",.*$",
        "link": "p.gu-profile-title a",
        "title": "p.gu-profile-text",
    }
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER}}


# Physics /people/ is a hand-built ``table.gu-table`` (Name<br>Rank | Office |
# Phone). The name link's text is "<Name> <Rank>" (the <br> collapses to a
# space under get_text), so a name_strip peels the rank tail off. The rank
# family covers 18/20 rows; the two endowed-chair titles whose DONOR name
# precedes the rank word ("… Robert L. McDevitt … Professor", "Joseph Semmes
# Ives Chair in Physics") have no generic text boundary before the donor name,
# so their exact chair strings are peeled explicitly (both verified live
# 2026-07-20).
_PHYS_NAME_STRIP = (
    r"\s+(?:(?:Distinguished|University|Associate|Assistant|Adjunct|Teaching"
    r"|Research|Visiting|Clinical|Senior|Full|Professorial|Interim)\s+)*"
    r"(?:Professor|Lecturer|Instructor|Director)\b.*$"
    r"|\s+Joseph\s+Semmes\s+Ives\s+Chair.*$"
    r"|\s+Robert\s+L\.\s+McDevitt.*$"
)


def _phys_table(short: str, name: str, majors: list[str], url: str) -> dict:
    """Physics — the FULL-TIME ``table.gu-table`` (the first ``.table-responsive``
    div; the EMERITUS and ADJUNCT tables that follow carry no rank text and would
    slip past the ladder filter, so scope stays on the first table). Rank comes
    from ``title_re`` over the row text; the profile pages carry an inline
    georgetown.edu mailto recovered by the env-gated profile pass.
    """
    sel: dict = {
        "card": "div.table-responsive:first-of-type table tbody tr",
        "name": "td:first-child a",
        "name_strip": _PHYS_NAME_STRIP,
        "link": "td:first-child a",
        "title_re": _RANK_RE,
    }
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER,
                       "profile_enrich": _ENRICH}}


def _neuro(short: str, name: str, majors: list[str], url: str) -> dict:
    """Neuroscience — the accordion roster. Each faculty is a
    ``div.expand-content`` whose ``p.body-text`` leads with a ``<strong>`` name,
    then a ``<br>`` rank line, then an inline mailto. Rank via ``title_re``; the
    accordion toggle links are bare ``href="#"`` anchors (no profile page), so
    the record URL is the directory listing and identity rides the unique email.
    """
    sel: dict = {
        "card": "div.expand-content",
        "name": "p.body-text strong",
        "name_strip": _NAME_STRIP,
        "title_re": _RANK_RE,
        "email": "a[href^='mailto:']",
        "research_re_text": _INTERESTS_RE,
    }
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER}}


def _hist(short: str, name: str, majors: list[str], url: str) -> dict:
    """History — a hand-built ``article.news-article`` list. Name is the clean
    ``p.title`` (the ``aria-label`` twin); rank is the leading ``<strong>`` in
    ``p.excerpt``; every card carries an inline mailto and a gufaculty360 profile
    link.
    """
    sel: dict = {
        "card": "article.news-article",
        "name": "p.title",
        "name_strip": _NAME_STRIP,
        "link": "a[href*='gufaculty360']",
        "title": "p.excerpt strong",
        "email": "a[href^='mailto:']",
    }
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": sel, "ladder_filter": _LADDER}}


SCHOOL: dict = {
    "school_slug": "georgetown",
    "source": "georgetown_faculty",
    "organization": "Georgetown University",
    "location": "Washington, DC",
    "id_prefix": "georgetown",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Georgetown University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Georgetown College — natural sciences (legacy gu-profile) ------
        _wp("CS", "Department of Computer Science", ["Computer Science"],
            "https://cs.georgetown.edu/faculty/", "h2.wp-block-heading a"),
        _wp("CHEM", "Department of Chemistry", ["Chemistry"],
            "https://chemistry.georgetown.edu/faculty/",
            "p.wp-block-paragraph a:first-of-type"),
        # ---- Georgetown College — gu_media Media&Text -----------------------
        _media("BIOL", "Department of Biology", ["Biology"],
               "https://biology.georgetown.edu/about/people/faculty/"),
        _media("MATH", "Department of Mathematics and Statistics",
               ["Mathematics", "Statistics"],
               "https://mathstat.georgetown.edu/people/full-time-faculty/"),
        _media("SOCI", "Department of Sociology", ["Sociology"],
               "https://sociology.georgetown.edu/people/faculty-2/"),
        _media("PHIL", "Department of Philosophy", ["Philosophy"],
               "https://philosophy.georgetown.edu/people/full-time-faculty/"),
        _media("THEO", "Department of Theology and Religious Studies",
               ["Theology", "Religious Studies"],
               "https://theology.georgetown.edu/people/ft-faculty/"),
        _media("ENGL", "Department of English", ["English"],
               "https://english.georgetown.edu/people/full-time-faculty-2/",
               enrich=_ENRICH),
        # ---- Georgetown College — gu_cards Profile-Card ---------------------
        _cards("GOVT", "Department of Government",
               ["Government", "Political Science", "International Politics"],
               "https://government.georgetown.edu/people/faculty/all/"),
        _cards("PSYC", "Department of Psychology", ["Psychology"],
               "https://psychology.georgetown.edu/people/faculty/"),
        _cards("LING", "Department of Linguistics", ["Linguistics"],
               "https://linguistics.georgetown.edu/about/people/faculty/"),
        _cards("SPAN", "Department of Spanish and Portuguese",
               ["Spanish", "Portuguese"],
               "https://spanport.georgetown.edu/all-faculty/"),
        _cards("GERM", "Department of German", ["German"],
               "https://german.georgetown.edu/people/faculty/"),
        _cards("CLSS", "Department of Classics", ["Classics", "Classical Studies"],
               "https://classics.georgetown.edu/faculty/"),
        # ---- Georgetown College — economics (gu_deck) -----------------------
        _deck("ECON", "Department of Economics", ["Economics"],
              "https://econ.georgetown.edu/people/faculty/"),
        # ---- McDonough School of Business (gu_cards area rosters) -----------
        _cards("MSBF", "McDonough School of Business — Finance",
               ["Finance"],
               "https://msb.georgetown.edu/faculty-research/finance/"),
        _cards("MSBA", "McDonough School of Business — Accounting and Business Law",
               ["Accounting", "Business Law"],
               "https://msb.georgetown.edu/faculty-research/accounting-business-law/"),
        _cards("MSBM", "McDonough School of Business — Management",
               ["Management"],
               "https://msb.georgetown.edu/faculty-research/management/"),
        _cards("MSBK", "McDonough School of Business — Marketing",
               ["Marketing"],
               "https://msb.georgetown.edu/faculty-research/marketing/"),
        _cards("MSBO", "McDonough School of Business — Operations and Analytics",
               ["Operations Management", "Business Analytics",
                "Information Management"],
               "https://msb.georgetown.edu/faculty-research/operations-analytics/"),
        _cards("MSBS", "McDonough School of Business — Strategy, Economics, "
               "Ethics, and Public Policy",
               ["Strategy", "Business Economics", "Business Ethics",
                "Public Policy"],
               "https://msb.georgetown.edu/faculty-research/"
               "strategy-economics-ethics-public-policy/"),
        # ---- Georgetown College — natural sciences (bespoke) ---------------
        _phys_table("PHYS", "Department of Physics", ["Physics"],
                    "https://physics.georgetown.edu/people/"),
        _neuro("NEUR", "Interdisciplinary Program in Neuroscience",
               ["Neuroscience"],
               "https://neuroscience.georgetown.edu/faculty/"),
        # ---- Georgetown College — humanities / social sciences -------------
        _hist("HIST", "Department of History", ["History"],
              "https://history.georgetown.edu/people/faculty/"),
        _deck_gu360("ANTH", "Department of Anthropology", ["Anthropology"],
                    "https://anthropology.georgetown.edu/people/"),
        # ---- McCourt School of Public Policy -------------------------------
        _guprofile("MCCT", "McCourt School of Public Policy",
                   ["Public Policy"],
                   "https://mccourt.georgetown.edu/people/faculty/mccourt-faculty/"),
        # ---- School of Nursing / School of Health --------------------------
        _guprofile("NURS", "School of Nursing", ["Nursing"],
                   "https://nursing.georgetown.edu/about/"
                   "school-of-nursing-faculty-2/"),
        _cards("HLTH", "School of Health", ["Health", "Global Health",
               "Health Management and Policy", "Human Science"],
               "https://health.georgetown.edu/about/school-of-health-faculty/"),
        # ---- School of Foreign Service (STIA — SFS-primary faculty) --------
        _cards("STIA", "Walsh School of Foreign Service — Science, Technology "
               "and International Affairs (STIA)",
               ["Science, Technology and International Affairs",
                "International Affairs"],
               "https://stia.georgetown.edu/faculty/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
