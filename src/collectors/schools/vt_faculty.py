"""Virginia Tech faculty config (via the faculty_graph engine).

Everything is server-rendered Adobe AEM (no WAF, no render mode anywhere;
~60 recon fetches all clean 200s). Four markup families, live-verified
2026-07-18:

* ``vt_list`` — the AEM "vt-list" bio-card component shared by most VT dept
  sites (Engineering, Pamplin, CALS, the liberalarts.vt.edu CLAHS hub, SPIA,
  Architecture, and the College of Science card sites). Cards are
  ``.vt-list-item-wrapper`` filtered to ``data-itemtype="bio"`` headings (the
  ME page prepends news-article cards; CEE's custom PHP webapp mimics the
  markup WITHOUT the bio heading, so its card selector stays bare). Several
  pages repeat people across By-Research-Area/Location sections (BEAM 459→122,
  chem 129→41, ENGL 243→97) — the engine's id/url dedupe collapses them. The
  description slot varies by dept: a plain rank (CS/ME/MSE), rank + email
  (ISE, the CLAHS depts), rank + colon + research blurb (BSE/FST/HNFE/BCHM),
  research blurb only (chem), an office address (PSCI/SOC/SOE), or nothing
  (ECE/AOE/ChE/BIT/HTM) — per-dept title/email/research selectors below.
  Role-mixed rosters gate by h2 section (BEAM/FIN/MGMT/HTM/NEUR) and/or by
  title regex; CS's ~15 courtesy professors live under
  ``/courtesy-appointment-faculty/`` and are link-filtered out.

* ``vt_grid`` — hand-built AEM "vt-multicolumn" photo grids, one bespoke
  selector set per dept: PHYS (``vt-phys-people-id``/``-contact`` cells,
  h2-sectioned with Adjunct/Emeriti siblings), STAT (h2-name + mailto rows),
  ENGE (one ``vt-text`` per person: name link + ", Rank |" + Gmail-compose
  email link — the email selector reads the cell TEXT), AAEC (figcaption
  cards "Name, Rank | Expertise: …"), GEOG (vt-col cells with an
  "Expertise:" block), FREC (h3-sectioned vt-text blocks whose <br>-separated
  tail lines are clean research keywords), SBIO (vt-col cells under the
  "Department Head" h2; the Post-Doctoral Scholars / Emeritus sections that
  follow are section-gated out).

* ``vt_table`` — plain HTML tables: BIOL (Name|Office|Phone|Email|Title, one
  table, "Last, First" names) and ENTO (Name|Discipline|Title|Contact, three
  h2-sectioned tables — only the "Faculty" one kept; the Discipline column is
  a clean research area).

* ``psyc_drupal`` — Psychology lives on support.psyc.vt.edu (Drupal): one
  /users page of h1-sectioned tables (Chair + Faculty kept; Affiliated/Staff/
  Grad Students dropped). Names are "Last , First"; email is a plain-text
  column. No rank or research anywhere on profiles.

Profiles: every AEM profile carries a plain mailto and a clean rank in
``.vt-bio-title`` (verified across CS/ECE/ME/MATH/SPES/BCHM/STAT/HTM/CEE/
AAEC/FREC) → the env-gated profile pass backfills email + authoritative
title everywhere. Clean per-profile research lists exist on CS/ME/MATH
("Research interests" h3 + ul) and SPES ("Expertise" h4 + ul). HTM's
directory mixes staff into its faculty section with no listing titles, so
HTM alone runs an ALWAYS-on profile pass with a require-professor recheck.

Single source ("vt_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred (2026-07-18 recon + this pass):
* ACIS (Pamplin Accounting & IS) — directory page is a contact-info card
  only; no parseable public faculty listing found.
* Economics (College of Science) — hand-built page of bare h2 names with no
  titles/emails; profiles are often just a CV PDF — accuracy-poor.
* Fish and Wildlife Conservation (CNRE) — grid packs several people per
  column cell; needs bespoke sub-splitting the engine doesn't do.
* ECE per-profile research — the "Research Interests" vt-tab panel joins its
  button by aria-controls id; the panel is empty in the static HTML on the
  profiles probed, and the engine's single-group research_html_re can't
  express the id join. Email+title enrich only; topics come from OpenAlex.
* CLAHS remaining depts (Communication, Religion & Culture, HDFS, Modern
  Languages, Philosophy, STS, Theatre/Cinema) — same liberalarts hub family,
  pages not fetched/verified this session.
* AAD remaining units (Myers-Lawson Construction, Design, Performing Arts,
  Visual Arts, Landscape Architecture) — directory paths not located yet.
* Academy of Integrated Science (CMDA/Nanoscience/Systems Biology) — not
  probed.
* Virginia-Maryland College of Veterinary Medicine + VT Carilion School of
  Medicine — clinical faculty needing their own gate; out of scope.
* Honors College / Hume Center — program units, covered on the campus side.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- vt_list (AEM bio-card) shared pieces ----------------------------------
_BIO_CARD = '.vt-list-item-wrapper:has(.vt-list-item-heading[data-itemtype="bio"])'
_DESC = "p.vt-list-item-description"

# Trailing sr-only ", bio"/", redirect" rides every card's name anchor; a few
# names also carry a ", P.E." licensure suffix the engine's credential
# stripper doesn't know.
_NAME_TAIL = r"\s*,\s*(?:bio|redirect)\s*$|\s*,\s*P\.?\s?E\.?(?=\s*,|\s*$)"

# "Research Associate Professor" is a real PI rank — the lookahead keeps it
# while plain research-staff titles drop.
_DROP = (r"emerit|adjunct|affiliat|courtesy|by affiliation|visiting|postdoc"
         r"|research (?:associate|assistant|scientist)(?!\s+professor)")
_LADDER = {"drop": _DROP}
_LADDER_REQ = {"require": r"professor|instructor|lecturer", "drop": _DROP}

# Rank extractor for grids whose title is loose text near the name (PHYS/
# ENGE/AAEC/GEOG/FREC). Case-sensitive by engine design — ranks are Titled.
_TITLE_RE = (r"\b((?:University Distinguished\s+|Department Chair and\s+)?"
             r"(?:Research\s+|Associate\s+|Assistant\s+|Collegiate\s+|Visiting\s+|Adjunct\s+)*"
             r"(?:Professor|Instructor|Lecturer)"
             r"(?:\s+(?:of|in)\s+[A-Z][A-Za-z&, ]{2,40})?(?:\s+Emerit[a-z]+)?"
             r"|Department Head)")

# "Rank: research blurb" descriptions (BSE/FST/HNFE/BCHM) — capture after the
# first colon or an inline "Research Area-" label.
_COLON_RESEARCH_RE = (r"vt-list-item-description[^>]*>\s*[^:<]{0,120}?"
                      r"(?:Research\s+Areas?\s*[-–—:]|:)\s*([^<]{3,400})")

# Grid cells with an inline "<strong>Expertise:</strong>/<strong>Research
# Interests:</strong>" label (GEOG/SBIO).
_EXPERTISE_RE = (r"(?:Expertise|Research\s+Interests)\s*:?\s*</strong>\s*"
                 r"(?:<br[^>]*>\s*)?:?\s*([^<]{3,400})")

# The description element only when it actually carries an address — a bare
# selector would make _clean_email return office-address TEXT as the email on
# cards without one (SOE has such rows).
_DESC_EMAIL = 'p.vt-list-item-description:-soup-contains("@vt.edu")'

# Drop dept aliases the enrich pass may hit first: self-named boxes
# (math@math.vt.edu, frec@frec.vt.edu) and shared-office prefixes.
_EMAIL_DROP = (r"^[^@]*$|^([a-z]+)@\1\."
               r"|^(?:info|contact|office|admin|web|dept|advising|undergrad|htmdpt)@")

# Every AEM profile publishes a plain mailto + a clean ".vt-bio-title" rank —
# the env-gated pass backfills both; the drop-only recheck prunes any emeriti
# the authoritative profile title reveals.
_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "email_drop": _EMAIL_DROP,
    "title_selector": ".vt-bio-title",
    "ladder_recheck": _LADDER,
    "throttle": 0.2,
}
# CS lowercases "Research interests", ME/MATH title-case it.
_ENRICH_RESEARCH = {**_ENRICH, "research_items_selector": (
    'h3:-soup-contains("Research interests") + ul > li, '
    'h3:-soup-contains("Research Interests") + ul > li')}
_ENRICH_EXPERTISE = {**_ENRICH, "research_items_selector":
                     'h4:-soup-contains("Expertise") + ul > li'}


def _lst(short: str, name: str, majors: list[str], url: str, *,
         desc_title: bool = False, title_strip: str | None = None,
         desc_email: bool = False, desc_research: bool = False,
         research_re: str | None = None, ladder: dict = _LADDER,
         section: dict | None = None, link_filter: str | None = None,
         name_flip: bool = False, card: str = _BIO_CARD,
         enrich: dict | None = _ENRICH) -> dict:
    """A department on the shared AEM vt-list bio-card component."""
    sel: dict = {"card": card, "name": "a.vt-list-item-title-link",
                 "name_strip": _NAME_TAIL, "link": "a.vt-list-item-title-link"}
    if desc_title:
        sel["title"] = _DESC
    if title_strip:
        sel["title_strip_after"] = title_strip
    if desc_email:
        sel["email"] = _DESC_EMAIL
    if desc_research:
        sel["research"] = _DESC
    if research_re:
        sel["research_re"] = research_re
    scrape: dict = {"url": url, "selectors": sel, "ladder_filter": ladder}
    if section:
        scrape["section_filter"] = section
    if link_filter:
        scrape["link_filter"] = link_filter
    if name_flip:
        scrape["name_flip"] = True
    if enrich:
        scrape["profile_enrich"] = enrich
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": scrape}


def _grid(short: str, name: str, majors: list[str], url: str, sel: dict, *,
          section: dict | None = None, ladder: dict = _LADDER,
          enrich: dict | None = _ENRICH, name_flip: bool = False) -> dict:
    """A hand-built vt-multicolumn grid dept (bespoke selectors per dept)."""
    scrape: dict = {"url": url, "selectors": sel, "ladder_filter": ladder}
    if section:
        scrape["section_filter"] = section
    if name_flip:
        scrape["name_flip"] = True
    if enrich:
        scrape["profile_enrich"] = enrich
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": scrape}


SCHOOL: dict = {
    "school_slug": "vt",
    "source": "vt_faculty",
    "organization": "Virginia Tech",
    "location": "Blacksburg, VA",
    "id_prefix": "vt",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Virginia Tech) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering ----------------------------------------
        _lst("CS", "Department of Computer Science", ["Computer Science"],
             "https://cs.vt.edu/people/faculty.html",
             desc_title=True, enrich=_ENRICH_RESEARCH,
             link_filter=r"/people/faculty/(?!courtesy-appointment-faculty/)"),
        _lst("ECE", "Bradley Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"],
             "https://ece.vt.edu/people/faculty.html"),
        _lst("ME", "Department of Mechanical Engineering", ["Mechanical Engineering"],
             "https://me.vt.edu/people/faculty.html",
             desc_title=True, enrich=_ENRICH_RESEARCH),
        _lst("AOE", "Kevin T. Crofton Department of Aerospace and Ocean Engineering",
             ["Aerospace Engineering", "Ocean Engineering"],
             "https://www.aoe.vt.edu/people/faculty.html"),
        _lst("BEAM", "Department of Biomedical Engineering and Mechanics",
             ["Biomedical Engineering", "Engineering Mechanics"],
             "https://bme.vt.edu/people/faculty.html",
             # Keep the BME core roster + the SBES members based at VT
             # Blacksburg; Wake Forest / Roanoke / emeritus sections excluded.
             section={"heading": "h2",
                      "include": (r"^bme teaching and research faculty$"
                                  r"|^virginia tech main campus")}),
        _lst("MSE", "Department of Materials Science and Engineering",
             ["Materials Science and Engineering"],
             "https://mse.vt.edu/faculty-staff/Faculty.html",
             desc_title=True, link_filter=r"mse\.vt\.edu"),
        _lst("ChE", "Department of Chemical Engineering", ["Chemical Engineering"],
             "https://che.vt.edu/People/faculty.html"),
        _lst("CEE", "Charles E. Via Jr. Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"],
             "https://www.webapps.cee.vt.edu/index.php?category=people&item=faculty&do=listing",
             desc_title=True, card=".vt-list-item-wrapper"),
        _lst("ISE", "Grado Department of Industrial and Systems Engineering",
             ["Industrial and Systems Engineering"],
             "https://www.ise.vt.edu/people/faculty.html",
             desc_title=True, title_strip=r"\s*\|", desc_email=True),
        _lst("MINE", "Department of Mining and Minerals Engineering",
             ["Mining Engineering"],
             "https://www.mining.vt.edu/people/faculty.html", desc_title=True),
        _lst("BSE", "Department of Biological Systems Engineering",
             ["Biological Systems Engineering", "Environmental Science"],
             "https://www.bse.vt.edu/about/people/faculty.html",
             desc_title=True, title_strip=r"[:\r\n]",
             research_re=_COLON_RESEARCH_RE),
        _grid("ENGE", "Department of Engineering Education",
              ["Engineering Education", "General Engineering"],
              "https://enge.vt.edu/People.html",
              {"card": "div.vt-text:has(p strong a)", "name": "p strong a",
               "link": "p strong a", "title_re": _TITLE_RE,
               # Emails are Gmail-compose links whose address survives only in
               # the cell TEXT — read the paragraph, not the anchor href.
               "email": 'p:-soup-contains("@vt.edu")'}),
        # ---- College of Science --------------------------------------------
        _lst("CHEM", "Department of Chemistry", ["Chemistry"],
             "https://chem.vt.edu/people/faculty.html", desc_research=True),
        _lst("MATH", "Department of Mathematics", ["Mathematics"],
             "https://math.vt.edu/people/faculty.html", enrich=_ENRICH_RESEARCH),
        _grid("PHYS", "Department of Physics", ["Physics"],
              "https://www.phys.vt.edu/About/people/Faculty.html",
              {"card": "div.vt-multicolumn.vt-phys-people-row",
               "name": ".vt-phys-people-id a", "link": ".vt-phys-people-id a",
               "title_re": _TITLE_RE,
               "email": ".vt-phys-people-contact a[href^='mailto:']"},
              section={"heading": "h2",
                       "include": r"^(?:department chair|associate chair|faculty)$"}),
        _grid("STAT", "Department of Statistics", ["Statistics"],
              "https://www.stat.vt.edu/people/stat-faculty.html",
              {"card": "div.vt-multicolumn", "name": "h2 a", "link": "h2 a",
               "email": "a[href^='mailto:']"}),
        {
            "short": "BIOL", "name": "Department of Biological Sciences",
            "majors": ["Biological Sciences", "Biology"],
            "directory_url": "https://www.biol.vt.edu/People/Faculty.html",
            "scrape": {
                "url": "https://www.biol.vt.edu/People/Faculty.html",
                # Some real faculty have no profile link, so the name is the
                # whole cell; a trailing legend row (building/fax/mail-code
                # abbreviations) is rejected by the engine's name-length guard.
                "selectors": {"card": "table tr", "name": "td:nth-of-type(1)",
                              "link": "td:nth-of-type(1) a[href*='.html']",
                              "email": "td:nth-of-type(4)",
                              "title": "td:nth-of-type(5)"},
                "name_flip": True,
                "ladder_filter": _LADDER_REQ,
            },
        },
        {
            # Drupal at support.psyc.vt.edu/users: five h1-sectioned tables
            # (Chair / Faculty / Affiliated Faculty / Staff / Grad Students).
            # No title column, so section_filter on the h1 is the ladder gate —
            # keep Chair + Faculty only. Name is "Last , First"; email col 2.
            "short": "PSYC", "name": "Department of Psychology",
            "majors": ["Psychology"],
            "directory_url": "https://support.psyc.vt.edu/users",
            "scrape": {
                "url": "https://support.psyc.vt.edu/users",
                "selectors": {"card": "table tr", "name": "td:nth-of-type(1)",
                              "link": "td:nth-of-type(1) a",
                              "email": "td:nth-of-type(2) a[href^='mailto:'], td:nth-of-type(2)"},
                "name_flip": True,
                "section_filter": {"heading": "h1", "include": r"^(?:chair|faculty)$"},
            },
        },
        _lst("GEOS", "Department of Geosciences", ["Geosciences", "Geology"],
             "https://geos.vt.edu/people/faculty.html",
             desc_title=True, name_flip=True),
        _lst("NEUR", "School of Neuroscience", ["Neuroscience"],
             "https://neuroscience.vt.edu/our-people.html",
             section={"heading": "h3",
                      "include": r"^(?:research|instructional) faculty$"}),
        # ---- Pamplin College of Business -----------------------------------
        _lst("MKTG", "Department of Marketing", ["Marketing", "Business"],
             "https://marketing.pamplin.vt.edu/people/faculty.html",
             desc_title=True, ladder=_LADDER_REQ),
        _lst("BIT", "Department of Business Information Technology",
             ["Business Information Technology", "Information Systems"],
             "https://bit.vt.edu/faculty/directory.html"),
        _lst("FIN", "Department of Finance, Insurance, and Business Law",
             ["Finance", "Real Estate"],
             "https://finance.pamplin.vt.edu/faculty/directory.html",
             section={"heading": "h2",
                      "include": r"^(?:leadership|full-time faculty)$"}),
        _lst("MGMT", "Department of Management", ["Management", "Business"],
             "https://management.pamplin.vt.edu/faculty/directory.html",
             desc_title=True,
             section={"heading": "h2",
                      "include": (r"^(?:full-time tenure track faculty"
                                  r"|collegiate faculty|professor of practice"
                                  r"|instructors)$")}),
        _lst("HTM", "Howard Feiertag Department of Hospitality and Tourism Management",
             ["Hospitality and Tourism Management"],
             "https://htm.pamplin.vt.edu/directory.html",
             # The faculty section mixes staff with no listing titles — the
             # always-on profile pass reads .vt-bio-title and require-gates.
             section={"heading": "h2",
                      "include": r"^department head$|^htm faculty\s*&\s*staff$"},
             enrich={**_ENRICH, "always": True, "ladder_recheck": _LADDER_REQ}),
        # ---- College of Agriculture and Life Sciences ----------------------
        _grid("AAEC", "Department of Agricultural and Applied Economics",
              ["Agricultural and Applied Economics", "Agribusiness"],
              "https://aaec.vt.edu/people/faculty.html",
              {"card": "figure:has(figcaption.vt-image-caption):has(a.vt-image-link)",
               "name": "figcaption.vt-image-caption", "name_strip": r",.*$",
               "link": "a.vt-image-link", "title_re": _TITLE_RE,
               "research_re": r"Expertise:\s*([^<]{3,400})"}),
        _lst("SAS", "School of Animal Sciences",
             ["Animal and Poultry Sciences", "Animal Science"],
             "https://sas.vt.edu/people/faculty.html",
             desc_title=True, ladder=_LADDER_REQ),
        {
            "short": "ENTO", "name": "Department of Entomology",
            "majors": ["Entomology", "Biological Sciences"],
            "directory_url": "https://www.ento.vt.edu/people/Faculty0.html",
            "scrape": {
                "url": "https://www.ento.vt.edu/people/Faculty0.html",
                "selectors": {"card": "table tr", "name": "td:nth-of-type(1)",
                              "link": "td:nth-of-type(1) a[href*='.html']",
                              "research": "td:nth-of-type(2)",
                              "title": "td:nth-of-type(3)",
                              "email": "td:nth-of-type(4)"},
                "section_filter": {"heading": "h2", "include": r"^faculty$"},
                "ladder_filter": _LADDER_REQ,
            },
        },
        _lst("FST", "Department of Food Science and Technology",
             ["Food Science and Technology"],
             "https://www.fst.vt.edu/about/faculty-and-staff.html",
             desc_title=True, title_strip=r"[:\r\n]",
             research_re=_COLON_RESEARCH_RE, ladder=_LADDER_REQ),
        _lst("HNFE", "Department of Human Nutrition, Foods, and Exercise",
             ["Human Nutrition, Foods, and Exercise"],
             "https://www.hnfe.vt.edu/people/faculty.html",
             desc_title=True, title_strip=r"[:\r\n]",
             research_re=_COLON_RESEARCH_RE),
        _lst("SPES", "School of Plant and Environmental Sciences",
             ["Plant Science", "Environmental Science"],
             "https://spes.vt.edu/faculty-staff.html", enrich=_ENRICH_EXPERTISE),
        _lst("BCHM", "Department of Biochemistry", ["Biochemistry"],
             "https://www.biochem.vt.edu/people/faculty.html",
             desc_title=True, title_strip=r"[:\r\n]",
             research_re=_COLON_RESEARCH_RE),
        # ---- College of Natural Resources and Environment ------------------
        _grid("FREC", "Department of Forest Resources and Environmental Conservation",
              ["Forestry", "Environmental Resources Management"],
              "https://frec.vt.edu/people/Faculty.html",
              {"card": "div.vt-text:has(p strong)", "name": "p strong",
               "link": "a[href*='.html']", "title_re": _TITLE_RE,
               "email": "a[href^='mailto:']",
               # The <br>-separated tail lines after the rank are clean
               # research keywords ("forest operations", "water policy").
               "research_re": (r"(?:Professor|Instructor|Lecturer|Specialist|Head)"
                               r"[^<]*((?:<br[^>]*/?>\s*[^<]+)+)")},
              section={"heading": "h3", "include": r"faculty$"}),
        _grid("GEOG", "Department of Geography", ["Geography", "Meteorology"],
              "https://geography.vt.edu/people/faculty.html",
              {"card": "div.vt-col:has(p a strong), div.vt-col:has(p strong a)",
               "name": "p a strong, p strong a", "link": "p a[href*='.html']",
               "title_re": _TITLE_RE, "email": "a[href^='mailto:']",
               "research_re": _EXPERTISE_RE}),
        _grid("SBIO", "Department of Sustainable Biomaterials",
              ["Sustainable Biomaterials", "Packaging Systems and Design"],
              "https://sbio.vt.edu/our-people/faculty.html",
              {"card": "div.vt-col:has(p strong)", "name": "p strong",
               "link": "a[href*='.html']", "email": "a[href^='mailto:']",
               "research_re": _EXPERTISE_RE},
              # The whole faculty grid rides under the "Department Head" h2;
              # the following Post-Doctoral Scholars / Emeritus sections drop.
              section={"heading": "h2", "include": r"^department head$"}),
        # ---- College of Liberal Arts and Human Sciences --------------------
        _lst("ENGL", "Department of English", ["English", "Creative Writing"],
             "https://liberalarts.vt.edu/departments-and-schools/department-of-english/faculty.html",
             desc_title=True, title_strip=r",\s*\d", desc_email=True,
             ladder=_LADDER_REQ),
        _lst("HIST", "Department of History", ["History"],
             "https://liberalarts.vt.edu/departments-and-schools/department-of-history/faculty.html",
             desc_title=True, title_strip=r"\s*\|", desc_email=True,
             research_re=r"Specialties:\s*([^|<]{3,300})", ladder=_LADDER_REQ),
        _lst("PSCI", "Department of Political Science",
             ["Political Science", "National Security and Foreign Affairs"],
             "https://liberalarts.vt.edu/departments-and-schools/department-of-political-science/faculty.html",
             desc_email=True),
        _lst("SOC", "Department of Sociology", ["Sociology", "Criminology"],
             "https://liberalarts.vt.edu/departments-and-schools/department-of-sociology/faculty.html",
             desc_email=True),
        _lst("SOE", "School of Education", ["Education"],
             "https://liberalarts.vt.edu/departments-and-schools/school-of-education/faculty.html",
             desc_email=True),
        _lst("SPIA", "School of Public and International Affairs",
             ["Public and International Affairs", "Urban Planning"],
             "https://spia.vt.edu/people/Faculty.html",
             desc_title=True, title_strip=r"\s*\|", desc_email=True),
        # ---- College of Architecture, Arts, and Design ---------------------
        _lst("ARCH", "School of Architecture", ["Architecture"],
             "https://arch.vt.edu/people/blacksburg-campus-faculty-directory.html",
             desc_title=True),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
