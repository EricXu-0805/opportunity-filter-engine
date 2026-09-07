"""The authoritative list of schools this product does not currently support.

A school leaves the supported set as a **product decision**, recorded here with
its reason and its date, and it takes effect everywhere at once: the collector
stops being scheduled for it, the release contract stops expecting its sources,
its stored records are marked inactive, the switcher stops offering it, and the
coverage/freshness denominators stop counting it.

Three things this is deliberately NOT:

* **Not a way to make a number look better.** Dropping a school from the
  denominator raises freshness, so the only honest version of this is one that
  also stops serving the school — which is what marking the records inactive
  does. A school that is still on the switcher must stay in the denominator.
* **Not deletion.** The records stay in the corpus, inactive, carrying
  ``deactivation_reason: school_unsupported``. Re-enabling is removing a line
  here and re-running the school's collector, not a re-onboarding.
* **Not a place to park a broken collector.** "We cannot scrape it this week"
  is a `suspicious_zero` and belongs in the ops queue. This is for schools the
  product has decided not to offer.
"""

from __future__ import annotations

# slug -> (decided_on, reason). Both are load-bearing: the date says when the
# denominator changed, which is what makes a freshness reading before and after
# comparable, and the reason is what a reviewer needs to reverse it.
UNSUPPORTED_SCHOOLS: dict[str, tuple[str, str]] = {
    "ucd": (
        "2026-09-06",
        "UC Davis serves its undergraduate-research pages behind a Cloudflare "
        "managed challenge that refuses the supported headless render path as "
        "well as plain requests, and its structured endpoints (jsonapi, rss, "
        "feed) return 403 alike. robots.txt permits the content, so the barrier "
        "is bot management rather than crawl policy and the only lawful unblock "
        "is an allowlist granted by UC Davis. Until then the seven records we "
        "hold cannot be re-observed, so the product stops offering the school "
        "rather than serving data it can no longer verify. "
        "See docs/corpus_freshness_recovery.md §10."
    ),
}

UNSUPPORTED_REASON = "school_unsupported"


def is_supported(slug: object) -> bool:
    """Whether ``slug`` is a school the product currently offers."""
    return not (isinstance(slug, str) and slug.strip().lower() in UNSUPPORTED_SCHOOLS)


def supported_only(slugs) -> list[str]:
    """``slugs`` minus the unsupported ones, order preserved."""
    return [s for s in slugs if is_supported(s)]


def unsupported_reason(slug: object) -> str | None:
    """The recorded rationale for dropping ``slug``, or None if it is supported."""
    if not isinstance(slug, str):
        return None
    entry = UNSUPPORTED_SCHOOLS.get(slug.strip().lower())
    return entry[1] if entry else None


def deactivate_unsupported_schools(opps: list[dict], today: object = None) -> dict:
    """Mark every record of an unsupported school inactive, in place.

    Idempotent, and re-run on every refresh rather than applied once: a merge
    is an upsert that sets ``is_active`` back to True, so a school that left the
    supported set has to be held out on each pass rather than trusted to stay
    out. Records already inactive for another reason keep that reason — this
    pass records why the product stopped serving them, and must not overwrite
    why the pipeline had already retired them.
    """
    from datetime import date

    stamp = (today or date.today()).isoformat()
    counts: dict[str, int] = {}
    for opp in opps:
        slug = opp.get("school")
        if is_supported(slug):
            continue
        meta = opp.setdefault("metadata", {})
        if meta.get("is_active") is not False:
            meta["is_active"] = False
            meta["deactivated_at"] = stamp
            meta["deactivation_reason"] = UNSUPPORTED_REASON
            counts[slug] = counts.get(slug, 0) + 1
        elif meta.get("deactivation_reason") is None:
            meta["deactivation_reason"] = UNSUPPORTED_REASON
    return {"deactivated": sum(counts.values()), "by_school": counts,
            "unsupported_schools": sorted(UNSUPPORTED_SCHOOLS)}
