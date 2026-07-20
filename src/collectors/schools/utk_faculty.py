"""University of Tennessee, Knoxville faculty config (via the faculty_graph engine).

Four server-rendered WordPress markup families, every one a plain static 200 to a
bare request (no WAF, no JS render). Live-verified 2026-07-20.

* **``sngl-ppl`` card — Physics & Astronomy, Chemistry, Mathematics.**
  The College of Arts & Sciences shares one WordPress "single-people" component:
  ``div.sngl-ppl-wrp`` holding a ``.sngl-ppl__name`` heading (an ``h2`` on Physics
  and Math, an ``h3`` on Chemistry — so the card selector keys off the class, not
  the tag), a ``.sngl-ppl__ttl`` rank, a ``.sngl-ppl__email`` mailto, and a
  ``.sngl-ppl__prfl-link`` profile anchor. All three publish a real ``mailto`` per
  person, so these land name+title+email in one pass.

  Title gate (``field_filter`` require ``professor|lecturer``): the directories mix
  in emeriti, term/teaching faculty, postdoctoral associates, and title-less staff
  (Physics lists a "Director of Undergraduate Laboratories"; Math lists dozens of
  "Teaching Assistant Professor" plus two "Postdoctoral Associate" rows). A
  ``field_filter`` (not ``ladder_filter``) is used so a title-less staff card can't
  fall through the engine's default-to-"Professor": ``require_present`` reads
  ``.sngl-ppl__ttl`` directly and drops the card when it is absent, then ``include``
  keeps only Professor/Lecturer ranks. Emeriti are additionally dropped by the
  engine's own ``_RETIRED_TITLE_RE``.

* **EECS custom card — Electrical Engineering & Computer Science.**
  The Min H. Kao department renders ``div.person`` cards: ``span.gal_name`` (wrapped
  in the profile ``a``), ``span.gal_title``, and — uniquely on this school — a
  ``span.gal_research`` interests line on the listing, so EECS lands keyworded
  faculty without a per-profile fetch. No email on the listing (recovered by the
  downstream OpenAlex / per-profile enrichment pass). The ``ladder_filter`` require
  drops the lone title-less-of-rank "Dean of the College of Emerging and
  Collaborative Studies" card while keeping every professor rank (incl. endowed /
  governor's-chair / associate-head titles).

* **MSE ``profileCard`` — Materials Science & Engineering (Tickle College).**
  ``div.profileCard`` with an ``h3.profileName`` name, a ``p.profileTitle`` rank, a
  "Research Expertise:" line captured via ``research_re``, and a Cloudflare-shielded
  address: ``<a href="/cdn-cgi/l/email-protection#HEX"><span class="__cf_email__"
  data-cfemail="HEX">`` — which the engine's ``_decode_cfemail`` XOR-decodes, so MSE
  lands emailed despite the obfuscation. The ``ladder_filter`` require drops the lone
  "Vice Provost for Faculty Affairs" admin card.

* **MAE nested ``wp-block-group`` — Mechanical, Aerospace & Biomedical Engineering.**
  The Gutenberg-block roster nests three identically-classed ``div.wp-block-group``
  wrappers per person (name+title / email / profile-link), so the clean card is the
  OUTER wrapper, selected with ``:has(> div > h2.wp-block-heading.has-large-font-size)``.
  Name in the ``h2``, rank in the first ``p.wp-block-paragraph``, the same Cloudflare
  ``data-cfemail`` scheme MSE uses (decoded by the engine), and the profile link in
  ``p.is-style-utkwds-single-link a`` (some point at utsi.edu — UT Space Institute —
  so the link is taken by its container class, not an href pattern). The
  ``ladder_filter`` require drops the lone "Jessie Rogers Zeanah Faculty Fellow" card
  that carries no professor/lecturer rank.

Single source ("utk_faculty"); department rides each record, ids namespaced by
department short-code.

Live-verified 2026-07-20 (cards → kept-after-gate): EECS 48/47, Physics 46/45,
Chemistry 55/40, Mathematics 98/85, MAE 55/54, MSE 22/21.
"""

from __future__ import annotations

from .. import faculty_graph

# ---- Shared A&S "sngl-ppl" component (Physics, Chemistry, Mathematics) ------
# Name heading is an h2 (Physics/Math) or h3 (Chemistry); key off the class so one
# selector covers all three. Real mailto per person; profile link in its own row.
_SNGL_SEL = {
    "card": "div.sngl-ppl-wrp",
    "name": ".sngl-ppl__name",
    "link": ".sngl-ppl__prfl-link a",
    "title": ".sngl-ppl__ttl",
    "email": ".sngl-ppl__email a[href^='mailto:']",
}
# field_filter (not ladder_filter): require_present drops the title-less staff cards
# the A&S directories mix in (they'd otherwise default to "Professor" and leak),
# then include keeps only professor/lecturer ranks. Emeriti drop via the retired gate.
_SNGL_FIELD = {
    "selector": ".sngl-ppl__ttl",
    "require_present": True,
    "include": r"professor|lecturer",
}

# ---- EECS custom card -------------------------------------------------------
# Name span sits inside the profile <a>; research interests render on the listing.
_EECS_SEL = {
    "card": "div.person",
    "name": "span.gal_name",
    "link": ".person-image a",
    "title": "span.gal_title",
    "research": "span.gal_research",
}

# ---- MSE profileCard (Tickle College) ---------------------------------------
# Cloudflare-shielded email (data-cfemail, engine-decoded); research on the listing.
_MSE_SEL = {
    "card": "div.profileCard",
    "name": ".profileName",
    "link": "a[href*='/faculty/']",
    "title": "p.profileTitle",
    "email": "a[href*='email-protection']",
    "research_re": r"Research Expertise:(.*?)</p>",
}

# ---- MAE nested wp-block-group (Tickle College) -----------------------------
# Outer wrapper is the card; inner groups (name+title / email / link) share its
# class, so :has() pins the outer one. Same Cloudflare email scheme as MSE.
_MAE_SEL = {
    "card": "div.wp-block-group:has(> div > h2.wp-block-heading.has-large-font-size)",
    "name": "h2.wp-block-heading.has-large-font-size",
    "link": "p.is-style-utkwds-single-link a",
    "title": "p.wp-block-paragraph",
    "email": "a[href*='email-protection']",
}

_LADDER = {"require": r"professor|lecturer"}


def _dept(short: str, name: str, majors: list[str], url: str, sel: dict,
          *, field: dict | None = None, ladder: dict | None = None) -> dict:
    """A department on one of the four UTK markup families."""
    scrape: dict = {"url": url, "selectors": sel}
    if field:
        scrape["field_filter"] = field
    if ladder:
        scrape["ladder_filter"] = ladder
    return {
        "short": short, "name": name, "majors": majors, "directory_url": url,
        "scrape": scrape,
    }


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
        _dept("EECS", "Min H. Kao Department of Electrical Engineering and Computer Science",
              ["Electrical Engineering", "Computer Science", "Computer Engineering"],
              "https://eecs.utk.edu/faculty/", _EECS_SEL, ladder=_LADDER),
        _dept("PHYS", "Department of Physics and Astronomy",
              ["Physics", "Astronomy", "Astrophysics"],
              "https://physics.utk.edu/faculty/", _SNGL_SEL, field=_SNGL_FIELD),
        _dept("CHEM", "Department of Chemistry", ["Chemistry", "Biochemistry"],
              "https://chem.utk.edu/faculty/", _SNGL_SEL, field=_SNGL_FIELD),
        _dept("MATH", "Department of Mathematics",
              ["Mathematics", "Applied Mathematics"],
              "https://math.utk.edu/directory/faculty/", _SNGL_SEL, field=_SNGL_FIELD),
        _dept("MABE", "Department of Mechanical, Aerospace and Biomedical Engineering",
              ["Mechanical Engineering", "Aerospace Engineering", "Biomedical Engineering"],
              "https://tickle.utk.edu/mae/faculty/", _MAE_SEL, ladder=_LADDER),
        _dept("MSE", "Department of Materials Science and Engineering",
              ["Materials Science and Engineering", "Materials Engineering"],
              "https://tickle.utk.edu/mse/faculty/", _MSE_SEL, ladder=_LADDER),
    ],
}


def fetch_and_normalize(deep: bool = True) -> list[dict]:
    """Wrapper bound to SCHOOL so refresh_all can call it like a collector."""
    return faculty_graph.fetch_and_normalize(SCHOOL, deep=deep)


def merge_into_processed(opps: list[dict]):
    return faculty_graph.merge_into_processed(opps)
