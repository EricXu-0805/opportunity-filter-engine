"""University at Buffalo (SUNY) faculty config (via the faculty_graph engine).

University-wide coverage across every college whose department directories
server-render their roster over plain HTTP. UB runs ONE campus component — the
Communique/AEM ``profileinfo-teaser`` card — and the disciplinary departments
of the School of Engineering and Applied Sciences, the College of Arts and
Sciences, and the School of Architecture and Planning all author it statically
(HTTP 200 to a bare request, no WAF, no JS render). Live-verified 2026-07-24.
One card is a ``div.profileinfo-teaser.teaser-block`` holding:

* ``div.profileinfo-teaser-name`` whose first ``<a>`` is the display name (the
  link points at the person's ``…host.html/content/shared/…`` profile page). The
  name text carries a trailing ``,PhD`` credential the engine's
  ``_strip_credentials`` removes, and a sibling ``.profileinfo-teaser-degree``
  ("PhD, University of Chicago") that is OUTSIDE the anchor, so the name selector
  never absorbs it;
* the rank in a per-card element that DIFFERS by CMS skin — the Engineering and
  Arts&Sciences "new-profiles" sites put it in ``.profileinfo-teaser-dept-title``;
  the ``www.buffalo.edu/cas`` skin (Math, English, Anthropology, Communication,
  Geography, Philosophy) puts it in ``.profileinfo-teaser-school-title``. One
  combined ``title`` selector covers both (only one variant exists per card);
* ``.profileinfo-teaser-contact`` with a ``mailto`` where the directory exposes an
  address (coverage is 90–100% per dept; the handful of profiles that publish no
  listing address are recovered by the downstream per-profile enrich pass via the
  profile link);
* an interests block whose topic list follows a
  ``.profileinfo-teaser-interests-title`` label span. The label wording varies by
  dept ("Research Topics:", "Research Interests:", and — on EE —
  "Specialty/Research Focus:", which the engine's shared label-strip does NOT
  know), so ``research`` is captured with a ``research_re`` that grabs the text
  AFTER the label span rather than a CSS selector that would fold the label into
  the first keyword chip. Departments that omit the block land name+title+email
  and topics come from OpenAlex enrichment.

Title gate (``field_filter``): the directories mix in emeriti, a lone Instructor
(Chemistry), and — crucially — real professors whose FIRST rank element is an
administrative role ("Department Chair", "Associate Dean for Research",
"Director of Undergraduate Studies"). The clean per-card rank element
(``…-dept-title`` / ``…-school-title``) shows only that first role, so gating on
it would drop those real professors. Instead the ``field_filter`` reads the
fuller ``.profileinfo-teaser-titles`` blob ("Department Chair Professor
Department of Physics …"), which carries the "Professor" word wherever the person
holds a ladder rank — ``require_present`` drops title-less cards, ``include``
keeps only ranks containing professor/lecturer (dropping the Instructor and any
pure-admin/staff card), and the engine's own ``_RETIRED_TITLE_RE`` — run on the
clean per-card rank ("Emeritus") — drops the emeriti even though their titles
blob contains "Professor Emeritus". The displayed ``title`` stays the clean
per-card rank; an administrator's card shows their admin role (accurate — they do
hold it).

Single source ("buffalo_faculty"); department rides each record, ids namespaced
by department short-code. Cross-listed interdisciplinary programs (GGSS,
Environment & Sustainability, Africana & American Studies, Comparative
Literature, Asian Studies) share faculty with the home departments; the engine's
email/URL/id dedup collapses the overlap onto whichever dept is processed first,
so their net contribution is their program-unique core.

Live-verified 2026-07-24 (raw teaser cards on the listing, pre-gate): SEAS —
CSE 66, EE 28, MAE 26, CBE 31, CSEE 32, ISE 38, BME 17. CAS — Physics 33,
Chemistry 30, Math 43, Biological Sciences 42, Psychology 36, Economics 15,
History 24, Art 19, Earth Sciences 21, English 38, Anthropology 16,
Communication 25, Geography 35, Philosophy 19, Political Science 20, Sociology &
Criminology 27, Linguistics 18, Music 20, Media Study 18, Classics 7, Romance
Languages 22, Theatre & Dance 25, Africana & American Studies 10, Global Gender
& Sexuality Studies 28, Comparative Literature 9, Environment & Sustainability
29. Architecture & Planning — 50 (one school-wide directory).
Emails land on ~95% of kept records; missing listing addresses are recovered by
the profile-enrich pass.

Dropped / phase-2 (client-side directory apps — no server-rendered roster and no
config-reachable JSON endpoint; the roster does NOT paint even under a headless
Playwright render with ``networkidle`` + 6 s settle, so a ``render:True`` scrape
lands zero cards):
* School of Management — the school-wide ``staff_member`` directory server-renders
  181 addresses but carries NO rank field (name + unit only), so it can't be gated
  to ladder faculty without inflating with business-office staff; the per-department
  pages (Accounting & Law, Finance, MSS, Marketing, OMS, Org & HR) are a JS
  teaser-search widget that paints nothing on load.
* School of Public Health and Health Professions — AEM people-directory search
  component; roster fetched via a JS-constructed query the static HTML never names.
* School of Nursing — same AEM directory-search widget; renders no roster on load.
* Materials Design and Innovation (SEAS) — ``faculty-and-staff.html`` server-renders
  only nav teasers; no faculty roster, no emails, no reachable feed.
All four need an interactive/paginated headless pass or a dedicated directory-API
adapter — out of scope for a config-only pass.

Also dropped: Department of Asian Studies — its 7-card roster is entirely
cross-listed faculty (History, Linguistics, Romance Languages, …); the engine's
email/id dedup absorbs all of them into their home departments, leaving zero
program-unique records, so it added only a redundant directory fetch.
"""

from __future__ import annotations

from .. import faculty_graph

# The shared UB Communique/AEM "profileinfo-teaser" card. The first <a> under
# ``.profileinfo-teaser-name`` is the name+profile link (the degree line is a
# sibling div outside it). The rank element differs by CMS skin — Engineering /
# Arts&Sciences "new-profiles" use ``…-dept-title``, the ``www.buffalo.edu/cas``
# skin uses ``…-school-title`` — so the ``title`` selector matches either (only
# one exists per card). Email is the first mailto in the contact block; research
# is captured after the interests label span (research_re) so a non-standard
# label ("Specialty/Research Focus:" on EE) never leaks into the first chip.
_SEL = {
    "card": "div.profileinfo-teaser",
    "name": ".profileinfo-teaser-name a",
    "link": ".profileinfo-teaser-name a",
    "title": ".profileinfo-teaser-dept-title, .profileinfo-teaser-school-title",
    "research_re": r"profileinfo-teaser-interests-title[^>]*>.*?</span>(.*?)</p>",
    "email": ".profileinfo-teaser-contact a[href^='mailto:']",
}

# Gate on the FULL titles blob (not the clean per-card rank) so a real professor
# whose first rank element is an admin role ("Department Chair") — but whose blob
# reads "Department Chair Professor …" — is kept, while the lone Instructor and
# any staff/title-less card are dropped. require_present blocks the missing-title
# default-to-"Professor"; emeriti drop via the engine's retired gate on the clean
# per-card rank.
_FIELD = {
    "selector": ".profileinfo-teaser-titles",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _dept(short: str, name: str, majors: list[str], url: str) -> dict:
    """A department on the shared UB profileinfo-teaser component."""
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": {"url": url, "selectors": _SEL, "field_filter": _FIELD},
    }


_SEAS = "https://engineering.buffalo.edu"
_CAS = "https://arts-sciences.buffalo.edu"
_CASW = "https://www.buffalo.edu/cas"


SCHOOL: dict = {
    "school_slug": "buffalo",
    "source": "buffalo_faculty",
    "organization": "University at Buffalo",
    "location": "Buffalo, NY",
    "id_prefix": "buffalo",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University at Buffalo, SUNY) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Engineering and Applied Sciences --------------------
        _dept("CSE", "Department of Computer Science and Engineering",
              ["Computer Science", "Computer Engineering", "Data Science"],
              f"{_SEAS}/computer-science-engineering/people/faculty-directory.html"),
        _dept("EE", "Department of Electrical Engineering",
              ["Electrical Engineering", "Computer Engineering"],
              f"{_SEAS}/ee/faculty/faculty_directory.html"),
        _dept("MAE", "Department of Mechanical and Aerospace Engineering",
              ["Mechanical Engineering", "Aerospace Engineering"],
              f"{_SEAS}/mechanical-aerospace/people/faculty.html"),
        _dept("CBE", "Department of Chemical and Biological Engineering",
              ["Chemical Engineering"],
              f"{_SEAS}/chemical-biological/people/faculty-directory.html"),
        _dept("CSEE", "Department of Civil, Structural and Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"],
              f"{_SEAS}/civil-structural-environmental/people/faculty_directory.html"),
        _dept("ISE", "Department of Industrial and Systems Engineering",
              ["Industrial Engineering"],
              f"{_SEAS}/industrial-systems/people/faculty-directory.html"),
        _dept("BME", "Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              f"{_SEAS}/bme/faculty/faculty_directory.html"),
        # ---- College of Arts and Sciences: natural sciences & math ---------
        _dept("PHYS", "Department of Physics", ["Physics"],
              f"{_CAS}/physics/faculty/faculty-directory.html"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
              f"{_CAS}/chemistry/faculty/faculty-directory.html"),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics", "Applied Mathematics"],
              f"{_CASW}/math/people/faculty.html"),
        _dept("BIO", "Department of Biological Sciences",
              ["Biological Sciences", "Bioinformatics and Computational Biology"],
              f"{_CAS}/biological-sciences/faculty/faculty-directory.html"),
        _dept("EAR", "Department of Earth Sciences",
              ["Geological Sciences", "Environmental Science"],
              f"{_CAS}/earth-sciences/faculty-staff/faculty.html"),
        _dept("PSYC", "Department of Psychology", ["Psychology"],
              f"{_CAS}/psychology/faculty/faculty-directory.html"),
        # ---- College of Arts and Sciences: social sciences -----------------
        _dept("ECON", "Department of Economics", ["Economics"],
              f"{_CAS}/economics/faculty/faculty-directory.html"),
        _dept("POLSCI", "Department of Political Science", ["Political Science"],
              f"{_CAS}/political-science/faculty/department-faculty.html"),
        _dept("SOC", "Department of Sociology and Criminology",
              ["Sociology"],
              f"{_CAS}/sociology-criminology/faculty/faculty-directory.html"),
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              f"{_CASW}/anthropology/faculty/faculty_directory.html"),
        _dept("GEOG", "Department of Geography", ["Geography"],
              f"{_CASW}/geography/faculty/faculty_directory.html"),
        _dept("COMM", "Department of Communication", ["Communication"],
              f"{_CASW}/communication/faculty/faculty-directory.html"),
        _dept("LING", "Department of Linguistics", ["Linguistics"],
              f"{_CAS}/linguistics/faculty/directory.html"),
        _dept("ENS", "Department of Environment and Sustainability",
              ["Environmental Science"],
              f"{_CAS}/environment-sustainability/faculty/faculty-directory.html"),
        # ---- College of Arts and Sciences: humanities & arts ---------------
        _dept("ENGL", "Department of English", ["English"],
              f"{_CASW}/english/faculty/faculty_directory.html"),
        _dept("HIST", "Department of History", ["History"],
              f"{_CAS}/history/faculty/faculty-directory.html"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"],
              f"{_CASW}/philosophy/faculty/faculty_directory.html"),
        _dept("ART", "Department of Art", ["Art History", "Studio Art"],
              f"{_CAS}/art/faculty/directory.html"),
        _dept("MUS", "Department of Music", ["Music"],
              f"{_CAS}/music/faculty/faculty.html"),
        _dept("MEDIA", "Department of Media Study", ["Media Study"],
              f"{_CAS}/media-study/people/faculty-directory.html"),
        _dept("THD", "Department of Theatre and Dance", ["Theatre", "Dance"],
              f"{_CAS}/theatre-dance/faculty/faculty-directory.html"),
        _dept("RLL", "Department of Romance Languages and Literatures",
              ["Spanish", "French"],
              f"{_CAS}/romance-languages-literatures/people/departmental-faculty.html"),
        _dept("CLAS", "Department of Classics", ["Classics"],
              f"{_CAS}/classics/faculty/core-faculty.html"),
        # ---- College of Arts and Sciences: interdisciplinary programs ------
        _dept("AAS", "Department of Africana and American Studies",
              ["Africana and American Studies"],
              f"{_CAS}/africana-and-american-studies/faculty/faculty-directory.html"),
        _dept("GGSS", "Department of Global Gender and Sexuality Studies",
              ["Global Gender and Sexuality Studies"],
              f"{_CAS}/global-gender-sexuality/faculty/faculty-directory.html"),
        _dept("COMPLIT", "Department of Comparative Literature",
              ["Comparative Literature"],
              f"{_CAS}/comparative-literature/faculty/faculty-directory.html"),
        # ---- School of Architecture and Planning (one school-wide roster) --
        _dept("ARCH", "School of Architecture and Planning",
              ["Architecture", "Environmental Design", "Urban Planning"],
              "https://archplan.buffalo.edu/People/faculty.html"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
