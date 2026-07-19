"""Boston College faculty config (via the faculty_graph engine).

Boston College runs on a single Adobe AEM platform (``www.bc.edu/content/
bc-web``) with no WAF (all ~90 recon fetches clean 200s on 2026-07-19). Two
markup families, both live-verified:

* ``bc_json`` (Morrissey College of Arts & Sciences + STM department pages) —
  every A&S department "people" page hydrates its roster client-side from an
  authoritative AEM JSON endpoint: the faculty-section component published at
  ``<component-path>.faculty-section.json``. Each record carries clean fields
  ``firstName``/``lastName``, ``position`` (rank), ``email`` (a real
  ``@bc.edu`` address, inline — no obfuscation), ``path`` (the profile page,
  joined onto ``https://www.bc.edu``) and an ``expertise`` list of
  ``{path,title}`` tag objects whose titles are clean atomic research areas
  (``expertise[].title`` fans out to keywords; most STEM depts leave it empty,
  economics/political-science/history populate it richly). This is consumed
  with the engine's ``json_dir`` mechanism (one hardcoded endpoint per dept).

  IMPORTANT: the AEM component path is PAGE-SPECIFIC, not derivable from the
  department slug — it varies wildly across depts (``bottompar`` vs ``par``,
  ``bc_tabbed_content`` vs ``bc_tabbed_content_0`` vs ``bc_tabs``, arbitrarily
  nested ``bc_padded_section``/``responsive_columns``, and node-name suffixes
  like ``bc_faculty_section_c``/``_179518802``). Every URL below was extracted
  from the live people page during recon and is hardcoded verbatim.

  A department's people page groups people into tabs (core faculty, research
  faculty, emeriti, postdocs, grad students, staff, ...). Each tab is its own
  faculty-section JSON. We point at the FACULTY tab(s) only. Three departments
  split their ladder faculty across sibling tabs, so they get one dept entry
  per faculty tab sharing the same ``name`` (records group by dept name; the
  engine's per-school email/url dedup keeps them distinct people):
    - Chemistry: Teaching Faculty (tab, n=6) + Research Faculty (tab, n=10).
    - Romance Languages: French (5) + Hispanic Studies (10) + Italian (4).
    - Art, Art History & Film: Art History (12) + Film Studies (8) +
      Studio Arts (12).
  The other 19 A&S depts + STM take a single faculty tab (tab-0 core).

* ``bc_expertise`` (Lynch / Carroll / Connell / Social Work / STM) — the
  professional schools do NOT use per-department people pages; each publishes
  one school-wide "Faculty Directory & Expertise" listing whose cards are
  server-rendered into an AEM HTML fragment at
  ``.../facultyList/faculty-list.items.html``. Cards are
  ``div.person-list-expertise`` with a ``a.directory-person`` name link (a
  trailing ``, Ph.D.``/``, Ed.D.`` credential span is name-stripped), an
  ``h4`` rank, an inline ``a[href^=mailto]``, and a ``.expertise-column li``
  list of clean research areas (``research_items``). Scraped directly off the
  fragment (no render, no pagination — the fragment returns the full roster;
  header "We've found N faculty" matched card count on every school).

Rank gating: a drop-only ``ladder_filter`` (``_DROP``) plus the engine's
unconditional emeritus/retired drop. No ``require`` — BC lists lab/program
directors and "Professor of the Practice" teaching faculty without the word
"professor" in some titles, and the tab/fragment scoping already excludes
students/postdocs/staff. Emails are inline everywhere, so NO profile_enrich
pass is configured (email coverage ~99% from the listings themselves).

Single source ("bc_faculty"); department rides each record, ids namespaced by
department short-code.

Deferred (2026-07-19 recon):
* Woods College of Advancing Studies — its faculty page redirects to a
  marketing hub (wcas.html) with no structured faculty listing; roster is
  overwhelmingly part-time/adjunct practitioners.
* Per-department splitting of the professional-school directories — the
  fragments carry a per-card ``data-department`` attribute (Lynch has 5 depts,
  Carroll 6) but the engine's field_filter gates on element TEXT, not
  attributes, so each professional school is onboarded as one dept entry.
* Emeritus / research-scientist / postdoc / grad-student tabs on the A&S
  people pages — intentionally excluded (not cold-email research PIs).
"""

from __future__ import annotations

from .. import faculty_graph

_BASE = "https://www.bc.edu"

# Drop non-ladder roles; the engine also unconditionally drops emeritus/
# emerita/retired titles on top of this. Keep Professors (incl. "of the
# Practice"), Lecturers, and program/lab Directors who are listed as faculty.
_DROP = (r"emerit|retired|in memoriam|in memorial|adjunct|\bpart.?time\b"
         r"|visiting|postdoc|post-doc|graduate student|ph\.?d\.? (?:student|candidate)")
_LADDER = {"drop": _DROP}


def _json(short: str, name: str, majors: list[str], people_url: str,
          json_url: str) -> dict:
    """A department served by the AEM faculty-section JSON endpoint."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": people_url,
        "json_dir": {
            "url": json_url,
            "name_fields": ["firstName", "lastName"],
            "title_field": "position",
            "email_field": "email",
            "link_field": "path",
            "link_base": _BASE,
            "research_field": "expertise[].title",
            "ladder_filter": _LADDER,
        },
    }


# Professional-school expertise fragment: shared card family.
_EXP_SEL = {
    "card": "div.person-list-expertise",
    "name": "a.directory-person",
    "name_strip": r"\s*,.*$",          # drop trailing ", Ph.D."/", Ed.D." credential
    "link": "a.directory-person",
    "title": "h4",
    "email": "a[href^='mailto:']",
    "research_items": ".expertise-column li",
}


def _prof(short: str, name: str, majors: list[str], dir_url: str,
          items_url: str) -> dict:
    """A professional school's school-wide expertise directory fragment."""
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": dir_url,
        "scrape": {"url": items_url, "selectors": _EXP_SEL,
                   "ladder_filter": _LADDER},
    }


# people-page base for directory_url (human-facing)
def _pp(dept: str) -> str:
    return f"{_BASE}/content/bc-web/schools/morrissey/departments/{dept}/people.html"


SCHOOL: dict = {
    "school_slug": "bc",
    "source": "bc_faculty",
    "organization": "Boston College",
    "location": "Chestnut Hill, MA",
    "id_prefix": "bc",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Boston College) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ==== Morrissey College of Arts & Sciences (JSON faculty-section) ====
        # -- Natural sciences / STEM --
        _json("BIOL", "Department of Biology", ["Biology", "Biological Sciences"],
              _pp("biology"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/biology/people/jcr:content/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        # Chemistry's tabbed people.html is stale (its "research_faculty" tab
        # is 1 active PI + 9 emeriti; active tenure-track PIs are absent). The
        # dept instead maintains the same faculty-expertise fragment the
        # professional schools use — the complete current roster (Gao,
        # Chatterjee, Bao, ...). Use that instead of the JSON tabs.
        _prof("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
              f"{_BASE}/content/bc-web/schools/morrissey/departments/chemistry/people/faculty-expertise.html",
              f"{_BASE}/content/bc-web/schools/morrissey/departments/chemistry/people/faculty-expertise/jcr:content/facultyList/faculty-list.items.html"),
        _json("CS", "Department of Computer Science", ["Computer Science"],
              _pp("computer-science"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/computer-science/people/jcr:content/bottompar/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("EESC", "Department of Earth and Environmental Sciences",
              ["Environmental Science", "Environmental Geoscience", "Geological Sciences"],
              _pp("eesc"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/eesc/people/jcr:content/par/bc_tabbed_content_co/tab-0/bc_faculty_section.faculty-section.json"),
        _json("ENGR", "Human-Centered Engineering (Schiller Institute)",
              ["Engineering", "Human-Centered Engineering"],
              _pp("engineering"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/engineering/people/jcr:content/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("MATH", "Department of Mathematics", ["Mathematics"],
              _pp("math"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/math/people/jcr:content/bottompar/bc_padded_section/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("PHYS", "Department of Physics", ["Physics"],
              _pp("physics"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/physics/people/jcr:content/par/bc_tabbed_content_co/tab-0/bc_faculty_section.faculty-section.json"),
        _json("PSYN", "Department of Psychology and Neuroscience",
              ["Psychology", "Neuroscience"],
              _pp("psychology-neuroscience"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/psychology-neuroscience/people/jcr:content/bottompar/bc_padded_section_557856871/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        # -- Social sciences --
        _json("ECON", "Department of Economics", ["Economics"],
              _pp("economics"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/economics/people/jcr:content/bottompar/bc_padded_section_1748513737/par/bc_tabs/tab-tab-0/bc_faculty_section.faculty-section.json"),
        _json("POLI", "Department of Political Science",
              ["Political Science", "International Studies"],
              _pp("political-science"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/political-science/people/jcr:content/bottompar/bc_padded_section/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("SOCY", "Department of Sociology", ["Sociology"],
              _pp("sociology"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/sociology/people/jcr:content/bottompar/bc_padded_section/par/bc_tabs/tab-tab-0/bc_faculty_section_c.faculty-section.json"),
        # -- Humanities --
        _json("ARTH", "Department of Art, Art History, and Film",
              ["Art History", "Film Studies", "Studio Art"],
              _pp("art"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/art/people/jcr:content/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("ARTF", "Department of Art, Art History, and Film",
              ["Art History", "Film Studies", "Studio Art"],
              _pp("art"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/art/people/jcr:content/par/bc_tabbed_content/tab-1/bc_faculty_section.faculty-section.json"),
        _json("ARTS", "Department of Art, Art History, and Film",
              ["Art History", "Film Studies", "Studio Art"],
              _pp("art"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/art/people/jcr:content/par/bc_tabbed_content/tab-2/bc_faculty_section_c.faculty-section.json"),
        _json("CLAS", "Department of Classical Studies",
              ["Classics", "Classical Studies"],
              _pp("classics"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/classics/people/jcr:content/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("COMM", "Department of Communication", ["Communication"],
              _pp("communication"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/communication/people/jcr:content/bottompar/bc_padded_section/par/bc_padded_section/par/bc_padded_section/par/bc_tabbed_content/tab-0/bc_padded_section/par/bc_faculty_section.faculty-section.json"),
        _json("ESG", "Department of Eastern, Slavic, and German Studies",
              ["German Studies", "Slavic Studies", "Russian"],
              _pp("eastern-slavic-german"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/eastern-slavic-german/people/jcr:content/bottompar/bc_padded_section/par/bc_tabs/tab-tab-0/bc_faculty_section_c.faculty-section.json"),
        _json("ENGL", "Department of English", ["English", "Creative Writing"],
              _pp("english"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/english/people/jcr:content/bottompar/bc_padded_section_950813004/par/bc_padded_section/par/bc_tabs/tab-Full-z3313f/bc_faculty_section_c.faculty-section.json"),
        _json("HIST", "Department of History", ["History"],
              _pp("history"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/history/people/jcr:content/bottompar/bc_padded_section_293803755/par/bc_tabbed_content/tab-0/bc_faculty_section_179518802.faculty-section.json"),
        _json("MUSA", "Department of Music", ["Music"],
              _pp("music"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/music/people/jcr:content/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("PHIL", "Department of Philosophy", ["Philosophy"],
              _pp("philosophy"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/philosophy/people/jcr:content/bottompar/bc_padded_section_2010981694/par/bc_padded_section/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("RLFR", "Department of Romance Languages and Literatures",
              ["French", "Francophone Studies", "Italian", "Hispanic Studies"],
              _pp("romance-languages"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/romance-languages/people/jcr:content/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("RLSP", "Department of Romance Languages and Literatures",
              ["French", "Francophone Studies", "Italian", "Hispanic Studies"],
              _pp("romance-languages"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/romance-languages/people/jcr:content/par/bc_tabbed_content/tab-1/bc_faculty_section.faculty-section.json"),
        _json("RLIT", "Department of Romance Languages and Literatures",
              ["French", "Francophone Studies", "Italian", "Hispanic Studies"],
              _pp("romance-languages"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/romance-languages/people/jcr:content/par/bc_tabbed_content/tab-2/bc_faculty_section.faculty-section.json"),
        _json("THEA", "Department of Theatre", ["Theatre"],
              _pp("theatre"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/theatre/people/jcr:content/par/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        _json("THEO", "Department of Theology", ["Theology"],
              _pp("theology"),
              f"{_BASE}/content/bc-web/schools/morrissey/departments/theology/people/jcr:content/par/bc_padded_section/par/responsive_columns/col1/bc_tabbed_content/tab-0/bc_faculty_section.faculty-section.json"),
        # ==== Professional schools (school-wide expertise fragment) ==========
        _prof("LSEHD", "Lynch School of Education and Human Development",
              ["Applied Psychology and Human Development", "Education",
               "Applied Developmental and Educational Psychology"],
              f"{_BASE}/content/bc-web/schools/lynch-school/faculty-research/faculty-directory-expertise.html",
              f"{_BASE}/content/bc-web/schools/lynch-school/faculty-research/faculty-directory-expertise/jcr:content/facultyList/faculty-list.items.html"),
        _prof("CSOM", "Carroll School of Management",
              ["Accounting", "Finance", "Marketing", "Business Analytics",
               "Management and Organization", "Business Law"],
              f"{_BASE}/content/bc-web/schools/carroll-school/faculty-research/faculty-expertise.html",
              f"{_BASE}/content/bc-web/schools/carroll-school/faculty-research/faculty-expertise/jcr:content/facultyList/faculty-list.items.html"),
        _prof("CSON", "Connell School of Nursing", ["Nursing"],
              f"{_BASE}/content/bc-web/schools/cson/faculty-research/faculty-directory.html",
              f"{_BASE}/content/bc-web/schools/cson/faculty-research/faculty-directory/jcr:content/facultyList/faculty-list.items.html"),
        _prof("SSW", "Boston College School of Social Work", ["Social Work"],
              f"{_BASE}/content/bc-web/schools/ssw/faculty/faculty-expertise.html",
              f"{_BASE}/content/bc-web/schools/ssw/faculty/faculty-expertise/jcr:content/facultyList/faculty-list.items.html"),
        _prof("STM", "School of Theology and Ministry",
              ["Theology", "Ministry", "Sacred Theology"],
              f"{_BASE}/content/bc-web/schools/stm/faculty/faculty-expertise.html",
              f"{_BASE}/content/bc-web/schools/stm/faculty/faculty-expertise/jcr:content/facultyList/faculty-list.items.html"),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
