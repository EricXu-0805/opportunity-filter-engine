"""MIT faculty config (via the faculty_graph engine).

MIT's departments each run their own site on their own subdomain — no shared
theme beyond small families — but everything is server-rendered static HTML
(no WAF, no render mode anywhere). ~30 departments across all five schools +
the Schwarzman College of Computing, all selectors live-verified 2026-07-15:

* School of Science: Math (custom cards; emails hidden as base64
  ``data-email`` — the engine's ``_decode_b64email`` recovers them on listing
  AND profile), Physics/EAPS (OPUS-WP teaser family), Chemistry, Biology
  (no rank text and no personal emails anywhere — dept policy), BCS (Drupal).
* School of Engineering: AeroAstro (tile links), BE/DMSE (faculty-teaser),
  ChemE (rank encoded in card CLASSES — the card selector unions the ladder
  ranks), CEE (self-link cards with a one-line research intro), EECS (the one
  big directory WITH emails + research tags), MechE ("Last, First" names;
  profile hrefs contain email-shaped IDs — they are IDs, not addresses),
  NSE (JS-only listing → WordPress REST, ``people_type=83`` = faculty),
  HST (paginated Drupal, no emails — Harvard-MIT joint institute).
* SHASS: Anthropology/PoliSci (Drupal "item" theme, emailed), CMSW (plain
  HTML tables behind a BROKEN TLS chain — ``insecure: True``; the host omits
  its intermediate cert), Economics (self-link teasers), Global Languages +
  History + IDSS (wp-block-post family, role in the ``li`` class list),
  Linguistics (bare link list under role headings), Philosophy (content boxes
  under ``h1`` role headings), Literature (Divi grid), Music & Theater Arts
  (Drupal 7 views, one mixed faculty+staff list — title filter), STS (WP-VIP
  host that 429s BROWSER UAs — ``ua: curl`` override; /people/sts-faculty/).
* Sloan: one giant static A-Z ``<dl>`` — the rank lives in the card's
  FOLLOWING ``<dd>`` sibling (engine ``title_sibling``). The directory lists
  each person once per ROLE (Joanne Yates ×4), so the parse count (~300)
  collapses to ~130 unique professors by design.
* SA+P: Architecture (paginated Drupal profile cards) + DUSP (same theme,
  one page, 228 people — title filter) + Media Lab (server-rendered PI list;
  profile links are ``data-href`` so records carry the directory URL).

Single source ("mit_faculty"); department rides each record, ids namespaced
by department short-code.

Deferred: Media Lab per-person profile URLs (data-href attribute — no href),
Biology/HST emails (none published), Sloan research prose (bio-only profiles),
Concourse/experimental programs.
"""

from __future__ import annotations

from .. import faculty_graph

# Ladder faculty: professor-titled ranks (incl. named chairs and "of the
# Practice"); drop emeriti/post-tenure/visiting/adjunct/instructors/research
# staff. Lecturers are dropped at MIT (Sloan alone lists 279 of them).
_LADDER = {
    "require": r"\bprofessor\b",
    "drop": (r"emerit|post-tenure|visiting|adjunct|\blecturer\b|instructor"
             r"|research scientist|research engineer|affiliat|in memoriam"),
}

# Departments whose roster is already faculty-only (class-filtered cards or a
# faculty-scoped URL): keep everyone except emeriti stragglers.
_LADDER_LIGHT = {"drop": r"emerit|post-tenure|in memoriam|visiting"}


def _dept(short: str, name: str, majors: list[str], url: str, selectors: dict,
          *, ladder: dict | None = _LADDER, enrich: dict | None = None,
          **scrape_extra) -> dict:
    scrape: dict = {"url": url, "selectors": selectors}
    if ladder:
        scrape["ladder_filter"] = ladder
    if enrich:
        scrape["profile_enrich"] = {**enrich, "throttle": 0.2}
    scrape.update(scrape_extra)
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


SCHOOL: dict = {
    "school_slug": "mit",
    "source": "mit_faculty",
    "organization": "Massachusetts Institute of Technology",
    "location": "Cambridge, MA",
    "id_prefix": "mit",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (MIT) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # ---- School of Science ---------------------------------------------
        _dept("MATH", "Department of Mathematics", ["Mathematics"],
              "https://math.mit.edu/directory/faculty/",
              {"card": "div.person", "name": ".name a", "link": ".name a",
               "title": ".title p", "email": "a.email-hidden"},
              name_flip=True),
        _dept("PHYS", "Department of Physics", ["Physics"],
              "https://physics.mit.edu/faculty/",
              {"card": ".card.faculty-card", "name": "h3 a",
               "link": "h3 a", "title": ".faculty-card__job-title"},
              enrich={"email_selector": ".faculty__email a[href^='mailto:']",
                      "email_drop": r"^[^@]*$",
                      "research_selector": ".faculty__header-research-areas"}),
        _dept("CHEM", "Department of Chemistry", ["Chemistry"],
              "https://chemistry.mit.edu/faculty/",
              {"card": ".faculty-profiles .profile", "name": "h2.entry-title",
               "link": "a.faculty-profile-link",
               "title": ".profile-landing-title span",
               "research": ".single-profile-description"},
              enrich={"email_selector": ".profile-info-item a[href^='mailto:']",
                      "email_drop": r"^[^@]*$"}),
        _dept("BIO", "Department of Biology", ["Biology"],
              "https://biology.mit.edu/faculty-and-research/faculty/",
              {"card": ".profile-item", "name": "h3", "link": "a",
               "research": "p.profile-description"},
              # Faculty-only roster; no rank text and no personal emails
              # anywhere (department policy) — records land unemailed.
              ladder=_LADDER_LIGHT),
        _dept("EAPS", "Department of Earth, Atmospheric and Planetary Sciences",
              ["Earth, Atmospheric and Planetary Sciences"],
              "https://eaps.mit.edu/people/faculty/",
              {"card": "article.faculty-tease", "name": "h3.faculty-tease__name",
               "link": "a.faculty-tease__link", "title": ".faculty-tease__role"},
              enrich={"email_selector": ".faculty-hero__info-item a[href^='mailto:']",
                      "email_drop": r"^[^@]*$",
                      "research_items_selector": ".faculty-hero__research-list li"}),
        _dept("BCS", "Department of Brain and Cognitive Sciences",
              ["Brain and Cognitive Sciences", "Neuroscience"],
              "https://bcs.mit.edu/faculty",
              {"card": "article.node--type-people-faculty", "name": ".person-name a",
               "link": ".person-name a",
               "title": ".field--name-field-primary-job-title"},
              enrich={"email_selector": ".field__item a[href^='mailto:']",
                      "email_drop": r"^[^@]*$",
                      "research_selector": ".field--name-field-research"}),
        # ---- School of Engineering -----------------------------------------
        _dept("AA", "Department of Aeronautics and Astronautics",
              ["Aeronautics and Astronautics", "Aerospace Engineering"],
              "https://aeroastro.mit.edu/faculty/",
              {"card": "a.tile__link", "name": ".tile__title", "link": ":self",
               "title": ".tile__description"},
              enrich={"email_selector": ".people__contact-details-value a[href^='mailto:']",
                      "email_drop": r"^[^@]*$",
                      "research_selector": ".person-header__research-areas"}),
        _dept("BE", "Department of Biological Engineering", ["Biological Engineering"],
              "https://be.mit.edu/faculty/",
              {"card": ".faculty-teaser", "name": ".faculty-teaser__title a",
               "link": ".faculty-teaser__title a", "title": ".faculty-teaser__roles",
               "research": ".faculty-teaser__summary"},
              enrich={"email_selector": ".faculty-contact__info a[href^='mailto:']",
                      "email_drop": r"^[^@]*$",
                      "research_selector": ".faculty-subjects-research__research-areas"}),
        _dept("CHEME", "Department of Chemical Engineering", ["Chemical Engineering"],
              "https://cheme.mit.edu/people/faculty/",
              # Rank rides the card CLASS list — union the ladder ranks and
              # skip emeriti/post-tenure/officer-only cards entirely.
              {"card": ("article.profile.rank-full-prof, article.profile.rank-associate-prof, "
                        "article.profile.rank-assistant-professor, article.profile.rank-inst-prof, "
                        "article.profile.rank-professor, article.profile.rank-jointly-appointed, "
                        "article.profile.rank-associate-professor-of-the-practice"),
               "name": "h2.faculty-name a", "link": "h2.faculty-name a",
               "name_strip": r"\s*arrow-right\s*$"},
              ladder=None,
              enrich={"email_selector": "a[href^='mailto:']",
                      "email_drop": r"^[^@]*$|chemeweb@"}),
        _dept("CEE", "Department of Civil and Environmental Engineering",
              ["Civil and Environmental Engineering"],
              "https://cee.mit.edu/faculty/",
              {"card": "a.people-item", "name": "h3", "link": ":self",
               "title": "span.profile-title", "research": "span.profile-intro"},
              enrich={"email_selector": "li a[href^='mailto:']",
                      "email_drop": r"^[^@]*$"}),
        _dept("EECS", "Department of Electrical Engineering and Computer Science",
              ["Electrical Engineering and Computer Science", "Computer Science"],
              "https://www.eecs.mit.edu/role/faculty/",
              {"card": ".people-entry:not(.no-show)", "name": "h5 a", "link": "h5 a",
               "title": "h5 + p", "email": "li a[href^='mailto:']",
               "research_items": ".people-research p a"},
              ladder=_LADDER_LIGHT),
        _dept("DMSE", "Department of Materials Science and Engineering",
              ["Materials Science and Engineering"],
              "https://dmse.mit.edu/people/faculty/",
              {"card": ".faculty-teaser", "name": "h2.faculty-teaser__name",
               "link": "a", "title": ".faculty-teaser__title"},
              enrich={"email_selector": ".info a[href^='mailto:']",
                      "email_drop": r"^[^@]*$"}),
        _dept("MECHE", "Department of Mechanical Engineering", ["Mechanical Engineering"],
              "https://meche.mit.edu/people",
              {"card": "a.clearfix[href*='/people/faculty/']", "name": "span.name",
               "link": ":self", "title": "span.title"},
              name_flip=True,
              enrich={"email_selector": "li.primary-contact-method.email a",
                      "email_drop": r"^[^@]*$",
                      "research_selector": ".interests"}),
        {
            # NSE's listing is JS-only; its WordPress REST API serves the
            # roster as JSON (people_type 83 = faculty; 90 = emeriti).
            "short": "NSE", "name": "Department of Nuclear Science and Engineering",
            "majors": ["Nuclear Science and Engineering"],
            "directory_url": "https://nse.mit.edu/people/?people_type=faculty",
            "api": {
                "type": "wp",
                "base": "https://nse.mit.edu",
                "post_type": "people",
                "category_include": {"people_type": [83]},
            },
            # Dept-level enrich: the wp-api source has no scrape block to hang it on.
            "profile_enrich": {
                "email_selector": ".h_info-container.email-container a",
                "email_drop": r"^[^@]*$",
                "research_selector": ".research-content",
                "throttle": 0.2,
            },
        },
        _dept("HST", "Institute for Medical Engineering and Science / HST",
              ["Bioengineering", "Biomedical Engineering"],
              "https://hst.mit.edu/faculty-research/faculty",
              {"card": "article.node--faculty-profile",
               "name": "h2.node__title",
               "link": "a.node--profile--teaser__link",
               "research_items": ".field--name-field-research-keywords .field__item"},
              # Joint Harvard-MIT institute: no rank text and no emails.
              ladder=None,
              paginate={"param": "page", "start": 1, "max": 6}),
        # ---- SHASS ----------------------------------------------------------
        _dept("ANTH", "Anthropology Program", ["Anthropology"],
              "https://anthropology.mit.edu/people/faculty",
              {"card": "article.item", "name": "h3.name a", "link": "h3.name a",
               "title": "p.title", "email": "p.contact.email a"}),
        _dept("CMSW", "Comparative Media Studies / Writing",
              ["Comparative Media Studies", "Writing"],
              "https://cmsw.mit.edu/people/",
              # Plain HTML tables; the host serves a broken TLS chain (missing
              # intermediate cert) — scrape-only insecure fetch.
              {"card": "table tr", "name": "td:nth-of-type(1)",
               "title": "td:nth-of-type(2)", "email": "td:nth-of-type(3)"},
              section_filter={"heading": "h3", "include": r"^faculty$"},
              insecure=True),
        _dept("ECON", "Department of Economics", ["Economics"],
              "https://economics.mit.edu/people/faculty",
              {"card": "a.profile-teaser", "name": "h3.profile-teaser__name",
               "link": ":self", "title": "h4.profile-teaser__title"},
              enrich={"email_selector": ".contact-info__data a[href^='mailto:']",
                      "email_drop": r"^[^@]*$"}),
        _dept("GSL", "Global Languages",
              ["French", "German Studies", "Spanish", "Chinese", "Japanese"],
              "https://languages.mit.edu/people/",
              {"card": "li.wp-block-post.people-type-global-languages-members",
               "name": ".wp-block-post-title a", "link": ".wp-block-post-title a",
               "title": ".mfb-repeater-item"},
              # Language faculty are lecturer-titled by design — keep them.
              ladder=_LADDER_LIGHT),
        _dept("HIST", "History Section", ["History"],
              "https://history.mit.edu/faculty/",
              {"card": "li.wp-block-post.position-faculty",
               "name": ".wp-block-post-title a", "link": ".wp-block-post-title a",
               "title": ".mfb-repeater-item"},
              ladder=_LADDER_LIGHT,
              enrich={"email_selector": ".field-item a[href^='mailto:']",
                      "email_drop": r"^[^@]*$|history-info@"}),
        _dept("LING", "Linguistics Section", ["Linguistics"],
              "https://linguistics.mit.edu/faculty/",
              {"card": ".menu-faculty-list-container a", "name": ":self",
               "link": ":self"},
              ladder=None,
              section_filter={"heading": "h2", "include": r"^faculty$"}),
        _dept("PHIL", "Philosophy Section", ["Philosophy"],
              "https://philosophy.mit.edu/faculty/",
              {"card": ".content-box-wrapper", "name": "h2.content-box-heading",
               "link": "a.heading-link", "title": ".content-container h5"},
              ladder=None,
              section_filter={"heading": "h1", "include": r"^faculty$"}),
        _dept("LIT", "Literature Section", ["Literature"],
              "https://lit.mit.edu/people/faculty/",
              {"card": "article.dp-dfg-item", "name": "h2.entry-title a",
               "link": "h2.entry-title a",
               "title": ".dp-dfg-cf-title .dp-dfg-custom-field-value"},
              ladder=_LADDER_LIGHT),
        _dept("MTA", "Music and Theater Arts Section", ["Music", "Theater Arts"],
              "https://mta.mit.edu/faculty-staff",
              {"card": ".views-row", "name": ".views-field-nothing-1 a",
               "link": ".views-field-nothing-1 a",
               "title": ".views-field-nothing .field-content",
               "email": ".views-field-field-person-email a[href^='mailto:']"}),
        _dept("POLISCI", "Department of Political Science", ["Political Science"],
              "https://polisci.mit.edu/people/faculty",
              {"card": "article.item", "name": ".namearea h2 a", "link": ".namearea h2 a",
               "title": "p.title", "email": "p.contact.email a"},
              enrich={"email_selector": "span.email a",
                      "email_drop": r"^[^@]*$",
                      "research_selector": "p.interests"}),
        _dept("STS", "Program in Science, Technology, and Society",
              ["Science, Technology, and Society"],
              "https://sts-program.mit.edu/people/sts-faculty/",
              # WP-VIP CDN 429s browser UAs on every request; an honest tool
              # UA passes clean.
              {"card": ".faculty-loop-item", "name": "h3.faculty-title",
               "link": "a", "title": "p.faculty-positions", "email": "a.email"},
              name_flip=True,
              ua="curl/8.7.1"),
        # ---- Sloan School of Management -------------------------------------
        _dept("SLOAN", "MIT Sloan School of Management",
              ["Management", "Finance", "Business Analytics"],
              "https://mitsloan.mit.edu/faculty/faculty-directory",
              # A-Z <dl>: the rank sits in the FOLLOWING <dd> sibling.
              {"card": "dt.directory--item-title", "name": "a", "link": "a",
               "title_sibling": "dd"},
              name_flip=True,
              enrich={"email_selector": ".page-profile-detail__get-in-touch-item a[href^='mailto:']",
                      "email_drop": r"^[^@]*$"}),
        # ---- School of Architecture + Planning ------------------------------
        _dept("ARCH", "Department of Architecture", ["Architecture", "Art and Design"],
              "https://architecture.mit.edu/people?roles_target_id=faculty&sort_bef_combine=field_last_name_value_ASC",
              {"card": "article.profile", "name": "h4.faux-full-title",
               "link": "a.card-link",
               "title": ".field--name-field-professional-titles"},
              paginate={"param": "page", "start": 1, "max": 5},
              enrich={"email_selector": ".field--name-field-user-contact-email a",
                      "email_drop": r"^[^@]*$"}),
        _dept("DUSP", "Department of Urban Studies and Planning",
              ["Urban Studies and Planning"],
              "https://dusp.mit.edu/people",
              {"card": "article.profile", "name": "h4.faux-full-title",
               "link": "a.card-link",
               "title": ".field--name-field-professional-titles"},
              enrich={"email_selector": ".field--name-field-user-contact-email a",
                      "email_drop": r"^[^@]*$"}),
        _dept("MEDIA", "Media Lab / Media Arts and Sciences", ["Media Arts and Sciences"],
              "https://www.media.mit.edu/people/",
              # Profile links are data-href (unreadable as href) — records
              # carry the directory URL; the static page is already the PI list.
              {"card": ".container-item.module.variant-person",
               "name": ".module-title", "title": ".module-subtitle"},
              ladder=_LADDER_LIGHT),
        # ---- Schwarzman College of Computing --------------------------------
        _dept("IDSS", "Institute for Data, Systems, and Society",
              ["Data Science", "Statistics"],
              "https://idss.mit.edu/people/faculty/core-faculty/",
              {"card": "li.wp-block-post.persons-category-core_faculty",
               "name": ".wp-block-post-title a", "link": ".wp-block-post-title a",
               "title": ".mfb-repeater-item", "email": "a[href^='mailto:']"},
              ladder=_LADDER_LIGHT),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
