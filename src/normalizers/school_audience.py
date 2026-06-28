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

VALID_AUDIENCES = frozenset({"campus", "open", "unknown"})

SOURCE_DEFAULTS: dict[str, tuple[str | None, str]] = {
    "uiuc_our_rss": ("uiuc", "campus"),
    "uiuc_faculty": ("uiuc", "campus"),
    "uiuc_js_faculty": ("uiuc", "campus"),
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
    "ucb_ne_faculty": ("ucb", "unknown"),
    "ucb_nst_faculty": ("ucb", "unknown"),
    "ucb_physics_faculty": ("ucb", "unknown"),
    "ucb_pmb_faculty": ("ucb", "unknown"),
    "ucb_polisci_faculty": ("ucb", "unknown"),
    "ucb_psych_faculty": ("ucb", "unknown"),
    "ucb_soc_faculty": ("ucb", "unknown"),
    "ucb_education_faculty": ("ucb", "unknown"),
    "ucb_english_faculty": ("ucb", "unknown"),
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
    # University of Michigan, Ann Arbor (#2 on the campus_graph engine).
    "umich_research_programs": ("umich", "campus"),
    "umich_external_research": (None, "open"),
    "umich_labs": ("umich", "unknown"),
    # Michigan faculty directory (curated, via the faculty_graph engine). Single
    # source across departments (UIUC model); cold-email targets whose
    # cross-school openness is per-professor, so audience is unknown.
    "umich_faculty": ("umich", "unknown"),
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
        opp["school"] = school
        opp["audience"] = audience
        counts[source] = counts.get(source, 0) + 1
    return counts
