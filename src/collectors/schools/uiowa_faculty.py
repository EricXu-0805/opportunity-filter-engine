"""University of Iowa faculty config (via the faculty_graph engine).

Two markup families, both live-verified 2026-07-24, cover the university:

* **Campus-standard SiteNow (Drupal) "people" card** — the CLAS departments, the
  College of Engineering departments, and the College of Nursing. One card is a
  ``div.views-row`` wrapping ``div.card--layout-…card`` and carrying:

  * an ``h3.headline`` whose ``a[href^='/people/']`` links to the profile and
    whose ``span.headline__heading`` holds the display name (often with a
    ", PhD" credential the engine's ``_strip_credentials`` trims);
  * a ``div.field--name-field-person-position`` block whose ``.field__items``
    hold one ``.field__item`` per appointment — the rank ("Professor",
    "Assistant Professor", "Professor of Instruction", "Lecturer") plus, for
    some, administrative roles ("Chair, Department of …") and endowed-title
    designations. Order varies, so a positional ``.field__item`` selector can't
    reliably land the rank;
  * a ``div.field--name-field-person-email`` block with a plain ``mailto:``.

  One shared selector set + one ``field_filter`` gate covers every SiteNow
  department. CLAS departments live on per-department subdomains
  (``<dept>.uiowa.edu/people/faculty``); the engineering departments live under
  the college host (``engineering.uiowa.edu/<dept>/people``); Nursing lists its
  whole roster at ``nursing.uiowa.edu/people`` (faculty + staff interleaved and
  Drupal-paginated ``?page=N``, so the gate + paginate are load-bearing).

  Gate — a ``field_filter`` on the position block (``require_present`` +
  ``include: professor|lecturer``): the block's varying item order defeats a
  single-item ``title`` selector, and the engine defaults a *missing* title to
  "Professor", which a ladder ``require`` would wave through. ``require_present``
  reads the position field directly and drops rank-less cards (advisors /
  administrators / staff); ``include`` drops research scientists, program
  specialists and postdocs. ``title_re`` extracts the clean rank for display and,
  by capturing a trailing "Emeritus"/"Emerita", feeds the engine's retired-title
  guard so emeriti drop while active endowed "…Scholar/Fellow" professors stay.

* **Campus "Directory Profiles" API (profiles.uiowa.edu)** — the colleges whose
  directories are painted client-side by the UIDS ``directory-listing`` widget
  (Tippie College of Business, College of Education). The widget reads a Nuxt
  REST service; ``GET /api/people?api-key=<college key>&cohort=<unit id>&size=200``
  returns the authoritative HR roster with ``personType`` (FACULTY / EMERITUS /
  ADJUNCT / STAFF / *_STUDENT), ``directoryTitle`` (clean rank), ``email`` (real
  @uiowa.edu, 100 % populated), ``profileName`` and ``departments``. Each college
  site embeds its own ``api-key``; each academic department is a ``cohort`` whose
  roster stays under the API's 200-row page cap, so one un-paginated ``json_dir``
  request per department fetches it whole. Gate is ``personType == FACULTY`` (one
  equality drops emeriti, adjuncts, staff and students — no title regex needed).

Single source ("uiowa_faculty"); department rides each record, ids namespaced by
department short-code. The API rosters carry no profile URL (email is the dedup
key), so joint appointments across two cohorts dedup on the shared @uiowa.edu.

Coverage (live-verified 2026-07-24): 25 departments across CLAS, Engineering,
Tippie Business, Education and Nursing — every unit whose roster is real ladder/
teaching faculty AND majority-emailed.

Dropped / phase-2 (recorded so a later pass knows where to look):
* **College of Public Health** — its people live in a WordPress ``faculty-profiles``
  post type that mixes faculty with alumni/students; only ~36 % carry a
  ``wpcf-email`` meta value and the public profile pages expose only the shared
  ``cph-webmaster@`` mailto. CPH does NOT embed a profiles.uiowa.edu directory
  widget (no reachable ``api-key``/cohort), so the clean campus API can't be hit
  config-only. Shipping it would mean ~60 % email-less name-only records — dropped
  pending a profile-enrich pass or CPH's own profiles key.
* **CLAS humanities on the legacy layout** (German, Classics & Religious Studies,
  Linguistics, Gender/Women's/Sexuality Studies, Geography, Rhetoric, French &
  Italian, Asian & Slavic, Cinematic Arts, Theatre) — their ``/people/faculty``
  pages render an older non-SiteNow template with zero ``card--layout`` person
  cards and no reachable email (a headless render still yields 0 cards), and CLAS
  exposes no profiles-widget api-key. Needs a per-site adapter — phase 2.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Campus SiteNow "people" card (CLAS + Engineering + Nursing) ---------------
# ``title_re`` extracts the rank from the whole card text (the position block is
# the first place a rank word appears), keeping any trailing "Emeritus"/"Emerita"
# so the engine's retired-title gate can drop actual emeriti.
_SEL = {
    "card": "div.views-row",
    "name": ".headline__heading",
    "link": "h3.headline a",
    "email": ".field--name-field-person-email .field__item a",
    "title_re": (
        r"((?:Adjunct |Visiting |Clinical |Research |Distinguished |Assistant "
        r"|Associate |Emeritus |Emerita )*Professor(?:\s+Emerit(?:us|a))?"
        r"(?:\s+of\s+Instruction)?|Lecturer|Instructor)"
    ),
}

# Keep Professors (ladder + teaching "of Instruction" + endowed) and Lecturers;
# drop research scientists, administrators, program specialists and postdocs the
# directories mix in. The position field is read directly (require_present) so a
# rank-less card can't fall through into the engine's "Professor" default;
# ``include`` then keeps only professor/lecturer ranks. Emeriti drop downstream
# via the title_re-extracted rank feeding the engine's retired-title guard.
_FIELD = {
    "selector": ".field--name-field-person-position .field__items",
    "require_present": True,
    "include": r"professor|lecturer",
}


def _dept(short: str, name: str, majors: list[str], url: str,
          paginate: dict | None = None) -> dict:
    """A department on the shared University of Iowa SiteNow people card."""
    scrape = {"url": url, "selectors": _SEL, "field_filter": _FIELD}
    if paginate:
        scrape["paginate"] = paginate
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


# ---- Campus "Directory Profiles" API (profiles.uiowa.edu) ----------------------
# Each academic department is a ``cohort`` under its college's ``api-key``; the
# roster fits one 200-row page. Gate on personType == FACULTY (drops emeriti /
# adjuncts / staff / students). No profile URL in the feed — email is the key.
_TIPPIE_KEY = "ebab7021-4a40-45b5-83d5-26922855e68d"
_TIPPIE_SITE = "https://tippie.uiowa.edu/people"
_EDU_KEY = "0f7ad038-cfa6-406d-ab27-c572dc435d59"
_EDU_SITE = "https://education.uiowa.edu/directory"


def _api(short: str, name: str, majors: list[str], key: str, cohort: int,
         site_url: str) -> dict:
    """A department off the campus Directory Profiles REST service.

    ``site_url`` is the human-facing college directory page — kept as the record
    fallback URL (the API feed carries no per-person profile link) so the stored
    record never exposes the ``api-key`` that only the fetch URL needs.
    """
    api_url = (f"https://profiles.uiowa.edu/api/people?api-key={key}"
               f"&cohort={cohort}&query&page=0&size=200")
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": site_url,
        "json_dir": {
            "url": api_url, "records_key": "results",
            "status_field": "personType", "status_value": "FACULTY",
            "name_fields": ["profileName"], "title_field": "directoryTitle",
            "email_field": "email",
        },
    }


SCHOOL: dict = {
    "school_slug": "uiowa",
    "source": "uiowa_faculty",
    "organization": "University of Iowa",
    "location": "Iowa City, IA",
    "id_prefix": "uiowa",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Iowa) — work authorization depends on "
        "the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Liberal Arts & Sciences (SiteNow subdomains) --------
        _dept("CS", "Department of Computer Science",
              ["Computer Science", "Data Science", "Informatics"],
              "https://cs.uiowa.edu/people/faculty"),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics", "Actuarial Science"],
              "https://math.uiowa.edu/people/faculty"),
        _dept("STAT", "Department of Statistics and Actuarial Science",
              ["Statistics", "Actuarial Science", "Data Science"],
              "https://stat.uiowa.edu/people/faculty"),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy"],
              "https://physics.uiowa.edu/people/faculty"),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"],
              "https://chem.uiowa.edu/people/faculty"),
        _dept("BIOL", "Department of Biology",
              ["Biology", "Neuroscience", "Genetics"],
              "https://biology.uiowa.edu/people/faculty"),
        _dept("PSYC", "Department of Psychological and Brain Sciences",
              ["Psychology", "Neuroscience"],
              "https://psychology.uiowa.edu/people/faculty"),
        _dept("POLS", "Department of Political Science", ["Political Science"],
              "https://politicalscience.uiowa.edu/people/faculty"),
        _dept("SOC", "Department of Sociology and Criminology",
              ["Sociology", "Criminology"],
              "https://sociology.uiowa.edu/people/faculty"),
        _dept("ANTH", "Department of Anthropology", ["Anthropology"],
              "https://anthropology.uiowa.edu/people/faculty"),
        _dept("HIST", "Department of History", ["History"],
              "https://history.uiowa.edu/people/faculty"),
        _dept("ENGL", "Department of English", ["English", "Creative Writing"],
              "https://english.uiowa.edu/people/faculty"),
        _dept("PHIL", "Department of Philosophy", ["Philosophy"],
              "https://philosophy.uiowa.edu/people/faculty"),
        _dept("AMST", "Department of American Studies", ["American Studies"],
              "https://americanstudies.uiowa.edu/people/faculty"),
        _dept("SPAN", "Department of Spanish and Portuguese",
              ["Spanish", "Portuguese"],
              "https://spanish-portuguese.uiowa.edu/people/faculty"),
        _dept("SART", "School of Art, Art History and Design",
              ["Studio Art", "Art History", "Graphic Design"],
              "https://art.uiowa.edu/people/faculty"),
        _dept("MUS", "School of Music", ["Music", "Music Education"],
              "https://music.uiowa.edu/people/faculty"),
        _dept("SJMC", "School of Journalism and Mass Communication",
              ["Journalism", "Mass Communication"],
              "https://journalism.uiowa.edu/people/faculty"),
        _dept("DANCE", "Department of Dance", ["Dance"],
              "https://dance.uiowa.edu/people/faculty"),
        # ---- College of Engineering (SiteNow, college host) -----------------
        _dept("ECE", "Department of Electrical and Computer Engineering",
              ["Electrical Engineering", "Computer Science and Engineering"],
              "https://engineering.uiowa.edu/ece/people"),
        _dept("ME", "Department of Mechanical Engineering",
              ["Mechanical Engineering"],
              "https://engineering.uiowa.edu/me/people"),
        _dept("BME", "Roy J. Carver Department of Biomedical Engineering",
              ["Biomedical Engineering"],
              "https://engineering.uiowa.edu/bme/people"),
        _dept("CBE", "Department of Chemical and Biochemical Engineering",
              ["Chemical Engineering"],
              "https://engineering.uiowa.edu/cbe/people"),
        _dept("CEE", "Department of Civil and Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"],
              "https://engineering.uiowa.edu/cee/people"),
        _dept("ISE", "Department of Industrial and Systems Engineering",
              ["Industrial and Systems Engineering"],
              "https://engineering.uiowa.edu/ise/ise-people-research/ise-people"),
        # ---- College of Nursing (SiteNow, whole-roster + gate + pager) ------
        _dept("NURS", "College of Nursing", ["Nursing"],
              "https://nursing.uiowa.edu/people",
              paginate={"param": "page", "start": 1, "max": 15}),
        # ---- Tippie College of Business (Directory Profiles API) ------------
        _api("ACCT", "Department of Accounting", ["Accounting"],
             _TIPPIE_KEY, 538101, _TIPPIE_SITE),
        _api("BAIS", "Department of Business Analytics",
             ["Business Analytics and Information Systems"],
             _TIPPIE_KEY, 537896, _TIPPIE_SITE),
        _api("ECON", "Department of Economics",
             ["Economics"], _TIPPIE_KEY, 538355, _TIPPIE_SITE),
        _api("FIN", "Department of Finance",
             ["Finance", "Risk Management and Insurance"], _TIPPIE_KEY, 537818,
             _TIPPIE_SITE),
        _api("MGMT", "Department of Management and Entrepreneurship",
             ["Management", "Entrepreneurship"], _TIPPIE_KEY, 417809,
             _TIPPIE_SITE),
        _api("MKTG", "Department of Marketing", ["Marketing"],
             _TIPPIE_KEY, 538980, _TIPPIE_SITE),
        # ---- College of Education (Directory Profiles API) ------------------
        _api("EDUTL", "Department of Teaching and Learning",
             ["Elementary Education", "Secondary Education", "Special Education"],
             _EDU_KEY, 519557, _EDU_SITE),
        _api("EDUPQ", "Department of Psychological and Quantitative Foundations",
             ["Educational Psychology"], _EDU_KEY, 519556, _EDU_SITE),
        _api("EDUPL", "Department of Educational Policy and Leadership Studies",
             ["Educational Administration"], _EDU_KEY, 519555, _EDU_SITE),
        _api("EDUCE", "Department of Counselor Education", ["Counseling"],
             _EDU_KEY, 519554, _EDU_SITE),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
