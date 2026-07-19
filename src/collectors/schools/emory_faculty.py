"""Emory University faculty config (via the faculty_graph engine).

Live recon 2026-07-19 (all fetches via requests, browser UA; every Emory
dept host serves clean 200s over HTTP/1.1 — no WAF, no Cloudflare
interstitial, no render mode anywhere). Three markup families:

* ``card_contact`` — the shared Emory College of Arts & Sciences
  "structured-biography-directory" template. One ``div.card-contact`` per
  person (``data-sort="Last, First"`` + a ``data-tags`` role array), with the
  name in ``h5.card-title`` linked from ``.card__titles a``, the rank in
  ``h6.card-subtitle``, and a plain inline ``mailto:`` inside
  ``.contact__email``. Names are already "First Last" (no flip). This one
  template backs ~all Humanities/Social-Science/Science depts on their own
  ``<dept>.emory.edu`` subdomain. Most sites expose a combined "Faculty &
  Staff" ``people/index.html`` that mixes staff, postdocs, coordinators and
  (on some) emeriti into the same card list, so the ladder filter
  (require professor/lecturer/instructor, drop emeritus) is what carves the
  faculty roster out; a few depts publish a dedicated faculty-only page
  (economics/polisci ``people/faculty/index.html``, envs/religion
  ``people/faculty.html``, mathematics ``people/faculty-math.html``).
  Chemistry embeds every bio inline on the listing so its card links are
  same-page ``#biography-…`` anchors (they resolve to the listing URL — email
  is the dedup identity there); History mixes an ``bios/emeriti/…`` section
  the "Emerit(us|a)" ladder-drop prunes.

* ``goizueta`` — the Goizueta Business School Drupal profile grid
  (``article.faculty-card``): name/link in ``h1.faculty-card__content--title
  a`` (relative ``/faculty/profiles/<slug>``), rank in
  ``.faculty-card__content--body``. 24 cards/page, Drupal 0-indexed query
  pagination (``?page=N``; the bare URL is page 0). No inline email — the
  env-gated profile pass backfills it from the profile ``mailto:``.

Email: inline ``mailto:`` on the entire card_contact family (~100% of kept
records carry a clean ``@emory.edu`` address); absent on goizueta, where the
env-gated profile_enrich pass (``a[href^='mailto:']``) recovers it — NOT run
in this verify pass, run centrally by the orchestrator.

Single source ("emory_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred (2026-07-19 recon):
* Computer Science (computerscience.emory.edu): its ``a.card.person-card``
  roster is injected client-side by a Drupal ``js-people-grid`` script — the
  server HTML the engine sees carries 0 cards, and a headless render of the
  page also returned no cards this pass. Needs the grid's JSON/views-ajax
  feed located, or a working render. Flagship STEM dept — revisit.
* QTM — Quantitative Theory & Methods (quantitative.emory.edu): the whole
  site returns 404 on every people/faculty path probed — it appears migrated/
  relocated; no live faculty listing found this pass.
* Center for the Study of Human Health (humanhealth.emory.edu): uses the
  ``card-informational`` variant with NO profile link and NO inline email, and
  names carry credential suffixes (", PhD, RD"). Low-value records; needs a
  bespoke pass.
* Linguistics (linguistics.emory.edu): the ``/faculty/`` page is a 4-card
  "Faculty Eminence" highlight, not a roster; the real listing was not
  located this pass. Small program.
* Goizueta pagination beyond the query pager, and the four Emory College
  language/arts programs on non-card templates (comparativelit, creativewriting,
  filmandmedia, dance) — not verified this pass.
* Rollins School of Public Health (sph.emory.edu ``/faculty-directory``),
  Nell Hodgson Woodruff School of Nursing (nursing.emory.edu
  ``/faculty-and-leadership-directory``), School of Medicine (med.emory.edu):
  each is a bespoke JS-rendered search application with no server-rendered
  card list — they need their own search-API integration and (for Medicine)
  a clinical-faculty gate. Out of scope for this A&S/STEM pass.
* Oxford College — separate two-year campus; not probed.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- card_contact (shared Emory College bio-directory) ---------------------
_CC_SEL = {
    "card": "div.card-contact",
    "name": "h5.card-title",
    "link": ".card__titles a",
    "title": "h6.card-subtitle",
    "email": ".contact__email a[href^='mailto:']",
}

# Require the professor/lecturer/instructor ladder (carves faculty out of the
# combined Faculty-&-Staff card lists); drop the emeritus sections some depts
# fold into the same page.
_LADDER = {"require": r"profess|lecturer|instructor", "drop": r"emerit"}

# card_contact profiles publish a plain mailto too; the env-gated pass only has
# work to do on the handful of kept records missing an inline address.
_CC_ENRICH = {"email_selector": "a[href^='mailto:']", "throttle": 0.2}


def _cc(short: str, name: str, majors: list[str], url: str) -> dict:
    """An Emory College dept on the shared card-contact bio directory."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _CC_SEL,
                       "ladder_filter": _LADDER,
                       "profile_enrich": _CC_ENRICH}}


SCHOOL: dict = {
    "school_slug": "emory",
    "source": "emory_faculty",
    "organization": "Emory University",
    "location": "Atlanta, GA",
    "id_prefix": "emory",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Emory University) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- Emory College — Natural Sciences ------------------------------
        _cc("BIOL", "Department of Biology", ["Biology", "Biological Sciences"],
            "https://biology.emory.edu/people/index.html"),
        _cc("CHEM", "Department of Chemistry", ["Chemistry"],
            "https://chemistry.emory.edu/people/index.html"),
        _cc("PHYS", "Department of Physics", ["Physics"],
            "https://physics.emory.edu/people/index.html"),
        _cc("MATH", "Department of Mathematics", ["Mathematics"],
            "https://mathematics.emory.edu/people/faculty-math.html"),
        _cc("NBB", "Program in Neuroscience and Behavioral Biology",
            ["Neuroscience and Behavioral Biology", "Neuroscience"],
            "https://nbb.emory.edu/people/index.html"),
        _cc("ENVS", "Department of Environmental Sciences",
            ["Environmental Sciences"],
            "https://envs.emory.edu/people/faculty.html"),
        _cc("PSYC", "Department of Psychology", ["Psychology"],
            "https://psychology.emory.edu/people/index.html"),
        # ---- Emory College — Social Sciences -------------------------------
        _cc("ECON", "Department of Economics", ["Economics"],
            "https://economics.emory.edu/people/faculty/index.html"),
        _cc("POLS", "Department of Political Science", ["Political Science"],
            "https://polisci.emory.edu/people/faculty/index.html"),
        _cc("SOC", "Department of Sociology", ["Sociology"],
            "https://sociology.emory.edu/people/index.html"),
        _cc("ANTH", "Department of Anthropology", ["Anthropology"],
            "https://anthropology.emory.edu/people/index.html"),
        # ---- Emory College — Humanities ------------------------------------
        _cc("ENG", "Department of English", ["English", "Creative Writing"],
            "https://english.emory.edu/people/index.html"),
        _cc("HIST", "Department of History", ["History"],
            "https://history.emory.edu/people/index.html"),
        _cc("PHIL", "Department of Philosophy", ["Philosophy"],
            "https://philosophy.emory.edu/people/index.html"),
        _cc("REL", "Department of Religion", ["Religion"],
            "https://religion.emory.edu/people/faculty.html"),
        _cc("CLAS", "Department of Classics", ["Classics"],
            "https://classics.emory.edu/people/index.html"),
        _cc("ARTH", "Department of Art History", ["Art History"],
            "https://arthistory.emory.edu/people/index.html"),
        _cc("FREN", "Department of French and Italian",
            ["French Studies", "Italian Studies"],
            "https://french.emory.edu/people/index.html"),
        _cc("GER", "Department of German Studies", ["German Studies"],
            "https://german.emory.edu/people/index.html"),
        _cc("SPAN", "Department of Spanish and Portuguese",
            ["Spanish", "Portuguese"],
            "https://spanport.emory.edu/people/index.html"),
        _cc("MESAS", "Department of Middle Eastern and South Asian Studies",
            ["Middle Eastern and South Asian Studies", "Arabic", "Hebrew"],
            "https://mesas.emory.edu/people/index.html"),
        _cc("REALC", "Department of Russian and East Asian Languages and Cultures",
            ["Russian", "East Asian Studies", "Chinese", "Japanese"],
            "https://realc.emory.edu/people/index.html"),
        _cc("WGSS", "Department of Women's, Gender, and Sexuality Studies",
            ["Women's, Gender, and Sexuality Studies"],
            "https://wgss.emory.edu/people/index.html"),
        _cc("MUS", "Department of Music", ["Music"],
            "https://music.emory.edu/people/index.html"),
        _cc("THEA", "Department of Theater and Dance", ["Theater Studies", "Dance"],
            "https://theater.emory.edu/people/index.html"),
        # ---- Goizueta Business School (Drupal profile grid) ----------------
        {
            "short": "GBS", "name": "Goizueta Business School",
            "majors": ["Business Administration", "Business"],
            "directory_url": "https://goizueta.emory.edu/faculty/profiles",
            "scrape": {
                "url": "https://goizueta.emory.edu/faculty/profiles",
                "selectors": {"card": "article.faculty-card",
                              "name": "h1.faculty-card__content--title",
                              "link": "h1.faculty-card__content--title a",
                              "title": ".faculty-card__content--body"},
                "paginate": {"param": "page", "start": 1, "max": 12},
                "ladder_filter": _LADDER,
                "profile_enrich": {"email_selector": "a[href^='mailto:']",
                                   "throttle": 0.3},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
