"""Northeastern University faculty config (via the faculty_graph engine).

Every college runs its own directory system, but all eight families are
server-rendered or expose an open WP REST API — no WAF, no render mode
anywhere. Live-verified 2026-07-18:

* **COE unified WordPress grid** (coe.northeastern.edu, five departments via
  the ``dept`` facet): the richest listing on campus — rank, plain mailto
  email AND a comma-separated research line all on the card.
  ``?type=Faculty&dept=N&display=all`` returns the whole facet in one page.
  The parse-tree quirk: an unclosed ``<br>`` swallows the research caption as
  a DESCENDANT, so no sibling CSS selector can reach it — ``research_re``
  bounds it after the ``contact__title`` dept link instead. The Faculty facet
  still mixes co-op coordinators / affiliated faculty / deans / emeriti, so a
  require-professor + drop-emeritus ladder gate prunes them (~30/dept).

* **Khoury CS** (two sources on one dept, engine dedupes by profile URL):
  the tenured/TT roster (124) rides the server-rendered HTML archive with
  ``filters[]=people_roles|931`` (16 cards/page, ``/people/page/N/``) because
  the cards carry rank — the ladder gate drops the "Professor Emeritus" cards
  the TT term itself contains. Teaching (928) + research (926) faculty ride
  the open WP API (``wp/v2/people?people_roles=928,926``, 217) whose records
  carry NO rank/email — they land "Professor"-titled; the profile-enrich pass
  (title ``p.single-people__header-description``, plain mailto, clean
  ``/research_areas/`` link list) backfills all three + a ladder recheck.

* **College of Science JSON feed** (cos.northeastern.edu
  ``wp/v2/nucos-faculty``): best-in-class — role gate is a real taxonomy term
  (1846 = faculty; emeriti/postdocs/PhD students are separate terms, so no
  title regex needed), departments facet server-side
  (``nucos-department-categories``), and per-person research tags ride the
  ``nucos-expertise`` taxonomy as clean controlled vocabulary. COS-Other
  catches the small programs (biochem/bioinformatics/biotech/linguistics/BNS)
  by excluding the six big dept terms client-side.

* **CSSH basic-grid** (cssh.northeastern.edu/faculty/, all social-science /
  humanities units in one 27-page directory): full rank+discipline title on
  every card ("Associate Professor of Political Science") — the discipline IS
  the research signal; profiles have NO structured research list (prose bios,
  not comma-splittable). Profile emails are Cloudflare-obfuscated
  ``data-cfemail`` — the FIRST one on the page is the person (later ones are
  dept inboxes like CSSHDean@), which is exactly what ``select_one`` takes.

* **Bouvé faculty-cards** (bouve.northeastern.edu/directory/,
  ``role[]=faculty``, 23 pages): schema.org Person cards with the job title
  in ``span[itemprop=jobTitle]`` and the email as a
  ``/cdn-cgi/l/email-protection#HEX`` link ON the listing card (the engine's
  cfemail decoder reads the href form). Profile "Research Interests" are
  prose paragraphs — poison, not scraped.

* **D'Amore-McKim person-lines** (damore-mckim.northeastern.edu/people/,
  ``?query-1-page=N``, 28 pages): rank + business-group line ("Professor,
  Supply Chain & Information Management") and plain mailto on every card.
  The unfiltered roster mixes advisors/staff — require-professor gate. The
  profile "Research & Teaching Interests" block is prose sentences (verified)
  — not comma-splittable, so no research enrich; the group-qualified title
  carries the topical signal.

* **CAMD people-directory** (camd.northeastern.edu/people/,
  ``?camd-type=faculty&pg=N``): card carries dept, a labelled Title value and
  a ``data-cfemail`` email ON the listing. The faculty type still includes
  production managers etc. — keep Professor/Lecturer titles, drop Part-Time.

* **School of Law WP API** (law.northeastern.edu ``wp/v2/faculty``): the HTML
  directory is JS-only, but the API record carries everything in ACF fields
  (first/last name, title, plain email) — served through the engine's
  ``json_dir`` source with dotted-path field mapping since the wp source
  reads ``meta_box``, not ``acf``. ``faculty_type=11`` = full-time (58);
  part-time (165) and emeriti (164) never fetched.

Single source ("neu_faculty"); department rides each record, ids namespaced
by department short-code.

Engine limitations hit / known warts:
* ``nucos-expertise`` has 891 terms but the wp source's term map caps at 5
  pages x 100, so ids resolving past the first 500 (alphabetical) drop
  silently — COS keywords are present but not exhaustive.
* One Law record publishes ``acf.email`` as "mailto:k.russellbrown@…" — the
  json_dir source stores the field verbatim (no ``_clean_email`` pass), so
  that one address carries the mailto: prefix.
* Four Bouvé cards publish typo'd addresses ("b.jernigan@ northeastern.edu",
  "c.powell@northeastern", "a.sathyanarayana", "…@northeastern.ed") — the
  cfemail payloads decode faithfully to the site's own typos, and the
  engine's ``_clean_email`` falls back to the raw string when the result
  isn't address-shaped.

Deferred (from the 2026-07-18 recon):
* College of Professional Studies — server-rendered but cards are name-only,
  wp-json is 401-restricted, sample profiles carry no email, and the ~1,400
  roster is overwhelmingly part-time non-research instructors; per-profile
  cost not worth the research-opportunity value.
* Mills College at Northeastern (Oakland) — no structured directory (prose
  page, zero profile links); post-merger faculty appear in the main college
  directories above.
* Roux Institute (Portland, ME) — graduate/professional research campus, not
  an undergraduate college.
* Northeastern University London — separate UK campus with its own site.
* COE "Software Engineering & Info Systems" / "First Year Engineering"
  facets — exist (dept=23, 11641, 11642) but not count-verified; their
  people largely hold appointments in the five wired departments.
"""

from __future__ import annotations

from .. import faculty_graph

# Professor-titled ranks only (drops co-op coordinators, affiliated faculty,
# deans-without-professorship, advisors, staff); emeriti out everywhere.
_LADDER = {"require": r"\bprofessor\b", "drop": r"emerit|visiting|adjunct"}

# Colleges whose rosters legitimately carry full-time Lecturer ranks (health
# sciences / arts) keep them; part-timers are still out.
_LADDER_LECT = {"require": r"\bprofessor\b|\blecturer\b",
                "drop": r"emerit|visiting|adjunct|part-?time"}

# ---- COE unified WordPress faculty/staff grid ------------------------------
_COE_SELECTORS = {
    "card": "div.block-small",
    "name": "a.contact__name",
    "link": "a.contact__name",
    "title": "div.caption",
    # every card's rank caption ends "Professor, " — cut the dangling comma
    "title_strip_after": r",\s*$",
    "email": ".caption__link__list--alt a[href^='mailto:']",
    # The research caption is nested inside an unclosed <br> in the parse tree
    # (unreachable by sibling selectors) — bound it after the dept link.
    "research_re": r'contact__title[^>]*>.*?<div class="caption">\s*(.*?)\s*</div>',
}


def _coe(short: str, name: str, majors: list[str], dept_id: int) -> dict:
    """A College of Engineering department (dept facet, single view-all page)."""
    url = ("https://coe.northeastern.edu/faculty-staff-directory/"
           f"?type=Faculty&dept={dept_id}&display=all")
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _COE_SELECTORS,
                       "ladder_filter": _LADDER}}


# ---- College of Science WP JSON feed (nucos-faculty) -----------------------
_COS_BASE = "https://cos.northeastern.edu"
_COS_ROLE_FACULTY = 1846  # emeriti(2074)/postdocs(2021)/PhD students(2022) are other terms
_COS_DEPT_TERMS = {"physics": 11, "chemistry": 7, "mathematics": 9,
                   "biology": 3, "psychology": 4, "mes": 5}

# API records default to "Professor"; the profile header carries the real rank
# and the (first) data-cfemail on the page is the person's address.
_COS_ENRICH = {
    "email_selector": "[data-cfemail]",
    "email_drop": r"^[^@]*$|dean@|info@|admissions@",
    "title_selector": ".nu-single-people-header__role li",
    "throttle": 0.2,
}


def _cos(short: str, name: str, majors: list[str], dept_slug: str) -> dict:
    """A College of Science department via the nucos-faculty JSON feed."""
    term = _COS_DEPT_TERMS[dept_slug]
    return {
        "short": short, "name": name, "majors": majors,
        "directory_url": f"{_COS_BASE}/people/?role=faculty&department={dept_slug}",
        "api": {
            "type": "wp", "base": _COS_BASE, "post_type": "nucos-faculty",
            "query": f"&nucos-people-role={_COS_ROLE_FACULTY}"
                     f"&nucos-department-categories={term}",
            "category_include": {"nucos-people-role": [_COS_ROLE_FACULTY]},
            "keyword_tax": ["nucos-expertise"],
        },
        "profile_enrich": dict(_COS_ENRICH),
    }


SCHOOL: dict = {
    "school_slug": "neu",
    "source": "neu_faculty",
    "organization": "Northeastern University",
    "location": "Boston, MA",
    "id_prefix": "neu",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Northeastern University) — work authorization depends "
        "on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- College of Engineering (unified grid, dept facets) ------------
        _coe("BIOE", "Department of Bioengineering",
             ["Bioengineering", "Biomedical Engineering"], 6),
        _coe("CHE", "Department of Chemical Engineering", ["Chemical Engineering"], 7),
        _coe("CEE", "Department of Civil and Environmental Engineering",
             ["Civil Engineering", "Environmental Engineering"], 8),
        _coe("ECE", "Department of Electrical and Computer Engineering",
             ["Electrical Engineering", "Computer Engineering"], 9),
        _coe("MIE", "Department of Mechanical and Industrial Engineering",
             ["Mechanical Engineering", "Industrial Engineering"], 10),
        # ---- Khoury College of Computer Sciences ---------------------------
        {
            "short": "CS", "name": "Khoury College of Computer Sciences",
            "majors": ["Computer Science", "Cybersecurity", "Data Science"],
            "directory_url": "https://www.khoury.northeastern.edu/people/",
            # Tenured/TT (term 931) via the server-rendered archive — the cards
            # carry rank, so the ladder gate can drop the Professor Emeritus
            # entries the TT term itself contains.
            "scrape": {
                "url": ("https://www.khoury.northeastern.edu/people/"
                        "?filters%5B%5D=people_roles%7C931"),
                "selectors": {"card": "article.standard-card--vertical",
                              "name": "h3.standard-card__title",
                              "link": "a[href*='/people/']",
                              "title": "p.standard-card__titles"},
                "ladder_filter": _LADDER,
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 10},
            },
            # Teaching (928) + research (926) faculty via the open WP API; the
            # records lack rank/email — the enrich pass below backfills them.
            "api": {
                "type": "wp",
                "base": "https://www.khoury.northeastern.edu",
                "post_type": "people",
                "query": "&people_roles=928,926",
                "category_include": {"people_roles": [928, 926]},
            },
            "profile_enrich": {
                "email_selector": ".single-people__aside-list a[href^='mailto:']",
                "email_drop": r"^[^@]*$|khoury@|info@",
                "title_selector": "p.single-people__header-description",
                "research_items_selector":
                    "ul.single-people__aside-list a[href*='/research_areas/']",
                "ladder_recheck": _LADDER,
                "throttle": 0.2,
            },
        },
        # ---- College of Science (nucos JSON feed, dept facets) -------------
        _cos("PHYS", "Department of Physics", ["Physics"], "physics"),
        _cos("CHEM", "Department of Chemistry and Chemical Biology",
             ["Chemistry and Chemical Biology", "Chemistry"], "chemistry"),
        _cos("MATH", "Department of Mathematics", ["Mathematics"], "mathematics"),
        _cos("BIO", "Department of Biology", ["Biology", "Biochemistry"], "biology"),
        _cos("PSYC", "Department of Psychology",
             ["Psychology", "Behavioral Neuroscience"], "psychology"),
        _cos("MES", "Department of Marine and Environmental Sciences",
             ["Marine and Environmental Sciences", "Environmental Science"], "mes"),
        {
            # The small COS programs (biochem / bioinformatics / biotech /
            # linguistics / behavioral neuroscience): everyone role-tagged
            # faculty who is NOT in one of the six big departments above.
            "short": "COSX", "name": "College of Science (other programs)",
            "majors": ["Biochemistry", "Bioinformatics", "Biotechnology",
                       "Linguistics", "Behavioral Neuroscience"],
            "directory_url": f"{_COS_BASE}/people/?role=faculty",
            "api": {
                "type": "wp", "base": _COS_BASE, "post_type": "nucos-faculty",
                "query": f"&nucos-people-role={_COS_ROLE_FACULTY}",
                "category_include": {"nucos-people-role": [_COS_ROLE_FACULTY]},
                "category_exclude": {
                    "nucos-department-categories": sorted(_COS_DEPT_TERMS.values())},
                "keyword_tax": ["nucos-expertise"],
            },
            "profile_enrich": dict(_COS_ENRICH),
        },
        # ---- College of Social Sciences and Humanities (one directory) -----
        {
            "short": "CSSH", "name": "College of Social Sciences and Humanities",
            "majors": ["Economics", "Political Science", "International Affairs",
                       "English", "History", "Criminology and Criminal Justice",
                       "Sociology", "Philosophy"],
            "directory_url": "https://cssh.northeastern.edu/faculty/",
            "scrape": {
                "url": "https://cssh.northeastern.edu/faculty/",
                "selectors": {"card": "li.basic-grid__list-item",
                              "name": "h3.basic-grid__title span",
                              "link": "a.basic-grid__link",
                              "title": "h4.basic-grid__subtitle"},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"emerit|visiting|adjunct|part-?time"},
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 28},
                # First data-cfemail on a profile is the person; later ones are
                # dept inboxes (CSSHDean@…). No research selector — profile
                # bodies are prose bios; the discipline rides the card title.
                "profile_enrich": {
                    "email_selector": "[data-cfemail]",
                    "email_drop": r"^[^@]*$|dean@|info@|admissions@",
                    "throttle": 0.2,
                },
            },
        },
        # ---- Bouvé College of Health Sciences ------------------------------
        {
            "short": "BOUVE", "name": "Bouvé College of Health Sciences",
            "majors": ["Nursing", "Pharmacy", "Health Science", "Public Health",
                       "Speech-Language Pathology and Audiology"],
            "directory_url": "https://bouve.northeastern.edu/directory/?role%5B%5D=faculty",
            "scrape": {
                "url": "https://bouve.northeastern.edu/directory/?role%5B%5D=faculty",
                "selectors": {"card": "article.wp-block-bouve-faculty-card",
                              "name": "h5.wp-block-bouve-faculty-card__name",
                              "link": "a[href*='/directory/']",
                              "title": "span.wp-block-bouve-faculty-card__job-title",
                              # cfemail-protected href on the listing card —
                              # the engine's decoder reads the #HEX fragment.
                              "email": "a[href^='/cdn-cgi/l/email-protection']"},
                "ladder_filter": _LADDER_LECT,
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 24},
                "profile_enrich": {
                    "email_selector": "[data-cfemail]",
                    "email_drop": r"^[^@]*$|dean@|info@|admissions@",
                    "throttle": 0.2,
                },
            },
        },
        # ---- D'Amore-McKim School of Business ------------------------------
        {
            "short": "DMSB", "name": "D'Amore-McKim School of Business",
            "majors": ["Business Administration", "Finance", "Accounting",
                       "Marketing", "Management", "Supply Chain Management",
                       "Entrepreneurship", "International Business"],
            "directory_url": "https://damore-mckim.northeastern.edu/people/",
            "scrape": {
                "url": "https://damore-mckim.northeastern.edu/people/",
                # :has() gate: cards WITHOUT a role line are program/student
                # entries ("Online MS in Taxation") that would otherwise
                # default to "Professor" and slip the ladder gate.
                "selectors": {"card": "div.person-line:has(div.person-line-role-category)",
                              "name": "h3.person-line-name a",
                              "link": "h3.person-line-name a",
                              "title": "div.person-line-role-category",
                              "title_strip_after": r",\s*$",
                              "email": "a.person-line-contact-item__email"},
                "ladder_filter": _LADDER,
                "paginate": {"param": "query-1-page", "start": 2, "max": 30},
            },
        },
        # ---- College of Arts, Media and Design -----------------------------
        {
            "short": "CAMD", "name": "College of Arts, Media and Design",
            "majors": ["Architecture", "Art + Design", "Communication Studies",
                       "Game Design", "Journalism", "Media and Screen Studies",
                       "Music", "Theatre"],
            "directory_url": "https://camd.northeastern.edu/people/?camd-type=faculty",
            "scrape": {
                "url": "https://camd.northeastern.edu/people/?camd-type=faculty",
                "selectors": {"card": "div.card.people-directory-list-card",
                              "name": "h3.people-directory__header__name",
                              "link": ".people-directory__cta a",
                              "title": ".item-job-title .people-directory__category__value",
                              "email": ".item-email [data-cfemail]"},
                "ladder_filter": _LADDER_LECT,
                "paginate": {"param": "pg", "start": 2, "max": 40},
            },
        },
        # ---- School of Law (JS directory -> open WP API, ACF fields) -------
        {
            "short": "LAW", "name": "School of Law",
            "majors": ["Law", "Criminology and Criminal Justice",
                       "Political Science", "Philosophy"],
            "directory_url": "https://law.northeastern.edu/faculty/",
            # json_dir (not the wp source): the record's name/title/email live
            # in ACF fields, which only dotted-path mapping can read.
            "json_dir": {
                "url": ("https://law.northeastern.edu/wp-json/wp/v2/faculty"
                        "?per_page=100&faculty_type=11"),
                "name_fields": ["acf.first_name", "acf.last_name"],
                "title_field": "acf.title",
                "email_field": "acf.email",
                "link_field": "link",
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
