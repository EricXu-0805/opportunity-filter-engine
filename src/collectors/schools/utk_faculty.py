"""University of Tennessee, Knoxville faculty config (via the faculty_graph engine).

UTK is a WordPress campus (the ``utkwds`` design system): almost every college
and department serves a server-rendered directory to a bare Chrome request (no
WAF, no client-only SPA), so coverage rides a handful of shared markup families
plus a few bespoke rosters. Live-verified 2026-07-24.

Markup families
---------------
* **``sngl-ppl`` card — the College of Arts & Sciences standard.** Almost every
  A&S department publishes the same "single-people" component: ``div.sngl-ppl-wrp``
  holding a ``.sngl-ppl__name`` heading (``h2`` or ``h3`` — key off the class),
  a ``.sngl-ppl__ttl`` rank, a real ``.sngl-ppl__email`` mailto, and a
  ``.sngl-ppl__prfl-link`` profile anchor. One selector covers Physics, Chemistry,
  Mathematics, Anthropology, Biochemistry & Cellular/Molecular Biology, Ecology &
  Evolutionary Biology, Microbiology, Classics, English, Geography, History,
  Philosophy, Sociology, Theatre, Psychology, and Religious Studies — all
  landed name+title+email in one static pass. The ``field_filter`` (not
  ``ladder_filter``) reads ``.sngl-ppl__ttl`` directly, drops title-less staff
  (so they can't default to "Professor" and leak), and keeps only
  Professor/Lecturer ranks; emeriti drop via the engine's ``_RETIRED_TITLE_RE``.

* **EECS custom ``div.person`` card.** ``span.gal_name`` (inside the profile ``a``),
  ``span.gal_title``, plus a ``span.gal_research`` interests line unique to this
  school (keywords without a per-profile fetch). No email on the listing
  (recovered downstream by OpenAlex / the profile pass). Civil & Environmental
  Engineering shares the ``div.person`` markup but has NO listing email and no
  research line, so it rides an ``always`` ``profile_enrich`` that follows each
  profile for the Cloudflare-obfuscated address.

* **``profileCard`` (Tickle College).** ``div.profileCard`` with an
  ``h3.profileName`` name, ``p.profileTitle`` rank, and a Cloudflare-shielded
  ``data-cfemail`` address (XOR-decoded by ``_decode_cfemail``). Materials Science
  (research on the listing via ``research_re``) and Industrial & Systems
  Engineering both land emailed here.

* **Nested ``wp-block-group`` (Gutenberg rosters).** Mechanical/Aerospace/Biomedical
  Engineering nests three identically-classed groups per person; the outer wrapper
  is the card, pinned with ``:has()``. Materials & the professional colleges
  (Social Work, Music, and the CCI schools of Advertising/PR and Information
  Sciences) use the same shape with an ``h3`` heading — a ``field_filter`` on the
  first ``p.wp-block-paragraph`` keeps only professor/lecturer ranks and the
  Cloudflare address is decoded at listing tier.

* **CBE table + profile enrich.** Chemical & Biomolecular Engineering renders a
  ``table.faculty`` (name/title/research columns) with the email only on each
  profile (plain mailto) — an ``always`` ``profile_enrich`` recovers it; the
  ladder gate drops emeriti/adjuncts (the table is faculty-only, and several
  chairs carry admin titles with no literal "Professor", so this is a drop gate
  rather than a require gate).

* **Bespoke rosters.** Political Science (``h2.people`` + ``p.field`` interests +
  ``p.fancyLink`` mailto; the rank ``<p>`` trails "Fields of Interest:", trimmed
  via ``title_strip_after``), World Languages & Cultures (``h2.people-name`` +
  ``p.fancyLink`` mailto), and Architecture & Design (Foundation ``div.fs-cell``
  cards, ``h2.contact_name`` + ``div.contact_title`` + a Cloudflare
  ``a.contact_detail_info_link``; the directory paints only the first page
  server-side and loads the rest via a ``/directory/page/N/`` path, walked with
  ``paginate`` mode ``path``).

Single source ("utk_faculty"); department rides each record, ids namespaced by
department short-code.

Dropped / phase-2 (recorded from the 2026-07-24 recon)
------------------------------------------------------
* **Nuclear Engineering** — the roster is painted by an AJAX ``datafetch``
  loader; there is no ``people`` WordPress REST post type and a headless render
  (networkidle) still yields no roster cards. Needs the datafetch endpoint reverse-
  engineered.
* **College of Nursing** — the ``wp-block-group`` roster renders ~60 ladder
  faculty but carries ZERO emails at listing tier (only a general-inquiries inbox);
  email-less, needs a profile-enrich phase-2.
* **Haslam College of Business** (Accounting, Finance, Marketing, Management,
  Business Analytics & Statistics, Supply Chain, Economics) — no open per-department
  faculty directory found; the site exposes only a curated "faculty-experts" page.
* **College of Education, Health & Human Sciences** (Nutrition, Kinesiology, Public
  Health, Child & Family Studies, Audiology & Speech Pathology, Retail/Hospitality/
  Tourism) — a ``cehhs.utk.edu/<dept>/`` multisite whose per-department roster paths
  were not resolved this pass.
* **Herbert College of Agriculture / UTIA** — separate ``tennessee.edu`` domain,
  not resolved this pass.
* **CCI Communication Studies & Journalism** — both school directories redirect to
  the college's administrative-offices directory (no per-school faculty roster);
  the main CCI ``/directory/`` gates to only ~6 faculty (staff-heavy).
* **School of Art, Statistics, Neuroscience, Global Studies, Cinema Studies** —
  interdisciplinary programs or a directory that redirects to a news page; no
  standalone ladder roster.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Shared A&S "sngl-ppl" component ----------------------------------------
_SNGL_SEL = {
    "card": "div.sngl-ppl-wrp",
    "name": ".sngl-ppl__name",
    "link": ".sngl-ppl__prfl-link a",
    "title": ".sngl-ppl__ttl",
    "email": ".sngl-ppl__email a[href^='mailto:']",
}
# field_filter (not ladder_filter): require_present drops title-less staff cards
# (they'd default to "Professor"); include keeps professor/lecturer; emeriti drop
# via the retired gate.
_SNGL_FIELD = {
    "selector": ".sngl-ppl__ttl",
    "require_present": True,
    "include": r"professor|lecturer",
}

# ---- EECS / CEE custom "div.person" card ------------------------------------
_EECS_SEL = {
    "card": "div.person",
    "name": "span.gal_name",
    "link": ".person-image a",
    "title": "span.gal_title",
    "research": "span.gal_research",
}
_PERSON_SEL = {
    "card": "div.person",
    "name": "span.gal_name",
    "link": "div.person > a",
    "title": "span.gal_title",
}
# CEE keeps no listing email; the profile carries a Cloudflare address. always=True
# because the address is the record's only contact value, not optional depth.
_CEE_ENRICH = {
    "email_selector": "a[href*='email-protection']",
    "email_drop": r"^[^@]*$|^cee@",
    "always": True,
    "throttle": 0.1,
    "timeout": 8,
}

# ---- profileCard (Tickle College) -------------------------------------------
_MSE_SEL = {
    "card": "div.profileCard",
    "name": ".profileName",
    "link": "a[href*='/faculty/']",
    "title": "p.profileTitle",
    "email": "a[href*='email-protection']",
    "research_re": r"Research Expertise:(.*?)</p>",
}
_ISE_SEL = {
    "card": "div.profileCard",
    "name": "h3.profileName",
    "link": "a[href*='/faculty/']",
    "title": "p.profileTitle",
    "email": "a[href*='email-protection']",
}

# ---- MAE nested wp-block-group (Tickle College) -----------------------------
_MAE_SEL = {
    "card": "div.wp-block-group:has(> div > h2.wp-block-heading.has-large-font-size)",
    "name": "h2.wp-block-heading.has-large-font-size",
    "link": "p.is-style-utkwds-single-link a",
    "title": "p.wp-block-paragraph",
    "email": "a[href*='email-protection']",
}

# ---- Gutenberg wp-block-group rosters (h3 heading) --------------------------
# Social Work, Music, and the CCI schools share the nested-group shape with an h3
# name and the rank in the first p.wp-block-paragraph; the Cloudflare address is
# decoded at listing tier. field_filter keeps only professor/lecturer ranks.
def _wpblk_sel(card: str) -> dict:
    return {
        "card": card,
        "name": "h3.wp-block-heading",
        "title": "p.wp-block-paragraph",
        "email": "a[href*='email-protection']",
    }
_WPBLK_FIELD = {
    "selector": "p.wp-block-paragraph",
    "require_present": True,
    "include": r"professor|lecturer",
}

# ---- Bespoke: Political Science ---------------------------------------------
_POLI_SEL = {
    "card": "div.entry-content:has(> h2.people)",
    "name": "h2.people",
    "link": "p.fancyLink a[href*='/person/']",
    "title": "p:first-of-type",
    "title_strip_after": r"\s*Fields of Interest",
    "research_re": r'class="field">(.*?)</p>',
    "email": "p.fancyLink a[href^='mailto:']",
}

# ---- Bespoke: World Languages & Cultures ------------------------------------
_WLC_SEL = {
    "card": "div:has(> h2.people-name)",
    "name": "h2.people-name a",
    "link": "h2.people-name a",
    "title": "p:first-of-type",
    "email": "p.fancyLink a[href^='mailto:']",
}

# ---- Bespoke: Architecture & Design (render for full roster) ----------------
_ARCH_SEL = {
    "card": "div.fs-cell:has(div.contact_details)",
    "name": "h2.contact_name",
    "link": "a.contact_name_link",
    "title": "div.contact_title",
    "email": "a.contact_detail_info_link[href*='email-protection']",
}

_LADDER = {"require": r"professor|lecturer"}
_CBE_LADDER = {"drop": r"emerit|adjunct|visiting|courtesy|of practice"}


def _dept(short: str, name: str, majors: list[str], url: str, sel: dict,
          *, field: dict | None = None, ladder: dict | None = None,
          enrich: dict | None = None) -> dict:
    scrape: dict = {"url": url, "selectors": sel}
    if field:
        scrape["field_filter"] = field
    if ladder:
        scrape["ladder_filter"] = ladder
    if enrich:
        scrape["profile_enrich"] = enrich
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": scrape,
    }


def _sngl(short: str, name: str, majors: list[str], url: str) -> dict:
    """An A&S department on the shared sngl-ppl component."""
    return _dept(short, name, majors, url, _SNGL_SEL, field=_SNGL_FIELD)


SCHOOL: dict = {
    "school_slug": "utk",
    "source": "utk_faculty",
    "organization": "University of Tennessee, Knoxville",
    "location": "Knoxville, TN",
    "id_prefix": "utk",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of Tennessee, Knoxville) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ==== College of Arts & Sciences (sngl-ppl) ======================
        _sngl("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy", "Astrophysics"],
              "https://physics.utk.edu/faculty/"),
        _sngl("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
              "https://chem.utk.edu/faculty/"),
        _sngl("MATH", "Department of Mathematics",
              ["Mathematics", "Applied Mathematics"],
              "https://math.utk.edu/directory/faculty/"),
        _sngl("ANTH", "Department of Anthropology", ["Anthropology"],
              "https://anthropology.utk.edu/people/faculty/"),
        _sngl("BCMB", "Department of Biochemistry and Cellular and Molecular Biology",
              ["Biochemistry", "Molecular Biology", "Biological Sciences"],
              "https://bcmb.utk.edu/directory/faculty/"),
        _sngl("EEB", "Department of Ecology and Evolutionary Biology",
              ["Biological Sciences", "Ecology", "Evolutionary Biology"],
              "https://eeb.utk.edu/faculty/"),
        _sngl("MICRO", "Department of Microbiology", ["Microbiology"],
              "https://micro.utk.edu/faculty/"),
        _sngl("CLAS", "Department of Classics", ["Classics"],
              "https://classics.utk.edu/directory/faculty/"),
        _sngl("ENGL", "Department of English",
              ["English", "Creative Writing", "Rhetoric and Writing"],
              "https://english.utk.edu/directory/all-faculty/"),
        _sngl("GEOG", "Department of Geography and Sustainability",
              ["Geography", "Geographic Information Science"],
              "https://geography.utk.edu/people/faculty/"),
        _sngl("HIST", "Department of History", ["History"],
              "https://history.utk.edu/people/faculty/"),
        _sngl("PHIL", "Department of Philosophy", ["Philosophy"],
              "https://philosophy.utk.edu/directory/faculty/"),
        _sngl("SOC", "Department of Sociology", ["Sociology"],
              "https://sociology.utk.edu/directory/faculty/"),
        _sngl("THEA", "Department of Theatre", ["Theatre"],
              "https://theatre.utk.edu/faculty/"),
        _sngl("PSYC", "Department of Psychology",
              ["Psychology", "Neuroscience"],
              "https://psychology.utk.edu/directory/our-faculty/"),
        _sngl("RELI", "Department of Religious Studies", ["Religious Studies"],
              "https://religion.utk.edu/directory/our-faculty/"),
        # ---- A&S bespoke ------------------------------------------------
        _dept("POLI", "Department of Political Science", ["Political Science"],
              "https://polisci.utk.edu/faculty/", _POLI_SEL, ladder=_LADDER),
        _dept("WLC", "Department of World Languages and Cultures",
              ["World Languages and Cultures", "Linguistics", "Global Studies"],
              "https://wlc.utk.edu/people-3/faculty/", _WLC_SEL, ladder=_LADDER),
        # ==== Tickle College of Engineering ==============================
        # EECS (eecs.utk.edu) dropped — listing is 100% email-less name-only
        # (mailto client-painted); needs a profile-enrich/headless pass (phase-2).
        _dept("MABE", "Department of Mechanical, Aerospace and Biomedical Engineering",
              ["Mechanical Engineering", "Aerospace Engineering", "Biomedical Engineering"],
              "https://tickle.utk.edu/mae/faculty/", _MAE_SEL, ladder=_LADDER),
        _dept("MSE", "Department of Materials Science and Engineering",
              ["Materials Science & Engineering", "Materials Engineering"],
              "https://tickle.utk.edu/mse/faculty/", _MSE_SEL, ladder=_LADDER),
        _dept("ISE", "Department of Industrial and Systems Engineering",
              ["Industrial Engineering", "Systems Engineering"],
              "https://tickle.utk.edu/ise/faculty/", _ISE_SEL, ladder=_LADDER),
        _dept("CEE", "Department of Civil and Environmental Engineering",
              ["Civil Engineering", "Environmental Engineering"],
              "https://cee.utk.edu/faculty/", _PERSON_SEL,
              ladder=_LADDER, enrich=_CEE_ENRICH),
        _dept("CBE", "Department of Chemical and Biomolecular Engineering",
              ["Chemical Engineering"],
              "https://cbe.utk.edu/faculty/",
              {"card": "table.faculty tr:has(td.table-info)",
               "name": "td.table-info h3 a",
               "link": "td.table-info h3 a",
               "title": "td.table-info span"},
              ladder=_CBE_LADDER,
              enrich={"email_selector": "a[href^='mailto:']",
                      "email_drop": r"^[^@]*$|^cbe@",
                      "always": True, "throttle": 0.1, "timeout": 8}),
        # ==== College of Social Work =====================================
        _dept("CSW", "College of Social Work", ["Social Work"],
              "https://csw.utk.edu/about/directory/",
              _wpblk_sel("div.wp-block-group:has(> div > h3.wp-block-heading)"),
              field=_WPBLK_FIELD),
        # ==== Natalie L. Haslam College of Music =========================
        _dept("MUSIC", "Natalie L. Haslam College of Music",
              ["Music", "Theory/Composition", "Studio Music & Jazz", "Voice"],
              "https://music.utk.edu/about/directory/faculty/",
              _wpblk_sel("div.wp-block-group:has(> h3.wp-block-heading)"),
              field=_WPBLK_FIELD),
        # ==== College of Communication & Information (per-school) =========
        _dept("ADPR", "Tombras School of Advertising and Public Relations",
              ["Advertising", "Public Relations"],
              "https://cci.utk.edu/adpr/about/directory/",
              _wpblk_sel("div.wp-block-group:has(> div > h3.wp-block-heading)"),
              field=_WPBLK_FIELD),
        _dept("SIS", "School of Information Sciences",
              ["Information Sciences"],
              "https://cci.utk.edu/sis/about/directory/",
              _wpblk_sel("div.wp-block-group:has(> div > h3.wp-block-heading)"),
              field=_WPBLK_FIELD),
        # ==== College of Architecture & Design ===========================
        # The directory paints only the first page server-side and loads the rest
        # via a /directory/page/N/ path (Foundation grid, ~10 cards/page).
        {
            "short": "ARCH", "name": "College of Architecture and Design",
            "majors": ["Architecture", "Interior Architecture", "Graphic Design",
                       "Landscape Architecture"],
            "directory_url": "https://archdesign.utk.edu/directory/",
            "scrape": {
                "url": "https://archdesign.utk.edu/directory/",
                "selectors": _ARCH_SEL,
                "field_filter": {"selector": "div.contact_title",
                                 "require_present": True,
                                 "include": r"professor|lecturer"},
                "paginate": {"mode": "path", "param": "page", "start": 2, "max": 8},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
