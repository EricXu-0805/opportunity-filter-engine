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

Single source ("uva_faculty"); department rides each record, ids namespaced by
department short-code.

Deferred (2026-07-19 recon):
* SEAS Electrical & Computer Engineering (Charles L. Brown Dept) — unlike the
  other six SEAS departments, its ``/people`` view renders an EMPTY roster
  under headless Chromium (no ``.people_list_item`` cards, no ``/faculty/``
  links in the settled DOM) and hangs on a ``networkidle`` wait; the faculty
  list is populated by a client-side data call that does not resolve under
  render. Needs a bespoke API/XHR probe before wiring.
* Biomedical Engineering (SEAS/SOM joint) — not present in the SEAS site's
  department nav under a stable ``/department/<slug>`` slug; needs its own
  render probe before wiring.
* Physics email — ``String.fromCharCode`` JS obfuscation in a malformed
  ``mailto:`` attribute; the engine's ``_clean_email`` / cf / base64 / rot13
  chain cannot decode it. Names + ranks collected; email deferred to the
  enrichment pass.
* Professional schools — McIntire (Commerce), School of Data Science, Batten
  (Public Policy), and Architecture all serve client-side-filtered JS
  directory SPAs with no server-rendered person cards and no inline email;
  Education (education.virginia.edu) sits behind a hard 403 WAF and Nursing
  (nursing.virginia.edu) did not resolve during recon. Each needs a bespoke
  render/API probe out of scope for this pass.
* A&S neuroscience / linguistics / american studies / global studies — their
  people pages do not render the shared ``uva_people-teaser`` component
  (bespoke or JS listings); paths not resolved this session.
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
_ENG_ENRICH = {
    "render": True,
    "email_selector": "a[href^='mailto:']",
    "email_drop": _EMAIL_DROP,
    "throttle": 0.3,
}


def _eng(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A SEAS department served by engineering.virginia.edu (render mode)."""
    url = f"https://engineering.virginia.edu/department/{slug}/people"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "render": True, "render_settle": 6000,
                   "selectors": _ENG_SEL, "ladder_filter": _LADDER,
                   "profile_enrich": _ENG_ENRICH},
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
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
