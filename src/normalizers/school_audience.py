"""Source-level school + audience tagging (multi-university Phase 1, PR #187).

Two-concept model: an opportunity's ``school`` (host-school slug, None =
national) and ``audience`` ('campus' = host-school students only, 'open' =
external applicants welcome, 'unknown' = unconfirmed) determine discovery;
the user's ``home_school`` is identity. Phase 1 assigns both fields
mechanically from the record's source; per-record overrides (e.g. the
minority of SRO entries that are actually UIUC-hosted) are the Phase 2
tagger's job.
"""

from __future__ import annotations

import re

VALID_AUDIENCES = frozenset({"campus", "open", "unknown"})

# Names a record's OWN host school may be called in its description. Used only
# to detect an EXPLICIT own-campus restriction ("for UCSB undergraduates",
# "must be enrolled at Purdue") on an audience='unknown' record — a UCSB-only
# summer internship ranked #1 for a Northwestern student because the
# "summer programs recruit nationally" rule assumed openness (2026-07 audit).
# Deliberately conservative: ambiguous shorts that double as common words or
# state names ("Illinois", "Washington") are omitted.
_CAMPUS_NAMES: dict[str, tuple[str, ...]] = {
    "uiuc": ("uiuc", "university of illinois urbana-champaign",
             "university of illinois at urbana-champaign"),
    "ucb": ("uc berkeley", "berkeley"),
    "uw": ("university of washington",),
    "ucla": ("ucla",),
    "utexas": ("ut austin", "university of texas at austin"),
    "stanford": ("stanford",),
    "gatech": ("georgia tech", "georgia institute of technology"),
    "wisc": ("uw-madison", "uw madison", "university of wisconsin-madison",
             "university of wisconsin"),
    "umich": ("university of michigan", "u-m", "umich"),
    "princeton": ("princeton",),
    "ucsd": ("uc san diego", "ucsd"),
    "uchicago": ("university of chicago", "uchicago"),
    "uci": ("uc irvine", "uci"),
    "ucsb": ("ucsb", "uc santa barbara"),
    "boulder": ("cu boulder", "university of colorado boulder"),
    "purdue": ("purdue",),
    "duke": ("duke",),
    "jhu": ("johns hopkins", "jhu"),
    "northwestern": ("northwestern",),
    "upenn": ("penn", "university of pennsylvania", "upenn"),
    "caltech": ("caltech",),
    "cornell": ("cornell",),
    "rice": ("rice",),
    "vanderbilt": ("vanderbilt",),
    "brown": ("brown",),
    "dartmouth": ("dartmouth",),
    "columbia": ("columbia",),
    "yale": ("yale",),
    "bc": ("bc", "boston college"),
    "emory": ("emory",),
    "georgetown": ("georgetown",),
    "nyu": ("nyu", "new york university"),
    "tufts": ("tufts",),
    "uva": ("uva", "university of virginia"),
    "cmu": ("cmu", "carnegie mellon"),
}

_CAMPUS_ONLY_TEMPLATES = (
    # "internships for UCSB undergraduates", "open only to Purdue students"
    r"(?:for|(?:open\s+)?(?:only\s+)?to)\s+(?:current(?:ly)?[\s-]*enrolled\s+)?{name}\s+(?:undergraduate|student)s?\b",
    # "UCSB students only"
    r"{name}\s+(?:undergraduate|student)s?\s+only\b",
    # "must be enrolled at UCSB" / "must be a UCSB student"
    r"must\s+be\s+(?:currently\s+)?(?:enrolled\s+(?:at|in)\s+{name}|an?\s+{name}\s+(?:undergraduate|student))",
    # "students from UCSB acquire research experience" (the RISE phrasing)
    r"(?:undergraduate|student)s?\s+from\s+{name}\s+(?:acquire|gain|receive|participate)",
)


def _campus_only_res(slug: str) -> tuple[re.Pattern, ...]:
    names = _CAMPUS_NAMES.get(slug)
    if not names:
        return ()
    alt = "(?:" + "|".join(re.escape(n) for n in names) + ")"
    return tuple(re.compile(t.format(name=alt), re.IGNORECASE) for t in _CAMPUS_ONLY_TEMPLATES)


_CAMPUS_ONLY_CACHE: dict[str, tuple[re.Pattern, ...]] = {}


def _explicitly_campus_only(school: str, opp: dict) -> bool:
    """True only when the record's own text restricts it to its host school's
    students. Mentions of OTHER schools never match (patterns are built from
    the host school's names), and absent phrasing leaves audience unchanged."""
    res = _CAMPUS_ONLY_CACHE.get(school)
    if res is None:
        res = _CAMPUS_ONLY_CACHE[school] = _campus_only_res(school)
    if not res:
        return False
    text = " ".join(filter(None, [
        opp.get("description_raw") or "",
        opp.get("description_clean") or "",
        (opp.get("eligibility") or {}).get("eligibility_text_raw") or "",
    ]))
    return any(r.search(text) for r in res)

SOURCE_DEFAULTS: dict[str, tuple[str | None, str]] = {
    "uiuc_our_rss": ("uiuc", "campus"),
    # uiuc_faculty covers all four scrape paths (static + js + json + html
    # variants) — they all emit source="uiuc_faculty", so one entry is the
    # whole family. Faculty cold-email targets like every other school's
    # directory: whether a cross-school collaboration is welcome is
    # professor-specific, so openness stays unconfirmed and visibility is
    # governed by the matcher's cross-school toggle, not a campus tag.
    "uiuc_faculty": ("uiuc", "unknown"),
    "uiuc_siebel": ("uiuc", "campus"),
    "uiuc_urap": ("uiuc", "campus"),
    "uiuc_ursa": ("uiuc", "campus"),
    "uiuc_drp": ("uiuc", "campus"),
    "uiuc_other": ("uiuc", "campus"),
    "handshake": ("uiuc", "campus"),
    # Other schools' Handshake (manual, login-gated; same per-school campus scope).
    "handshake_ucb": ("ucb", "campus"),
    "handshake_umich": ("umich", "campus"),
    # SRO is UIUC's database OF external summer research programs
    # (researchops.web.illinois.edu) — it catalogs programs hosted elsewhere
    # that welcome outside applicants, so its records are national + open
    # despite the uiuc_ source prefix.
    "uiuc_sro": (None, "open"),
    "nsf_reu": (None, "open"),
    "simplify_internships": (None, "open"),
    # Faculty cold-email targets: whether a remote/external collaboration is
    # welcome is professor-specific, so openness stays unconfirmed.
    "ucb_eecs_faculty": ("ucb", "unknown"),
    "ucb_stat_faculty": ("ucb", "unknown"),
    "ucb_chem_faculty": ("ucb", "unknown"),
    "ucb_cee_faculty": ("ucb", "unknown"),
    # Remaining Berkeley department directories wired into refresh_all. Same
    # (ucb, unknown) as the originals — faculty cold-email targets whose
    # cross-school openness is professor-specific.
    "ucb_anthro_faculty": ("ucb", "unknown"),
    "ucb_arch_faculty": ("ucb", "unknown"),
    "ucb_astro_faculty": ("ucb", "unknown"),
    "ucb_bioe_faculty": ("ucb", "unknown"),
    "ucb_cbe_faculty": ("ucb", "unknown"),
    "ucb_dcrp_faculty": ("ucb", "unknown"),
    "ucb_econ_faculty": ("ucb", "unknown"),
    "ucb_eps_faculty": ("ucb", "unknown"),
    "ucb_espm_faculty": ("ucb", "unknown"),
    "ucb_ib_faculty": ("ucb", "unknown"),
    "ucb_ieor_faculty": ("ucb", "unknown"),
    "ucb_larch_faculty": ("ucb", "unknown"),
    "ucb_law_faculty": ("ucb", "unknown"),
    "ucb_ling_faculty": ("ucb", "unknown"),
    "ucb_math_faculty": ("ucb", "unknown"),
    "ucb_mcb_faculty": ("ucb", "unknown"),
    "ucb_me_faculty": ("ucb", "unknown"),
    "ucb_mse_faculty": ("ucb", "unknown"),
    "ucb_datascience_faculty": ("ucb", "unknown"),
    "ucb_ne_faculty": ("ucb", "unknown"),
    "ucb_neuro_faculty": ("ucb", "unknown"),
    "ucb_nst_faculty": ("ucb", "unknown"),
    "ucb_physics_faculty": ("ucb", "unknown"),
    "ucb_pmb_faculty": ("ucb", "unknown"),
    "ucb_polisci_faculty": ("ucb", "unknown"),
    "ucb_psych_faculty": ("ucb", "unknown"),
    "ucb_soc_faculty": ("ucb", "unknown"),
    "ucb_education_faculty": ("ucb", "unknown"),
    "ucb_english_faculty": ("ucb", "unknown"),
    "ucb_extra_faculty": ("ucb", "unknown"),
    "ucb_geog_faculty": ("ucb", "unknown"),
    "ucb_haas_faculty": ("ucb", "unknown"),
    "ucb_history_faculty": ("ucb", "unknown"),
    "ucb_journalism_faculty": ("ucb", "unknown"),
    "ucb_philos_faculty": ("ucb", "unknown"),
    "ucb_socwel_faculty": ("ucb", "unknown"),
    "ucb_sph_faculty": ("ucb", "unknown"),
    # L&S humanities/language faculty directories (Open-Berkeley person grids).
    "ucb_music_faculty": ("ucb", "unknown"),
    "ucb_complit_faculty": ("ucb", "unknown"),
    "ucb_german_faculty": ("ucb", "unknown"),
    "ucb_french_faculty": ("ucb", "unknown"),
    "ucb_slavic_faculty": ("ucb", "unknown"),
    "ucb_tdps_faculty": ("ucb", "unknown"),
    "ucb_rhetoric_faculty": ("ucb", "unknown"),
    "ucb_spanish_portuguese_faculty": ("ucb", "unknown"),
    "ucb_scandinavian_faculty": ("ucb", "unknown"),
    "ucb_filmmedia_faculty": ("ucb", "unknown"),
    "ucb_classics_faculty": ("ucb", "unknown"),
    "ucb_publicpolicy_faculty": ("ucb", "unknown"),
    "ucb_urap": ("ucb", "campus"),
    # URAP live project DB (urapprojects.berkeley.edu) — Berkeley-matriculated
    # students only, like the URAP overview.
    "ucb_urap_projects": ("ucb", "campus"),
    # UCSB URCA undergraduate-research directory — per-project board (sitemap-fed,
    # ~243 faculty-posted projects), UCSB-enrollment-gated like URAP.
    "ucsb_urca_projects": ("ucsb", "campus"),
    # Campus-wide opportunity graph (src/collectors/ucb_campus.py). Three emit
    # buckets, audience chosen so the discovery-scope filter stays correct:
    #   * ucb_research_programs — Berkeley-enrollment-gated programs, department
    #     pages, on-campus jobs, announcements → campus-only.
    #   * ucb_external_research — external fellowships + REU-style listings
    #     hosted on Berkeley pages that welcome any-school applicants → open.
    #   * ucb_labs — "join our lab" / center recruiting pages (cold-email
    #     targets); cross-school openness is per-lab → unknown.
    "ucb_research_programs": ("ucb", "campus"),
    "ucb_external_research": (None, "open"),
    "ucb_labs": ("ucb", "unknown"),
    # Top-50 rollout via the generic campus_graph engine (src/collectors/schools/).
    # Same three emit buckets per school. Princeton (US-News #1) is first.
    "princeton_research_programs": ("princeton", "campus"),
    "princeton_external_research": (None, "open"),
    "princeton_labs": ("princeton", "unknown"),
    "princeton_faculty": ("princeton", "unknown"),
    "brown_research_programs": ("brown", "campus"),
    "brown_faculty": ("brown", "unknown"),
    "cornell_research_programs": ("cornell", "campus"),
    "cornell_faculty": ("cornell", "unknown"),
    "rice_research_programs": ("rice", "campus"),
    "rice_faculty": ("rice", "unknown"),
    "vanderbilt_research_programs": ("vanderbilt", "campus"),
    "vanderbilt_faculty": ("vanderbilt", "unknown"),
    "mit_research_programs": ("mit", "campus"),
    "mit_faculty": ("mit", "unknown"),
    "harvard_research_programs": ("harvard", "campus"),
    "harvard_faculty": ("harvard", "unknown"),
    "yale_research_programs": ("yale", "campus"),
    "yale_faculty": ("yale", "unknown"),
    "cmu_research_programs": ("cmu", "campus"),
    "cmu_faculty": ("cmu", "unknown"),
    "dartmouth_research_programs": ("dartmouth", "campus"),
    "dartmouth_faculty": ("dartmouth", "unknown"),
    "columbia_research_programs": ("columbia", "campus"),
    "columbia_faculty": ("columbia", "unknown"),
    "usc_research_programs": ("usc", "campus"),
    "usc_faculty": ("usc", "unknown"),
    "umn_research_programs": ("umn", "campus"),
    "umn_faculty": ("umn", "unknown"),
    "osu_research_programs": ("osu", "campus"),
    "osu_faculty": ("osu", "unknown"),
    "nd_research_programs": ("nd", "campus"),
    "nd_faculty": ("nd", "unknown"),
    "rochester_research_programs": ("rochester", "campus"),
    "rochester_faculty": ("rochester", "unknown"),
    "uf_research_programs": ("uf", "campus"),
    "uf_faculty": ("uf", "unknown"),
    "umass_research_programs": ("umass", "campus"),
    "umass_faculty": ("umass", "unknown"),
    "vt_research_programs": ("vt", "campus"),
    "vt_faculty": ("vt", "unknown"),
    "tamu_research_programs": ("tamu", "campus"),
    "tamu_faculty": ("tamu", "unknown"),
    "umd_research_programs": ("umd", "campus"),
    "umd_faculty": ("umd", "unknown"),
    "neu_research_programs": ("neu", "campus"),
    "neu_faculty": ("neu", "unknown"),
    "sbu_research_programs": ("sbu", "campus"),
    "sbu_faculty": ("sbu", "unknown"),
    "bu_research_programs": ("bu", "campus"),
    "bu_faculty": ("bu", "unknown"),
    "washu_research_programs": ("washu", "campus"),
    "washu_faculty": ("washu", "unknown"),
    "rutgers_research_programs": ("rutgers", "campus"),
    "rutgers_faculty": ("rutgers", "unknown"),
    "ncsu_research_programs": ("ncsu", "campus"),
    "ncsu_faculty": ("ncsu", "unknown"),
    "psu_research_programs": ("psu", "campus"),
    "psu_faculty": ("psu", "unknown"),
    # Wave-2 batch 2 (UCSC, Arizona, UCR, ASU, Pitt, MSU).
    "ucsc_research_programs": ("ucsc", "campus"),
    "ucsc_faculty": ("ucsc", "unknown"),
    "arizona_research_programs": ("arizona", "campus"),
    "arizona_faculty": ("arizona", "unknown"),
    "ucr_research_programs": ("ucr", "campus"),
    "ucr_faculty": ("ucr", "unknown"),
    "asu_research_programs": ("asu", "campus"),
    "asu_faculty": ("asu", "unknown"),
    "pitt_research_programs": ("pitt", "campus"),
    "pitt_faculty": ("pitt", "unknown"),
    "msu_research_programs": ("msu", "campus"),
    "msu_faculty": ("msu", "unknown"),
    # Wave-4 batch 1 (2026-07-20).
    "buffalo_research_programs": ("buffalo", "campus"),
    "buffalo_faculty": ("buffalo", "unknown"),
    "fsu_research_programs": ("fsu", "campus"),
    "fsu_faculty": ("fsu", "unknown"),
    "usf_research_programs": ("usf", "campus"),
    "usf_faculty": ("usf", "unknown"),
    "utk_research_programs": ("utk", "campus"),
    "utk_faculty": ("utk", "unknown"),
    "clemson_research_programs": ("clemson", "campus"),
    "clemson_faculty": ("clemson", "unknown"),
    "colostate_research_programs": ("colostate", "campus"),
    "colostate_faculty": ("colostate", "unknown"),
    "oregonstate_research_programs": ("oregonstate", "campus"),
    "oregonstate_faculty": ("oregonstate", "unknown"),
    "drexel_research_programs": ("drexel", "campus"),
    "drexel_faculty": ("drexel", "unknown"),
    # Wave-5 batch 1 (2026-07-20).
    "stevens_research_programs": ("stevens", "campus"),
    "stevens_faculty": ("stevens", "unknown"),
    "njit_research_programs": ("njit", "campus"),
    "njit_faculty": ("njit", "unknown"),
    "wpi_research_programs": ("wpi", "campus"),
    "wpi_faculty": ("wpi", "unknown"),
    "uky_research_programs": ("uky", "campus"),
    "uky_faculty": ("uky", "unknown"),
    "lehigh_research_programs": ("lehigh", "campus"),
    "lehigh_faculty": ("lehigh", "unknown"),
    "syracuse_research_programs": ("syracuse", "campus"),
    "syracuse_faculty": ("syracuse", "unknown"),
    "cincinnati_research_programs": ("cincinnati", "campus"),
    "cincinnati_faculty": ("cincinnati", "unknown"),
    "unl_research_programs": ("unl", "campus"),
    "unl_faculty": ("unl", "unknown"),
    "lsu_research_programs": ("lsu", "campus"),
    "lsu_faculty": ("lsu", "unknown"),
    "utdallas_research_programs": ("utdallas", "campus"),
    "utdallas_faculty": ("utdallas", "unknown"),
    # Wave-3 batch 1 (2026-07-19).
    "casewestern_research_programs": ("casewestern", "campus"),
    "casewestern_faculty": ("casewestern", "unknown"),
    "houston_research_programs": ("houston", "campus"),
    "houston_faculty": ("houston", "unknown"),
    "iastate_research_programs": ("iastate", "campus"),
    "iastate_faculty": ("iastate", "unknown"),
    "indiana_research_programs": ("indiana", "campus"),
    "indiana_faculty": ("indiana", "unknown"),
    "miami_research_programs": ("miami", "campus"),
    "miami_faculty": ("miami", "unknown"),
    "rpi_research_programs": ("rpi", "campus"),
    "rpi_faculty": ("rpi", "unknown"),
    "ucf_research_programs": ("ucf", "campus"),
    "ucf_faculty": ("ucf", "unknown"),
    "uconn_research_programs": ("uconn", "campus"),
    "uconn_faculty": ("uconn", "unknown"),
    "udel_research_programs": ("udel", "campus"),
    "udel_faculty": ("udel", "unknown"),
    "uiowa_research_programs": ("uiowa", "campus"),
    "uiowa_faculty": ("uiowa", "unknown"),
    "utah_research_programs": ("utah", "campus"),
    "utah_faculty": ("utah", "unknown"),
    "uga_research_programs": ("uga", "campus"),
    "uga_faculty": ("uga", "unknown"),
    # University of Michigan, Ann Arbor (#2 on the campus_graph engine).
    "umich_research_programs": ("umich", "campus"),
    "umich_external_research": (None, "open"),
    "umich_labs": ("umich", "unknown"),
    # University of Washington, Seattle (#3 on the campus_graph engine).
    "uw_research_programs": ("uw", "campus"),
    "uw_external_research": (None, "open"),
    "uw_labs": ("uw", "unknown"),
    # Georgia Institute of Technology (#4 on the campus_graph engine).
    "gatech_research_programs": ("gatech", "campus"),
    "gatech_external_research": (None, "open"),
    "gatech_labs": ("gatech", "unknown"),
    # Stanford University (#5 on the campus_graph engine).
    "stanford_research_programs": ("stanford", "campus"),
    "stanford_external_research": (None, "open"),
    "stanford_labs": ("stanford", "unknown"),
    # The University of Texas at Austin (#6 on the campus_graph engine; no lab bucket).
    "utexas_research_programs": ("utexas", "campus"),
    "utexas_external_research": (None, "open"),
    # University of Wisconsin-Madison (#7 on the campus_graph engine).
    "wisc_research_programs": ("wisc", "campus"),
    "wisc_external_research": (None, "open"),
    "wisc_labs": ("wisc", "unknown"),
    # University of California, Los Angeles (#8 on the campus_graph engine).
    "ucla_research_programs": ("ucla", "campus"),
    "ucla_external_research": (None, "open"),
    "ucla_labs": ("ucla", "unknown"),
    # University of California, San Diego (#9 on the campus_graph engine; first
    # stop of the UC-system rollout).
    "ucsd_research_programs": ("ucsd", "campus"),
    "ucsd_external_research": (None, "open"),
    "ucsd_labs": ("ucsd", "unknown"),
    # University of Chicago (#10 on the campus_graph engine).
    "uchicago_research_programs": ("uchicago", "campus"),
    "uchicago_external_research": (None, "open"),
    "uchicago_labs": ("uchicago", "unknown"),
    # University of California, Irvine (#11 on the campus_graph engine).
    "uci_research_programs": ("uci", "campus"),
    "uci_external_research": (None, "open"),
    "uci_labs": ("uci", "unknown"),
    # University of California, Santa Barbara (#12 on the campus_graph engine).
    "ucsb_research_programs": ("ucsb", "campus"),
    "ucsb_external_research": (None, "open"),
    "ucsb_labs": ("ucsb", "unknown"),
    # University of Colorado Boulder (#13 on the campus_graph engine).
    "boulder_research_programs": ("boulder", "campus"),
    "boulder_external_research": (None, "open"),
    "boulder_labs": ("boulder", "unknown"),
    # Michigan faculty directory (curated, via the faculty_graph engine). Single
    # source across departments (UIUC model); cold-email targets whose
    # cross-school openness is per-professor, so audience is unknown.
    "umich_faculty": ("umich", "unknown"),
    # UW faculty directory (live-scraped, via the faculty_graph engine). Same
    # single-source model; per-professor openness, so audience is unknown.
    "uw_faculty": ("uw", "unknown"),
    # Georgia Tech faculty directory (live-scraped, via the faculty_graph engine).
    "gatech_faculty": ("gatech", "unknown"),
    # Stanford faculty directory (live-scraped, via the faculty_graph engine).
    "stanford_faculty": ("stanford", "unknown"),
    # UT Austin faculty directory (live-scraped, via the faculty_graph engine).
    "utexas_faculty": ("utexas", "unknown"),
    # UW-Madison faculty directory (live-scraped, via the faculty_graph engine).
    "wisc_faculty": ("wisc", "unknown"),
    # UCLA faculty directory (WordPress-REST, via the faculty_graph engine).
    "ucla_faculty": ("ucla", "unknown"),
    # UCSD faculty directory (live-scraped, via the faculty_graph engine).
    "ucsd_faculty": ("ucsd", "unknown"),
    # Purdue (campus-graph engine) + faculty (server-rendered).
    "purdue_research_programs": ("purdue", "campus"),
    "purdue_external_research": (None, "open"),
    "purdue_labs": ("purdue", "unknown"),
    "purdue_faculty": ("purdue", "unknown"),
    # Duke (campus-graph engine) + faculty (render-mode Pratt directories).
    "duke_research_programs": ("duke", "campus"),
    "duke_external_research": (None, "open"),
    "duke_labs": ("duke", "unknown"),
    "duke_faculty": ("duke", "unknown"),
    "jhu_research_programs": ("jhu", "campus"),
    "jhu_external_research": (None, "open"),
    "jhu_labs": ("jhu", "unknown"),
    "jhu_faculty": ("jhu", "unknown"),
    "northwestern_research_programs": ("northwestern", "campus"),
    "northwestern_external_research": (None, "open"),
    "northwestern_labs": ("northwestern", "unknown"),
    "northwestern_faculty": ("northwestern", "unknown"),
    # UChicago faculty directory (live-scraped + curated-API, via faculty_graph).
    "uchicago_faculty": ("uchicago", "unknown"),
    # UC Irvine faculty directory (live-scraped, via the faculty_graph engine).
    "uci_faculty": ("uci", "unknown"),
    # UC Santa Barbara faculty directory (live-scraped, via the faculty_graph engine).
    "ucsb_faculty": ("ucsb", "unknown"),
    # CU Boulder faculty directory (live-scraped from CU Experts/VIVO, via the
    # faculty_graph engine).
    "boulder_faculty": ("boulder", "unknown"),
    # UPenn (campus-graph engine) + faculty (live-scraped, via faculty_graph).
    "upenn_research_programs": ("upenn", "campus"),
    "upenn_external_research": (None, "open"),
    "upenn_labs": ("upenn", "unknown"),
    "upenn_faculty": ("upenn", "unknown"),
    # Caltech (campus-graph engine) + faculty (live-scraped, via faculty_graph).
    "caltech_research_programs": ("caltech", "campus"),
    "caltech_external_research": (None, "open"),
    "caltech_labs": ("caltech", "unknown"),
    "caltech_faculty": ("caltech", "unknown"),
    # Wave-3 batch 1 (2026-07-20)
    "bc_research_programs": ("bc", "campus"),
    "bc_faculty": ("bc", "unknown"),
    "emory_research_programs": ("emory", "campus"),
    "emory_faculty": ("emory", "unknown"),
    "georgetown_research_programs": ("georgetown", "campus"),
    "georgetown_faculty": ("georgetown", "unknown"),
    "nyu_research_programs": ("nyu", "campus"),
    "nyu_faculty": ("nyu", "unknown"),
    "tufts_research_programs": ("tufts", "campus"),
    "tufts_faculty": ("tufts", "unknown"),
    "uva_research_programs": ("uva", "campus"),
    "uva_faculty": ("uva", "unknown"),
}


def apply_school_audience(opportunities: list[dict]) -> dict[str, int]:
    """Set top-level ``school`` + ``audience`` on every record (in place).

    Sources in SOURCE_DEFAULTS are always re-stamped from the mapping, so the
    pass is idempotent and self-healing. Manual (and any unmapped) sources keep
    explicit per-record values when present — normalized at this boundary so a
    hand-typed "UIUC" or a bad audience can't leak past the DQ gate — and fall
    back to the conservative (None, 'unknown').

    Returns per-source counts of records stamped.
    """
    counts: dict[str, int] = {}
    for opp in opportunities:
        source = opp.get("source") or "unknown"
        if source in SOURCE_DEFAULTS:
            school, audience = SOURCE_DEFAULTS[source]
        else:
            raw_school = opp.get("school")
            school = str(raw_school).strip().lower() if raw_school is not None else None
            school = school or None
            audience = opp.get("audience")
            if audience not in VALID_AUDIENCES:
                audience = "unknown"
        if audience == "unknown" and school and _explicitly_campus_only(school, opp):
            audience = "campus"
        opp["school"] = school
        opp["audience"] = audience
        counts[source] = counts.get(source, 0) + 1
    return counts
