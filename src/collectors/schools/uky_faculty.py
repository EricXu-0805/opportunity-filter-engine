"""University of Kentucky faculty config (via the faculty_graph engine).

Full university-wide coverage across the five colleges the catalog spans —
Engineering, Arts & Sciences, Gatton Business & Economics, Martin-Gatton
Agriculture/Food/Environment, and Communication & Information. Five markup
families; four are plain server-rendered 200s through the proxy, the fifth
(CI) sits behind a JS bot wall and is recovered headless.

* **College of Engineering — one shared Drupal "people-list" table.**
  All seven engineering departments render from ONE base
  (``engr.uky.edu/people``) differentiated only by a server-side
  ``?field_department_target_id=<id>`` filter. Each person is one
  ``td.views-field-rendered-entity`` cell holding ``span.people-list--name >
  a.underline-link`` (name + ``/people/<slug>``), ``span.people-list--title``
  (rank), and a contact-info ``<dl>`` whose Email ``<dd>`` carries a PLAIN
  ``mailto:`` (~100% emailed on the listing). Status is a FIELD here, not the
  rank string: the same ``<dl>`` carries a "Categories" row (Faculty / Emeritus
  / Staff / Adjunct), and a ``field_filter`` on it is what drops the retired and
  staff rows — a ladder gate on the title alone leaks both (a retired professor
  keeps his rank, and a lab manager's title reads "Lab Instructor").
  No pagination.

* **College of Arts & Sciences — one shared Drupal "directory-card" grid.**
  Nine departments each live on their own ``<dept>.as.uky.edu/faculty``
  subdomain but share one card component: ``div.directory-card`` wrapping a
  ``.directory-content`` block whose bold div holds the name + ``/users/<netid>``
  link and whose non-bold sibling holds the rank. There is NO email on these
  listings — addresses come from an always-on per-profile enrichment pass that
  follows the ``/users/<netid>`` link and reads the address out of the profile's
  "Contact Information" block (``div.text1.font-bold:-soup-contains("Contact
  Information") + div``; live-verified 5/5 on Physics and History). Mathematics
  paginates (40/page); the rest are single-page. A ``name_strip`` trims a rank
  baked into two Mathematics anchors and the semicolon-joined name-variant dump
  English publishes for one professor. A few cards render the rank div EMPTY, so
  the title selector carries ``:not(:empty)`` — matching an empty div would set
  title="" and the ladder gate would drop a listed professor (Physics' Gary
  Ferland) for having no rank. The ladder gate keeps
  professor/lecturer/instructor AND endowed/named ``chair`` holders (History and
  the humanities carry many named-chair faculty who lack the word "Professor").

* **Gatton College of Business & Economics — the SAME Drupal people-list View
  as Engineering.** One base (``gatton.uky.edu/faculty-research/faculty-
  directory``) filtered by ``?field_gatton_department_target_id=<id>``; identical
  inner markup (``span.people-list--name`` / ``span.people-list--title`` / plain
  ``mailto:``) except the card is a ``div`` not a ``td``. ~100% emailed on the
  listing. Five departments (Accountancy, Economics, Finance & Quantitative
  Methods, Management, Marketing & Supply Chain).

* **Martin-Gatton College of Agriculture, Food & Environment — the campus
  "college-personnel" directory.** Every CAFE department's own site links to one
  authoritative host, ``personnel.mgcafe.uky.edu/home?combined_department_filter=
  <primary_secondary>``, a Drupal View paginated 36/person-per-page. Each
  ``div.views-row`` carries a ``.views-field-nothing`` name link
  (``/directory/<slug>``), a ``.views-field-field-personnel-preferred-title``
  rank, and a ``.views-field-field-personnel-email-address`` plain ``mailto:``
  (~100% emailed). The directory mixes faculty with a heavy tail of grad research
  assistants, post-docs, engineers, and administrative staff, so a
  ``require professor|lecturer|instructor`` ladder gate is essential. Four
  academic departments (Agricultural Economics; Animal & Food Sciences;
  Biosystems & Agricultural Engineering; Forestry & Natural Resources).

* **College of Communication & Information — headless render (JS bot wall).**
  ``ci.uky.edu`` serves a JS challenge ("Making sure you're not a bot!") to a
  plain request, so both the listing and the profiles are fetched through the
  headless browser (cron-safe: refresh-data installs Playwright). The college
  directory is a Drupal AJAX View at ``/about/directory`` filtered by
  ``?field_directory_type_value=faculty&field_department_target_id=<id>``; each
  ``div.mb-5.col-6.col-lg-3`` card holds a ``strong > a`` name link
  (``/about/directory/<slug>``) and a ``.views-field-field-position-title`` rank.
  The listing has no email, so an ``always``-on profile pass renders each profile
  and reads the personal ``mailto:`` (the shared ``a.ico-email`` webmanager inbox
  is excluded by ``:not(.ico-email)`` AND by ``email_drop``; live-verified 4/4 on
  Communication). Like A&S, the pass is NOT env-gated: it is the only source of a
  CI address, and a harvest that skips it emits no email at all, which leaves the
  merge carrying whatever the corpus already held. Four units (Communication;
  Journalism & Media; Information Science; Integrated Strategic Communication).

Single source ("uky_faculty"); department rides each record, ids namespaced by
department short-code.

Deliberately DROPPED (recorded, not silently omitted):
* **A&S Neuroscience** — an interdisciplinary undergraduate PROGRAM, not a
  department; ``neuroscience.as.uky.edu`` publishes no ``directory-card`` roster
  and its faculty are cross-listed from Biology / Psychology (both covered), so
  the Neuroscience major rides on those two departments' ``majors`` instead.

Live-verified 2026-07-24.
"""

from __future__ import annotations

from .. import faculty_graph

# Keep ladder + teaching (lecturer/instructor) faculty AND endowed/named chairs;
# drop the Staff / advising / systems buckets whose titles carry none of these
# words. Emeriti pass the require gate ("Emeritus Professor" contains "Professor")
# and are dropped by the engine's own retired-title guard in _normalize.
_LADDER = {"require": r"professor|lecturer|instructor|chair"}

# ---- College of Engineering: shared Drupal people-list table ---------------
# One person = one rendered-entity cell. Name/title in dedicated spans; the email
# is the plain mailto in the contact-info definition list. Profile hrefs are
# root-relative (/people/<slug>); the engine urljoins them onto the base. The
# engineering ladder deliberately stays professor|lecturer|instructor (verified
# clean at 100% email) — the broader "chair" gate is used on the humanities/
# business/agriculture rosters where named-chair faculty are common.
_ENG_SEL = {
    "card": "td.views-field-rendered-entity",
    "name": "span.people-list--name a.underline-link",
    "link": "span.people-list--name a.underline-link",
    "title": "span.people-list--title",
    "email": "a[href^='mailto:']",
}
_ENG_LADDER = {"require": r"professor|lecturer|instructor"}
# The rank string is NOT the site's status field: engr.uky.edu keeps that in the
# contact-info <dl> ("Categories": Faculty / Emeritus / Staff / Adjunct), and a
# retired professor keeps whatever rank he held ("Associate Professor" for
# J. Robert Heath and William Smith, "University President 2001-11, Professor
# 1974-83, 2011-14" for Lee T. Todd, whose appointments ended in 2014) — so the
# title gate and the engine's retired-title guard both wave them through. The
# same field is the only thing marking a Staff row whose job title happens to
# carry a ladder word ("Research Facilities Manager/Lab Instructor"). Gate on
# the field itself. Eight active faculty (e.g. CS's Ruiquan Huang, MAE's
# Samantha Zambuto) publish NO Categories row at all, so the absent-field-passes
# default is load-bearing — an ``include`` gate here would delete them.
_ENG_CATEGORY = {
    "selector": 'dl.invisible-labels dt:-soup-contains("Categories") + dd',
    "exclude": r"emeritus|staff",
}


def _eng(short: str, name: str, majors: list[str], dept_id: int) -> dict:
    """An engineering department on the shared people-list table."""
    url = f"https://engr.uky.edu/people?field_department_target_id={dept_id}"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _ENG_SEL, "ladder_filter": _ENG_LADDER,
                   "field_filter": _ENG_CATEGORY},
    }


# ---- College of Arts & Sciences: shared Drupal directory-card grid ----------
# The bold div holds the name link (/users/<netid>); the non-bold sibling div
# holds the rank — sometimes empty. No email on the listing — the always-on
# profile pass follows the profile link and reads the address from the "Contact
# Information" block.
_AS_SEL = {
    "card": "div.directory-card",
    "name": "div.directory-content div.font-bold a",
    "link": "div.directory-content div.font-bold a",
    # Two strips on one pattern: a rank baked into two Mathematics anchors, and
    # a semicolon-joined name-variant dump (English publishes "Janet Eldred;
    # Janet Carey Eldred; JCM Eldred" as the anchor text — every alias the
    # person publishes under). Keep the first, displayed form.
    "name_strip": r"\s*;.*$|,\s*[A-Za-z ]*Professor\s*$",
    # ``:not(:empty)`` matters: a handful of cards (Physics' Gary Ferland and
    # Ryan Sanders, Math's Amy Green, Psychology's Cara Worick) render the rank
    # div with nothing in it. Matching it would set title="" and the ladder gate
    # would drop a listed faculty member for having no rank; not matching it
    # lets the engine's "Professor" default stand so they ship.
    "title": "div.directory-content div.text.color-wildcat-blue:not(.font-bold):not(:empty)",
}
# The A&S profile keeps the address as the first div after the "Contact
# Information" heading (no mailto, no email class) — an adjacent-sibling selector
# lands it; _clean_email extracts the address shape (a non-address sibling yields
# None, never a wrong value). Env-gated: OFF in CI / weekly refresh (the merge
# richer-guard carries a committed contact_email forward), ON for the deliberate
# enrichment run that generates the data.
_AS_ENRICH = {
    "email_selector": 'div.text1.font-bold:-soup-contains("Contact Information") + div',
    # The A&S directory cards carry NO email at all — the address lives only on
    # each person's profile page — so this pass is where the record's contact
    # field comes from, not optional depth. always:True bypasses the monthly
    # OFE_ENRICH_PROFILES gate (which the weekly cron only sets first-week), so
    # every A&S department ships majority-emailed instead of name-only.
    "always": True,
    "throttle": 0.1,
    "timeout": 8,
}


def _as(short: str, name: str, majors: list[str], url: str,
        paginate: dict | None = None) -> dict:
    """An Arts & Sciences department on the shared directory-card grid."""
    scrape = {"url": url, "selectors": _AS_SEL, "ladder_filter": _LADDER,
              "profile_enrich": _AS_ENRICH}
    if paginate:
        scrape["paginate"] = paginate
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": scrape,
    }


# ---- Gatton College of Business & Economics: same people-list View ----------
# Identical inner markup to Engineering; the card is a div (responsive grid) not
# a td, and the department filter param is field_gatton_department_target_id.
# Plain mailto on the listing (~100% emailed).
_GAT_SEL = {
    "card": "div.views-field-rendered-entity",
    "name": "span.people-list--name a.underline-link",
    "link": "span.people-list--name a.underline-link",
    "title": "span.people-list--title",
    "email": "a[href^='mailto:']",
}
_GAT_BASE = "https://gatton.uky.edu/faculty-research/faculty-directory"


def _gatton(short: str, name: str, majors: list[str], dept_id: int) -> dict:
    """A Gatton department on the shared Drupal people-list View."""
    url = f"{_GAT_BASE}?field_gatton_department_target_id={dept_id}"
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _GAT_SEL, "ladder_filter": _LADDER},
    }


# ---- Martin-Gatton College of Agriculture: college-personnel directory ------
# The authoritative campus personnel View, filtered per department by the
# combined primary_secondary code. Clean class-based fields; plain mailto on each
# row (~100% emailed). Paginated 36/page (0-indexed pager: base is page 0). The
# roster mixes in grad assistants / post-docs / engineers / staff, so the ladder
# gate is load-bearing.
_CAFE_SEL = {
    "card": "div.views-row",
    "name": "div.views-field-nothing a",
    "link": "div.views-field-nothing a",
    "title": "div.views-field-field-personnel-preferred-title",
    "email": "div.views-field-field-personnel-email-address a[href^='mailto:']",
}
_CAFE_LADDER = {"require": r"professor|lecturer|instructor"}
_CAFE_BASE = ("https://personnel.mgcafe.uky.edu/home?combined_department_filter="
              "{code}&field_personnel_ext_county_target_id=All"
              "&field_personnel_name_last_value=")


def _cafe(short: str, name: str, majors: list[str], code: str) -> dict:
    """A CAFE academic department on the personnel.mgcafe.uky.edu View."""
    url = _CAFE_BASE.format(code=code)
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CAFE_SEL, "ladder_filter": _CAFE_LADDER,
                   "paginate": {"param": "page", "start": 1, "max": 8}},
    }


# ---- College of Communication & Information: headless render -----------------
# ci.uky.edu is bot-walled; the college directory is a Drupal AJAX View. Render
# the filtered listing (wait for the card grid past the challenge + AJAX), then
# render each profile in the env-gated pass to read the personal mailto.
_CI_SEL = {
    "card": "div.mb-5.col-6.col-lg-3",
    "name": "strong a[href*='/about/directory/']",
    "link": "strong a[href*='/about/directory/']",
    "title": "div.views-field-field-position-title",
}
_CI_ENRICH = {
    "render": True,
    "render_wait": "domcontentloaded",
    "email_selector": "a[href^='mailto:']:not(.ico-email)",
    "email_drop": r"webmanager|ciwebmanager|^info@|^comm@|^sis@",
    # Same reason A&S sets it: the CI LISTING carries no email at all, so this
    # pass is where the address comes from, not optional depth. Left env-gated,
    # every harvest that runs without OFE_ENRICH_PROFILES emits contact_email=
    # None for all ~95 CI faculty, and the merge's carry-forward then re-installs
    # whatever address the corpus already held — freezing pre-fix values in place
    # (the display-cased "Clements@uky.edu" / "HannahJones@uky.edu" the site
    # publishes, and the shared ciwebmanager@uky.edu inbox this block's own
    # ``email_drop``/``:not(.ico-email)`` were added to reject). Running it every
    # harvest re-derives each address through _clean_email, so the canonical
    # lowercase value wins and a dropped address is never re-derived.
    "always": True,
    "throttle": 0.0,
}
_CI_BASE = ("https://ci.uky.edu/about/directory"
            "?field_directory_type_value=faculty&field_department_target_id={id}")


def _ci(short: str, name: str, majors: list[str], dept_id: int) -> dict:
    """A CI unit recovered headless from the college's Drupal AJAX directory."""
    url = _CI_BASE.format(id=dept_id)
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CI_SEL, "ladder_filter": _LADDER,
                   "render": True, "render_wait": "networkidle",
                   "render_settle": 6000, "profile_enrich": _CI_ENRICH},
    }


SCHOOL: dict = {
    "school_slug": "uky",
    "source": "uky_faculty",
    "organization": "University of Kentucky",
    "location": "Lexington, KY",
    "id_prefix": "uky",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Kentucky) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering (shared people-list table) -------------
        _eng("CS", "Department of Computer Science",
             ["Computer Science", "Data Science"], 30),
        _eng("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"], 38),
        _eng("MAE", "Department of Mechanical and Aerospace Engineering",
             ["Mechanical Engineering", "Aerospace Engineering"], 54),
        _eng("BME", "F. Joseph Halcomb III, M.D. Department of Biomedical Engineering",
             ["Biomedical Engineering"], 17),
        _eng("CME", "Department of Chemical and Materials Engineering",
             ["Chemical Engineering", "Materials Engineering", "Materials Science"], 24),
        _eng("CE", "Department of Civil Engineering",
             ["Civil Engineering", "Environmental Engineering"], 27),
        _eng("MNG", "Department of Mining Engineering",
             ["Mining Engineering"], 55),
        # ---- College of Arts & Sciences (shared directory-card grid) -------
        _as("PHYS", "Department of Physics and Astronomy",
            ["Physics", "Astronomy"], "https://pa.as.uky.edu/faculty"),
        _as("CHEM", "Department of Chemistry",
            ["Chemistry", "Biochemistry"], "https://chem.as.uky.edu/faculty"),
        _as("MATH", "Department of Mathematics",
            ["Mathematics", "Applied Mathematics"], "https://math.as.uky.edu/faculty",
            paginate={"param": "page", "max": 3}),
        _as("STAT", "Dr. Bing Zhang Department of Statistics",
            ["Statistics", "Data Science"], "https://stat.as.uky.edu/faculty"),
        _as("BIO", "Department of Biology",
            ["Biology", "Neuroscience"], "https://bio.as.uky.edu/faculty"),
        _as("PSY", "Department of Psychology",
            ["Psychology", "Neuroscience"], "https://psychology.as.uky.edu/faculty"),
        _as("ENGL", "Department of English",
            ["English"], "https://english.as.uky.edu/faculty"),
        _as("HIST", "Department of History",
            ["History"], "https://history.as.uky.edu/faculty"),
        _as("POLS", "Department of Political Science",
            ["Political Science"], "https://polisci.as.uky.edu/faculty"),
        # ---- Gatton College of Business & Economics (people-list View) -----
        _gatton("ACC", "Von Allmen School of Accountancy",
                ["Accounting"], 1),
        _gatton("ECON", "Department of Economics",
                ["Economics"], 9),
        _gatton("FIN", "Department of Finance and Quantitative Methods",
                ["Finance", "Business Analytics"], 12),
        _gatton("MGT", "Department of Management",
                ["Management"], 25),
        _gatton("MKT", "Department of Marketing and Supply Chain",
                ["Marketing"], 27),
        # ---- Martin-Gatton College of Agriculture (personnel directory) ----
        _cafe("AEC", "Department of Agricultural Economics",
              ["Agricultural Economics"], "primary_44_secondary_696"),
        _cafe("AFS", "Department of Animal and Food Sciences",
              ["Animal Sciences", "Food Science"], "primary_11_secondary_698"),
        _cafe("BAE", "Department of Biosystems and Agricultural Engineering",
              ["Biosystems Engineering"], "primary_47_secondary_652"),
        _cafe("FNR", "Department of Forestry and Natural Resources",
              ["Forestry and Natural Resources"], "primary_42_secondary_705"),
        # ---- College of Communication & Information (headless render) ------
        _ci("COMM", "Department of Communication",
            ["Communication"], 18),
        _ci("JAM", "School of Journalism and Media",
            ["Journalism", "Media Arts and Studies"], 20),
        _ci("SIS", "School of Information Science",
            ["Information Communication Technology"], 21),
        _ci("ISC", "Department of Integrated Strategic Communication",
            ["Communication"], 19),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
