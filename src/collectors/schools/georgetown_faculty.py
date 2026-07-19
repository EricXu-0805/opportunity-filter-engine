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

Deferred (2026-07-19 recon):
* Physics (physics.georgetown.edu/meet-the-faculty/) — the roster is injected
  client-side; static HTML has zero person cards. Needs render mode; left for
  a follow-up so the plain-HTTP fleet stays render-free.
* Neuroscience (neuroscience.georgetown.edu/faculty/) — faculty live inside
  ``div.gu-block-expand-content`` accordions with no per-person card wrapper;
  needs a bespoke accordion splitter the engine doesn't offer.
* History (history.georgetown.edu/people/faculty/) — a hand-built
  ``article.news-article`` list with pipe-delimited excerpt text (name | rank
  | degree | region | email); no reusable card family.
* Anthropology (anthropology.georgetown.edu) — people page renders empty in
  static HTML (JS-hydrated); directory path not resolved this pass.
* School of Foreign Service (sfs.georgetown.edu/category/faculty/) — a
  JS-hydrated blog-category grid, faculty spread across many program subsites.
* McCourt School of Public Policy — /people/faculty/ is a section-landing page
  linking to a sub-roster (/mccourt-faculty/) not fetched this pass.
* MSB Strategy/Economics/Public-Policy and Operations/Analytics areas — those
  two area pages returned no cards (different template); the other four MSB
  areas are wired.
* School of Nursing & Health / School of Health — served off the medical
  center host (gumc.georgetown.edu); clinical faculty need their own gate.
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
               "https://msb.georgetown.edu/faculty-research/accounting/"),
        _cards("MSBM", "McDonough School of Business — Management",
               ["Management"],
               "https://msb.georgetown.edu/faculty-research/management/"),
        _cards("MSBK", "McDonough School of Business — Marketing",
               ["Marketing"],
               "https://msb.georgetown.edu/faculty-research/marketing/"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
