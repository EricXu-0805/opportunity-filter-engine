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

Added 2026-07-20 (deferred STEM/professional depts re-reconned):
* Computer Science (computerscience.emory.edu/people/index.html): the first
  pass's "client-side js-people-grid, 0 server cards" was WRONG — the page
  serves 30 static ``div.card.card-contact`` cards on the shared College
  template. Same ``card_contact`` family; card links are same-page
  ``#biography-…`` anchors (email is the dedup identity, ~all carry an inline
  ``.contact__email`` mailto). Wired via ``_cc``.
* Data & Decision Sciences — DSci (datascience.emory.edu/people/index.html):
  QTM (quantitative.emory.edu) went 404 because the Institute for Quantitative
  Theory & Methods became the Dept of Data & Decision Sciences in July 2025 at
  a NEW subdomain. 41 ``card_contact`` cards; roster mixes admin-titled core
  faculty (Chair/Director) with affiliated secondary appointments and a
  postdoc, so it uses a bespoke DROP-only ladder (``_DSCI_LADDER``) instead of
  the require-professor gate, dropping only affiliated/postdoc/emeritus.
* Linguistics (linguistics.emory.edu/faculty/core.html): the ``/faculty/``
  index is a highlight page, but ``/faculty/core.html`` is the real 20-card
  roster. It's a card_contact *variant* — name/rank in ``h5.card-title`` /
  ``h6.card-subtitle`` but the mailto sits in ``address a.email`` and the
  profile link is a ``a.btn`` bio button (often to a joint-appt home dept).
  Bespoke ``_LING_SEL``.
* Center for the Study of Human Health (humanhealth.emory.edu): 45
  ``div.card-informational`` cards — NO profile link, NO inline email (only a
  ``human.health@emory.edu`` inbox), names carry credential suffixes. Bespoke
  ``_HH_SEL`` (name in ``h5.card-title`` with ``name_strip`` cutting ", PhD…";
  rank in ``.card-text h5``); shared require-professor ladder carves the ~37
  professor/instructor cards out of the health-educator/program-director/
  emeritus/postdoc chaff. Records are email-less (confidence 0.5) — the
  profile URL is the contact point.
* Rollins School of Public Health (sph.emory.edu/faculty-directory/) and
  Nell Hodgson Woodruff School of Nursing (nursing.emory.edu
  /faculty-and-leadership-directory): BOTH ride the same Emory Drupal-Cohesion
  "faculty-listing" template — ``div.profile-cards article`` cards with
  ``h3.coh-heading`` names, a rank in the shared ``div.coh-ce-85493992``
  container, and clean ``?page=N`` query pagination (15/page, server-rendered;
  the "infinite scroll" is just a query pager). Shared ``_coh`` helper +
  require-professor ladder. Nursing profiles expose personal
  ``@emoryhealthcare.org``/``@emory.edu`` mailtos (recovered by the central
  profile_enrich pass); Rollins profiles expose ONLY the shared
  ``rsph.info@emory.edu`` inbox (``email_drop``-guarded), so Rollins records
  stay email-less until/unless a personal address surfaces — the profile URL
  is the contact point.

Still deferred (2026-07-20):
* School of Medicine (med.emory.edu): large clinical enterprise; its directory
  is a bespoke JS search app with a clinical/hospital-faculty majority that
  needs a research-faculty gate we don't have — re-deferred as clinical.
* Goizueta pagination beyond the query pager, and the four Emory College
  language/arts programs on non-card templates (comparativelit, creativewriting,
  filmandmedia, dance) — not verified this pass.
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

# DSci (formerly QTM): its people page lists admin-titled core faculty (Chair,
# Directors) alongside affiliated secondary appointments (home dept elsewhere)
# and a postdoc. A require-professor gate would drop the admin-titled core
# faculty, so gate by DROP only — keep everyone but the affiliated secondaries,
# postdocs and emeriti.
_DSCI_LADDER = {"drop": r"emerit|affiliated|post.?doc|graduate student"}


def _cc(short: str, name: str, majors: list[str], url: str,
        ladder: dict | None = None) -> dict:
    """An Emory College dept on the shared card-contact bio directory."""
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _CC_SEL,
                       "ladder_filter": ladder or _LADDER,
                       "profile_enrich": _CC_ENRICH}}


# ---- Linguistics card_contact variant --------------------------------------
# Same h5.card-title / h6.card-subtitle heads as the shared template, but the
# mailto lives in an <address> and the profile link is a bio "button" (often to
# a joint-appointment home-department subdomain).
_LING_SEL = {
    "card": "div.card-contact",
    "name": "h5.card-title",
    "title": "h6.card-subtitle",
    "link": ".card-body a.btn[href]",
    "email": "address a[href^='mailto:']",
}

# ---- Center for the Study of Human Health (card-informational) -------------
# No profile link, no personal mailto; rank is the (uppercase) role heading
# inside .card-text. name_strip drops the credential tail after the first comma
# ("Carolyn Accardi, PhD, RD" -> "Carolyn Accardi").
_HH_SEL = {
    "card": "div.card-informational",
    "name": "h5.card-title",
    "name_strip": r",.*$",
    "title": ".card-text h5",
}

# ---- Emory Drupal-Cohesion "faculty-listing" grid (Rollins SPH, Nursing) ---
# div.profile-cards > article cards; name in h3.coh-heading (its <a> is the
# profile link); rank in the shared div.coh-ce-85493992 rank container (the
# department taxonomy sits in a sibling <span>, so the first descendant
# div.coh-inline-element is the rank). Clean ?page=N query pagination, 15/page.
_COH_SEL = {
    "card": "div.profile-cards article",
    "name": "h3.coh-heading",
    "link": "h3.coh-heading a",
    "title": "div.coh-ce-85493992 div.coh-inline-element",
}


def _coh(short: str, name: str, majors: list[str], url: str,
         email_drop: str | None = None) -> dict:
    """A professional school on the shared Emory Cohesion faculty-listing grid."""
    enrich = {"email_selector": "a[href^='mailto:']", "throttle": 0.3}
    if email_drop:
        enrich["email_drop"] = email_drop
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url,
            "scrape": {"url": url, "selectors": _COH_SEL,
                       "paginate": {"param": "page", "start": 1, "max": 40},
                       "ladder_filter": _LADDER,
                       "profile_enrich": enrich}}


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
        # ---- Emory College — STEM / interdisciplinary (added 2026-07-20) ---
        _cc("CS", "Department of Computer Science", ["Computer Science"],
            "https://computerscience.emory.edu/people/index.html"),
        _cc("DSCI", "Department of Data and Decision Sciences",
            ["Data Science", "Quantitative Theory and Methods",
             "Quantitative Sciences"],
            "https://datascience.emory.edu/people/index.html",
            ladder=_DSCI_LADDER),
        {
            "short": "LING", "name": "Program in Linguistics",
            "majors": ["Linguistics"],
            "directory_url": "https://linguistics.emory.edu/faculty/core.html",
            "scrape": {"url": "https://linguistics.emory.edu/faculty/core.html",
                       "selectors": _LING_SEL, "ladder_filter": _LADDER,
                       "profile_enrich": _CC_ENRICH},
        },
        {
            "short": "HH", "name": "Center for the Study of Human Health",
            "majors": ["Human Health"],
            "directory_url": "https://humanhealth.emory.edu/people/index.html",
            "scrape": {"url": "https://humanhealth.emory.edu/people/index.html",
                       "selectors": _HH_SEL, "ladder_filter": _LADDER},
        },
        # ---- Professional schools on the Cohesion faculty-listing grid -----
        _coh("RSPH", "Rollins School of Public Health",
             ["Public Health", "Epidemiology", "Biostatistics",
              "Global Health", "Environmental Health", "Health Policy",
              "Behavioral Sciences and Health Education"],
             "https://sph.emory.edu/faculty-directory/",
             email_drop=r"^rsph\.info@|^info@"),
        _coh("NURS", "Nell Hodgson Woodruff School of Nursing",
             ["Nursing"],
             "https://www.nursing.emory.edu/faculty-and-leadership-directory"),
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
                # The generic first-mailto selector picks up the site-nav inbox
                # (executiveeducation@emory.edu); the personal address lives only
                # inside the full faculty card, and the GBS shared inboxes drop.
                "profile_enrich": {
                    "email_selector": "article.faculty-card--full a[href^='mailto:']",
                    "email_drop": r"^(?:executiveeducation|gbsalumni|gbsinfo|gbs[\w.-]*|info)@",
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
