"""UC San Diego faculty config (via the faculty_graph engine).

Thirty departments across two batches (selectors verified against live
directory HTML, Jul 2026):

**Batch 1 — Jacobs School + Physical/Social Sciences + HDSI (13 depts):**

- **Jacobs School / campus Drupal grids** (server-rendered Views): CSE (the
  ``block_1`` Faculty + ``block_9`` Leadership views — the same page's
  Affiliated/Emeritus/Alumni views are skipped by scoping the card selector),
  ECE (emails on the listing; research capsule via gated profile pass), MAE,
  Bioengineering (ladder filter drops the grid's adjunct/affiliated rows),
  Structural Engineering, and the NanoEngineering + Chemical Engineering
  roster tables (emails on the listing; rank section-headers ride the table so
  titles default to "Professor").
- **Blink "profile-listing-card" template** (shared campus CMS): Cognitive
  Science and Psychology (both with listing emails), Sociology (its active
  Faculty section lists no emails — only the filtered-out emeritus/lecturer
  sections do), Political Science (currently-active subpage), and Economics —
  Econ/Soc list Emeritus/Adjunct/Lecturer sections on the same page, gated out
  via ``section_filter`` on the nearest ``h2``; Econ's "Research Interests:"
  line lands as keywords via ``research_re``.
- **Odd one out**: HDSI's WordPress grid (``vc_grid-term-faculty`` cards,
  ladder-filtered).
- Physics rides its public JSON profile API via the engine's ``json_dir``
  block (names/titles/emails in the feed).

**Batch 2 — remaining Social Sciences, Arts & Humanities, Math, professional
schools (17 depts):** mostly the same Blink card template with per-dept quirks
(loose-text ranks → ``title_re``; role sections under h1/h2 headings →
anchored ``section_filter``; research interests as labelled listing lines →
tag-tolerant ``research_re``). Standouts: Anthropology's hand-authored
Bootstrap panels; Literature's bare "Last, First" link-list and Theatre &
Dance's per-discipline link cards, whose titles/emails only exist on profile
pages (``profile_enrich`` with ``always``/``title_selector``/``email_selector``
+ post-enrich ``ladder_recheck``); Music served from music-cms.ucsd.edu (the
music.ucsd.edu cert fails strict verification); Mathematics via the POST-only
campus EAH HR feed (``json_dir`` with ``method``/``field_filters`` gating job
codes and a ``title_map`` from code → rank); Rady's roster where the ``li``
CSS class is the role filter; Public Health under alphabetical h2 sections;
and Scripps Oceanography's Drupal Views listing (verified against a snapshot —
the host is unreachable from some local egress paths; CI collects it fine).

All 32 targeted departments now collect. The two once-deferred cases:
Biology's API keeps the rank in a nested ``titleInfo.standardTitle`` (reached
via dotted-path ``json_dir``), and Chemistry & Biochemistry's server presents a
mismatched TLS intermediate (an ECC leaf with the RSA intermediate) that
strict-verify clients — requests, curl — can't connect through, so it rides the
headless-render fetch (``scrape.render``), which survives via a browser's AIA
chasing. (The UCSD REAL Portal — the campus research-project board — is
deliberately excluded: Cloudflare bot-management plus a robots.txt that names
AI crawlers signal no automated collection; route it through the AIP office if
its data is ever needed.)

Single source ("ucsd_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

# Ladder faculty only: "professor" matches Assistant/Associate/Distinguished/
# Teaching Professor ranks; drop emeriti, adjuncts, and visitors outright.
_LADDER = {"require": r"\bprofessor\b", "drop": r"\bemerit|\badjunct|\bvisiting"}

# The Jacobs School profile template (jacobsschool.ucsd.edu/faculty/profile?id=N,
# /people/profile/<slug>, /node/N — all one Drupal template) keeps a one-line
# research capsule in a bold div unique to the page; the optional p/span run
# tolerates the template's malformed nesting (<p><p>text</p></p>).
_JACOBS_CAPSULE_RE = (r'class="mt-5 font-weight-bold">\s*(?:<(?:p|span)>\s*)*([^<]+)')

# Blink "profile-listing-card" grid shared by the social-science departments.
_BLINK = {
    "card": "li.profile-listing-card",
    "name": "p.h3 > a",
    "link": "p.h3 > a",
    "title": "h4",
    "email": ".profile-listing-data a[href^='mailto:']",
}


def _dept(short: str, name: str, majors: list[str], url: str, scrape: dict) -> dict:
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": {"url": url, **scrape}}


SCHOOL: dict = {
    "school_slug": "ucsd",
    "source": "ucsd_faculty",
    "organization": "University of California, San Diego",
    "location": "La Jolla, CA",
    "id_prefix": "ucsd",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (UC San Diego) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- Jacobs School of Engineering + campus Drupal grids ------------
        {
            **_dept(
                "CSE", "Department of Computer Science & Engineering",
                ["Computer Science", "Computer Engineering", "Data Science"],
                "https://cse.ucsd.edu/people/faculty-profiles",
                {
                    # Faculty (block_1) + Department Leadership (block_9) views only;
                    # the page's Lecturer/Adjunct/Affiliated/Emeritus/Alumni views
                    # are separate blocks and stay out of the card selector.
                    "selectors": {
                        "card": (".view-display-id-block_1 .views-field-nothing .field-content, "
                                 ".view-display-id-block_9 .views-field-nothing .field-content"),
                        "name": "a[href^='/people/faculty-profiles/'] p strong",
                        "link": "a[href^='/people/faculty-profiles/']",
                    },
                },
            ),
            # CSE's own site carries zero research data (listing and profiles
            # both); the Jacobs School JSON:API maps name → capsule keywords,
            # paginated via links.next (the HTML directory clamps to 10
            # rows/page, the API gives 50).
            "research_join": {
                "url": ("https://jacobsschool.ucsd.edu/jsonapi/node/person_profile"
                        "?filter%5Ba%5D%5Bcondition%5D%5Bpath%5D=field_profile_associations"
                        "&filter%5Ba%5D%5Bcondition%5D%5Boperator%5D=CONTAINS"
                        "&filter%5Ba%5D%5Bcondition%5D%5Bvalue%5D=CSE"
                        "&page%5Blimit%5D=50"
                        "&fields%5Bnode--person_profile%5D=title,field_profile_keywords"),
                "key": "name",
                "item_re": (r'"attributes":\{(?=[^{}]*"title":\s*"(?P<key>(?:[^"\\]|\\.)+)")'
                            r'[^{}]*"field_profile_keywords":\s*"(?P<areas>(?:[^"\\]|\\.)+)"'),
                "next_re": r'"next":\{"href":"([^"]+)"',
                "max_pages": 8,
            },
        },
        _dept(
            "ECE", "Department of Electrical & Computer Engineering",
            ["Electrical Engineering", "Computer Engineering", "Engineering Physics"],
            "https://ece.ucsd.edu/people/faculty",
            {
                "selectors": {
                    "card": "div.faculty-member",
                    "name": "h2 > a",
                    "link": "h2 > a",
                    # The rank shares one <p> with the email + lab links; cut at
                    # the first email address or "Lab Web" marker.
                    "title": "p",
                    "title_strip_after": r"\s+\S+@|\s+Lab\s+Web\b",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
                # Stored profile links (jacobsschool.ucsd.edu/faculty/profile?id=N)
                # carry the shared Jacobs research capsule. Gated
                # (OFE_ENRICH_PROFILES=1) — optional depth.
                "profile_enrich": {"research_html_re": _JACOBS_CAPSULE_RE,
                                   # jacobsschool profile shows the email as
                                   # plain text in the col-3 sidebar (no mailto).
                                   "email_selector": ".col-3 p",
                                   "throttle": 1.5},
            },
        ),
        _dept(
            "MAE", "Department of Mechanical & Aerospace Engineering",
            ["Mechanical Engineering", "Aerospace Engineering"],
            "https://mae.ucsd.edu/people/faculty-profiles",
            {
                "selectors": {
                    "card": "div.profile-window",
                    "name": ".profile-info h4 > a",
                    "link": ".profile-info h4 > a",
                    "title": ".profile-info h5",
                },
                "ladder_filter": _LADDER,
                # Stored links go off-site to jacobsschool profile pages (three
                # URL flavors, one shared template) — the same research capsule
                # as ECE. Gated pass.
                "profile_enrich": {"research_html_re": _JACOBS_CAPSULE_RE,
                                   # jacobsschool profile shows the email as
                                   # plain text in the col-3 sidebar (no mailto).
                                   "email_selector": ".col-3 p",
                                   "throttle": 1.5},
            },
        ),
        _dept(
            "BE", "Department of Bioengineering",
            ["Bioengineering", "Bioengineering: Biotechnology",
             "Bioengineering: Bioinformatics", "Bioengineering: BioSystems"],
            "https://be.ucsd.edu/faculty",
            {
                "selectors": {
                    "card": "div.faculty-profile",
                    "name": ".faculty-information h3 > a",
                    "link": ".faculty-information h3 > a",
                    # Malformed <h6>Rank<h6 /> swallows the lab link that follows;
                    # cut the title at the lab/group name.
                    "title": ".faculty-information h6",
                    "title_strip_after": r"\s+(?:\S+\s+)?(?:Research|Lab\b|Laboratory|Group)\b.*",
                },
                "ladder_filter": _LADDER,
                # Stored links resolve to jacobsschool profile pages — the
                # shared research capsule. Gated pass.
                "profile_enrich": {"research_html_re": _JACOBS_CAPSULE_RE,
                                   # jacobsschool profile shows the email as
                                   # plain text in the col-3 sidebar (no mailto).
                                   "email_selector": ".col-3 p",
                                   "throttle": 1.5},
            },
        ),
        {
            **_dept(
                "NANO", "Department of NanoEngineering",
                ["NanoEngineering"],
                "https://nanoengineering.ucsd.edu/fac/nanoe-faculty",
                {
                    # Roster table: rank lives in tr.table-active section headers
                    # (those rows carry no <a>, so they're skipped automatically);
                    # the name cell links to the professor's lab site.
                    "selectors": {
                        "card": "table tbody tr",
                        "name": "td:nth-of-type(1) a",
                        "link": "td:nth-of-type(1) a",
                        "email": "td a[href^='mailto:']",
                    },
                    "name_flip": True,
                },
            ),
            # Roster links point at personal lab sites (no shared template to
            # regex), so research rides the Jacobs JSON:API name→keywords join,
            # NENG-filtered.
            "research_join": {
                "url": ("https://jacobsschool.ucsd.edu/jsonapi/node/person_profile"
                        "?filter%5Ba%5D%5Bcondition%5D%5Bpath%5D=field_profile_associations"
                        "&filter%5Ba%5D%5Bcondition%5D%5Boperator%5D=CONTAINS"
                        "&filter%5Ba%5D%5Bcondition%5D%5Bvalue%5D=NENG"
                        "&page%5Blimit%5D=50"
                        "&fields%5Bnode--person_profile%5D=title,field_profile_keywords"),
                "key": "name",
                "item_re": (r'"attributes":\{(?=[^{}]*"title":\s*"(?P<key>(?:[^"\\]|\\.)+)")'
                            r'[^{}]*"field_profile_keywords":\s*"(?P<areas>(?:[^"\\]|\\.)+)"'),
                "next_re": r'"next":\{"href":"([^"]+)"',
                "max_pages": 4,
            },
        },
        _dept(
            "CHE", "Chemical Engineering Program",
            ["Chemical Engineering"],
            "https://nanoengineering.ucsd.edu/chemical-engineering-faculty",
            {
                # Same roster-table markup as the NanoE page that hosts it.
                "selectors": {
                    "card": "table tbody tr",
                    "name": "td:nth-of-type(1) a",
                    "link": "td:nth-of-type(1) a",
                    "email": "td a[href^='mailto:']",
                },
                "name_flip": True,
            },
        ),
        _dept(
            "SE", "Department of Structural Engineering",
            ["Structural Engineering", "Civil Engineering"],
            "https://se.ucsd.edu/people/faculty",
            {
                "selectors": {
                    "card": "div[id^='views-bootstrap-faculty-page'] .row > div[class*='col-']",
                    "name": ".views-field-field-last-name .field-content",
                    # The web-page cell holds 1-2 links (personal lab site
                    # and/or "Faculty Profile"); prefer the jacobsschool one —
                    # canonical, and it feeds the research-capsule pass. Cards
                    # without it fall back to the directory URL.
                    "link": ".views-field-field-web-page a[href*='jacobsschool']",
                    "title": ".views-field-field-staff-title em",
                },
                "name_flip": True,
                "ladder_filter": _LADDER,
                "profile_enrich": {"research_html_re": _JACOBS_CAPSULE_RE,
                                   # jacobsschool profile shows the email as
                                   # plain text in the col-3 sidebar (no mailto).
                                   "email_selector": ".col-3 p",
                                   "throttle": 1.5},
            },
        ),
        # ---- School of Biological Sciences ----------------------------------
        {
            "short": "BIO", "name": "School of Biological Sciences",
            "majors": ["General Biology", "Human Biology", "Molecular and Cell Biology",
                       "Microbiology", "Neurobiology", "Ecology, Behavior & Evolution",
                       "Biochemistry", "Biology with a Specialization in Bioinformatics",
                       "Marine Biology", "Mathematical Biology"],
            "directory_url": "https://biology.ucsd.edu/research/faculty/index.html",
            # The directory page is a JS spinner over this public feed (bare
            # array, 218 records, everyone from adjuncts to emeriti) — the rank
            # sits at the NESTED titleInfo.standardTitle (the dotted-path reason
            # this dept was deferred in batch 1). The feed itself carries each
            # person's research summary and profile link.
            "json_dir": {
                "url": ("https://public.biology.ucsd.edu/api/prod/website-data/"
                        "v1/globs/people/filterBy?type=faculty"),
                "name_fields": ["fname", "lname"],
                "title_field": "titleInfo.standardTitle",
                "email_field": "email",
                "link_field": "profileInfo.profileURL",
                # Section tags first (clean area chips, 213/218 records);
                # prose lab summary as fallback.
                "research_field": ["profileInfo.sections[].title",
                                   "profileInfo.researchSummary"],
                "ladder_filter": {
                    "require": r"\bprofessor\b",
                    "drop": r"\bemerit|\badjunct|\bvisiting|of practice|\blecturer"},
            },
        },
        # ---- School of Physical Sciences -----------------------------------
        _dept(
            "CHEM", "Department of Chemistry & Biochemistry",
            ["Chemistry", "Biochemistry", "Pharmacological Chemistry",
             "Molecular Synthesis"],
            "https://chemistry.ucsd.edu/faculty/index.shtml",
            {
                # The server ships a mismatched TLS intermediate (ECC leaf with
                # the RSA intermediate) that strict-verify clients can't
                # connect through — but a real browser survives via AIA
                # chasing, so this dept rides the headless-render fetch.
                # Legacy tabbed directory: inline-styled cards, no title
                # element (ranks are bare text nodes) — everyone ships with the
                # default "Professor" title; the page lists no emeriti.
                "render": True,
                "selectors": {
                    "card": "#tabs div[style*='float: right']",
                    "name": "h5 > a.mylinks",
                    "link": "h5 > a.mylinks",
                },
                "name_flip": True,
            },
        ),
        {
            "short": "PHYS", "name": "Department of Physics",
            "majors": ["Physics", "General Physics", "Astronomy & Astrophysics"],
            "directory_url": "https://physics.ucsd.edu/people/faculty",
            # The listing page is a JS spinner over this public JSON API.
            "json_dir": {
                "url": "https://physics.ucsd.edu/api/profiles/faculty",
                "name_fields": ["first_name", "last_name"],
                "title_field": "display_title",
                "email_field": "email",
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\badjunct|\bvisiting"},
            },
            # The roster feed has no research field; the site's own JS enriches
            # each person from /api/profile/<email-user>/<dept-code>, whose JSON
            # carries a research paragraph. Dept-level (the json_dir path has no
            # scrape block); gated pass.
            "profile_enrich": {
                "url_template": "https://physics.ucsd.edu/api/profile/{email_local}/000220",
                "research_html_re": r'"research":"((?:[^"\\]|\\.)*)"',
                "throttle": 1.0,
            },
        },
        # ---- School of Social Sciences --------------------------------------
        _dept(
            "COGSCI", "Department of Cognitive Science",
            ["Cognitive Science", "Cognitive and Behavioral Neuroscience"],
            "https://cogsci.ucsd.edu/people/faculty/",
            {
                "selectors": dict(_BLINK),
                "ladder_filter": _LADDER,
                # Every profile page keeps a "Research Interests" accordion tab.
                # Gated pass.
                "profile_enrich": {
                    "research_html_re": (
                        r'Research Interests\s*</h2>\s*<div[^>]*'
                        r'class="resp-tab-content"[^>]*>\s*(.*?)\s*</div>'),
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "PSYCH", "Department of Psychology",
            ["Psychology", "Business Psychology"],
            # Only the flat .html path serves the directory (/people/faculty/ 403s).
            "https://psychology.ucsd.edu/people/faculty.html",
            {
                "selectors": {
                    **_BLINK,
                    # The card's last content run before the closing tags is a
                    # comma-separated research blurb (44/46 cards; usually a
                    # trailing <p>, sometimes span-wrapped, once bare text).
                    "research_re": (
                        r">\s*([A-Z][^<>]{8,}?)\s*(?:</span>\s*|</p>\s*)*</span>\s*</li>"),
                },
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "ECON", "Department of Economics",
            ["Economics", "Business Economics", "Joint Major Mathematics & Economics"],
            "https://economics.ucsd.edu/faculty-and-research/faculty-profiles/index.html",
            {
                # One page, h2-grouped roles (Faculty / Emeritus / Adjunct /
                # Affiliated / Lecturers / Visiting) — keep the Faculty section.
                # No title element (loose text), so rank defaults to Professor;
                # the "Research Interests:" line becomes keywords.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "h3 > a",
                    "link": "h3 > a",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    "research_re": r"Research Interests:\s*(.{4,300}?)(?:<|$)",
                },
                "section_filter": {"include": r"^Faculty$", "heading": "h2"},
            },
        ),
        {
            **_dept(
                "POLI", "Department of Political Science",
                ["Political Science - General Political Science", "Political Science - International Relations"],
                "https://polisci.ucsd.edu/people/faculty/faculty-directory/currently-active-faculty/index.html",
                {"selectors": dict(_BLINK), "ladder_filter": _LADDER},
            ),
            # One static "faculty by field" page maps profile slugs to subfield
            # areas ('<a href=.../SLUG-profile.html>Name</a>, Title. Ph.D.,
            # School. AREAS.') — the areas are the last dot-free run before the
            # closing </li>; a person under several field headings accumulates.
            "research_join": {
                "url": "https://polisci.ucsd.edu/people/faculty/faculty-by-field/index.html",
                "key": "slug",
                "item_re": (
                    r'href="[^"]*?/(?P<key>[a-z0-9-]+-profile\.html)"'
                    r"(?:(?!</li>).)*?\.\s*(?P<areas>[^<.]{5,200}?)\.?\s*</li>"),
            },
        },
        _dept(
            "SOC", "Department of Sociology",
            ["Sociology"],
            "https://sociology.ucsd.edu/people/faculty/index.html",
            {
                # Same h2-grouped single page as Econ (Faculty / Emeritus /
                # Adjunct / Affiliated / Lecturers / Visiting Scholars); the
                # name rides a bare h3 and the rank is loose text. The card
                # prose ends in a research-areas run after the "PhD <school>
                # <year>." / "Professor," anchor — a text-level regex (the [^.]
                # classes would trip on dots inside HTML attributes).
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "h3 > a",
                    "link": "h3 > a",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    "research_re_text": (
                        r"(?:.*Ph\.?D\.?[^.]*\.|.*\bProfessor;[^.]*\.|"
                        r"[^.]*?\bProfessor(?:\s+of\s+Teaching)?,)\s*([^.]+)"),
                },
                "section_filter": {"include": r"^Faculty$", "heading": "h2"},
            },
        ),
        # ---- Halıcıoğlu Data Science Institute ------------------------------
        _dept(
            "HDSI", "Halıcıoğlu Data Science Institute",
            ["Data Science"],
            "https://datascience.ucsd.edu/faculty/",
            {
                # WordPress/WPBakery grid; scope to the "faculty" term cards and
                # ladder-filter out the grid's lecturers/directors/fellows.
                "selectors": {
                    "card": "div.vc_grid-item.vc_grid-term-faculty",
                    "name": ".vc_gitem-post-data-source-post_title h4 > a",
                    "link": ".vc_gitem-post-data-source-post_title h4 > a",
                    "title": ".field.pendari_people_title",
                },
                "ladder_filter": _LADDER,
                # Per-person pendari pages are server-rendered; the bio prose
                # opens with a "research (interests|focus) …" sentence. Gated.
                "profile_enrich": {
                    "research_html_re": (
                        r"research(?:\s+interests?|\s+focus(?:es)?)?\s+"
                        r"(?:is|are|lies?|spans?|focus(?:es)?|centers?|interests?)\s*"
                        r"(?:in|on|at|around)?\s*([^<.]{10,400})"),
                    # Personal mailto on the pendari profile; the page footer
                    # also carries a shared inbox, dropped.
                    "email_selector": ".person-page .email a[href^='mailto:']",
                    "email_drop": r"communication@ucsd\.edu",
                    "throttle": 1.0,
                },
            },
        ),
        # ---- School of Social Sciences, second batch ------------------------
        _dept(
            "ANTH", "Department of Anthropology",
            ["Anthropology with a Concentration in Archaeology",
             "Anthropology with a Concentration in Biological Anthropology",
             "Anthropology with a Concentration in Climate Change and Human Solutions",
             "Anthropology with a Concentration in Sociocultural Anthropology",
             "Environmental Anthropology", "Biological Anthropology"],
            "https://anthropology.ucsd.edu/people/faculty/index.html",
            {
                # Hand-authored Bootstrap panels (not the Blink card template);
                # page is ladder-only (adjuncts/lecturers/visitors live on
                # separate pages). Each card's bio paragraph usually contains a
                # "research focuses on ..." sentence — capture it tag-free.
                "selectors": {
                    "card": "section.main-section div.panel.panel-default",
                    "name": "h3 > a",
                    "link": "h3 > a",
                    "title": "p > strong",
                    "title_strip_after": r"[,|]",
                    "email": "a[href^='mailto:']",
                    "research_re": (
                        r"((?:research|work)[^<.]{0,80}?"
                        r"(?:interests?|focus\w*|includes?|examines?|explores?"
                        r"|centers?|specializ\w+)[^<]{0,300}\.)"),
                },
            },
        ),
        _dept(
            "COMM", "Department of Communication",
            ["Communication", "Media Industries and Communication"],
            "https://communication.ucsd.edu/people/faculty/index.html",
            {
                # Blink cards but the rank is loose text (no stable element) —
                # title_re extracts it from the card text. One affiliated
                # professor (home dept elsewhere, "(Affiliated)" name suffix)
                # is excluded via field_filter so she isn't double-counted when
                # her home department is scraped.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "p.h3 > a",
                    "link": "p.h3 > a",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    "title_re": (
                        r"((?:(?:Distinguished|Associate|Assistant)\s+)?"
                        r"(?:Teaching\s+)?Professor"
                        r"(?:\s*,\s*(?:Chair|Vice Chair))?)"),
                    "research_re": r"Research\s+Interests?\s*:\s*([^<]{4,400})",
                },
                "field_filter": {"selector": "p.h3", "exclude": r"\(Affiliated\)"},
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "EDS", "Department of Education Studies",
            ["Education Sciences"],
            "https://eds.ucsd.edu/people/faculty/index.html",
            {
                # Blink cards, hand-edited markup: the rank <strong> floats at
                # inconsistent depths (first non-name strong wins); 3 cards keep
                # the email as plain text (skipped — mailto covers 24/27).
                # Research lives in profile-page prose only.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "p.h3 > a",
                    "link": "p.h3 > a",
                    "title": ".profile-listing-data strong:not(p.h3 strong)",
                    "title_strip_after": ",",
                    "email": ".profile-listing-data a[href^='mailto:']",
                },
                "ladder_filter": _LADDER,
                # Research lives only in profile-page prose ("...research
                # examines/focuses on ..."). Gated pass.
                "profile_enrich": {
                    "research_re": (
                        r"research\s+(?:examines|focuses on|explores"
                        r"|centers on|investigates)\s+([^.]{10,300})"),
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "ETHN", "Department of Ethnic Studies",
            ["Ethnic Studies"],
            "https://ethnicstudies.ucsd.edu/people/faculty.html",
            {
                # One page holds 148 cards; 121 are Affiliated Faculty from
                # OTHER departments (real "Professor" titles, so only the
                # h2 section gate separates them). Listing emails are rare —
                # the always-off profile pass (env-gated) can fill them later;
                # the research line is the card's semicolon-delimited last <p>.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": ".profile-listing-data h3 > a",
                    "link": ".profile-listing-data h3 > a",
                    "title": ".profile-listing-data h4",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    "research_re": r"<p>\s*([^<]*;[^<]{5,300})\s*</p>",
                },
                "section_filter": {"include": r"^Department Faculty$", "heading": "h2"},
                "profile_enrich": {
                    "email_selector": "a[href^='mailto:']",
                    "research_html_re": (
                        r"Research\s+Interests?\s*</h3>\s*(?:<[^>]+>\s*)*([^<]{5,400})"),
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "LING", "Department of Linguistics",
            ["Linguistics", "Linguistics - Cognition and Language",
             "Linguistics - Language and Society", "Linguistics - Language Studies",
             "Linguistics - Speech and Language Sciences"],
            "https://linguistics.ucsd.edu/people/faculty/index.html",
            {
                # Blink cards; rank is loose text in the data span (cut at the
                # "Ph.D.," degree line). Listing has research interests but no
                # emails — profile pages carry exactly one scoped mailto.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "p.h3 a",
                    "link": "p.h3 a",
                    "title": "span.profile-listing-data",
                    "title_strip_after": r"Ph\.D\.,",
                    "research_re": (
                        r"Research\s+Interests?:(?:</strong>)?\s*([^<]{4,300})"),
                },
                "ladder_filter": _LADDER,
                "profile_enrich": {
                    "email_selector":
                        "article.profile-section-contact li.email a[href^='mailto:']",
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "USP", "Department of Urban Studies and Planning",
            ["Urban Studies and Planning", "Real Estate and Development"],
            "https://usp.ucsd.edu/about/faculty/index.html",
            {
                # Blink cards under two h2 sections (keep "Faculty", drop
                # "Lecturers and Affiliated Faculty"); ~4 cards have a linkless
                # h3, and ranks are loose text — title_re + require-professor
                # drops the section's Continuing Lecturers.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "h3",
                    "link": "h3 a[href]",
                    "email": "a[href^='mailto:']",
                    "title_re": (
                        r"((?:Assistant |Associate |Adjunct |Senior )?"
                        r"(?:Teaching )?(?:Professor|Continuing Lecturer)"
                        r"(?: Emeritus)?(?: of [A-Za-z ]+)?(?:, [A-Za-z &]+)?)"),
                    "research_re": (
                        r"Specializations\s*:?\s*(?:<[^>]+>\s*)*([^<]{4,400})"),
                },
                "section_filter": {"include": r"^Faculty$", "heading": "h2"},
                "ladder_filter": _LADDER,
            },
        ),
        _dept(
            "GPS", "School of Global Policy and Strategy",
            ["International Studies—Anthropology", "International Studies—Economics",
             "International Studies—History", "International Studies—International Business",
             "International Studies—Linguistics", "International Studies—Literature",
             "International Studies—Philosophy", "International Studies—Political Science",
             "International Studies—Sociology"],
            "https://gps.ucsd.edu/faculty-research/faculty.html",
            {
                # GPS is graduate-only; it serves undergrads through the
                # International Studies Program tracks. Drop-only ladder gate:
                # two ladder professors carry endowed-chair/Dean titles without
                # the word "Professor", so a require-regex would lose them.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "p.h3 > a",
                    "link": "p.h3 > a",
                    "title": "span.profile-listing-data > p:nth-of-type(2)",
                    "title_strip_after": ";",
                    "research_re": r"Research\s+Fields?:\s*([^<]{4,400})",
                },
                "ladder_filter": {
                    "drop": r"\bof practice|\bteaching professor|\bemerit|\badjunct|\bvisiting"},
                "profile_enrich": {
                    "email_selector":
                        "article.profile-section-contact li.email a[href^='mailto:']",
                    "throttle": 1.0,
                },
            },
        ),
        # ---- School of Arts & Humanities ------------------------------------
        _dept(
            "HIST", "Department of History",
            ["History"],
            "https://history.ucsd.edu/people/faculty/index.html",
            {
                # Blink cards grouped under h1 headings (Department Chair /
                # Faculty / Faculty Emeriti / In Memoriam) — anchor the include
                # so "Faculty Emeriti" can't prefix-match. Every kept card has a
                # "Field of Study:" line. One title has a typo ("Profesor"), and
                # emeriti often lack titles entirely — the section gate is the
                # real filter, no ladder regex.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "p.h3 a",
                    "link": "p.h3 a",
                    "title": "p.h3 + p",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    "research_re": r"Field of Study:\s*(?:<[^>]+>\s*)*([^<]{2,200})",
                },
                "section_filter": {
                    "include": r"^(Department\s+Chair|Faculty)\s*$", "heading": "h1"},
            },
        ),
        _dept(
            "LIT", "Department of Literature",
            ["Literatures in English", "Literatures in Spanish",
             "World Literature and Culture", "Literary Arts"],
            "https://literature.ucsd.edu/people/faculty/index.html",
            {
                # Bare "Last, First" link-list (no titles/emails on the listing)
                # — the profile pass is where the record's core fields live, so
                # it runs on every refresh (always) and the ladder gate fires
                # after titles exist (the Faculty section mixes ~15 language
                # lecturers among the ladder professors).
                "selectors": {
                    "card": ("section.main-section > div.row:nth-of-type(1) "
                             "div.col-md-4 > a"),
                    "name": ":self",
                    "link": ":self",
                },
                "name_flip": True,
                "profile_enrich": {
                    "always": True,
                    "title_selector": "header.profile-section-header p.subhead",
                    "email_selector":
                        "article.profile-section-contact li.email a[href^='mailto:']",
                    "ladder_recheck": {
                        "require": r"\bprofessor\b",
                        "drop": r"\bemerit|\badjunct|\bvisiting|\blecturer"},
                    "research_re": r"interests include ([^.]{10,400})",
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "PHIL", "Department of Philosophy",
            ["Philosophy"],
            "https://philosophy.ucsd.edu/people/faculty.html",
            {
                # Blink cards under h2 sections; keep Department Chair + Faculty
                # (anchored — "Faculty Affiliates" must not match). No ladder
                # regex: two ladder titles are split across span boundaries and
                # would fail a require-professor gate; the sections are already
                # ladder-only.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": ".profile-listing-data p.h3",
                    "link": ".profile-listing-data p.h3 a[href]",
                    "title": (".profile-listing-data > p:not(.h3)"
                              ":not(:has(a[href^='mailto:']))"),
                    "title_strip_after": r"Ph\.D",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    # The card's info paragraph ends with the research line
                    # after a double <br>.
                    "research_re": r"<br\s*/?>\s*<br\s*/?>\s*([^<]{21,400})",
                },
                "section_filter": {
                    "include": r"^(Department Chair|Faculty)$", "heading": "h2"},
            },
        ),
        _dept(
            "MUS", "Department of Music",
            ["Music", "Music/Humanities", "Interdisciplinary Computing and the Arts"],
            # music.ucsd.edu fails TLS verification; music-cms is the same site
            # behind a valid certificate.
            "https://music-cms.ucsd.edu/people/faculty/index.html",
            {
                # Blink cards under five h2 role sections; keep Faculty +
                # University Professor (Lecturer/Emeritus cards often have no
                # title element at all, so the section gate beats a title
                # regex). Every card carries an "Emphasis:" line.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": ".profile-listing-data h3 > a",
                    "link": ".profile-listing-data h3 > a",
                    "title": ".profile-listing-data h3 + p",
                    "title_strip_after": "&",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    "research_re": r"Emphasis:\s*(?:</strong>)?\s*([^<]{2,200})",
                },
                "section_filter": {
                    "include": r"^(Faculty|University Professor)$", "heading": "h2"},
            },
        ),
        _dept(
            "TDPS", "Department of Theatre and Dance",
            ["Theatre", "Dance"],
            "https://theatre.ucsd.edu/people/faculty/index.html",
            {
                # Nonstandard: each Blink "card" is a per-DISCIPLINE section
                # holding bare person links, with lecturers listed below strong
                # markers inside the same card. Names carry */++ area-head
                # markers. Titles/emails live on profile pages (always-on
                # pass); ladder gate is drop-based because ladder titles here
                # often lack the word "professor" ("Design Faculty", "Head of
                # Graduate Acting").
                "selectors": {
                    "card": "li.profile-listing-card p a[href]",
                    "name": ":self",
                    "link": ":self",
                    "name_strip": r"[\s*]+$",
                },
                "link_filter": r"^(?!.*(archive|emeritus|in-memoriam))",
                "section_filter": {
                    "include": (r"^(Acting|Dance|Design|Directing|Performance Studies"
                                r"|Playwriting|Stage Management) Faculty$"),
                    "heading": "h2"},
                "profile_enrich": {
                    "always": True,
                    "title_selector": "header.profile-section-header p.subhead",
                    "email_selector":
                        "article.profile-section-contact li.email a[href^='mailto:']",
                    "ladder_recheck": {
                        "drop": r"\blecturer|\bemerit|\bmemoriam|\bvisiting|\badjunct"},
                    # Mostly the Performance Studies profiles carry a Research
                    # Areas tab; artists' pages simply won't match.
                    "research_re": (
                        r"Research Areas\s*(.{10,400}?)\s*"
                        r"(?:Biography|Education|Selected|Affiliations|$)"),
                    "throttle": 1.0,
                },
            },
        ),
        _dept(
            "VIS", "Department of Visual Arts",
            ["Visual Arts (Art History/Criticism)", "Visual Arts (Media)",
             "Visual Arts (Studio)", "Interdisciplinary Computing and the Arts",
             "Speculative Design"],
            "https://visarts.ucsd.edu/people/faculty/index.html",
            {
                # Blink cards, professorial-only page (emeriti/lecturers are on
                # separate pages). Each card's h5 carries comma-separated area
                # tags matching the department's five majors.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "p.h3 > a",
                    "link": "p.h3 > a",
                    "title": "h4",
                    "title_strip_after": ",",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    "research_items": "h5",
                },
            },
        ),
        # ---- School of Physical Sciences (continued) -------------------------
        {
            "short": "MATH", "name": "Department of Mathematics",
            "majors": ["Mathematics", "Applied Mathematics",
                       "Mathematics—Computer Science", "Mathematics—Applied Science",
                       "Mathematics—Secondary Education",
                       "Joint Major Mathematics & Economics",
                       "Probability and Statistics", "Mathematical Biology"],
            "directory_url": "https://math.ucsd.edu/people/faculty",
            # The listing is a JS DataTable over the campus EAH HR feed (POST-
            # only; GET returns an empty body). The feed lists ALL department
            # employees once per job association — the field gates keep active
            # Academic: Faculty in ladder/teaching/chair job codes, and the
            # school-wide email dedup collapses multi-association repeats. The
            # dept's own /export feed stays broken (no name field); records
            # link to the directory page via the linkless fallback.
            "json_dir": {
                "url": "https://soeapp.ucsd.edu/tools/eah/department.php",
                "method": "post",
                "data": {"department_code[]": "000212"},
                "name_fields": ["employee_preferred_first_name_current",
                                "employee_preferred_last_name_current"],
                "title_field": "job_code",
                "title_map": {
                    "001100": "Professor", "001143": "Professor",
                    "001200": "Associate Professor", "001243": "Associate Professor",
                    "001300": "Assistant Professor", "001343": "Assistant Professor",
                    "001603": "Teaching Professor",
                    "001607": "Associate Teaching Professor",
                    "001680": "Assistant Teaching Professor",
                    "001096": "Professor, Department Chair",
                },
                "email_field": "identity_email_address_current",
                "field_filters": [
                    {"field": "employee_class", "include": r"^Academic: Faculty$"},
                    {"field": "employee_status", "exclude": r"Retired|Terminated"},
                    {"field": "job_code",
                     "include": (r"^(001100|001143|001200|001243|001300|001343"
                                 r"|001603|001607|001680|001096)$")},
                ],
            },
            # The dept's own /export feed is useless as a roster (no name
            # field) but fine as an email-keyed join: field_work_email →
            # field_primary_research_area (108/335 populated).
            "research_join": {
                "url": "https://math.ucsd.edu/export/people/faculty",
                "key": "email",
                "item_re": (r'"field_work_email":\s*"(?P<key>[^"]+)"[^{}]*?'
                            r'"field_primary_research_area":\s*"(?P<areas>[^"]+)"'),
            },
        },
        # ---- Professional schools --------------------------------------------
        _dept(
            "RADY", "Rady School of Management",
            ["Business Economics", "Business Psychology",
             "International Studies—International Business"],
            "https://rady.ucsd.edu/faculty-research/faculty-directory/index.html",
            {
                # Custom roster (not Blink): the li CSS class IS the role filter
                # — research-faculty holds exactly the 41 ladder professors
                # (lecturing/teaching-professor/adjunct/emeriti ride other
                # classes). 100% of cards carry name/link/title/email. Research
                # areas live on profile pages (gated pass; bounded before the
                # "Industry Areas" block).
                "selectors": {
                    "card": "ul.rady-facultylist > li.research-faculty",
                    "name": "h3",
                    "link": "h3 > a[href]",
                    "title": "span.profile-listing-data",
                    "email": "a[href^='mailto:']",
                },
                "profile_enrich": {
                    # The accordion heading is "Research Areas" or "Research &
                    # Industry Areas" (with an inner "Research Areas" label
                    # under the combined form); bound before the neighbouring
                    # sections.
                    "research_re": (
                        r"Research(?:\s*(?:&|and)\s*Industry)?\s+Areas\s*"
                        r"(?:Research\s+Areas\s*)?(.{4,400}?)\s*"
                        r"(?:Industry Areas|Teaching|Education|Biography|Rady School|$)"),
                    "throttle": 1.5,
                },
            },
        ),
        _dept(
            "HWSPH", "Herbert Wertheim School of Public Health and Human Longevity Science",
            ["Public Health",
             "Public Health with Concentration in Biostatistics",
             "Public Health with Concentration in Climate and Environmental Sciences",
             "Public Health with Concentration in Community Health Sciences",
             "Public Health with Concentration in Epidemiology",
             "Public Health with Concentration in Health Policy and Management Sciences",
             "Public Health with Concentration in Medicine Sciences"],
            # publichealth.ucsd.edu 301s here; relative links only resolve
            # against this host.
            "https://hwsph.ucsd.edu/people/faculty/faculty-directory.html",
            {
                # Blink cards under ALPHABETICAL h2 sections (A-D … U-Z) — the
                # letter-range include drops the trailing Emeritus/Voluntary
                # sections. Within the core sections a ladder regex still has to
                # drop clinical/lecturer/non-salaried ranks. Secondary-appointed
                # professors (primary in the School of Medicine) are kept: real
                # professors, no duplicate-source risk.
                "selectors": {
                    "card": "li.profile-listing-card",
                    "name": "h3 a",
                    "link": "h3 a[href]",
                    "title": ".profile-listing-data strong",
                    "email": ".profile-listing-data a[href^='mailto:']",
                    "research_re": (
                        r"Research\s+Interests?\s*:?\s*(?:<[^>]+>\s*)*([^<]{4,500})"),
                },
                "section_filter": {"include": r"^[A-Z]\s*-\s*[A-Z]$", "heading": "h2"},
                "ladder_filter": {
                    "require": r"\bprofessor\b",
                    "drop": (r"\bemerit|\badjunct|\bvisiting|\bclinical|\blecturer"
                             r"|\binstructor|non-salaried")},
            },
        ),
        _dept(
            "SIO", "Scripps Institution of Oceanography",
            ["Geosciences", "Marine Biology", "Oceanic & Atmospheric Sciences",
             "Environmental Systems—Earth Sciences",
             "Environmental Systems—Ecology, Behavior and Evolution"],
            "https://scripps.ucsd.edu/people/faculty",
            {
                # Single server-rendered Drupal Views page (~207 rows, no
                # pagination) mixing Professor ranks with Researcher series,
                # emeriti, and adjuncts — the title regex keeps the ~100 ladder
                # professors. Names render "LAST, FIRST"; research topics are
                # per-row taxonomy links; emails are profile-page only (gated
                # pass fills them). NOTE: selectors were verified against a
                # 2-day-old snapshot + live-content cross-check — this host is
                # unreachable from some local egress paths (collection runs
                # fine from CI).
                "selectors": {
                    "card": "div.views-row",
                    "name": ".views-field--dir-name a",
                    "link": ".views-field--dir-name a",
                    "title": ".views-field--dir-title .field-content",
                    "title_strip_after": "/",
                    "email": ".views-field--dir-email a[href^='mailto:']",
                    "research_items": ".views-field-research-topic a",
                },
                "name_flip": True,
                "ladder_filter": {
                    "require": r"\bprofessor\b",
                    "drop": r"\bemerit|\badjunct|\bvisiting|\brecall|\brtad|\bpractice"},
                "profile_enrich": {
                    "email_selector": ".views-field--dir-email a[href^='mailto:']",
                    "throttle": 1.0,
                },
            },
        ),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
