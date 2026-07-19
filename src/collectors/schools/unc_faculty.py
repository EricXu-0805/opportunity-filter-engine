"""University of North Carolina at Chapel Hill faculty config (faculty_graph).

UNC-CH has NO single shared faculty platform. Every department site is its own
WordPress multisite install (cas-wp1.oasis.unc.edu for the College of Arts &
Sciences), and each dept has picked its own theme/generation, so — unlike the
VT AEM fleet — the markup is genuinely bespoke per department. Recon
(curl, real Chrome UA, ~1 req/sec, 2026-07-19) grouped the STATICALLY-rendered,
cleanly-parseable rosters into these loose families; the many departments whose
"People" pages render their roster only via a client-side WP-Views AJAX call
(empty in static HTML) or via a two-column split layout are DEFERRED below.

Families (all plain HTTP 200, no WAF, no render mode anywhere):

* ``wpv_inline`` — the Toolset/WP-Views bio-card list rendered SERVER-SIDE.
  Biology is the confirmed inline member: ``.js-wpv-view-layout`` wraps one
  ``div.row`` per person (``.col-sm-2`` photo + ``.col-sm-10`` info + a
  ``.col-sm-12`` "Research interests:" blurb). Name is "Last, First" in the
  first ``.col-sm-10 span`` (flipped), rank in ``em``, a plain mailto, and the
  profile link is the ``/faculty-profile/<slug>/`` anchor. NB most OTHER CAS
  depts (sociology people-page excepted, English, religion, anthropology's
  sibling depts) carry the SAME ``js-wpv-view-layout`` markers but with an
  EMPTY layout in static HTML — those load the view over admin-ajax and are
  deferred (would need render mode + a bespoke ajax view-hash).

* ``fac_member`` — the older custom "Faculty Member" CPT theme keyed on
  ``/faculty-member/<slug>/`` profile links, but with per-dept card wrappers:
  MATH uses ``div.col-md-12`` cards (``.faculty-name-strong`` = "Last, First",
  ``.faculty-name`` = rank, inline mailto); STOR uses ``div.row`` cards holding
  a ``.faculty-holder-strong`` name link (rank recovered by title-regex);
  ROMANCE STUDIES uses the newer block-theme ``.people-container`` group
  (``h2`` name in natural order, rank by title-regex, inline mailto).

* ``block_people`` — the newest Gutenberg block theme exposing a ``people``
  custom-post-type with a public WP REST feed AND a ``role`` taxonomy.
  CHEMISTRY is served via the ``api`` (wp) mechanism straight off
  ``/wp-json/wp/v2/people`` filtered to the ``faculty`` role term (id 13, 56
  people) excluding emeriti/adjunct terms — the authoritative complete roster;
  emails live on the profile pages (env-gated profile pass backfills them).

* ``h2_card`` — hand-built block columns, one person per
  ``div.tb-fields-and-text`` (ANTHROPOLOGY): ``h2`` name (natural order),
  first ``p strong`` = rank, inline mailto.

* ``table`` — SOCIOLOGY's people-page table: one ``tr`` per person with a
  ``/people-page/<slug>/`` name link, a phone cell, an inline mailto, and a
  rank cell (recovered by title-regex).

* ``hand_seq`` — PHYSICS & ASTRONOMY hand-built page with NO per-person
  wrapper: an ``h4`` name anchor followed by sibling ``h5`` rank/address/email.
  Card = the ``h4``; rank is picked up via ``title_sibling`` (the next ``h5``);
  the email h5 uses a malformed (non-mailto) href so listing email is absent —
  the env-gated profile pass recovers it.

Every profile publishes a plain mailto, so the env-gated ``profile_enrich``
pass (``OFE_ENRICH_PROFILES=1``, run centrally, NOT in this verify) backfills
email everywhere the listing lacks it (physics, chem). Single source
("unc_faculty"); department rides each record, ids namespaced by short-code.

Deferred (2026-07-19 recon), with reasons:
* Computer Science (cs.unc.edu) — /people/faculty/ 301-redirects into a
  JS-driven directory; roster is not in static HTML (needs render + a bespoke
  card scrape). High-value; revisit with render mode.
* Statistics & Operations Research is INCLUDED (STOR); Applied Physical
  Sciences (aps.unc.edu) — host did not resolve/serve during recon.
* Earth/Marine/Environmental Sciences (emes.unc.edu), Marine Sciences — new
  merged-dept hostnames not located/served this pass.
* Psychology & Neuroscience — /people/faculty/ WP-View is AJAX-empty in static
  HTML (render + ajax view-hash needed).
* English & Comparative Literature, History, Philosophy, Classics,
  Communication, Music, Art & Art History, Geography, Exercise & Sport
  Science, American Studies, African/African-American Studies, Women's &
  Gender Studies, Germanic & Slavic, Public Policy — either AJAX-rendered
  WP-Views (empty static roster) or bespoke non-card paths; not verifiable
  statically this session.
* Asian & Middle Eastern Studies — inline emails present but the roster uses a
  two-column ``col-sm-6`` split (name column separate from the contact
  column), which the single-card engine model can't join without a bespoke
  fetcher.
* Economics, Political Science — dept hosts timed out / 000 repeatedly.
* Gillings School of Global Public Health depts (Biostatistics, Epidemiology,
  Health Policy & Management, Health Behavior, Nutrition, Environmental
  Sciences & Engineering, Maternal & Child Health), Nursing, Pharmacy,
  Education, School of Data Science & Society, Kenan-Flagler Business, School
  of Information & Library Science — hosted off separate domains / behind
  ?_role AJAX filters; each needs its own probe pass. Onboard in a follow-up.
* School of Medicine clinical departments — clinical faculty need their own
  gate; out of scope for the undergraduate-research audience.
"""

from __future__ import annotations

from .. import faculty_graph

# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------
# Drop research-staff / non-ladder titles. "Research Professor" survives via
# the negative lookahead; teaching professors and lecturers are kept.
_DROP = (r"emerit|adjunct|affiliat|visiting|courtesy|postdoc|emeritus"
         r"|research (?:associate|assistant|scientist)(?!\s+professor)")
_LADDER = {"drop": _DROP}

# Rank extractor for cards whose title is loose text near the name (STOR / ROM
# / SOC). Case-sensitive by engine design — ranks are Titled.
_TITLE_RE = (r"\b((?:Distinguished\s+|Teaching\s+|Research\s+|Clinical\s+|"
             r"Associate\s+|Assistant\s+|Adjunct\s+|Visiting\s+)*"
             r"(?:Professor|Lecturer|Instructor)"
             r"(?:\s+of\s+(?:the\s+)?Practice)?)")

# Every UNC profile publishes a plain mailto — the env-gated pass backfills
# email where the listing lacks it, and re-drops any emeriti a profile reveals.
_ENRICH = {
    "email_selector": "a[href^='mailto:']",
    "throttle": 0.3,
}


def _scrape(short, name, majors, url, selectors, *, ladder=_LADDER,
            name_flip=False, section=None, enrich=_ENRICH):
    scrape = {"url": url, "selectors": selectors, "ladder_filter": ladder}
    if name_flip:
        scrape["name_flip"] = True
    if section:
        scrape["section_filter"] = section
    if enrich:
        scrape["profile_enrich"] = enrich
    return {"short": short, "name": name, "majors": majors,
            "directory_url": url, "scrape": scrape}


SCHOOL: dict = {
    "school_slug": "unc",
    "source": "unc_faculty",
    "organization": "University of North Carolina at Chapel Hill",
    "location": "Chapel Hill, NC",
    "id_prefix": "unc",
    "audience": "unknown",
    "work_auth_notes": (
        "External campus (University of North Carolina at Chapel Hill) — work "
        "authorization depends on the arrangement; ask the professor."
    ),
    "departments": [
        # ---- wpv_inline (server-rendered WP-Views bio cards) ---------------
        _scrape(
            "BIOL", "Department of Biology", ["Biology", "Biological Sciences"],
            "https://bio.unc.edu/people/faculty/",
            {"card": ".js-wpv-view-layout div.row:has(div.col-sm-10)",
             "name": "div.col-sm-10 span",
             "link": "a[href*='/faculty-profile/']",
             "title": "div.col-sm-10 em",
             "email": "div.col-sm-10 a[href^='mailto:']",
             "research_re": r"Research interests:\s*</strong>\s*([^<]{3,300})"},
            name_flip=True),
        # ---- block_people (WP REST people CPT, role taxonomy) --------------
        {
            "short": "CHEM", "name": "Department of Chemistry", "majors": ["Chemistry"],
            "directory_url": "https://chem.unc.edu/people/?_role=faculty",
            "api": {
                "type": "wp",
                "base": "https://chem.unc.edu",
                "post_type": "people",
                "category_include": {"role": [13]},        # Faculty
                "category_exclude": {"role": [70, 71]},     # Emeriti, Adjunct
            },
            "profile_enrich": _ENRICH,
        },
        # ---- fac_member (Faculty Member CPT, per-dept wrappers) ------------
        _scrape(
            "MATH", "Department of Mathematics", ["Mathematics"],
            "https://math.unc.edu/people/faculty/",
            {"card": "div.col-md-12:has(.faculty-name-strong)",
             "name": ".faculty-name-strong",
             "link": "a[href*='/faculty-member/']",
             "title": ".faculty-name",
             "email": "a[href^='mailto:']"},
            name_flip=True),
        _scrape(
            "STOR", "Department of Statistics and Operations Research",
            ["Statistics", "Operations Research", "Statistics and Analytics"],
            "https://stor.unc.edu/people/faculty/",
            {"card": "div.row:has(.faculty-holder-strong)",
             "name": ".faculty-holder-strong",
             "link": "a[href*='/faculty-member/']",
             "title_re": _TITLE_RE,
             "email": "a[href^='mailto:']"},
            name_flip=True),
        _scrape(
            "ROML", "Department of Romance Studies",
            ["Romance Languages", "Spanish", "French"],
            "https://romancestudies.unc.edu/people/faculty/",
            {"card": "div.people-container",
             "name": "h2",
             "link": "a[href*='/faculty-member/']",
             "title_re": _TITLE_RE,
             "email": "a[href^='mailto:']"}),
        # ---- h2_card (hand-built block columns) ----------------------------
        _scrape(
            "ANTH", "Department of Anthropology", ["Anthropology"],
            "https://anthropology.unc.edu/faculty/",
            {"card": "div.tb-fields-and-text:has(a[href^='mailto:'])",
             "name": "h2",
             "link": "h2 a",
             "title": "p strong",
             "email": "a[href^='mailto:']"}),
        # ---- table (people-page table) -------------------------------------
        _scrape(
            "SOCI", "Department of Sociology", ["Sociology"],
            "https://sociology.unc.edu/people/faculty/",
            {"card": "table tr:has(a[href^='mailto:'])",
             "name": "a[href*='/people-page/']",
             "link": "a[href*='/people-page/']",
             "title_re": _TITLE_RE,
             "email": "a[href^='mailto:']"}),
        # ---- hand_seq (physics h4 + title_sibling) -------------------------
        _scrape(
            "PHYS", "Department of Physics and Astronomy",
            ["Physics", "Astronomy", "Astrophysics"],
            "https://physics.unc.edu/people-pages/faculty/",
            {"card": "main.main h4:has(a[href*='/people/'])",
             # The h4 wraps a photo <a href=...jpg> BEFORE the name <a> for
             # many people, so target the profile anchor explicitly (a bare
             # "a" selector would grab the empty image link).
             "name": "a[href*='/people/']",
             "link": "a[href*='/people/']",
             "title": "nonexistent-in-card",
             "title_sibling": "h5"},
            name_flip=True),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
