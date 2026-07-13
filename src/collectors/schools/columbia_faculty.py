"""Columbia University faculty config (via the faculty_graph engine).

Columbia fronts its shared "Columbia Sites" Drupal platform (fas/gsas/
engineering + most department hosts) with a Cloudflare *managed challenge* —
plain requests get 403 regardless of UA/headers, but the engine's headless
render clears it (verified live on physics.columbia.edu; the wall re-arms
under burst pressure, so the render settle + profile throttle matter).
Coverage splits in three, all live-verified 2026-07-12/13:

* **Static hosts (no challenge)** — departments on the CUIT WordPress farm,
  Squarespace, or self-hosted servers; six themes: Economics (WP Divi
  TotalShowcase — the ``.ts-float-left`` subset, the page renders every card
  twice; names are NOT links), History (cmed list view, "Last, First"),
  Mathematics (WP Connections; email in a hidden-but-static ``.cn-detail``),
  EALAC (WP listing grid, rank in ``.excerpt``), MESAAS (hand-rolled
  bootstrap; rank is a bare text node → ``title_re``), Classics (Squarespace
  ``/profiles``; no rank on the listing, email as plain text in the excerpt),
  SEAS Computer Science (custom WP; "Last, First").

* **Columbia Sites teaser hosts (render mode)** — one shared card markup:
  ``article.teaser``, name in ``h2``, profile link on the card ``a``, and a
  *group label* (not always an academic rank) in
  ``.field--name-field-cu-faculty-rank .field--item`` — values range from
  "Professor Emeritus" (physics) to "Full-time Faculty" (english) to
  "Current" (chem), so the shared ladder gate keys on group semantics.
  Listings are single-page everywhere (no pager). Emails are never on the
  listing; the gated profile pass renders each profile (same wall) and reads
  ``field--name-field-cu-email-address`` (+ research interests + real title).

* **stat.columbia.edu** — curl-403 but render clears it; a self-hosted WP
  Connections directory whose cards carry name, bare-text rank AND a real
  mailto, so it lands emailed with no profile pass.

Anthropology's directory is a name-tile view (no rank on the tile) but is
faculty-only, so tiles land with the default title and the gated profile pass
recovers rank/email. Cross-institution affiliates ("Professor, Barnard
College", "…, SIPA") are dropped by title regex on the static hosts.

Single source ("columbia_faculty"); department rides each record, ids
namespaced by department short-code.

Deferred (documented blockers): Political Science + Astronomy (name-tile
directories that MIX faculty with staff/researchers and carry no rank —
unsafe to gate without an always-on rendered profile pass; revisit via a
rank-bearing view once found), APAM (four per-program roster pages, all
challenge-shelled during recon), the Columbia Engineering theme departments
BME/ChemE/EEE/ME/Civil (12-card XHR pagination; the grid exposes a JSON API
at ``/search_results/api/v1/directory`` worth wiring as a dedicated source),
professional schools — Law (AJAX-only directory), Teachers College (JS app),
Business/Journalism/SIPA/Climate/Social Work (same challenge, lower priority),
GSAPP (460 cards, names only, no rank), and Vagelos/CUMC clinical departments
(unmapped per-dept hosts).
"""

from __future__ import annotations

from .. import faculty_graph

# Ladder faculty on the STATIC hosts, where the title is a real academic rank;
# drop emeriti/adjunct/visiting and cross-institution affiliates whose title
# carries their real home.
_LADDER = {
    "require": r"\bprofessor\b|\blecturer\b",
    "drop": (r"emerit|adjunct|visiting|barnard|union theological|jewish theological"
             r"|teachers college|\bsipa\b|international and public affairs"),
}

# ---- Columbia Sites Drupal platform (Cloudflare-challenged; render mode) ----
_CU_SELECTORS = {
    "card": "article.teaser",
    "name": "h2",
    "link": "a",
    # Union: the rank/group field when present, else the card's trailing title
    # div — so a rank-less card (germanic's "PhD Student" tiles) falls back to
    # text the ladder gate can reject instead of the "Professor" default.
    "title": ".field--name-field-cu-faculty-rank .field--item, :scope > div",
}

# The rank field is a GROUP label; keep faculty/professor/lecturer groups,
# drop every non-ladder group observed across the platform (music alone tags
# alumni/grads/performance associates/in-memoriam on its /people directory).
_CU_LADDER = {
    "require": r"faculty|professor|lecturer",
    "drop": (r"emerit|adjunct|alumni|graduate|student|staff|memoriam|previously"
             r"|performance|affiliat|barnard|fellow|instructional|postdoc|other depts"),
}

# Gated per-profile pass (OFE_ENRICH_PROFILES=1): profiles sit behind the same
# challenge, so it renders each one. Serial + throttled — concurrent renders
# re-arm the wall. Recovers the real title (the listing carried a group label),
# public email, and the research-interests line.
_CU_ENRICH = {
    "render": True,
    "email_selector": ".field--name-field-cu-email-address a[href^='mailto:']",
    "email_drop": r"^[^@]*$",
    "research_selector": ".field--name-field-cu-research-interest-ref",
    "title_selector": ".field--name-field-cu-title-department",
    "ladder_recheck": {"drop": r"emerit|adjunct|visiting"},
    "throttle": 2.0,
}


def _cusite(short: str, name: str, majors: list[str], host: str,
            path: str = "/content/faculty", *, ladder: dict | None = None) -> dict:
    """A Columbia Sites platform department (headless render past the CF wall)."""
    url = f"https://{host}{path}"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _CU_SELECTORS,
                       "ladder_filter": ladder or _CU_LADDER,
                       "render": True, "render_settle": 8000,
                       "profile_enrich": _CU_ENRICH}}


SCHOOL: dict = {
    "school_slug": "columbia",
    "source": "columbia_faculty",
    "organization": "Columbia University",
    "location": "New York, NY",
    "id_prefix": "columbia",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Columbia University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Static hosts (no Cloudflare challenge) -------------------------
        {
            "short": "ECON", "name": "Department of Economics", "majors": ["Economics"],
            "directory_url": "https://econ.columbia.edu/faculty/",
            "scrape": {
                "url": "https://econ.columbia.edu/faculty/",
                # .ts-float-left subset only — the page renders every card twice.
                "selectors": {"card": "div.tshowcase-inner-box.ts-float-left",
                              "name": "div.tshowcase-box-title",
                              "title": "div.tshowcase-single-position",
                              "email": "div.tshowcase-single-email a[href^='mailto:']"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "HIST", "name": "Department of History", "majors": ["History"],
            "directory_url": "https://history.columbia.edu/faculty/",
            "scrape": {
                "url": "https://history.columbia.edu/faculty/",
                "selectors": {"card": "li.cmed_list_view_item",
                              "name": "p.cmed_list_view_title a b",
                              "link": "p.cmed_list_view_title a",
                              "title": "span.cmed_list_view_position",
                              "email": "a[href^='mailto:']"},
                "name_flip": True,
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "MATH", "name": "Department of Mathematics", "majors": ["Mathematics"],
            "directory_url": "https://www.math.columbia.edu/people/faculty-by-rank/",
            "scrape": {
                "url": "https://www.math.columbia.edu/people/faculty-by-rank/",
                "selectors": {"card": "div.cn-entry",
                              "name": "span.fn",
                              "link": "h3.cn-accordion-item a",
                              "title": "span.title",
                              "email": "span.email-address a[href^='mailto:']"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "EALAC", "name": "Department of East Asian Languages and Cultures",
            "majors": ["East Asian Languages and Cultures"],
            "directory_url": "https://ealac.columbia.edu/people/faculty/",
            "scrape": {
                "url": "https://ealac.columbia.edu/people/faculty/",
                "selectors": {"card": "div.listing-item", "name": "a.title",
                              "link": "a.title", "title": "span.excerpt"},
                "ladder_filter": _LADDER,
                # No emails on the listing — WP profiles carry a real mailto.
                "profile_enrich": {
                    "email_selector": ".entry-content a[href^='mailto:']",
                    "email_drop": r"^[^@]*$",
                    "throttle": 0.15,
                },
            },
        },
        {
            "short": "MESAAS",
            "name": "Department of Middle Eastern, South Asian, and African Studies",
            "majors": ["Middle Eastern, South Asian, and African Studies"],
            "directory_url": "https://mesaas.columbia.edu/faculty-directory/",
            "scrape": {
                "url": "https://mesaas.columbia.edu/faculty-directory/",
                # The rank is a bare text node between <br>s — no wrapper element.
                "selectors": {"card": "div.col-sm-6:has(b a)", "name": "b a",
                              "link": "b a",
                              "title_re": (r"\b((?:Senior |Adjunct |Visiting |Associate "
                                           r"|Assistant )?(?:Professor|Lecturer)"
                                           r"[^@]{0,60}?)\s+[A-Za-z0-9._%+-]+@"),
                              "email": "a[href^='mailto:']"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "CLST", "name": "Department of Classics", "majors": ["Classics"],
            "directory_url": "https://classics.columbia.edu/profiles",
            "scrape": {
                "url": "https://classics.columbia.edu/profiles",
                # Squarespace: no rank on the listing (everyone lands as the
                # "Professor" default); email is plain text inside the excerpt.
                "selectors": {"card": "div.summary-item",
                              "name": "a.summary-title-link",
                              "link": "a.summary-title-link",
                              "email": "div.summary-excerpt"},
                # The one Barnard affiliate is only identifiable by excerpt text.
                "field_filter": {"selector": "div.summary-excerpt",
                                 "exclude": r"@barnard\.edu|barnard hall"},
            },
        },
        {
            "short": "CS", "name": "Department of Computer Science",
            "majors": ["Computer Science"],
            "directory_url": "https://www.cs.columbia.edu/people/faculty/",
            "scrape": {
                "url": "https://www.cs.columbia.edu/people/faculty/",
                "selectors": {"card": "div.row.faculty-row",
                              "name": "span.faculty-name a",
                              "link": "span.faculty-name a",
                              "title": "div.faculty-title small",
                              "email": "a[href^='mailto:']"},
                "name_flip": True,
                "ladder_filter": _LADDER,
            },
        },
        # ---- Columbia Sites platform (render past the Cloudflare challenge) --
        # Arts & Sciences: Humanities
        _cusite("ARTH", "Department of Art History and Archaeology",
                ["Art History", "Architecture"], "arthistory.columbia.edu"),
        _cusite("ENGL", "Department of English and Comparative Literature",
                ["English", "Comparative Literature and Society"], "english.columbia.edu"),
        _cusite("FREN", "Department of French", ["French"], "french.columbia.edu",
                path="/faculty"),
        _cusite("GERM", "Department of Germanic Languages", ["German"],
                "germanic.columbia.edu", path="/people"),
        _cusite("ITAL", "Department of Italian", ["Italian"], "italian.columbia.edu",
                path="/people"),
        _cusite("LAIC", "Department of Latin American and Iberian Cultures",
                ["Spanish", "Latin American and Caribbean Studies"],
                "laic.columbia.edu"),
        _cusite("MUSI", "Department of Music", ["Music"], "music.columbia.edu",
                path="/people"),
        _cusite("PHIL", "Department of Philosophy", ["Philosophy"],
                "philosophy.columbia.edu"),
        _cusite("RELI", "Department of Religion", ["Religion"], "religion.columbia.edu"),
        {
            # Slavic embeds the rank in the h2 name ("Name, Senior Lecturer in…").
            **_cusite("SLAV", "Department of Slavic Languages", ["Slavic Studies"],
                      "slavic.columbia.edu", path="/faculty"),
            "scrape": {
                "url": "https://slavic.columbia.edu/faculty",
                "selectors": {**_CU_SELECTORS,
                              "name_strip": r",\s*[^,]*(?:Professor|Lecturer|Chair).*$"},
                "ladder_filter": _CU_LADDER,
                "render": True, "render_settle": 8000,
                "profile_enrich": _CU_ENRICH,
            },
        },
        # Arts & Sciences: Social Sciences
        _cusite("AAADS", "Department of African American and African Diaspora Studies",
                ["African American and African Diaspora Studies"],
                "afamstudies.columbia.edu", path="/faculty"),
        {
            # Anthropology's directory is a name-tile view (faculty-only, no rank
            # on the tile) — records land with the default title; the gated
            # profile pass recovers rank/email and re-gates.
            "short": "ANTH", "name": "Department of Anthropology",
            "majors": ["Anthropology"],
            "directory_url": "https://anthropology.columbia.edu/content/faculty-directory",
            "scrape": {
                "url": "https://anthropology.columbia.edu/content/faculty-directory",
                "selectors": {"card": "div.views-row",
                              "name": ".views-field-title a",
                              "link": ".views-field-title a"},
                "render": True, "render_settle": 8000,
                "profile_enrich": _CU_ENRICH,
            },
        },
        _cusite("SOCI", "Department of Sociology", ["Sociology"],
                "sociology.columbia.edu", path="/faculty"),
        # Arts & Sciences: Natural Sciences
        _cusite("BIOL", "Department of Biological Sciences", ["Biology"],
                "biology.columbia.edu", path="/content/faculty-directory"),
        _cusite("CHEM", "Department of Chemistry", ["Chemistry"], "chem.columbia.edu",
                # chem tags its ladder roster "Current" (vs Instructional/Adjunct).
                ladder={"require": r"\bcurrent\b|faculty|professor|lecturer",
                        "drop": r"instructional|adjunct|emerit"}),
        _cusite("EESC", "Department of Earth and Environmental Sciences",
                ["Earth and Environmental Sciences"], "eesc.columbia.edu"),
        _cusite("E3B", "Department of Ecology, Evolution and Environmental Biology",
                ["Biology", "Sustainable Development"], "e3b.columbia.edu",
                path="/faculty"),
        _cusite("PHYS", "Department of Physics", ["Physics"], "physics.columbia.edu"),
        _cusite("PSYC", "Department of Psychology", ["Psychology"],
                "psychology.columbia.edu"),
        # SEAS (Columbia Sites hosts)
        _cusite("EE", "Department of Electrical Engineering",
                ["Electrical Engineering", "Computer Engineering"],
                "www.ee.columbia.edu"),
        _cusite("IEOR", "Department of Industrial Engineering and Operations Research",
                ["Industrial Engineering and Operations Research"],
                "ieor.columbia.edu", path="/people/ieor-faculty"),
        # ---- stat.columbia.edu (WP Connections behind the challenge) --------
        {
            "short": "STAT", "name": "Department of Statistics", "majors": ["Statistics"],
            "directory_url": "https://stat.columbia.edu/faculty",
            "scrape": {
                "url": "https://stat.columbia.edu/faculty",
                # Cards carry name, bare-text rank, AND a real mailto — the one
                # challenged host that needs no profile pass.
                "selectors": {"card": "div.cn-list-item.vcard",
                              "name": "h3.cn-entry-name a",
                              "link": "h3.cn-entry-name a",
                              "title_re": (r"\b((?:Associate |Assistant |Visiting "
                                           r"|Adjunct |Senior )?(?:Professor|Lecturer)"
                                           r"(?:\s+(?:of|in)\s+[A-Za-z ]{2,30})?)"),
                              "email": "a[href^='mailto:']"},
                "ladder_filter": _LADDER,
                "render": True, "render_settle": 8000,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
