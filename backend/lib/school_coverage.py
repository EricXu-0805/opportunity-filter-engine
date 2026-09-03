"""The one definition of "how much coverage does this school have".

The university switcher chip and the first-visit confirmation gate both answer
one question — *how much of this campus do we actually have?* — and the answer
is::

    total_count = listing_count + faculty_contact_count

Both halves, because the product treats a professor we can introduce a student
to as coverage in exactly the same sense as a posted opening. Faculty contacts
are ~97% of the corpus, so a count that omits them understates a school by one
to two orders of magnitude (JHU: 28 listings against 4,554 faculty contacts).

That is not a hypothetical. The switcher previously read only the listings half
of a two-map response while the static fallback counted every record, so the
same chip showed ~4,500 before the fetch resolved and 28 after it landed. This
module exists so there is no second place to get that wrong: the API route and
the build-time static fallback (``scripts/gen_school_stats.py``) both call
``school_coverage`` and publish the same numbers under the same names.

Three rules the counting obeys, each of which the previous implementation broke:

**Slug from ``record["school"]``, not the source-name prefix.** ``school`` is the
field the shards are keyed by (``scripts/shard_corpus.py``) and the field the
static generator already used. Splitting ``source`` on ``_`` instead disagreed
with it three ways: it dropped 71 UIUC Handshake listings (prefix ``handshake``),
credited UIUC with 279 *national* records collected by a UIUC-named collector,
and silently gave UNC zero because ``unc`` was missing from a hand-maintained
allowlist. National records (``school`` unset, ``audience='open'``) belong to no
campus card — every school sees them, and the switcher footer says so.

**Three populations, never two.** ``record_kind`` is the shared allowlist, and it
returns ``unknown`` for a source type nobody has reviewed. Bucketing with
``if faculty else listing`` — the anti-pattern already removed from the admin
data-quality route — counts unreviewed records as proven openings. ``unreviewed``
is reported explicitly and is *not* in ``total_count``: it is the count of
records we cannot yet classify, not a third kind of coverage.

**The same filter stack as every other count.** Release scope then actionability,
so the chip describes the universe ``/opportunities`` and "what's due soon"
describe, rather than one padded with fellowships the release hides and
professors who have stated they are not taking undergraduates.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from backend.lib.release_scope import release_visible_opportunities
from backend.lib.target_actionability import actionable_opportunities
from src.evidence import record_kind

# Bumped whenever the *meaning* of the numbers changes, not when the numbers do.
# Clients compare it before reading any count: a payload without it is a
# pre-fix body (listings-only under the key ``counts``) held by an HTTP cache or
# an older deploy, and reading its numbers would resurrect the exact bug this
# schema was cut to end. Mirrored in frontend/src/lib/school-coverage.ts.
SCHOOL_COVERAGE_SCHEMA = "school-coverage-v2"


@dataclass(frozen=True)
class SchoolCoverage:
    """One school's coverage, with every population it was derived from.

    All three are kept on the record so ``total_count`` is auditably the sum of
    the two that count, and so no consumer has to derive a population by
    subtracting others — an inference that changes meaning the moment a fourth
    population exists.
    """

    listing_count: int = 0
    faculty_contact_count: int = 0
    #: Records whose ``source_type`` is not on the reviewed allowlist. Deliberately
    #: outside ``total_count``: an unclassifiable record proves neither an opening
    #: nor a contact.
    unreviewed_count: int = 0

    @property
    def total_count(self) -> int:
        """The canonical coverage number: unique listings + unique contacts."""
        return self.listing_count + self.faculty_contact_count

    def as_payload(self) -> dict[str, int]:
        return {
            "listing_count": self.listing_count,
            "faculty_contact_count": self.faculty_contact_count,
            "unreviewed_count": self.unreviewed_count,
            "total_count": self.total_count,
        }


def school_coverage(opportunities: Iterable[dict]) -> dict[str, SchoolCoverage]:
    """Per-school coverage over an unfiltered corpus.

    Takes raw records and applies the release/actionability stack itself, so a
    caller cannot accidentally count a differently-filtered universe than the
    one the switcher promises.

    A school appears in the result only if it has at least one record that
    survives filtering. Absence therefore means "we have nothing for this
    campus", which the client renders as its pending/unknown state — it is not
    a zero, and callers must not substitute one (see
    ``frontend/src/lib/school-coverage.ts``).

    Counting rows is the correct dedup: ``backend.data_loader`` canonicalizes the
    corpus unique-by-``id`` at load (first occurrence wins) and the collector
    already collapsed same-person faculty duplicates before the shards were
    written, so one surviving row is one unique product entity. Re-deduping here
    on a weaker key (name, email, URL) would silently merge the distinct people
    that ``collapse_same_person_faculty`` deliberately kept apart.
    """
    listings: dict[str, int] = {}
    faculty: dict[str, int] = {}
    unreviewed: dict[str, int] = {}

    for record in actionable_opportunities(release_visible_opportunities(opportunities)):
        # Belt-and-braces: actionability already drops these, but the chip must
        # never advertise a record an explicit flag has retired.
        if (record.get("metadata") or {}).get("is_active") is False:
            continue
        slug = record.get("school")
        if not isinstance(slug, str) or not slug.strip():
            continue  # national / open-to-everyone pool: belongs to no campus card
        slug = slug.strip()
        bucket = {
            "listing": listings,
            "faculty_contact": faculty,
            "unknown": unreviewed,
        }[record_kind(record)]
        bucket[slug] = bucket.get(slug, 0) + 1

    return {
        slug: SchoolCoverage(
            listing_count=listings.get(slug, 0),
            faculty_contact_count=faculty.get(slug, 0),
            unreviewed_count=unreviewed.get(slug, 0),
        )
        for slug in sorted(listings.keys() | faculty.keys() | unreviewed.keys())
    }


def coverage_payload(opportunities: Iterable[dict]) -> dict[str, object]:
    """The wire form served by ``/api/opportunities/coverage`` and written to the
    static fallback, so the two can never drift into different shapes."""
    return {
        "schema": SCHOOL_COVERAGE_SCHEMA,
        "schools": {
            slug: coverage.as_payload()
            for slug, coverage in school_coverage(opportunities).items()
        },
    }


def total_counts(coverage: Mapping[str, SchoolCoverage]) -> dict[str, int]:
    """``{slug: total_count}`` — for tests and reporting, never for the wire."""
    return {slug: entry.total_count for slug, entry in coverage.items()}


# Display flooring, mirrored in frontend/src/lib/school-coverage.ts — change
# both or neither, the same rule this module already follows for record_kind.
# The chip reads "N+", so the number is rounded DOWN and never overstates.
#
# It lives here because the coverage contract's consistency guarantee is stated
# at this granularity: the committed fallback and a fresh computation must
# render the SAME chip. Exact equality is a stronger claim than the product
# makes and than a live corpus can keep — the shards move every refresh, and a
# retired listing among 2,799 is invisible behind this floor.
def display_count(count: int) -> int:
    """What the switcher chip actually shows for ``count``."""
    if count >= 1000:
        return count // 100 * 100
    if count >= 100:
        return count // 10 * 10
    return count


def national_count(opportunities: Iterable[dict]) -> int:
    """Actionable records that belong to no campus — the open pool every school
    also sees.

    Counted through the same filter stack as the per-school numbers so the
    switcher footer ("every school also sees N national opportunities") and the
    cards describe one universe. Never folded into a school's total: a shared
    pool added to each card would overstate every card and, summed across the
    grid, count itself once per school.
    """
    records = actionable_opportunities(release_visible_opportunities(opportunities))
    return sum(
        1
        for record in records
        if not isinstance(record.get("school"), str) or not record["school"].strip()
        if (record.get("metadata") or {}).get("is_active") is not False
    )


def school_stats_payload(opportunities: Iterable[dict]) -> dict[str, object]:
    """The committed static fallback's full contents.

    Lives beside the wire payload rather than in the generator script so the
    file the frontend ships and the body the API serves are assembled by one
    module — and so tests can rebuild it without shelling out.
    """
    payload = coverage_payload(opportunities)
    payload["national_count"] = national_count(opportunities)
    return payload
