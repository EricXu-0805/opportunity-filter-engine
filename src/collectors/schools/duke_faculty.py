"""Duke University faculty config (via the faculty_graph engine).

Two directory themes:

* **Pratt School of Engineering** — client-side-rendered department pages sharing
  a rich ``.faculty-overview`` card (name + profile link, public mailto, research
  interests), so records land emailed + keyworded in one render pass.

* **Trinity College of Arts & Sciences** — server-rendered department pages sharing
  a thin ``.member-card`` (a photo + name wrapped in a single ``<a>`` to the
  person's Scholars@Duke profile — no rank, email, or research on the listing).
  Like UCSD's bare link-lists, the record's core fields live on the profile, so a
  per-profile pass runs on every refresh (``always``): it reads the rank from the
  Scholars ``.sub-h1`` and the public email from ``.prof-contact-info``, and the
  ladder gate fires afterward (the ``/people/faculty`` listing mixes in cross-
  appointed emeriti). A ``link_filter`` keeps only Scholars-linked cards, dropping
  the handful of legacy dept-page emeritus links that can't be enriched.

* **School of Medicine (basic sciences)** — a Drupal Views + Duke-Scholars theme
  (Cloudflare -> render): ``.views-row`` cards with name + ``/profile`` link and
  the rank on the listing; email comes from the gated per-profile pass.

* **Trinity humanities** — the same ``.member-card`` + Scholars theme as the
  sciences, at each department's own faculty-listing path.

* **Nicholas (Environment) / Sanford (Public Policy) / Nursing** — three bespoke
  themes: a render+networkidle Drupal grid (Nicholas sits behind an Anubis
  proof-of-work wall, names only), a render ``.person-card`` grid with a
  Core-Faculty section filter (Sanford), and a server-rendered ``.directory-row``
  with mailto + Scholars link on the listing (Nursing).

Single source ("duke_faculty"); department rides each record's ``department``,
ids namespaced by department short-code. Audience "unknown".
"""

from __future__ import annotations

from .. import faculty_graph

_LADDER = {"require": r"\bprofessor\b", "drop": r"\bemerit"}

# Pratt School of Engineering shared theme: an ``article.faculty-overview`` card
# whose name + profile link live in ``.faculty-overview__info h3 a``, the public
# mailto in ``.faculty-overview__email``, and research interests in
# ``.faculty-overview__research``. Client-side rendered -> render mode.
_PRATT = {
    "card": ".faculty-overview",
    "name": ".faculty-overview__info h3 a",
    "link": ".faculty-overview__info h3 a",
    "email": ".faculty-overview__email",
    "research": ".faculty-overview__research",
}


def _pratt(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "render": True, "selectors": _PRATT,
                       "ladder_filter": _LADDER}}


# Trinity College shared theme: ``div.member-card`` = a single ``<a href=
# "scholars.duke.edu/person/..">`` wrapping the photo + a ``.h4`` name heading.
# No rank/email/research on the listing -> the Scholars@Duke profile pass supplies
# them (server-rendered, plain fetch). ``link_filter`` keeps only Scholars-linked
# cards so every kept record is enrichable + ladder-gatable.
_TRINITY = {"card": ".member-card", "name": ".h4", "link": "a"}
_SCHOLARS_ENRICH = {
    "always": True,
    "title_selector": ".sub-h1.font-bold",
    "email_selector": ".prof-contact-info a[href^='mailto:']",
    "ladder_recheck": {"require": r"\bprofessor\b",
                       "drop": r"\bemerit|\badjunct|\bvisiting|\blecturer"},
    "throttle": 0.25,
}


def _trinity(short: str, name: str, majors: list[str], host: str) -> dict:
    url = f"https://{host}.duke.edu/people/faculty"
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _TRINITY,
                       "link_filter": r"scholars\.duke\.edu/person/",
                       "profile_enrich": _SCHOLARS_ENRICH}}


# Duke School of Medicine basic-science departments share a Drupal Views + Duke-
# Scholars theme (Cloudflare -> render): a ``.views-row`` card with the name +
# ``/profile/<slug>`` link in ``h3.views-field-title a`` and the rank on the
# listing. Email lives on the profile, recovered by the gated per-profile pass
# (title is already on the listing, so weekly runs ladder-filter without it).
_BASIC_SCI_SEL = {"card": ".views-row", "name": "h3.views-field-title a",
                  "link": "h3.views-field-title a",
                  "title": ".views-field-duke-scholars-profile-positions-target-id .field-content"}


def _basic_sci(short: str, name: str, majors: list[str], url: str) -> dict:
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "render": True, "selectors": _BASIC_SCI_SEL,
                       "ladder_filter": _LADDER,
                       "profile_enrich": {"render": True, "throttle": 0.2,
                                          "email_selector": "a[href^='mailto:']"}}}


def _trinity_at(short: str, name: str, majors: list[str], url: str) -> dict:
    """A Trinity ``.member-card`` department whose faculty listing is at a
    non-standard path (the humanities depts vary: /people/faculty,
    /people/other-faculty/faculty, /people/appointed-faculty/primary-faculty)."""
    return {"short": short, "name": name, "majors": majors, "directory_url": url,
            "scrape": {"url": url, "selectors": _TRINITY,
                       "link_filter": r"scholars\.duke\.edu/person/",
                       "profile_enrich": _SCHOLARS_ENRICH}}


SCHOOL: dict = {
    "school_slug": "duke",
    "source": "duke_faculty",
    "organization": "Duke University",
    "location": "Durham, NC",
    "id_prefix": "duke",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (Duke University) — work authorization depends on the "
        "arrangement; ask the professor."
    ),
    "departments": [
        # --- Pratt School of Engineering (render mode, rich cards) ---
        _pratt("ECE", "Department of Electrical & Computer Engineering",
               ["Electrical Engineering", "Computer Engineering"],
               "https://ece.duke.edu/faculty"),
        _pratt("BME", "Department of Biomedical Engineering",
               ["Biomedical Engineering"], "https://bme.duke.edu/faculty"),
        _pratt("MEMS", "Department of Mechanical Engineering & Materials Science",
               ["Mechanical Engineering", "Materials Science"],
               "https://mems.duke.edu/faculty"),
        _pratt("CEE", "Department of Civil & Environmental Engineering",
               ["Civil Engineering", "Environmental Engineering"],
               "https://cee.duke.edu/faculty"),
        # --- Trinity College of Arts & Sciences (Scholars@Duke enrich) ---
        _trinity("BIO", "Department of Biology", ["Biology"], "biology"),
        _trinity("CHEM", "Department of Chemistry", ["Chemistry"], "chem"),
        _trinity("CS", "Department of Computer Science",
                 ["Computer Science"], "cs"),
        _trinity("ECON", "Department of Economics", ["Economics"], "econ"),
        _trinity("MATH", "Department of Mathematics", ["Mathematics"], "math"),
        _trinity("PHYS", "Department of Physics", ["Physics"], "phy"),
        _trinity("POLSCI", "Department of Political Science",
                 ["Political Science"], "polisci"),
        _trinity("PSYNEURO", "Department of Psychology & Neuroscience",
                 ["Psychology", "Neuroscience"], "psychandneuro"),
        _trinity("STAT", "Department of Statistical Science",
                 ["Statistical Science"], "stat"),
        # --- School of Medicine (basic sciences; Drupal Views + Scholars) ---
        _basic_sci("BIOCHEM", "Department of Biochemistry", ["Biochemistry"],
                   "https://www.biochem.duke.edu/faculty"),
        _basic_sci("CELLBIO", "Department of Cell Biology", ["Cell Biology"],
                   "https://www.cellbio.duke.edu/about-us/primary-faculty"),
        _basic_sci("MGM", "Department of Molecular Genetics & Microbiology", ["Molecular Genetics", "Microbiology"],
                   "https://mgm.duke.edu/about-us/faculty-and-staff/primary-faculty"),
        _basic_sci("NEURO", "Department of Neurobiology", ["Neurobiology", "Neuroscience"],
                   "https://www.neuro.duke.edu/people/primary-faculty"),
        _basic_sci("PHARM", "Department of Pharmacology & Cancer Biology", ["Pharmacology", "Cancer Biology"],
                   "https://www.pharmacology.duke.edu/primary-faculty"),
        _basic_sci("PATH", "Department of Pathology", ["Pathology"],
                   "https://pathology.duke.edu/faculty"),
        _basic_sci("BIOSTAT", "Department of Biostatistics & Bioinformatics", ["Biostatistics", "Bioinformatics"],
                   "https://biostat.duke.edu/people/all-faculty"),
        # --- Trinity College humanities (member-card + Scholars) ---
        _trinity_at("ENGLISH", "Department of English", ["English"],
                    "https://english.duke.edu/people/faculty"),
        _trinity_at("HIST", "Department of History", ["History"],
                    "https://history.duke.edu/people/faculty"),
        _trinity_at("PHIL", "Department of Philosophy", ["Philosophy"],
                    "https://philosophy.duke.edu/people/faculty"),
        _trinity_at("SOC", "Department of Sociology", ["Sociology"],
                    "https://sociology.duke.edu/people/faculty"),
        _trinity_at("AAHVS", "Department of Art, Art History & Visual Studies", ["Art History", "Visual Studies", "Visual Arts"],
                    "https://aahvs.duke.edu/people/faculty"),
        _trinity_at("ROMST", "Department of Romance Studies", ["Romance Studies", "French", "Italian", "Spanish"],
                    "https://romancestudies.duke.edu/people/faculty"),
        _trinity_at("CLST", "Department of Classical Studies", ["Classical Studies", "Classics"],
                    "https://classicalstudies.duke.edu/people/faculty"),
        _trinity_at("GERM", "Department of Germanic Languages & Literature", ["German Studies", "German"],
                    "https://german.duke.edu/people/faculty"),
        _trinity_at("AAAS", "Department of African & African American Studies", ["African & African American Studies"],
                    "https://aaas.duke.edu/people/faculty"),
        _trinity_at("CULANTH", "Department of Cultural Anthropology", ["Cultural Anthropology"],
                    "https://culturalanthropology.duke.edu/people/faculty"),
        _trinity_at("AMES", "Department of Asian & Middle Eastern Studies", ["Asian & Middle Eastern Studies"],
                    "https://asianmideast.duke.edu/people/faculty"),
        _trinity_at("LING", "Program in Linguistics", ["Linguistics"],
                    "https://linguisticsprogram.duke.edu/people/faculty"),
        _trinity_at("RELST", "Department of Religious Studies", ["Religious Studies"],
                    "https://religiousstudies.duke.edu/people/other-faculty/faculty"),
        _trinity_at("GSF", "Program in Gender, Sexuality & Feminist Studies", ["Gender, Sexuality & Feminist Studies"],
                    "https://gendersexualityfeminist.duke.edu/people/appointed-faculty/primary-faculty"),
        _trinity_at("MUSIC", "Department of Music", ["Music"],
                    "https://music.duke.edu/people/other-faculty/all-faculty"),
        # --- Nicholas (Environment), Sanford (Public Policy), Nursing ---
        {
            "short": "PUBPOL",
            "name": "Sanford School of Public Policy",
            "majors": ["Public Policy", "Public Administration"],
            "directory_url": "https://sanford.duke.edu/sanford-faculty/",
            # /people/faculty 301s to /sanford-faculty/. The .personlist__wrapper
            # sections render client-side (empty in server HTML) -> render mode. Cards
            # are .person-card: name+on-site profile link + rank on the listing, no
            # email. Five h2 sections (Core/Visiting/Emeriti/Secondary&Adjunct/Research
            # Scholars) -> section_filter keeps just Core Faculty. Email lives on the
            # profile (/profile/<slug>/, plain-fetchable) -> gated per-profile pass.
            "scrape": {
                "url": "https://sanford.duke.edu/sanford-faculty/",
                "render": True,
                "selectors": {
                    "card": ".person-card",
                    "name": ".person-card__content h3.heading a",
                    "link": ".person-card__content h3.heading a",
                    "title": ".person-card-position",
                },
                "section_filter": {"heading": "h2", "include": r"Core Faculty"},
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\badjunct|\bvisiting|\blecturer"},
                "profile_enrich": {"email_selector": "aside.profile-meta a[href^='mailto:']",
                                   "throttle": 0.15},
            },
        },
        {
            "short": "ENV",
            "name": "Nicholas School of the Environment",
            "majors": ["Environmental Science", "Environmental Policy",
                       "Earth & Climate Sciences", "Marine Science & Conservation"],
            "directory_url": "https://nicholas.duke.edu/people/faculty",
            # Whole subdomain is behind an Anubis proof-of-work bot wall: a plain fetch
            # returns a 5.8KB "not a bot" challenge for every path, and /faculty is a 404
            # stub -- the real listing is /people/faculty. render_wait="networkidle"
            # clears the challenge (domcontentloaded fires too early); the Drupal Views
            # grid then exposes .node--type-person cards (name in
            # .field--name-node-title h2 a, rank in .field--name-field-employment-position).
            # No email on the listing; ships name+rank+dept (see profile_enrich note).
            "scrape": {
                "url": "https://nicholas.duke.edu/people/faculty",
                "render": True,
                "render_wait": "networkidle",
                "selectors": {
                    "card": ".node--type-person",
                    "name": ".field--name-node-title h2 a",
                    "link": ".field--name-node-title h2 a",
                    "title": ".field--name-field-employment-position",
                },
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\badjunct|\bvisiting|\blecturer"},
                # Optional email recovery: the profile carries a public mailto, but each
                # profile sits behind the SAME Anubis wall, so the pass must render every
                # one (render_wait networkidle) ~39s/profile => ~45-70min for ~70 faculty.
                # Enable only for the deliberate one-shot enrichment run:
                # "profile_enrich": {"always": True, "render": True,
                #                    "render_wait": "networkidle",
                #                    "email_selector": "a[href^='mailto:']"},
            },
        },
        {
            "short": "NURS",
            "name": "School of Nursing",
            "majors": ["Nursing"],
            "directory_url": "https://nursing.duke.edu/directories/faculty",
            # /faculty is 404; the searchable listing is /directories/faculty, fully
            # server-rendered (no render needed). Each .directory-row carries name +
            # Scholars@Duke link (h3.faculty_staff_title a), rank in .magnolia-title, and
            # a public mailto on the card -> emailed + titled in one listing pass.
            # Post-nominal credentials on the name (", PhD, RN, FAAN") are stripped by
            # the engine's _strip_credentials.
            "scrape": {
                "url": "https://nursing.duke.edu/directories/faculty",
                "selectors": {
                    "card": ".directory-row",
                    "name": "h3.faculty_staff_title a",
                    "link": "h3.faculty_staff_title a",
                    "title": ".magnolia-title",
                    "email": "a[href^='mailto:']",
                },
                "ladder_filter": {"require": r"\bprofessor\b",
                                  "drop": r"\bemerit|\badjunct|\bvisiting|\blecturer|\bconsulting|\binstructor"},
            },
        },
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
