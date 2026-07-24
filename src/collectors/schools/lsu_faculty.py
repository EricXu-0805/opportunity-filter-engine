"""Louisiana State University faculty config (via the faculty_graph engine).

LSU has NO shared campus directory template — every department ships its own
hand-built OmniUpdate (a.cms.omniupdate.com) or Drupal markup, so each of the 43
departments below carries its own selector set. Almost every page is a plain
server-rendered 200 through a bare request (no WAF) and almost every address is
a plain ``mailto:`` (no cfemail / base64 / hex obfuscation anywhere), so the
engine's existing selectors + decoders cover them. Live-verified 2026-07-24.

Markup families (each has a helper below):

* **Clean columnar table** — ``_table_sel``. Name / Rank / … / Email in their
  own cells: CHEM, BIOSCI, GEOL (Science), CMST, WLLC, FREN (HSS), all five
  AgCenter departments, and the College of the Coast & Environment roster.
  The name is taken from the *cell*, not its anchor, because instructors with no
  profile page leave the name cell anchor-less — keying off ``td a`` there would
  grab the row's ``mailto`` as the name. Where the page groups rows under
  ``<h2>`` role headings a ``section_filter`` drops the Emeritus / Adjunct /
  Staff / Graduate-Student groups.

* **Card grid / loose block with the rank in free text** — ``_block_sel``. A
  Bootstrap column (``col-lg-3`` BAE, ``col-md-4`` HIST, ``col-md-6`` SOCI/CM,
  ``col-md-3`` ENGL/GA, ``col-lg-7`` PETE/Manship), a bare ``<p>`` sequence
  (CEE, POLI, PSYC), a table cell (COMD, PRS) or a Drupal ``div.personalinfo``
  (MATH). The rank has no element of its own, so ``title_re`` lifts the first
  rank phrase out of the card's text.

* **Engineering "faculty-entry" card** (CSE, CHE) — a two-column Bootstrap row
  whose right ``col-lg-7`` holds name + contact. CSE renders the name in
  ``h3 > strong`` and the rank in the first ``p > em``; CHE renders a bare
  centered ``h3`` and lifts the rank with ``title_re`` (the chair's first ``p``
  is "Department Chair", with the real rank one ``p`` down). PETE uses the same
  visual layout but its ``div.faculty-entry`` wrappers are malformed (several
  people per wrapper, three empty ones), so PETE keys on ``div.col-lg-7``.

* **schema.org ``div.faculty-member``** — ``_design_sel``. The College of Art &
  Design (design.lsu.edu, WordPress) tags every person with
  ``itemprop=name/jobtitle/email`` plus a group class per school, so one page
  serves several schools and the group class scopes each department cleanly.

* **Headless render (ECE only)** — ``www.lsu.edu/eng/ece/…`` paints its A-to-Z
  roster client-side from a JS blob, so a bare GET sees zero addresses.
  ``scrape["render"] = True`` runs it through Playwright, after which the roster
  is ordinary ``td.fac-az-cell-name`` markup with ``div.name`` / ``div.nrank``
  and a plain ``mailto`` on every row (27/27 emailed).

Every department carries a ladder gate (``ladder_filter require:
professor|lecturer|instructor``) so coordinators / advisors / directors,
academic counsellors, postdocs, research associates and grad-student rows drop
while ladder + research + teaching + adjunct professors and lecturers/
instructors are kept. Emeriti are dropped by the engine's own retired-title
guard (``_RETIRED_TITLE_RE``) — note that ``_TITLE_RE`` must therefore be able
to match the *prefixed* "Emeritus Professor" form as well as the suffixed
"Professor Emeritus", or a retired professor's title would normalize to a bare
"Professor" and sail through the guard (PETE and ECE both publish the prefixed
form).

Three sources carry NO address on the listing and recover it with a per-profile
``profile_enrich`` pass (``always: True`` — the profile page is where the field
lives, not optional depth): the six E. J. Ourso business departments (rank on
the card, email only on ``/business/directory/employee-profiles/<slug>.php``),
Psychology (listing is a bare "Name, Rank" link list) and Renewable Natural
Resources. Each pairs the pass with a ``link_filter`` so a card with no profile
link is dropped rather than enriched from the listing page itself, and with an
``email_drop`` so a profile lacking a personal address can never inherit the
shared departmental inbox.

DROPPED / phase-2:

* **International Studies (``/hss/isp/faculty/directory.php``)** — static and
  fully emailed, but it is an interdisciplinary *program* roster: every member
  is a cross-listing of a department already covered here (History, French,
  Economics, Political Science), so the school-level email de-dup would discard
  the whole roster anyway. It also has no per-person card container (a bare
  ``h2`` + ``<p>`` sequence), so there is nothing to select as a card.

* **Linguistics (``/hss/linguistics/people/index.php``)** — same interdisciplinary
  cross-listing problem, and the second line of each card is the member's HOME
  department ("Dept. of English"), not a rank, so the ladder gate has nothing to
  read and cannot separate faculty from affiliates.

* **E. J. Ourso college-wide A-to-Z directory (``/business/directory/``)** — 170
  addresses in one table, but the columns are Name / Department / Contact with
  no rank cell at all, so faculty cannot be separated from staff. Superseded by
  the six per-department pages, which do carry rank.

* **LSU AgCenter central directory (``lsuagcenter.com/portals/directory``)** —
  a JS search widget with no reachable roster endpoint; the departments' own
  ``lsu.edu/agriculture/<dept>/people/`` tables are the better source and are
  wired instead.

Single source ("lsu_faculty"); department rides each record, ids namespaced by
department short-code.
"""

from __future__ import annotations

from .. import faculty_graph

# Keep ladder + research + teaching + adjunct professors and lecturers/
# instructors; drop coordinators / directors / advisors / counsellors /
# postdocs / research associates whose titles carry none of these words.
# Emeriti drop via the engine's retired gate.
_LADDER = {"require": r"professor|lecturer|instructor"}

# First rank phrase in a card's text — used where the rank has no clean element
# of its own. Ordered so a fuller phrase wins over a bare "Professor". BOTH
# emeritus word orders ride along ("Emeritus Professor" via the leading modifier
# group, "Professor Emeritus" via the trailing one) so the retired gate can see
# a retired rank whichever way the department writes it.
_TITLE_RE = (
    r"((?:Distinguished |Research |Visiting |Clinical |Adjunct |Teaching "
    r"|Senior |Emerit\w+ )*(?:Assistant |Associate )?Professor(?:\s+Emerit\w+)?"
    r"|Senior Lecturer|Lecturer|Instructor)"
)

_MAILTO = "a[href^='mailto:']"


def _table_sel(*, name: int = 1, title: int = 2, research: int | None = None,
               email: int | None = None, link: str | None = None) -> dict:
    """Clean columnar table: Name / Rank / … / Email each in their own cell.

    Columns are 1-based ``td`` positions. ``email`` defaults to the row's
    ``mailto`` (most tables) but takes a column where the address is bare text.
    """
    sel = {
        "card": "table tr",
        "name": f"td:nth-of-type({name})",
        "title": f"td:nth-of-type({title})",
        "email": f"td:nth-of-type({email})" if email else _MAILTO,
    }
    if link:
        sel["link"] = link
    if research:
        sel["research"] = f"td:nth-of-type({research})"
    return sel


def _block_sel(card: str, name: str, *, link: str | None = None,
               research: str | None = None, name_strip: str | None = None,
               title: str | None = None, email: str = _MAILTO) -> dict:
    """Card grid / loose block whose rank is free text, lifted by ``title_re``.

    Pass ``title`` instead when the rank does have an element of its own (the
    Manship cards, where the first ``<p>`` is the rank line).
    """
    sel: dict = {"card": card, "name": name, "email": email}
    if title:
        sel["title"] = title
    else:
        sel["title_re"] = _TITLE_RE
    if link:
        sel["link"] = link
    if research:
        sel["research"] = research
    if name_strip:
        sel["name_strip"] = name_strip
    return sel


def _design_sel(group: str) -> dict:
    """College of Art & Design (design.lsu.edu) schema.org person card.

    One page carries several schools' faculty (an architecture professor also
    teaches in the Doctor of Design program), so the per-school group class
    scopes the card to the department that owns the person.
    """
    return {
        "card": f"div.faculty-member.{group}",
        "name": "a.fac_name",
        "link": "a.fac_name",
        "title": "h3[itemprop='jobtitle']",
        "email": "a[itemprop='email']",
        "research": "span.faculty_field",
    }


# ---- Engineering "faculty-entry" card (CSE, CHE) ---------------------------
# CSE: name in h3>strong, rank in the first p>em. CHE: bare centered h3 name,
# rank as <strong> text in a following p — but the chair's first p is "Department
# Chair", so CHE reads the rank with title_re over the whole card instead.
_CSE_SEL = {
    "card": "div.faculty-entry",
    "name": "h3 strong",
    "link": "a.btn-purple",
    "title": "p em",
    "email": _MAILTO,
}
_CHE_SEL = {
    "card": "div.faculty-entry",
    "name": ".col-lg-7 h3",
    "link": "a.btn-purple",
    "title": ".col-lg-7 p",
    "title_re": _TITLE_RE,
    "email": _MAILTO,
}


def _business(short: str, name: str, majors: list[str], slug: str) -> dict:
    """One E. J. Ourso department: identical card grid + per-profile email pass.

    The card carries the rank (name in ``<strong>``, rank on the following
    ``<br>`` lines) but no address; the address lives on the college's shared
    ``/business/directory/employee-profiles/<slug>.php`` page, whose first
    ``mailto`` is the person's own.
    """
    url = f"https://www.lsu.edu/business/{slug}/faculty-staff.php"
    return {
        "short": short,
        "name": name,
        "majors": majors,
        "directory_url": url,
        "scrape": {
            "url": url,
            "selectors": _block_sel("div.col-lg-3", "p strong",
                                    link="a[href*='/employee-profiles/']"),
            # A card with no profile link has nowhere to read an address from —
            # drop it rather than let the enrich pass fetch the LISTING page and
            # hand everyone the college's shared inbox.
            "link_filter": r"/employee-profiles/",
            "ladder_filter": _LADDER,
            "profile_enrich": {
                "always": True,
                "email_selector": _MAILTO,
                "email_drop": r"experienceourso@|^business@",
                "throttle": 0.2,
            },
        },
    }


SCHOOL: dict = {
    "school_slug": "lsu",
    "source": "lsu_faculty",
    "organization": "Louisiana State University",
    "location": "Baton Rouge, LA",
    "id_prefix": "lsu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Louisiana State University) — work authorization "
        "depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ================= College of Engineering =========================
        {
            "short": "CSE",
            "name": "Division of Computer Science and Engineering",
            "majors": ["Computer Science", "Computer Engineering", "Data Science"],
            "directory_url": "https://www.lsu.edu/eng/cse/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/cse/people/faculty/index.php",
                "selectors": _CSE_SEL,
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "CHE",
            "name": "Cain Department of Chemical Engineering",
            "majors": ["Chemical Engineering"],
            "directory_url": "https://www.lsu.edu/eng/che/people/faculty.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/che/people/faculty.php",
                "selectors": _CHE_SEL,
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "ECE",
            "name": "Division of Electrical and Computer Engineering",
            "majors": ["Electrical Engineering", "Computer Engineering"],
            "directory_url": "https://www.lsu.edu/eng/ece/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/ece/people/faculty/index.php",
                # The A-to-Z roster is injected from a JS blob; a bare GET sees
                # the shell with zero names and zero addresses. Rendered, it is
                # ordinary table markup with a mailto on every row.
                "render": True,
                "selectors": {
                    "card": "td.fac-az-cell-name",
                    "name": "div.name",
                    "link": "div.name a",
                    "title": "div.nrank",
                    "email": _MAILTO,
                },
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "MIE",
            "name": "Department of Mechanical and Industrial Engineering",
            "majors": ["Mechanical Engineering", "Industrial Engineering"],
            "directory_url": "https://www.lsu.edu/eng/mie/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/mie/people/faculty/index.php",
                "selectors": {
                    "card": "table tr",
                    "name": "td:nth-of-type(2) a",
                    "title_re": _TITLE_RE,
                    "email": _MAILTO,
                },
                "name_flip": True,
                # The main faculty table sits under the page <h1> with no <h2>;
                # exclude the four <h2> sub-sections (Research / Affiliated /
                # Emeritus / Past) whose rows would otherwise leak.
                "section_filter": {
                    "heading": "h2",
                    "exclude": r"Research Faculty|Affiliated Faculty|Emeritus Faculty|Past Faculty",
                },
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "CEE",
            "name": "Department of Civil and Environmental Engineering",
            "majors": ["Civil Engineering", "Environmental Engineering"],
            "directory_url": "https://www.lsu.edu/eng/cee/people/faculty-and-instructors.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/cee/people/faculty-and-instructors.php",
                # CEE anchor text carries heavy post-nominals ("Louay N.
                # Mohammad, Ph.D., P.E. (WY), F. ASCE"); the engine's credential
                # stripper misses the state-license parentheticals. Names here
                # are "First Last" (never flipped), so any comma begins the
                # credential tail — cut from the first comma.
                "selectors": _block_sel(
                    "p", "a[href*='/eng/cee/people/'][href$='.php']",
                    name_strip=r",.*$"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "BAE",
            "name": "Department of Biological and Agricultural Engineering",
            "majors": ["Biological Engineering", "Biological and Agricultural Engineering"],
            "directory_url": "https://www.lsu.edu/eng/bae/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/bae/people/faculty/index.php",
                "selectors": _block_sel(
                    "div.col-lg-3",
                    "a[href*='/eng/bae/people/faculty/'][href$='.php']"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "PETE",
            "name": "Craft & Hawkins Department of Petroleum Engineering",
            "majors": ["Petroleum Engineering"],
            "directory_url": "https://www.lsu.edu/eng/pete/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/pete/people/faculty/index.php",
                # Not div.faculty-entry: PETE's wrappers are malformed (three are
                # empty, others swallow the next person), so key on the right-hand
                # text column, which is exactly one per person.
                "selectors": _block_sel("div.col-lg-7", "h3", link="a.btn-purple"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "CM",
            "name": "Bert S. Turner Department of Construction Management",
            "majors": ["Construction Management"],
            "directory_url": "https://www.lsu.edu/eng/cm/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/eng/cm/people/faculty/index.php",
                # Names carry credential tails ("Berryman, Ph.D., CPC") and are
                # "First Last", so cut from the first comma. The :not() keeps the
                # section-nav "Faculty" link (…/faculty/index.php) from becoming
                # a person.
                "selectors": _block_sel(
                    "div.col-md-6",
                    "a[href*='/eng/cm/people/faculty/'][href$='.php']"
                    ":not([href$='index.php'])",
                    name_strip=r",.*$"),
                "ladder_filter": _LADDER,
            },
        },
        # ================= College of Science ==============================
        {
            "short": "CHEM",
            "name": "Department of Chemistry",
            "majors": ["Chemistry", "Biochemistry"],
            "directory_url": "https://www.lsu.edu/science/chemistry/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/science/chemistry/faculty/index.php",
                "selectors": _table_sel(research=7,
                                        link="td:nth-of-type(1) a[href$='.php']"),
                "section_filter": {"heading": "h2", "exclude": r"Emeritus|Adjunct|Gratis"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "BIOSCI",
            "name": "Department of Biological Sciences",
            "majors": ["Biological Sciences", "Biology", "Microbiology"],
            "directory_url": "https://www.lsu.edu/science/biosci/faculty-and-staff/faculty.php",
            "scrape": {
                "url": "https://www.lsu.edu/science/biosci/faculty-and-staff/faculty.php",
                "selectors": _table_sel(link="td:nth-of-type(1) a[href$='.php']"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "PHYS",
            "name": "Department of Physics and Astronomy",
            "majors": ["Physics", "Astronomy", "Medical Physics"],
            "directory_url": "https://www.lsu.edu/physics/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/physics/people/faculty/index.php",
                "selectors": {
                    # Scope to the active-faculty table (div.col-md-12 > table);
                    # the second (div.table-responsive) table is mostly emeriti.
                    "card": "div.col-md-12 > table tr",
                    "name": "td a[href*='/people/faculty/']",
                    "title_re": _TITLE_RE,
                    "email": _MAILTO,
                },
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "GEOL",
            "name": "Department of Geology and Geophysics",
            "majors": ["Geology", "Geophysics", "Environmental Geology"],
            "directory_url": "https://www.lsu.edu/science/geology/people/faculty.php",
            "scrape": {
                "url": "https://www.lsu.edu/science/geology/people/faculty.php",
                "selectors": _table_sel(link="td:nth-of-type(1) a"),
                # Three tables: "Professors & Instructors", then Emeritus and
                # Adjunct rosters whose columns don't even line up (their second
                # cell is a phone number).
                "section_filter": {"heading": "h2",
                                   "exclude": r"Emeritus|Adjunct|Retired"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "MATH",
            "name": "Department of Mathematics",
            "majors": ["Mathematics"],
            "directory_url": "https://www.math.lsu.edu/people/professors",
            "scrape": {
                "url": "https://www.math.lsu.edu/people/professors",
                "selectors": {
                    "card": "div.personalinfo",
                    "name": "span[style*='larger']",
                    "link": "a[href*='/~']",
                    "title_re": _TITLE_RE,
                    "research_re": r"Research interest[s]?:\s*</span>\s*(.*?)\s*<br",
                    "email": _MAILTO,
                },
                "ladder_filter": _LADDER,
            },
        },
        # ================= E. J. Ourso College of Business =================
        _business("ACCT", "Department of Accounting", ["Accounting"], "accounting"),
        _business("FIN", "Department of Finance",
                  ["Finance", "Financial Economics"], "finance"),
        _business("ECON", "Department of Economics",
                  ["Economics", "International Trade and Finance"], "economics"),
        _business("MGT", "Rucks Department of Management",
                  ["Management", "Human Resource Management"], "management"),
        _business("MKT", "Department of Marketing", ["Marketing"], "marketing"),
        _business("SDEIS", "Stephenson Department of Entrepreneurship and Information Systems",
                  ["Information Systems and Decision Sciences", "Entrepreneurship",
                   "Business Analytics"], "sdeis"),
        # ========= College of Humanities & Social Sciences =================
        {
            "short": "PSYC",
            "name": "Department of Psychology",
            "majors": ["Psychology", "Behavioral Neuroscience"],
            "directory_url": "https://www.lsu.edu/hss/psychology/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/psychology/faculty/index.php",
                # Bare link list grouped by research area: the anchor text is
                # "Name, Rank" (title_re lifts the rank, name_strip cuts it off
                # the name) and no address appears anywhere on the page.
                "selectors": _block_sel(
                    "p",
                    "a[href*='/hss/psychology/faculty/'][href$='.php']"
                    ":not([href$='index.php'])",
                    name_strip=r",.*$"),
                "link_filter": r"/hss/psychology/faculty/",
                "section_filter": {"heading": "h2",
                                   "exclude": r"Retired|In Memoriam"},
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "always": True,
                    "email_selector": _MAILTO,
                    "email_drop": r"^psychology@",
                    "throttle": 0.2,
                },
            },
        },
        {
            "short": "POLI",
            "name": "Department of Political Science",
            "majors": ["Political Science", "International Studies"],
            "directory_url": "https://www.lsu.edu/hss/polisci/faculty_and_staff/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/polisci/faculty_and_staff/index.php",
                "selectors": _block_sel(
                    "p", "a[href*='/faculty_and_staff/'][href$='.php']"),
                "section_filter": {"heading": "h2", "exclude": r"Retired|Staff"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "ENGL",
            "name": "Department of English",
            "majors": ["English", "Creative Writing", "Film and Media Arts"],
            "directory_url": "https://www.lsu.edu/hss/english/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/english/faculty/index.php",
                "selectors": _block_sel(
                    "div.col-md-3", "a[href*='/english/faculty/']"),
                "section_filter": {"heading": "h2",
                                   "exclude": r"Front Desk|Emeritus"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "HIST",
            "name": "Department of History",
            "majors": ["History"],
            "directory_url": "https://www.lsu.edu/hss/history/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/history/people/faculty/index.php",
                "selectors": _block_sel(
                    "div.col-md-4", "p strong",
                    link="a[href*='/people/faculty/']"),
                "section_filter": {"heading": "h2", "exclude": r"Retired"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "SOCI",
            "name": "Department of Sociology",
            "majors": ["Sociology"],
            "directory_url": "https://www.lsu.edu/hss/sociology/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/sociology/people/faculty/index.php",
                # Sociology writes the address as plain text ("Email: troy@lsu.edu")
                # on about half the cards rather than a mailto, so the email
                # selector points at the labelled <p> and lets _clean_email pull
                # the address out of its text.
                "selectors": _block_sel(
                    "div.col-md-6", "p.lead a",
                    email="p:-soup-contains('Email')"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "CMST",
            "name": "Department of Communication Studies",
            "majors": ["Communication Studies"],
            "directory_url": "https://www.lsu.edu/hss/cmst/people/faculty/1facultylist.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/cmst/people/faculty/1facultylist.php",
                "selectors": _table_sel(link="td:nth-of-type(1) a"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "PRS",
            "name": "Department of Philosophy and Religious Studies",
            "majors": ["Philosophy", "Religious Studies"],
            "directory_url": "https://www.lsu.edu/hss/prs/people/faculty.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/prs/people/faculty.php",
                # Each person is a table ROW whose second cell holds the name
                # (p.lead) and rank — not a columnar table, so the block helper.
                "selectors": _block_sel("tr", "p.lead a"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "COMD",
            "name": "Department of Communication Sciences and Disorders",
            "majors": ["Communication Sciences and Disorders", "Speech-Language Pathology"],
            "directory_url": "https://www.lsu.edu/hss/comd/people_new_website/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/comd/people_new_website/index.php",
                # Photo-grid built out of table cells: one <td> per person.
                "selectors": _block_sel("td", "a[href*='/comd/']"),
                "section_filter": {"heading": "h2",
                                   "exclude": r"Emeritus|Professional Staff"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "WLLC",
            "name": "Department of World Languages, Literatures and Cultures",
            "majors": ["Spanish", "German", "Italian", "Classical Studies",
                       "World Languages"],
            "directory_url": "https://www.lsu.edu/hss/wllc/faculty/faculty-name.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/wllc/faculty/faculty-name.php",
                "selectors": _table_sel(link="td:nth-of-type(1) a"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "FREN",
            "name": "Department of French Studies",
            "majors": ["French", "Francophone Studies"],
            "directory_url": "https://www.lsu.edu/hss/french/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/hss/french/people/faculty/index.php",
                # Name cell is bare text (no profile anchor anywhere in the table).
                "selectors": _table_sel(),
                "section_filter": {"heading": "h2", "exclude": r"Emeritus"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "GA",
            "name": "Department of Geography and Anthropology",
            "majors": ["Geography", "Anthropology"],
            "directory_url": "https://www.lsu.edu/ga/people/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/ga/people/faculty/index.php",
                "selectors": _block_sel(
                    "div.col-md-3", "a[href*='/ga/people/faculty/']",
                    research="em"),
                "section_filter": {"heading": "h2", "exclude": r"Emeriti|Adjunct"},
                "ladder_filter": _LADDER,
            },
        },
        # ================= College of Agriculture ==========================
        {
            "short": "ANSC",
            "name": "School of Animal Sciences",
            "majors": ["Animal Sciences", "Dairy Science", "Poultry Science"],
            "directory_url": "https://www.lsu.edu/agriculture/animal-sciences/people/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/agriculture/animal-sciences/people/index.php",
                "selectors": _table_sel(research=3),
                "name_flip": True,
                "section_filter": {"heading": "h2",
                                   "exclude": r"Emeritus|Staff|Graduate"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "SPESS",
            "name": "School of Plant, Environmental and Soil Sciences",
            "majors": ["Plant and Soil Systems", "Environmental Management Systems",
                       "Horticulture", "Agronomy"],
            "directory_url": "https://www.lsu.edu/agriculture/spess/people/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/agriculture/spess/people/index.php",
                "selectors": _table_sel(research=3, link="td:nth-of-type(1) a"),
                "name_flip": True,
                "section_filter": {
                    "heading": "h2",
                    "exclude": r"Emeritus|Staff|Graduate|Affiliated|Research/Extension",
                },
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "AGEC",
            "name": "Department of Agricultural Economics and Agribusiness",
            "majors": ["Agricultural Economics", "Agribusiness"],
            "directory_url": "https://www.lsu.edu/agriculture/agecon/people/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/agriculture/agecon/people/index.php",
                "selectors": _table_sel(research=3, link="td:nth-of-type(1) a"),
                "name_flip": True,
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "ENTM",
            "name": "Department of Entomology",
            "majors": ["Entomology", "Pest Management"],
            "directory_url": "https://www.lsu.edu/agriculture/entomology/people/",
            "scrape": {
                "url": "https://www.lsu.edu/agriculture/entomology/people/",
                # Names are "First Last" here (unlike the other AgCenter tables).
                "selectors": _table_sel(research=3),
                "section_filter": {"heading": "h2", "exclude": r"Research Associates"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "NFS",
            "name": "School of Nutrition and Food Sciences",
            "majors": ["Nutrition and Food Sciences", "Food Science", "Dietetics"],
            "directory_url": "https://www.lsu.edu/agriculture/nfs/people/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/agriculture/nfs/people/index.php",
                # Address sits in its own column as bare text, not a mailto.
                "selectors": _table_sel(email=3, research=6),
                "name_flip": True,
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "RNR",
            "name": "School of Renewable Natural Resources",
            "majors": ["Natural Resource Ecology and Management", "Forestry",
                       "Wildlife Ecology", "Fisheries"],
            "directory_url": "https://www.lsu.edu/agriculture/rnr/people/faculty-staff.php",
            "scrape": {
                "url": "https://www.lsu.edu/agriculture/rnr/people/faculty-staff.php",
                # Photo / Name / Title / Expertise — no address column at all;
                # each profile page carries it as its first mailto.
                "selectors": _table_sel(name=2, title=3, research=4,
                                        link="td:nth-of-type(2) a"),
                "link_filter": r"/people/profiles/",
                "section_filter": {"heading": "h2",
                                   "exclude": r"Staff|Emeritus|Retired"},
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "always": True,
                    "email_selector": _MAILTO,
                    "email_drop": r"^druther@",
                    "throttle": 0.2,
                },
            },
        },
        # ========= Manship School of Mass Communication ====================
        {
            "short": "MC",
            "name": "Manship School of Mass Communication",
            "majors": ["Mass Communication", "Digital Advertising",
                       "Public Relations", "Journalism", "Political Communication"],
            "directory_url": "https://www.lsu.edu/manship/about/who-we-are/faculty/faculty/index.php",
            "scrape": {
                "url": "https://www.lsu.edu/manship/about/who-we-are/faculty/faculty/index.php",
                # The rank IS an element here (the first <p> under the name), so
                # pass it as `title`. The page also carries a four-card
                # "Area Heads" col-lg-3 teaser whose cards show the area instead
                # of a rank — keying on col-lg-7 skips it (those four people are
                # all listed again, ranked, in the main roster).
                "selectors": _block_sel("div.col-lg-7.py-3", "h4",
                                        link="a.btn-purple", title="p"),
                "section_filter": {"heading": "h2", "exclude": r"Emeritus"},
                "ladder_filter": _LADDER,
            },
        },
        # ================= College of Art & Design =========================
        {
            "short": "ARCH",
            "name": "School of Architecture",
            "majors": ["Architecture"],
            "directory_url": "https://design.lsu.edu/architecture/people/",
            "scrape": {
                "url": "https://design.lsu.edu/architecture/people/",
                "selectors": _design_sel("architecture"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "ART",
            "name": "School of Art",
            "majors": ["Studio Art", "Graphic Design", "Digital Art", "Art History"],
            "directory_url": "https://design.lsu.edu/art/people/",
            "scrape": {
                "url": "https://design.lsu.edu/art/people/",
                "selectors": _design_sel("art"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "INTD",
            "name": "School of Interior Design",
            "majors": ["Interior Design"],
            "directory_url": "https://design.lsu.edu/interior-design/people/",
            "scrape": {
                "url": "https://design.lsu.edu/interior-design/people/",
                "selectors": _design_sel("interior-design"),
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "LARC",
            "name": "Robert Reich School of Landscape Architecture",
            "majors": ["Landscape Architecture"],
            "directory_url": "https://design.lsu.edu/landscape-architecture/people/",
            "scrape": {
                "url": "https://design.lsu.edu/landscape-architecture/people/",
                "selectors": _design_sel("landscape-architecture"),
                "ladder_filter": _LADDER,
            },
        },
        # ========= College of the Coast & Environment ======================
        # One college-wide roster with a department code cell (DOCS / DES /
        # CC&E), so a field_filter splits it into the two academic departments.
        {
            "short": "DOCS",
            "name": "Department of Oceanography and Coastal Sciences",
            "majors": ["Coastal Environmental Science", "Oceanography"],
            "directory_url": "https://www.lsu.edu/cce/about/cce-directories/all-staff-directory.php",
            "scrape": {
                "url": "https://www.lsu.edu/cce/about/cce-directories/all-staff-directory.php",
                # Surname and given name live in separate columns.
                "selectors": dict(_table_sel(name=2, title=3, email=6),
                                  name_last="td:nth-of-type(1)"),
                "field_filter": {"selector": "td:nth-of-type(4)", "include": r"^DOCS$"},
                "ladder_filter": _LADDER,
            },
        },
        {
            "short": "DES",
            "name": "Department of Environmental Sciences",
            "majors": ["Environmental Science", "Environmental Management Systems"],
            "directory_url": "https://www.lsu.edu/cce/about/cce-directories/all-staff-directory.php",
            "scrape": {
                "url": "https://www.lsu.edu/cce/about/cce-directories/all-staff-directory.php",
                "selectors": dict(_table_sel(name=2, title=3, email=6),
                                  name_last="td:nth-of-type(1)"),
                "field_filter": {"selector": "td:nth-of-type(4)", "include": r"^DES$"},
                "ladder_filter": _LADDER,
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
