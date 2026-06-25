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
    "ucb_urap": ("ucb", "campus"),
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
