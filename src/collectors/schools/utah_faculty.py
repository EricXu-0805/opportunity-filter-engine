"""University of Utah faculty config (via the faculty_graph engine).

University-wide coverage across the six undergraduate colleges in the catalog
(``frontend/src/lib/catalogs/utah.ts``). All departments are plain server-rendered
HTTP 200s (no headless render, no WAF); every entry below was live-verified to
yield ladder faculty. Six markup families cover the buildable departments:

* **The7 "faculty card" grid (ECE + Mechanical Engineering).**
  ``www.ece.utah.edu/faculty/`` and ``www.mech.utah.edu/directory/faculty/`` share
  one custom-templated The7 grid: each member is a ``div.person-container`` whose
  ``div.t-entry`` holds the name (``h2.t-entry-title``), the rank (``h3.t-entry-meta``),
  a ``ul.card-links-list`` of phone/email/office, and a free-text research excerpt
  (topics come from OpenAlex, not the card). GOTCHA: the department's hand-authored
  HTML mis-closes the headings (``<h2>Name</h3>``, ``<h3>Rank</h4>``) so
  ``html.parser`` nests the following nodes inside the heading. ``name_strip`` trims
  the name back at the first rank/role token; ``title_strip_after`` trims the rank at
  the first contact marker.

* **University "v2 faculty directory" (OMNI CMS, ``div.grid-item.faculty``).**
  A single campus-wide template (``websites.it.utah.edu/v2-faculty-directory``)
  embedded per-department across Humanities, CSBS, and the School of Music. Each
  person is a ``div.grid-item.faculty`` with ``h2.name`` (name), a rank paragraph
  (``.content > p[class='']`` on the compact variant, ``.section-1 p.h6`` on the
  two-column variant used by World Languages), and a ``p.email`` mailto. Two quirks
  the selectors absorb: (1) the two-column variant prefixes the name with an
  ``<span class="sr-only">Profile for </span>`` — ``name_strip`` removes it; (2) an
  admin appointment ("Department Chair", "Associate Dean") is sometimes listed above
  the academic rank, so ``title_re`` pulls the real Professor/Lecturer rank from
  anywhere in the card (the CSS ``title`` stays as a staff-safety fallback so a
  role-only card fails the ladder gate). Covers English, History, Linguistics,
  Philosophy, World Languages & Cultures, Writing & Rhetoric, Communication, Family
  & Consumer Studies, and the School of Music.

* **UU "team member" WordPress widget (Civil & Environmental Engineering).**
  ``www.civil.utah.edu/directory/`` renders each person as a
  ``div.uu-team-member-widget-card``. GOTCHA: the widget's field classes are
  swapped — ``.uu-team-member-widget-title`` holds the *name* and
  ``.uu-team-member-widget-name`` holds the *rank*.

* **OMNI "flip-panel" grids (Anthropology, Political Science, Economics,
  Psychology, Sociology).** An older hand-templated OMNI layout (``c-panel`` /
  ``isotope-item`` cells) where the rank lives in an inconsistent element per site.
  Rather than chase each element, ``title_re`` extracts the Professor/Lecturer rank
  (with any Emeritus suffix, so the retired gate can drop it) from the card text;
  a per-site CSS ``title`` stays as the staff fallback. Name selectors differ by
  site (``h2.h4 a`` / ``span.h3`` / ``h4.text-uppercase a``); the SHOUTING rosters
  (Psychology, Sociology) get ``name_title_case``.

* **Chemistry (dedicated card grid).** ``www.chemistry.utah.edu/faculty-directory/``
  renders one ``div.chem-faculty-card`` per person: name in ``.h3``, rank as the
  first ``.titles .title``, a mailto, and research-area icons (no text).

* **Mathematics (bio-list).** ``www.math.utah.edu/directory/faculty.php`` is a
  server-rendered ``ul`` of ``li.biolist-item`` rows sub-classed by track; the card
  selector keeps only ``tenure-line`` and ``career-line-faculty`` rows.

Two more platforms carry a single department each:

* **Kahlert School of Computing (Gutenberg blocks).**
  ``www.cs.utah.edu/people/faculty/`` — ``div.t-entry`` with ``h2`` (name), ``h4``
  (rank), a mailto, and a "Research Interests" paragraph. A ``field_filter`` on the
  ``h4`` drops the title-less adjunct/affiliated cards.
* **Parks, Recreation & Tourism (College of Health, Cohesion CMS).**
  ``health.utah.edu/parks-recreation-tourism/faculty`` — ``div.gls-card`` with
  ``h3.gls-card-title`` (name), ``p.gls-text-meta`` (rank), a mailto.
* **Theatre (custom Bootstrap cards).** ``theatre.utah.edu/about/people`` —
  ``div.card`` with ``.card-title`` (name) and ``.card-text`` (rank); no published
  email. People are listed once per performance area, so the engine's id/url dedup
  collapses the cross-area duplicates.

Three more platforms, one department each, recovered from the JS-rendered pass:

* **College of Engineering shared Vue directory (backing JSON).** Chemical
  Engineering and Biomedical Engineering (Bioengineering) render their people
  page as a Vue app over a static per-department
  ``admin.coe.utah.edu/.../<slug>/faculty.json`` roster — a ``directory_tag``
  field cleanly gates ladder ``Faculty`` (CHE 38→26, BME 152→25) from the
  Emeritus/Adjunct blocks, with rank + email inline (``_coe_json``). Materials
  Science & Engineering also carries the Metallurgical Engineering major (that
  standalone COE roster is a 3-person subset of MSE's faculty).
* **Materials Science & Engineering (SiteOrigin roster).** ``mse.utah.edu/faculty/``
  is server-rendered after all (``div.textwidget:has(address)`` cards, ~28
  faculty with rank + mailto; ``_MSE_SEL``).
* **Art & Art History (SiteOrigin link-list + profile pass).** A bare
  name-link roster grouped by teaching area; rank + email come from each
  server-rendered profile via the unconditional enrich pass.

Two more platforms, recovered from the JS-rendered pass via server-rendered
profile pages / a static PHP roster:

* **David Eccles School of Business (Avada/Fusion ``team`` CPT via sitemap).**
  The college directory (``eccles.utah.edu/faculty/``) and its per-department
  pages are Avada marketing shells whose faculty grids load through the
  awsm-team-pro ``admin-ajax`` — a static fetch surfaces zero cards, and the
  ``awsm_team_member`` REST route exposes only 3 stub records. But every person
  has a fully server-rendered profile at ``/team/<slug>/`` (``h2.name`` /
  ``h4.position`` / ``div.team-email`` mailto, plus an ``h4.department`` link),
  and the site's ``directory-sitemap.xml`` enumerates all 621 of them. The
  ``sitemap`` fetcher walks that sitemap and parses each profile; a
  require-professor/lecturer gate (drop emeritus/adjunct/visiting) keeps the
  ladder faculty and drops the interleaved staff/advisors/PhD students
  (coordinators, directors, etc.). One college-wide pool — the profiles' own
  department link is not carried into per-dept attribution (all land under the
  school, mapped to every Eccles major), same as the NCSU Poole/CHASS pools.
* **Mining Engineering (hand-authored PHP flip-panel roster).** The 2026-07
  recon marked this unreachable, but ``mining.utah.edu/department-info/
  faculty.php`` is a plain server-rendered PHP page: each person is a
  ``div.c-panel-flip`` whose name-panel carries an ``h3.h4`` name (SHOUTING →
  ``name_title_case``) followed by a rank ``<p>``, and whose adjacent bio-panel
  holds the mailto. ``title_re`` pulls the rank from the card text and the
  ladder gate drops the emeriti (a separate ``<h2 class="h4">`` block) and the
  table-listed adjuncts. GOTCHA: the name selector is pinned to ``h3.h4:has(+
  p)`` because the panels are padded with empty ``&nbsp;`` headings and an
  image-only ``h2.h4`` that a bare ``h3.h4``/``h2.h4`` selector would grab
  first; the one member whose name sits in an ``h2.h4`` (image + text) is left
  behind rather than reintroduce those empty matches.

Not built — needs a headless render pass (phase 2), not wireable from a config
block with the current engine fetchers:
* **Physics & Astronomy** — FacetWP grid (``/department-directory/``): only the
  first 12 cards render server-side (the rest load via a ``facetwp_refresh``
  ajax pager the engine can't drive), the bare ``faculty`` wp-json feed carries
  no rank/email/role to gate emeriti (verified: records are name+link only, no
  meta/acf/taxonomy), and the ``/faculty/<slug>/`` profile pages are themselves
  React shells (only a generic ``help@`` inbox renders server-side).
* **Biology** — FacetWP directory (``/directory/``) renders as one flat table of
  everyone (faculty + grad students + staff) with no rank/role column, and the
  WP REST exposes no person CPT (only ``degrees`` / ``biology-publication``), so
  there is no signal to gate faculty.
* **Dance, Film & Media Arts** — Squarespace sites whose ``/faculty-staff``
  roster lives only inside a client-rendered block-JSON payload (no
  server-rendered DOM cards, no clean people array), so neither ``scrape`` nor
  ``json_dir`` can read it.
Biochemistry (College of Science major) is covered by the Chemistry department.

Single source ("utah_faculty"); department rides each record, ids namespaced by
department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# The mis-closed The7 headings nest the rank + contacts inside the name heading;
# trim the name back to the person by cutting at the first rank/role token. On a
# cleanly-closed heading (most of ECE) there is no such token, so this is a
# no-op. Deliberately only genuine rank/role words that never occur inside a
# personal name, so it can never truncate a real surname.
_NAME_STRIP = (
    r"\s+(?:Distinguished|Associate|Assistant|Adjunct|Clinical|Visiting|Research"
    r"|Emeritus|Emerita|Endowed|USTAR|Professor|Lecturer|Instructor|Chair|Dept\.?"
    r"|Director|Dir\.?|Dean|Robotics|Advisor|Fellow|Scientist|Coordinator"
    r"|Program|Acting|Interim).*$"
)
# The rank heading absorbs the phone/email/office/excerpt below it; keep only the
# text before the first contact marker.
_TITLE_STRIP_AFTER = r"\s+(?:Phone|Email|Office|Advisor|Fax|Website)\b"

# Pull the academic rank (Professor/Lecturer, with modifiers and an Emeritus
# suffix) from anywhere in a card's text. Used as ``title_re`` on the directories
# whose markup lists an admin appointment ("Department Chair") above the academic
# rank, or hides the rank in an inconsistent element. Capturing the Emeritus
# suffix lets the engine's retired-title gate drop emeriti; a card with no rank
# match keeps its CSS ``title`` (a staff role), which the ladder gate then drops.
_RANK_RE = (
    r"((?:(?:Distinguished|University|Presidential|Endowed|Research|Clinical"
    r"|Teaching|Adjunct|Visiting|Associate|Assistant|Emeritus|Emerita)\s+)*"
    r"(?:Professor|Lecturer)(?:\s+Emerit(?:us|a))?)"
)
_LADDER = {"require": r"professor|lecturer"}


# ---- The7 faculty-card grid (ECE + Mechanical Engineering) -----------------
# No research selector: the card's excerpt is free-form prose that comma-splits
# into junk, so topics come from OpenAlex and the card ships name+title+email.
_CARD_SEL = {
    "card": "div.person-container",
    "name": "h2.t-entry-title",
    "name_strip": _NAME_STRIP,
    "title": "h3.t-entry-meta",
    "title_strip_after": _TITLE_STRIP_AFTER,
    "email": "li.card-email a[href^='mailto:']",
}


def _card_dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """An ECE/ME department on the shared The7 faculty-card grid."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _CARD_SEL, "ladder_filter": _LADDER},
    }


# ---- University "v2 faculty directory" OMNI template -----------------------
# ``name_strip`` drops the World-Languages "Profile for " sr-only prefix (no-op
# elsewhere). The CSS ``title`` is the first rank line (compact ``.content`` cards
# or two-column ``.section-1`` cards); ``title_re`` overrides it with the academic
# rank when an admin role is listed first. ``link`` prefers the in-name profile
# anchor (two-column variant), else the profile-link button (compact variant).
_OMNI_SEL = {
    "card": "div.grid-item.faculty",
    "name": "h2.name",
    "name_strip": r"^\s*Profile for\s+",
    "link": "h2.name a, p.profile-link a",
    "title": ".content > p[class=''], .section-1 p.h6",
    "title_re": _RANK_RE,
    "email": "p.email a[href^='mailto:']",
}


def _omni_dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the campus-wide v2 faculty-directory OMNI template."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _OMNI_SEL, "ladder_filter": _LADDER},
    }


# ---- OMNI "flip-panel" grids (rank lives in an inconsistent element) --------
def _flip_dept(short: str, name: str, majors: list[str], url: str, *,
               card: str, name_sel: str, title_sel: str,
               title_case: bool = False, strip_after: str | None = None) -> dict:
    """An older OMNI flip-panel directory: ``title_re`` recovers the rank, the
    per-site CSS ``title`` is the staff-safety fallback."""
    sels: dict = {
        "card": card, "name": name_sel, "title": title_sel,
        "title_re": _RANK_RE, "email": "a[href^='mailto:']",
    }
    if title_case:
        sels["name_title_case"] = True
    if strip_after:
        sels["title_strip_after"] = strip_after
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": sels, "ladder_filter": _LADDER},
    }


# ---- UU "team member" WordPress widget (field classes are swapped) ----------
# The widget renders the name in ``.uu-team-member-widget-title`` (an ``h3``) and
# the rank in ``.uu-team-member-widget-name`` (a ``p``) — key off the class, not
# the tag. The address is a plain card-level ``mailto`` (no email-field wrapper).
_TEAM_SEL = {
    "card": "div.uu-team-member-widget-card",
    "name": ".uu-team-member-widget-title",
    "title": ".uu-team-member-widget-name",
    "email": "a[href^='mailto:']",
}


# ---- College of Engineering shared Vue directory (backing JSON) -------------
# Several Price College of Engineering departments (Chemical, Biomedical) render
# their people page as a Vue app (``div#directory-listing``) that GETs a static
# per-department roster from the college's admin host:
# ``admin.coe.utah.edu/public/storage/profile/<slug>/faculty.json`` →
# ``{"profiles": [{name, titles, email, summary, directory_tag, ...}]}``. A
# static scrape of the shell lands zero people, but the JSON is complete and
# authoritative: ``directory_tag`` cleanly separates ladder ``Faculty`` from
# ``Emeritus Faculty`` / ``Adjunct Faculty`` (the gate the mixed-rank roster
# needs), and every faculty record carries rank + email inline. The JSON has no
# per-person profile URL, so records land linkless (the engine points them at
# the department directory) and de-dup on email.
def _coe_json(short: str, name: str, majors: list[str], slug: str,
              directory_url: str) -> dict:
    """A Price College of Engineering department fetched from its shared Vue
    directory's backing ``faculty.json`` (``directory_tag`` == Faculty gate)."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": directory_url,
        "json_dir": {
            "url": (f"https://admin.coe.utah.edu/public/storage/profile/"
                    f"{slug}/faculty.json"),
            "records_key": "profiles",
            "name_fields": ["name"],
            "title_field": "titles",
            "email_field": "email",
            # The roster's own role tag is the primary gate — it isolates ladder
            # Faculty from the Emeritus/Adjunct blocks the same feed carries.
            "filter_field": "directory_tag",
            "filter_value": "Faculty",
            # Belt-and-suspenders on the title in case a block is mis-tagged.
            "ladder_filter": {"drop": r"emerit|adjunct"},
        },
    }


# ---- Materials Science & Engineering (SiteOrigin PageBuilder roster) ---------
# ``mse.utah.edu/faculty/`` is a server-rendered SiteOrigin layout: each faculty
# member is a ``div.textwidget`` holding ``<h4>Name</h4>`` and an ``<address>``
# with the rank (first ``<strong>``) + a plain mailto. The ``:has(address)``
# card gate keeps only the person widgets (the alternating "Research Interest"
# textwidgets have no address). Emeriti are dropped by the engine's retired-rank
# gate. Also carries the Metallurgical Engineering catalog major (the standalone
# metallurgical-engineering roster is a 3-person subset of these same faculty).
_MSE_SEL = {
    "card": "div.textwidget:has(address)",
    "name": "h4",
    "title": "address strong",
    "email": "address a[href^='mailto:']",
}


SCHOOL: dict = {
    "school_slug": "utah",
    "source": "utah_faculty",
    "organization": "University of Utah",
    "location": "Salt Lake City, UT",
    "id_prefix": "utah",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Utah) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ===== College of Science ===========================================
        {
            "short": "CS",
            "name": "Kahlert School of Computing",
            "majors": ["Computer Science", "Data Science", "Computer Engineering"],
            "directory_url": "https://www.cs.utah.edu/people/faculty/",
            "scrape": {
                "url": "https://www.cs.utah.edu/people/faculty/",
                "selectors": {
                    "card": "div.t-entry",
                    "name": "h2",
                    "title": "h4",
                    "email": "a[href^='mailto:']",
                    # Research Interests live in a <p> after a <strong> label;
                    # bound just that paragraph so the label doesn't leak in.
                    "research_re": r"Research Interests</strong>(.*?)</p>",
                },
                # The adjunct/affiliated cards are bare h2's with no rank h4 —
                # require the h4 to exist, then keep only professor/lecturer ranks.
                "field_filter": {
                    "selector": "h4",
                    "require_present": True,
                    "include": r"professor|lecturer",
                },
            },
        },
        {
            "short": "CHEM",
            "name": "Department of Chemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://www.chemistry.utah.edu/faculty-directory/",
            "scrape": {
                "url": "https://www.chemistry.utah.edu/faculty-directory/",
                "selectors": {
                    "card": "div.chem-faculty-card",
                    "name": "div.chem-faculty-card-content-inner div.h3",
                    "link": "div.chem-faculty-card-content-inner a[href*='/faculty/']",
                    # First .title is the rank; a second .title holds an endowed
                    # chair line, which select_one ignores.
                    "title": "div.titles div.title",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "MATH",
            "name": "Department of Mathematics",
            "majors": ["Mathematics", "Applied Mathematics", "Statistics"],
            "directory_url": "https://www.math.utah.edu/directory/faculty.php",
            "scrape": {
                "url": "https://www.math.utah.edu/directory/faculty.php",
                # Keep only tenure-line + career-line faculty rows; adjunct,
                # emeritus, and Asia-campus rows are excluded by construction.
                "selectors": {
                    "card": "li.biolist-item.tenure-line, li.biolist-item.career-line-faculty",
                    "name": "h2.h3",
                    "link": "h2.h3 a[href]",
                    "title": ".h5",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        },
        # ===== John & Marcia Price College of Engineering ===================
        _card_dept("ECE", "Department of Electrical and Computer Engineering",
                   ["Electrical Engineering", "Computer Engineering"],
                   "https://www.ece.utah.edu/faculty/"),
        _card_dept("ME", "Department of Mechanical Engineering",
                   ["Mechanical Engineering"],
                   "https://www.mech.utah.edu/directory/faculty/"),
        {
            "short": "CVEEN",
            "name": "Department of Civil and Environmental Engineering",
            "majors": ["Civil Engineering"],
            "directory_url": "https://www.civil.utah.edu/directory/",
            "scrape": {
                "url": "https://www.civil.utah.edu/directory/",
                "selectors": _TEAM_SEL,
                "ladder_filter": _LADDER,
            },
        },
        _coe_json("CHE", "Department of Chemical Engineering",
                  ["Chemical Engineering"], "chemical-engineering",
                  "https://www.che.utah.edu/department/people/faculty/"),
        _coe_json("BME", "Department of Biomedical Engineering",
                  ["Biomedical Engineering"], "bioengineering",
                  "https://www.bme.utah.edu/department-directory/"),
        {
            "short": "MSE",
            "name": "Department of Materials Science and Engineering",
            "majors": ["Materials Science and Engineering",
                       "Metallurgical Engineering"],
            "directory_url": "https://mse.utah.edu/faculty/",
            "scrape": {
                "url": "https://mse.utah.edu/faculty/",
                "selectors": _MSE_SEL,
                "ladder_filter": _LADDER,
            },
        },
        # Mining Engineering: hand-authored PHP flip-panel roster. The name is
        # pinned to ``h3.h4:has(+ p)`` (the heading immediately before the rank
        # paragraph) so the empty ``&nbsp;`` and image-only headings padding each
        # panel don't win ``select_one``; ``title_re`` recovers the rank and the
        # gate drops the emeriti block + the table-listed adjuncts.
        {
            "short": "MINING",
            "name": "Department of Mining Engineering",
            "majors": ["Mining Engineering"],
            "directory_url": "https://mining.utah.edu/department-info/faculty.php",
            "scrape": {
                "url": "https://mining.utah.edu/department-info/faculty.php",
                "selectors": {
                    "card": "div.c-panel-flip",
                    "name": "h3.h4:has(+ p)",
                    "name_title_case": True,
                    "title_re": _RANK_RE,
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": {"require": r"professor|lecturer",
                                  "drop": r"emerit|adjunct|visiting"},
            },
        },
        # ===== College of Humanities (v2 OMNI template) =====================
        _omni_dept("ENGL", "Department of English", ["English"],
                   "https://english.utah.edu/directory/faculty.php"),
        _omni_dept("HIST", "History Department", ["History"],
                   "https://history.utah.edu/faculty/index.php"),
        _omni_dept("LING", "Department of Linguistics", ["Linguistics"],
                   "https://linguistics.utah.edu/about/faculty-and-staff.php"),
        _omni_dept("PHIL", "Department of Philosophy", ["Philosophy"],
                   "https://philosophy.utah.edu/directory/faculty.php"),
        _omni_dept("WLC", "Department of World Languages and Cultures",
                   ["World Languages and Cultures"],
                   "https://languages.utah.edu/directory/faculty.php"),
        _omni_dept("WRTG", "Department of Writing and Rhetoric Studies",
                   ["Writing and Rhetoric Studies"],
                   "https://writing.utah.edu/directory/faculty.php"),
        # ===== College of Social and Behavioral Science =====================
        _omni_dept("COMM", "Department of Communication", ["Communication"],
                   "https://communication.utah.edu/about/directory/faculty.php"),
        _omni_dept("FCS", "Department of Family and Consumer Studies",
                   ["Family and Consumer Studies"],
                   "https://fcs.utah.edu/faculty-directory/index.php"),
        _flip_dept("ANTH", "Department of Anthropology", ["Anthropology"],
                   "https://anthro.utah.edu/people/faculty.php",
                   card="div.c-grid-layout__cell", name_sel="h2.h4 a",
                   title_sel="p"),
        _flip_dept("POLS", "Department of Political Science", ["Political Science"],
                   "https://poli-sci.utah.edu/faculty.php",
                   card="div.isotope-item", name_sel="h2.h4 a", title_sel="em"),
        _flip_dept("PSYCH", "Department of Psychology", ["Psychology"],
                   "https://psych.utah.edu/people/faculty/index.php",
                   card="div.isotope-item", name_sel="h2.h4 a", title_sel="p",
                   title_case=True,
                   strip_after=r"\s+(?:Office|Phone|Email|Fax)\b"),
        _flip_dept("SOC", "Department of Sociology", ["Sociology"],
                   "https://soc.utah.edu/people/index.php",
                   card="div.c-grid-layout__cell",
                   name_sel="h4.text-uppercase a",
                   title_sel="h4:not(.text-uppercase)", title_case=True),
        _flip_dept("ECON", "Department of Economics", ["Economics"],
                   "https://econ.utah.edu/people/faculty.php",
                   card="div.isotope-item", name_sel="span.h3", title_sel="em"),
        # Parks, Recreation & Tourism (College of Health, Cohesion CMS).
        {
            "short": "PRT",
            "name": "Department of Parks, Recreation, and Tourism",
            "majors": ["Parks, Recreation and Tourism"],
            "directory_url": "https://health.utah.edu/parks-recreation-tourism/faculty",
            "scrape": {
                "url": "https://health.utah.edu/parks-recreation-tourism/faculty",
                "selectors": {
                    "card": "div.gls-card",
                    "name": "h3.gls-card-title",
                    "title": "p.gls-text-meta",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
            },
        },
        # ===== College of Fine Arts =========================================
        # Art & Art History: the faculty-list page is a SiteOrigin bare link-list
        # (names grouped by teaching area, no rank/email inline) — each person is
        # an ``<a href=".../faculty-list/<slug>/">``; ``link_filter`` keeps only
        # the slugged profile links (dropping the bare nav "Faculty List" link).
        # The rank + personal email live on each server-rendered profile page, so
        # the profile pass runs unconditionally (``always``): it sets the real
        # rank (``use_position_title`` → ``ladder_recheck`` drops emeriti) and
        # reads the personal mailto from the profile's contact button (the site
        # menu also carries the department advisor's mailto — scoped out).
        {
            "short": "ART",
            "name": "Department of Art and Art History",
            "majors": ["Studio Art", "Art History"],
            "directory_url": "https://www.art.utah.edu/faculty-list/",
            "scrape": {
                "url": "https://www.art.utah.edu/faculty-list/",
                "selectors": {
                    "card": "a[href*='/faculty-list/']",
                    "name": ":self",
                    "link": ":self",
                },
                "link_filter": r"/faculty-list/[^/]+/?$",
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "always": True,
                    "email_selector": "div.ow-button-base a[href^='mailto:']",
                    "email_drop": r"^[^@]*$",
                    "position_re": (
                        r"(?:Distinguished |University |Clinical |Adjunct "
                        r"|Visiting |Research |Associate |Assistant )*"
                        r"Professor(?:\s+Emerit(?:us|a))?|Lecturer|Instructor"
                    ),
                    "use_position_title": True,
                    "ladder_recheck": {"require": r"professor|lecturer",
                                       "drop": r"emerit"},
                    "throttle": 0.2,
                },
            },
        },
        _omni_dept("MUSIC", "School of Music", ["Music"],
                   "https://music.utah.edu/faculty/index.php"),
        {
            "short": "THEATRE",
            "name": "Department of Theatre",
            "majors": ["Theatre"],
            "directory_url": "https://theatre.utah.edu/about/people",
            "scrape": {
                "url": "https://theatre.utah.edu/about/people",
                # People are listed once per performance area — the engine's
                # id/url dedup collapses the cross-area duplicates.
                "selectors": {
                    "card": "div.card",
                    "name": ".card-title",
                    "link": "a[href]",
                    "title": ".card-text",
                    "title_re": _RANK_RE,
                },
                "ladder_filter": _LADDER,
            },
        },
        # ===== David Eccles School of Business ===============================
        # Marketing shells hide the roster behind awsm-team-pro admin-ajax, but
        # every person has a server-rendered ``/team/<slug>/`` profile and the
        # ``directory-sitemap.xml`` enumerates all 621. The ``sitemap`` fetcher
        # parses each profile; the require-professor/lecturer gate keeps ladder
        # faculty and drops the interleaved staff/advisors/PhD students. One
        # college-wide pool (no per-dept attribution from the profile), mapped to
        # every Eccles catalog major.
        {
            "short": "BUS",
            "name": "David Eccles School of Business",
            "majors": ["Accounting", "Finance", "Marketing", "Management",
                       "Economics", "Entrepreneurship", "Information Systems"],
            "directory_url": "https://eccles.utah.edu/faculty/",
            "sitemap": {
                "sitemaps": ["https://eccles.utah.edu/directory-sitemap.xml"],
                # /team/<slug>/ profiles only — skip the /team/ archive root and
                # nested .xml locs.
                "include": r"/team/[a-z][a-z0-9-]+/?$",
                "selectors": {
                    "name": "h2.name",
                    "title": "h4.position",
                    "email": "div.team-email a[href^='mailto:']",
                },
                "ladder_filter": {"require": r"professor|lecturer",
                                  "drop": r"emerit|adjunct|visiting|affiliate"},
                "throttle": 0.15,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
