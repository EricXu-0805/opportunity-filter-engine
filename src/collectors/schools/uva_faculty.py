"""University of Virginia faculty config (via the faculty_graph engine).

Live-verified 2026-07-19. UVA splits cleanly into four markup families:

* ``as_teaser`` — the College of Arts & Sciences shared Drupal 10 platform.
  Every A&S department runs the same ``uva-as-*`` theme; the faculty roster
  lives at a per-dept ``/faculty`` view (a handful use a variant path:
  English ``/general-faculty``, Astronomy ``/faculty-senior-research-staff``,
  Creative Writing ``/people``) built from ``article.uva_people-teaser``
  cards. Each card carries a clean name link (``a.node-title`` →
  ``/people/<slug>``) and a rank line (``.field-field_title``, e.g.
  "Associate Professor of Biology; Director of Graduate Studies"); emeriti,
  affiliated, and courtesy faculty live on SEPARATE pages
  (``/emeritus-faculty``, ``/affiliated-faculty``) so the ``/faculty`` view is
  already core-faculty-only — the ladder_filter is a light safety gate. No
  email is exposed on the listing, so the env-gated profile pass backfills
  email (plain ``mailto:``) and the authoritative rank (``.field-field_title``)
  from each ``/people/<slug>`` profile. Served over plain nginx, no WAF, no
  render needed.

* ``math_bootstrap`` — the Department of Mathematics runs its own bespoke
  Bootstrap directory at math.virginia.edu/faculty/. One ``div.row`` per
  person: name link ``a.nonupper-h5`` (absolute ``/people/<uid>/`` URL), rank
  in the first ``.mb-1 em``, and — unlike A&S — a plain inline ``mailto:``, so
  no profile pass is needed here.

* ``phys_table`` — the Department of Physics runs a legacy ASP directory.
  The list view (people-list.asp?CATEGORY=Faculty&VIEW=list) yields a clean
  per-person ``td.views-field-title`` cell (name ``h4 a`` →
  ``personal.asp?UID=``, rank the first ``em``). The email column is
  JavaScript ``String.fromCharCode`` obfuscation inside a malformed
  ``mailto:`` attribute that the engine's decode chain cannot recover, so
  Physics records carry name + rank + department only (email backfills via the
  central OpenAlex/enrichment pass, not the directory).

* ``eng_people`` — the School of Engineering & Applied Science (SEAS) is
  consolidated on ONE Cloudflare-challenged site (engineering.virginia.edu);
  the per-dept subdomains and the standalone CS site all redirect here. The
  Turnstile interstitial requires headless render (``render: True``), after
  which each dept's ``/department/<slug>/people`` view exposes
  ``.people_list_item`` cards (name ``.contact_block_name_link_label`` →
  ``/faculty/<slug>``, rank ``.people_list_item_title``). The people view
  mixes staff and courtesy cross-appointments in with the faculty, so the
  ladder_filter require-gate on rank is load-bearing here; the engine's
  url-based dedup collapses professors who appear on several dept pages
  (courtesy appointments) to their first-seen department. Email lives only on
  the (also-challenged) profile pages, so the profile pass runs with
  ``render: True`` when enrichment is enabled.

Professional schools + interdisciplinary programs added 2026-07-20 through four
more markup families, all live-verified this pass:

* ``json_dir`` — McIntire School of Commerce runs a decoupled Nuxt frontend over
  a Drupal JSON:API (content.mcintire.virginia.edu); the faculty roster rides
  ``/jsonapi/node/person?filter[field_role]=faculty``. JSON:API hard-caps
  ``page[limit]`` at 50, so the ~111 faculty are pulled across three disjoint
  ``page[offset]`` windows (nid-sorted for stability). Batten (Public Policy)
  runs a WordPress ``uva_person`` custom post type; its ``?person_type=17``
  facet returns every faculty member in one 100-cap page (nested name/position
  objects, a clean ``research_interests`` list → keywords).
* ``sitemap`` — the School of Architecture directory is a JS "rocket_search"
  grid whose data endpoint returns HTML-inside-JSON (escaped quotes defeat the
  scrape parser) and hard-caps pagesize at 12; but each ``/people/<slug>``
  PROFILE is plain server-rendered HTML, so the sitemap mechanism enumerates the
  profile URLs from ``sitemap.xml`` and scrapes ``h1.post__heading`` /
  ``.post__subhead`` / ``mailto`` off each, ladder-gating the staff/students/
  board/emeriti out.
* ``scrape`` + ``render`` + ``paginate`` — the School of Data Science (Nuxt SSR
  ``/search?t=people``, ten ``.teaser--search`` cards per ``?page=N``, a
  ``field_filter`` on the role label keeps "Faculty") and the School of
  Education & Human Development (Drupal directory behind an Akamai 403 to plain
  HTTP but reachable through headless Chromium; the ``?type=11`` facet scopes to
  Faculty, ``?page=N`` 0-indexed pagination, rank in ``ul.positions``).
* ``people_view`` — the Program in Fundamental Neuroscience and the American
  Studies core-faculty page render the shared A&S Drupal through the
  ``our-people-view`` component (``article.container`` / ``uva_people-teaser``
  cards, name link nested in an ``h2/h3.node-title``). Both are interdisciplinary
  rosters whose cross-appointed members mostly dedup back to their home
  departments (Biology, Psychology, English, Politics …), so each nets only its
  home-based faculty.

Single source ("uva_faculty"); department rides each record, ids namespaced by
department short-code.

Deferred (2026-07-20 recon):
* School of Nursing (nursing.virginia.edu) — unreachable from this environment:
  the server drops the connection during the TLS handshake
  (curl ``SSL_ERROR_SYSCALL``; headless Chromium ``net::ERR_CONNECTION_CLOSED``
  on all three attempts). A TLS-fingerprint / IP-level block, not a markup
  problem — needs an allow-listed egress or the official channel.
* Linguistics Program — ``linguistics.virginia.edu/faculty`` renders to a shell
  under headless Chromium: zero person cards, zero ``/people`` or profile links
  in the settled DOM (the faculty list never populates). Its faculty are
  cross-appointments from covered A&S departments (Anthropology, English,
  Spanish, Psychology).
* Global Studies — served by the bespoke provost-``sites`` SPA
  (``vssl-stripe--card`` components on api.sites.provost.virginia.edu); the few
  listed faculty are cross-appointments whose profile URLs resolve to already-
  covered home departments, so it nets ~zero net-new records.
* Physics email — ``String.fromCharCode`` JS obfuscation (it decodes to
  ``<uid>@virginia.edu``, but no config mechanism derives an address from a
  profile's URL param); names + ranks collected, email backfilled by the
  central OpenAlex/enrichment pass.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- shared ladder gates ---------------------------------------------------
# Keep tenure-track + teaching-track + research professors and lecturers; drop
# the emeritus/adjunct/visiting/courtesy tails that some listings still mix in.
_DROP = r"emerit|adjunct|visiting|courtesy|by affiliation"
_REQ = r"professor|lecturer|instructor|lector|artist"
_LADDER = {"require": _REQ, "drop": _DROP}
_LADDER_DROP = {"drop": _DROP}

# Shared dept inboxes an enrich pass might grab off a profile before the
# personal address; never assign them (would also collapse people in dedup).
_EMAIL_DROP = (r"^(?:info|contact|office|admin|dept|department|advising|undergrad"
               r"|engr-comms|comms|webmaster|as-)")

# ---- as_teaser (College of Arts & Sciences shared Drupal) ------------------
_TEASER_SEL = {
    "card": "article.uva_people-teaser",
    "name": "a.node-title",
    "link": "a.node-title",
    "title": ".field-field_title",
}
# The A&S profile pages publish a plain mailto and repeat the authoritative
# rank in .field-field_title — the env-gated pass backfills both.
_TEASER_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": _EMAIL_DROP,
    "title_selector": ".field-field_title",
    "ladder_recheck": _LADDER_DROP,
    # A&S profiles that carry a research-areas taxonomy publish one chip per area
    # (Psychology, Political Science, …); depts without it yield nothing (mixed).
    "research_items_selector": (".field-field_research_areas a, "
                                ".field-field_research_interesdt > div:nth-of-type(2) div"),
    "throttle": 0.2,
}


def _teaser(short: str, name: str, majors: list[str], url: str, *,
            ladder: dict = _LADDER) -> dict:
    """An A&S department on the shared uva_people-teaser Drupal component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _TEASER_SEL,
                   "ladder_filter": ladder, "profile_enrich": _TEASER_ENRICH},
    }


# ---- eng_people (SEAS, Cloudflare-challenged → render) ---------------------
_ENG_SEL = {
    "card": ".people_list_item",
    "name": ".contact_block_name_link_label",
    "link": ".contact_block_name_link",
    "title": ".people_list_item_title",
}
# SEAS profiles sit behind the same Cloudflare Turnstile as the listing, so a
# per-profile RENDER enrich would headless-render ~200 pages at up to 60s each
# (pathologically slow, and Turnstile fails most). Keep a cheap plain-HTTP email
# probe (fails fast on the challenge shell); SEAS ships title-only when it does
# not resolve. The dept LISTING render (one page per dept) still runs.
_ENG_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": _EMAIL_DROP,
    "throttle": 0.2,
}


def _eng(short: str, name: str, majors: list[str], slug: str, *,
         view: str = "people") -> dict:
    """A SEAS department served by engineering.virginia.edu (render mode).

    Most departments expose their roster at ``/department/<slug>/people``. The
    Charles L. Brown Dept of Electrical & Computer Engineering is the lone
    exception: its ``/people`` view renders an EMPTY grid (its faculty list is
    populated by a client-side call that never resolves under headless
    Chromium), but the SAME site serves the full ``.people_list_item`` roster
    at a distinct ``/department/electrical-and-computer-engineering/faculty``
    sub-view — so ECE passes ``view="faculty"``.
    """
    url = f"https://engineering.virginia.edu/department/{slug}/{view}"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "render": True, "render_settle": 6000,
                   "selectors": _ENG_SEL, "ladder_filter": _LADDER,
                   "profile_enrich": _ENG_ENRICH},
    }


# ---- people_view (A&S interdisciplinary programs, article.container variant)
# The neuroscience program and the American Studies core-faculty page run the
# SAME shared A&S Drupal, but render the roster through the ``our-people-view``
# component whose cards differ from the plain ``uva_people-teaser``: the name
# link nests inside a heading (``h2/h3.node-title > a``) with a visually-hidden
# "(opens in a new tab)" span, so the name selector reaches the inner ``a`` and
# strips the a11y suffix. Rank stays in ``.field-field_title``. Many of these
# people are cross-appointments whose profile URL points back to their home
# department (Biology, English, Politics, …) — the engine's url-dedup collapses
# them there, so a program page nets only its home-based faculty.
_PV_SEL = {
    "card": "article.uva_people-teaser",
    "name": ".node-title a",
    "link": ".node-title a",
    "name_strip": r"\s*\(opens in a new tab\)\s*$",
    "title": ".field-field_title",
}


def _pv(short: str, name: str, majors: list[str], url: str, *,
        card: str = "article.uva_people-teaser", ladder: dict = _LADDER) -> dict:
    """An A&S program on the shared Drupal ``our-people-view`` card variant."""
    sel = {**_PV_SEL, "card": card}
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": sel, "ladder_filter": ladder,
                   "profile_enrich": _TEASER_ENRICH},
    }


# ---- McIntire (decoupled Drupal JSON:API, page[offset] windows) ------------
_MCI_LADDER = {"require": r"professor|lecturer|instructor",
               "drop": r"emerit|visiting|adjunct"}


def _mcintire(offset: int) -> dict:
    """One page[offset] window of McIntire's faculty JSON:API (50/page cap)."""
    url = ("https://content.mcintire.virginia.edu/jsonapi/node/person"
           "?filter[field_role]=faculty&sort=drupal_internal__nid"
           f"&page[limit]=50&page[offset]={offset}")
    return {
        "short": f"MCI{offset}", "name": "McIntire School of Commerce",
        "majors": ["Commerce", "Business", "Accounting", "Finance",
                   "Marketing", "Management", "Information Technology"],
        "directory_url": "https://www.commerce.virginia.edu/faculty",
        "json_dir": {
            "url": url, "records_key": "data",
            "name_fields": ["attributes.title"],
            "title_field": "attributes.field_job_title",
            "email_field": "attributes.field_email",
            "link_field": "attributes.path.alias",
            "link_base": "https://www.commerce.virginia.edu/faculty",
            "ladder_filter": _MCI_LADDER,
        },
    }


SCHOOL: dict = {
    "school_slug": "uva",
    "source": "uva_faculty",
    "organization": "University of Virginia",
    "location": "Charlottesville, VA",
    "id_prefix": "uva",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Virginia) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Arts & Sciences: natural sciences ------------------
        _teaser("BIOL", "Department of Biology", ["Biology"],
                "https://bio.as.virginia.edu/faculty"),
        _teaser("CHEM", "Department of Chemistry", ["Chemistry"],
                "https://chemistry.as.virginia.edu/faculty"),
        _teaser("EVSC", "Department of Environmental Sciences",
                ["Environmental Sciences"],
                "https://evsc.as.virginia.edu/faculty"),
        _teaser("PSYC", "Department of Psychology", ["Psychology"],
                "https://psychology.as.virginia.edu/faculty"),
        _teaser("STAT", "Department of Statistics", ["Statistics"],
                "https://statistics.as.virginia.edu/faculty"),
        _teaser("ASTR", "Department of Astronomy", ["Astronomy"],
                "https://astronomy.as.virginia.edu/faculty-senior-research-staff"),
        # ---- Mathematics & Physics (bespoke platforms) ---------------------
        {
            "short": "MATH", "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": "https://math.virginia.edu/faculty/",
            "scrape": {
                "url": "https://math.virginia.edu/faculty/",
                "selectors": {"card": "div.row:has(a.nonupper-h5)",
                              "name": "a.nonupper-h5", "link": "a.nonupper-h5",
                              "title": ".mb-1 em",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "PHYS", "name": "Department of Physics", "majors": ["Physics"],
            "directory_url": "https://www.phys.virginia.edu/People/people-list.asp?CATEGORY=Faculty&VIEW=list",
            "scrape": {
                "url": "https://www.phys.virginia.edu/People/people-list.asp?CATEGORY=Faculty&VIEW=list",
                # Email column is String.fromCharCode JS in a malformed mailto
                # attribute the decode chain can't recover — no email selector.
                "selectors": {"card": "td.views-field-title",
                              "name": "h4 a", "link": "h4 a", "title": "em"},
                "ladder_filter": _LADDER,
            },
        },
        # ---- College of Arts & Sciences: social sciences -------------------
        _teaser("ANTH", "Department of Anthropology", ["Anthropology"],
                "https://anthropology.as.virginia.edu/faculty"),
        _teaser("ECON", "Department of Economics", ["Economics"],
                "https://economics.virginia.edu/faculty"),
        _teaser("POLI", "Department of Politics", ["Political Science", "Politics"],
                "https://politics.virginia.edu/faculty"),
        _teaser("SOC", "Department of Sociology", ["Sociology"],
                "https://sociology.as.virginia.edu/faculty"),
        _teaser("PST", "Program in Political and Social Thought",
                ["Political and Social Thought"],
                "https://pst.as.virginia.edu/faculty"),
        _teaser("WGS", "Department of Women, Gender & Sexuality",
                ["Women, Gender and Sexuality"],
                "https://wgs.as.virginia.edu/faculty"),
        # ---- College of Arts & Sciences: humanities ------------------------
        _teaser("HIST", "Corcoran Department of History", ["History"],
                "https://history.virginia.edu/faculty"),
        _teaser("ENGL", "Department of English", ["English", "Literature"],
                "https://english.as.virginia.edu/general-faculty"),
        _teaser("CRWR", "Creative Writing Program", ["Creative Writing"],
                "https://creativewriting.virginia.edu/people"),
        _teaser("PHIL", "Corcoran Department of Philosophy", ["Philosophy"],
                "https://philosophy.virginia.edu/faculty"),
        _teaser("RELG", "Department of Religious Studies", ["Religious Studies"],
                "https://religiousstudies.as.virginia.edu/faculty"),
        _teaser("CLAS", "Department of Classics", ["Classics"],
                "https://classics.as.virginia.edu/faculty"),
        _teaser("ARTH", "Department of Art", ["Art History", "Studio Art"],
                "https://art.as.virginia.edu/faculty"),
        _teaser("MUSI", "McIntire Department of Music", ["Music"],
                "https://music.virginia.edu/faculty"),
        _teaser("MDST", "Department of Media Studies", ["Media Studies"],
                "https://mediastudies.as.virginia.edu/faculty"),
        _teaser("FREN", "Department of French", ["French"],
                "https://french.as.virginia.edu/faculty"),
        _teaser("GERM", "Department of Germanic Languages and Literatures",
                ["German"], "https://german.as.virginia.edu/faculty"),
        _teaser("SLAV", "Department of Slavic Languages and Literatures",
                ["Slavic Studies"], "https://slavic.as.virginia.edu/faculty"),
        _teaser("SIP", "Department of Spanish, Italian, and Portuguese",
                ["Spanish", "Italian", "Portuguese"],
                "https://spanitalport.as.virginia.edu/faculty"),
        _teaser("EALC", "Department of East Asian Languages, Literatures and Cultures",
                ["East Asian Studies"],
                "https://eastasian.as.virginia.edu/faculty"),
        _teaser("MESALC", "Department of Middle Eastern and South Asian Languages and Cultures",
                ["Middle Eastern Studies", "South Asian Studies"],
                "https://mesalc.as.virginia.edu/faculty"),
        # ---- School of Engineering & Applied Science (render) --------------
        _eng("CS", "Department of Computer Science", ["Computer Science"],
             "computer-science"),
        _eng("MAE", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"],
             "mechanical-and-aerospace-engineering"),
        _eng("CHE", "Department of Chemical Engineering", ["Chemical Engineering"],
             "chemical-engineering"),
        _eng("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "civil-and-environmental-engineering"),
        _eng("MSE", "Department of Materials Science and Engineering",
             ["Materials Science and Engineering"],
             "materials-science-and-engineering"),
        _eng("ENGS", "Department of Engineering and Society",
             ["Engineering and Society"], "engineering-and-society"),
        _eng("ECE",
             "Charles L. Brown Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "electrical-and-computer-engineering", view="faculty"),
        _eng("BME", "Department of Biomedical Engineering",
             ["Biomedical Engineering"], "biomedical-engineering"),
        # ---- School of Data Science ----------------------------------------
        # Nuxt SSR search grid (datascience.virginia.edu/search?t=people); each
        # ?page=N is a server-rendered page of ten .teaser--search cards mixing
        # faculty, staff, students, and board — the field_filter keeps the
        # role-label "Faculty" (and "Faculty Leadership") and drops the rest.
        # The Drupal JSON:API (api.dsi.virginia.edu) returns node--person empty
        # to anonymous, so the rendered search is the only public roster.
        {
            "short": "DS", "name": "School of Data Science",
            "majors": ["Data Science", "Statistics", "Machine Learning"],
            "directory_url": "https://datascience.virginia.edu/search?t=people",
            "scrape": {
                "url": "https://datascience.virginia.edu/search?t=people",
                "render": True, "render_settle": 5000,
                "selectors": {"card": ".teaser--search",
                              "name": ".field--name",
                              "link": "h3.teaser-title a"},
                "field_filter": {"selector": ".teaser-label",
                                 "include": r"faculty", "exclude": r"emerit"},
                "paginate": {"param": "page", "start": 2, "max": 30},
            },
        },
        # ---- McIntire School of Commerce -----------------------------------
        # Nuxt-over-Drupal-JSON:API: the roster lives at the decoupled backend
        # content.mcintire.virginia.edu/jsonapi/node/person, filtered to
        # field_role=faculty. JSON:API hard-caps page[limit] at 50 and json_dir
        # does one fetch, so the ~111 faculty ride three disjoint page[offset]
        # windows (sorted by nid for stability); the ladder_filter drops the
        # emeriti mixed into the faculty role. Profile URLs are path.alias
        # joined onto /faculty/<alias>.
        *(_mcintire(off) for off in (0, 50, 100)),
        # ---- Frank Batten School of Leadership and Public Policy -----------
        # WordPress custom post type ``uva_person`` (a shared UVA WP plugin); the
        # ?person_type=17 facet returns all faculty in one 100-cap page. Nested
        # fields: name.{firstname,lastname}, position.primary, research_interests
        # (a clean list → keywords).
        {
            "short": "BATTEN",
            "name": "Frank Batten School of Leadership and Public Policy",
            "majors": ["Public Policy", "Leadership"],
            "directory_url": "https://batten.virginia.edu/faculty",
            "json_dir": {
                "url": "https://batten.virginia.edu/wp-json/wp/v2/uva_person"
                       "?per_page=100&person_type=17",
                "name_fields": ["name.firstname", "name.lastname"],
                "title_field": "position.primary",
                "email_field": "email", "link_field": "permalink",
                "research_field": "research_interests[]",
                "ladder_filter": {"require": r"professor|lecturer|instructor",
                                  "drop": r"emerit|adjunct|visiting"},
            },
        },
        # ---- School of Architecture ----------------------------------------
        # A JS "rocket_search" grid whose data endpoint returns HTML-inside-JSON
        # (escaped quotes defeat the scrape parser) and hard-caps pagesize at 12,
        # so the listing can't be walked directly — but every /people/<slug>
        # PROFILE is served as plain server-rendered HTML (h1.post__heading name,
        # .post__subhead rank, mailto). The sitemap mechanism enumerates the
        # profile URLs from sitemap.xml and scrapes each; the ladder_filter keeps
        # professors/lecturers and drops the staff, students, board, and emeriti
        # that share the /people/ namespace.
        {
            "short": "ARCH", "name": "School of Architecture",
            "majors": ["Architecture", "Landscape Architecture",
                       "Urban and Environmental Planning", "Architectural History"],
            "directory_url": "https://www.arch.virginia.edu/people/faculty",
            "sitemap": {
                "sitemaps": ["https://www.arch.virginia.edu/sitemap.xml"],
                "include": r"/people/[a-z0-9]+-[a-z0-9-]+",
                "render": False,
                "selectors": {"name": "h1.post__heading",
                              "title": ".post__subhead",
                              "email": "a[href^='mailto:']"},
                "ladder_filter": {"require": r"professor|lecturer|instructor|artist",
                                  "drop": r"emerit|adjunct|visiting"},
                "cap": 200, "throttle": 0.15,
            },
        },
        # ---- School of Education and Human Development ----------------------
        # Drupal directory behind an Akamai 403 to plain HTTP but reachable via
        # headless Chromium; the ?type=11 facet scopes to Faculty, paginated
        # (?page=N, 0-indexed). Rank lives in ul.positions → ladder gate drops
        # the emeriti/leadership-only rows.
        {
            "short": "EDHD",
            "name": "School of Education and Human Development",
            "majors": ["Education", "Human Development", "Kinesiology",
                       "Educational Psychology"],
            "directory_url": "https://education.virginia.edu/about/directory",
            "scrape": {
                "url": "https://education.virginia.edu/about/directory?type=11",
                "render": True, "render_settle": 5000,
                "selectors": {"card": "li.profile-listing__rows-items__profile",
                              "name": "h3 a.link-arrow",
                              "link": "h3 a.link-arrow",
                              "title": "ul.positions"},
                "ladder_filter": {"require": r"professor|lecturer|instructor",
                                  "drop": r"emerit|adjunct|visiting"},
                "paginate": {"param": "page", "start": 1, "max": 12},
            },
        },
        # ---- College of Arts & Sciences: interdisciplinary programs --------
        _pv("NESC", "Program in Fundamental Neuroscience", ["Neuroscience"],
            "https://neuroscience.as.virginia.edu/people",
            card="article.container[data-history-node-id]"),
        _pv("AMST", "Department of American Studies", ["American Studies"],
            "https://americanstudies.as.virginia.edu/core-faculty"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
