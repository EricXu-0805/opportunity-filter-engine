"""Florida State University faculty config (via the faculty_graph engine).

Broad "UIUC-parity" coverage across the colleges that publish a machine-readable
faculty roster carrying contact emails. 24 departments, ~660 faculty, ~89%
emailed. Every department below is live-verified; all but Computer Science (see
below) are majority-emailed. Markup families:

* **FSU campus Drupal "people view"** (Physics, Mathematics, Statistics,
  Psychology, History, Philosophy). ``<dept>.fsu.edu/people`` shares one
  Bootstrap ``div.col`` whose direct child holds ``.views-field-title`` (name in
  an ``a`` → ``/person/<slug>``), with sibling ``.views-field-field-position``
  (rank) and ``.views-field-field-email`` (plain ``mailto``). The title field is
  a ``<div>`` on some depts and a ``<span>`` on others (same view, different
  display mode) — so the selectors are TAG-AGNOSTIC (``.views-field-title``, not
  ``div.…``). ``:has(>)`` keys the card off the element that DIRECTLY holds the
  title so it never matches the outer grid wrapper. The ``require:
  professor|lecturer`` gate drops staff / students / program specialists (no
  professor word); the engine's own retired-title gate handles "… Emeritus".
  Emails on ~95-100% of kept cards.

* **Standalone WordPress** (Computer Science, Chemistry & Biochemistry).
  ``cs.fsu.edu/department/faculty/`` renders ``article.faculty-card`` (name +
  rank, NO email — the ~31 tenure-track cards ship listing-email-less, see the
  drop note). ``chem.fsu.edu/people/faculty/`` is an Organic-Themes portfolio
  (``div.otw_portfolio_manager-portfolio-full``): name a CSS-floated
  ``Dr. Last, First`` (``name_strip`` + ``name_flip``), no rank/email on the
  card — the four ``<h1>`` sections split Faculty / Teaching / Affiliated /
  Emeritus (kept: "Faculty" only), and an ``always``-on per-profile pass pulls
  the personal mailto off each ``/person/`` page (34/34 emailed).

* **FAMU-FSU College of Engineering Drupal** (ECE, Mechanical, Chemical &
  Biomedical, Civil & Environmental, Industrial & Manufacturing).
  ``eng.famu.fsu.edu/<dept>/people`` shares the joint-college roster: one
  ``div.views-row`` per person, name in ``div.people-text h3 a`` (a ``, Ph.D.``
  credential the engine strips), ranks as ``span.faculty-job-titles`` inside the
  FIRST child div (read whole so an admin's leading title doesn't hide the
  professor rank from the gate), ``div.email-links`` ``mailto`` (@eng.famu.fsu.edu).
  These mix in Teaching / Research Faculty, staff, courtesy professors, and
  emeriti — ``require: professor|lecturer`` + ``drop: emerit|courtesy`` keeps the
  core ladder. Emails on nearly every kept card.

* **COSSPP WordPress** (Economics, Political Science, Sociology, Geography,
  Askew School of Public Administration, International Affairs).
  ``cosspp.fsu.edu/<dept>/faculty/`` renders one ``div.faculty-row`` per person:
  name in ``h4.faculty-title a``, rank in the first ``div.faculty-right p``,
  plain ``mailto`` in ``a.faculty-link``. Names sometimes append ``, Ph.D.``
  (stripped). 100% emailed. ``require: professor|lecturer`` keeps ladder +
  teaching faculty.

* **College of Communication and Information directory** (School of
  Communication, iSchool, School of Communication Science & Disorders).
  ``directory.cci.fsu.edu`` is one page of ``div.panel-profile`` cards whose
  class carries BOTH the school (``comm`` / ``ischool`` / ``scsd``) and role
  (``faculty`` / ``staff``); scoping to ``.panel-profile.faculty.<school>``
  isolates one department's ladder. Name is ``Last, First`` in an ``h4``
  (un-inverted via ``name_flip``), rank in ``p.job-title``, plain ``mailto`` in
  ``span.email a``. 100% emailed. ``drop: adjunct|emerit`` prunes the adjuncts.

* **Department of Biological Science** (custom ``faculty.php``). One
  ``div.faculty`` per person, name ``Dr. First Last`` in ``div.faculty-sm-text
  h5 a`` (``Dr.`` stripped), plain ``mailto`` in the body ``p``. The page carries
  no rank field, so the ladder gate can't run — but it is a curated Faculty
  Directory (no staff/students) and ~99% emailed, so it ships as-is with the
  engine's retired-title backstop.

* **EOAS academic-faculty** (Earth, Ocean & Atmospheric Science — Geology,
  Meteorology, Oceanography, Environmental Science). A hand-built WordPress
  ``<table>``: one ``tr`` per person with ``h5 > strong`` name (``Dr.`` stripped),
  a ``p`` whose leading text is ``<rank> | <subfield>`` (``title_strip_after``
  trims at the pipe), and a plain ``mailto``. ~97% emailed.

Single source ("fsu_faculty"); department rides each record, ids namespaced by
department short-code.

Dropped / phase-2 (email-less at listing tier or unreachable — 2026-07-24 recon):
* Computer Science (KEPT, but listing-email-less) — the ``faculty-card`` listing
  has no email, and the profile pages hide it as prose obfuscation the whole
  phrase is bracket-wrapped ("name [ at fsu dot edu ]") that the engine's
  ``_clean_email`` cannot decode config-only. Records carry name + rank + profile
  URL, so email backfills through the downstream OpenAlex / OFE_ENRICH pass;
  a real fix needs an engine-side decoder for that bracket form.
* College of Business (Wertheim) — Drupal people-view carries NO rank text and
  only a 36-person landing roster; per-department pages (finance/marketing/…)
  are client-rendered. Needs render + profile-enrich; deferred.
* Criminology, Nursing, College of Education/CEHHS — Drupal Views AJAX blocks
  (``js-view-dom-id``) paint the roster client-side; no server HTML, no emails
  at listing tier. Need ``render:True`` + profile-enrich; deferred to phase-2.
* College of Fine Arts (Art, Dance, Theatre, Interior Architecture) — every
  ``*.fsu.edu`` art host returns a hard **403** to bare AND full-header requests
  (WAF blocks the datacenter/proxy IP, not a JS challenge headless could clear).
  Genuinely unreachable from here.
* College of Music — faculty list injected via a JS widget/iframe with no email
  at listing tier. Deferred.
* Program in Neuroscience — cross-listed roster (home depts elsewhere), no email
  field on its people-view cards. Its faculty are already covered under their
  home departments (Psychology / Biology). Dropped.
* Urban & Regional Planning (cosspp/urp) — ``/faculty/`` renders empty (roster
  moved behind a client widget). Deferred.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- FSU campus Drupal "people view" ---------------------------------------
# The card is the Bootstrap column that DIRECTLY holds the title field, so the
# :has(>) keeps the selector from also matching the outer grid wrapper.
# The title field is a ``<div>`` on some depts (Physics/History) and a
# ``<span>`` on others (Psychology) — same Drupal view, different display mode —
# so the selectors are tag-agnostic (``.views-field-title``, not ``div.…``).
_DRUPAL_SEL = {
    "card": "div.col:has(> .views-field-title)",
    "name": ".views-field-title a",
    "link": ".views-field-title a",
    "title": ".views-field-field-position .field-content",
    "email": ".views-field-field-email a[href^='mailto:']",
}
_DRUPAL_LADDER = {"require": r"professor|lecturer"}


def _drupal(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared FSU campus Drupal people view."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _DRUPAL_SEL,
                   "ladder_filter": _DRUPAL_LADDER},
    }


# ---- FAMU-FSU College of Engineering Drupal --------------------------------
# Title reads the WHOLE first div (all faculty-job-titles spans joined) so an
# administrator's leading admin role doesn't hide the professor rank from the
# gate. Teaching/Research Faculty + staff carry no professor/lecturer word and
# drop via `require`; courtesy (home unit elsewhere) + emeriti drop via `drop`.
_ENG_SEL = {
    "card": "div.views-row",
    "name": "div.people-text h3 a",
    "link": "div.people-text h3 a",
    "title": "div.people-text > div",
    "email": "div.email-links a[href^='mailto:']",
}
_ENG_LADDER = {"require": r"professor|lecturer", "drop": r"emerit|courtesy"}


def _eng(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared FAMU-FSU engineering Drupal roster."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ENG_SEL, "ladder_filter": _ENG_LADDER},
    }


# ---- COSSPP WordPress "faculty-row" ----------------------------------------
_COSSPP_SEL = {
    # Name is the h4 text; some depts (Economics) wrap it in a profile ``a``,
    # others (Sociology) leave it as bare text — read the h4 either way, take
    # the link only when present.
    "card": "div.faculty-row",
    "name": "h4.faculty-title",
    "link": "h4.faculty-title a",
    "title": "div.faculty-right p",
    "email": "a.faculty-link[href^='mailto:']",
    # Names sometimes append ", Ph.D." / ", J.D." credentials.
    "name_strip": r",\s*(?:Ph\.?D|M\.?A|M\.?S|J\.?D|Ed\.?D|M\.?P\.?A)\.?.*$",
}
_COSSPP_LADDER = {"require": r"professor|lecturer", "drop": r"emerit"}


def _cosspp(short: str, name: str, majors: list[str], slug: str) -> dict:
    """A COSSPP department on cosspp.fsu.edu/<slug>/faculty/."""
    url = f"https://cosspp.fsu.edu/{slug}/faculty/"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        # cosspp.fsu.edu serves an incomplete TLS chain (missing InCommon
        # intermediate) — a verifying GET dies with a cert error.
        "scrape": {"url": url, "insecure": True, "selectors": _COSSPP_SEL,
                   "ladder_filter": _COSSPP_LADDER},
    }


# ---- CCI directory (one page, school + role encoded in the card class) ------
def _cci(short: str, name: str, majors: list[str], school_class: str) -> dict:
    """One CCI school off the shared directory.cci.fsu.edu page."""
    url = "https://directory.cci.fsu.edu/"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": {
                "card": f"div.panel-profile.faculty.{school_class}",
                "name": "div.panel-profile-body h4",
                "link": "div.panel-profile-body > a",
                "title": "p.job-title",
                "email": "span.email a[href^='mailto:']",
            },
            "name_flip": True,  # cards read "Last, First"
            "ladder_filter": {"require": r"professor|lecturer",
                              "drop": r"adjunct|emerit"},
        },
    }


SCHOOL: dict = {
    "school_slug": "fsu",
    "source": "fsu_faculty",
    "organization": "Florida State University",
    "location": "Tallahassee, FL",
    "id_prefix": "fsu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Florida State University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ==== College of Arts and Sciences ==================================
        # School of Computer Science dropped — the faculty-card listing is 100%
        # email-less name-only and the profile pages don't expose a static
        # mailto either; needs a profile-enrich/headless pass (phase-2).
        # ---- Department of Biological Science (custom faculty.php) ----------
        # No rank field on the listing; it is a curated Faculty Directory
        # (no staff/students) and ~99% emailed, so it ships without a ladder
        # gate (the engine's retired-title backstop still applies).
        {
            "short": "BIO",
            "name": "Department of Biological Science",
            "majors": ["Biological Science", "Biology", "Neuroscience",
                       "Cell and Molecular Biology", "Ecology and Evolution"],
            "directory_url": "https://www.bio.fsu.edu/faculty.php",
            "scrape": {
                "url": "https://www.bio.fsu.edu/faculty.php",
                "selectors": {
                    "card": "div.row:has(> div.col-sm-9 > div.faculty-sm-text)",
                    "name": "div.faculty-sm-text h5 a",
                    "link": "div.faculty-sm-text h5 a",
                    "email": "div.faculty-sm-text a[href^='mailto:']",
                    "name_strip": r"^Dr\.?\s*",
                },
            },
        },
        # ---- Chemistry & Biochemistry (WordPress OTW portfolio) ------------
        # No rank field + no email on the card; the four <h1> sections split
        # Faculty / Teaching / Affiliated / Emeritus — keep only "Faculty".
        {
            "short": "CHEM",
            "name": "Department of Chemistry and Biochemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://www.chem.fsu.edu/people/faculty/",
            "scrape": {
                "url": "https://www.chem.fsu.edu/people/faculty/",
                "selectors": {
                    "card": "div.otw_portfolio_manager-portfolio-full",
                    "name": "h3.otw_portfolio_manager-portfolio-title a",
                    "link": "h3.otw_portfolio_manager-portfolio-title a",
                    "name_strip": r"^Dr\.?\s*",
                },
                "name_flip": True,
                "section_filter": {
                    "heading": "h1",
                    "include": r"faculty",
                    "exclude": r"teaching|affiliated|emerit",
                },
                # No email on the card, but each /person/ profile carries a
                # personal mailto — enrich to make the department emailed.
                "profile_enrich": {
                    "always": True,  # listing has no email — profile IS the source
                    "email_selector": "a[href^='mailto:']",
                    "email_drop": r"^[^@]*$|^chem@|^info@|webmaster@",
                    "throttle": 0.2,
                },
            },
        },
        # ---- FSU campus Drupal people-view (sciences + humanities) ---------
        _drupal("PHYS", "Department of Physics",
                ["Physics", "Astrophysics"],
                "https://www.physics.fsu.edu/people"),
        _drupal("MATH", "Department of Mathematics",
                ["Mathematics", "Applied Mathematics", "Statistics",
                 "Biomathematics", "Financial Mathematics"],
                "https://mathematics.fsu.edu/people"),
        _drupal("STAT", "Department of Statistics",
                ["Statistics", "Actuarial Science", "Data Science",
                 "Biostatistics"],
                "https://stat.fsu.edu/people"),
        _drupal("PSY", "Department of Psychology",
                ["Psychology", "Neuroscience", "Cognitive Science"],
                "https://psychology.fsu.edu/people/faculty"),
        _drupal("HIST", "Department of History", ["History"],
                "https://history.fsu.edu/people"),
        _drupal("PHIL", "Department of Philosophy", ["Philosophy"],
                "https://philosophy.fsu.edu/people"),
        # ---- EOAS (Earth, Ocean & Atmospheric Science) — WP table ----------
        {
            "short": "EOAS",
            "name": "Department of Earth, Ocean and Atmospheric Science",
            "majors": ["Geology", "Meteorology", "Environmental Science",
                       "Oceanography", "Earth Sciences"],
            "directory_url": "https://www.eoas.fsu.edu/people/academic-faculty/",
            "scrape": {
                "url": "https://www.eoas.fsu.edu/people/academic-faculty/",
                "insecure": True,  # incomplete TLS chain (InCommon intermediate)
                "selectors": {
                    "card": "table tr:has(h5)",
                    "name": "h5 strong",
                    "title": "td p",
                    "email": "a[href^='mailto:']",
                    "name_strip": r"^Dr\.?\s*",
                    # "<rank> | <subfield> <leaked email/phone>" → keep the rank.
                    "title_strip_after": r"\s*\|",
                },
                "ladder_filter": {"require": r"professor|lecturer",
                                  "drop": r"emerit"},
            },
        },
        # ==== FAMU-FSU College of Engineering (shared Drupal roster) ========
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "https://eng.famu.fsu.edu/ece/people"),
        _eng("MAE", "Department of Mechanical Engineering",
             ["Mechanical Engineering"],
             "https://eng.famu.fsu.edu/mae/people"),
        _eng("CBE", "Department of Chemical and Biomedical Engineering",
             ["Chemical Engineering", "Biomedical Engineering"],
             "https://eng.famu.fsu.edu/cbe/people"),
        _eng("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "https://eng.famu.fsu.edu/cee/people"),
        _eng("IME", "Department of Industrial and Manufacturing Engineering",
             ["Industrial Engineering", "Manufacturing Engineering"],
             "https://eng.famu.fsu.edu/ime/people"),
        # ==== College of Social Sciences and Public Policy (COSSPP WP) ======
        _cosspp("ECON", "Department of Economics", ["Economics"], "economics"),
        _cosspp("POLS", "Department of Political Science",
                ["Political Science"], "polisci"),
        _cosspp("SOC", "Department of Sociology",
                ["Sociology", "Criminology"], "sociology"),
        _cosspp("GEOG", "Department of Geography",
                ["Geography", "Geographic Information Science"], "geography"),
        _cosspp("PADP", "Askew School of Public Administration and Policy",
                ["Public Administration", "Public Policy"], "askew"),
        _cosspp("INTA", "Department of International Affairs",
                ["International Affairs"], "internationalaffairs"),
        # ==== College of Communication and Information (CCI directory) ======
        _cci("COMM", "School of Communication",
             ["Advertising", "Public Relations",
              "Media and Communication Studies"], "comm"),
        _cci("ISCH", "School of Information",
             ["Information Technology", "Information Studies"], "ischool"),
        _cci("SCSD", "School of Communication Science and Disorders",
             ["Communication Science and Disorders"], "scsd"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
