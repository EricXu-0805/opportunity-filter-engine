"""HTTP boundary for the target-truth contract.

``src.evidence.target_truth`` answers whether a record supports action. This is
the one place that turns that answer into a refusal, so every target action
refuses the same way and a client can branch on a stable code instead of prose.

Deliberately separate from ``release_scope.release_visible_opportunity_by_id``:
that resolver is shared with the read paths, and a closed listing must stay
*readable*. A student who saved a URAP project last term should still be able
to open it, see why it is closed, and follow the source link. What must stop is
acting on it — tailoring a résumé to it, drafting an email about it, spending
provider budget on it.

Call this immediately after the record resolves and before anything
irreversible: provider calls, usage metering, persistence, outbound mail.

Scope note: this module decides whether an action may PROCEED. It does not
build public payloads. Shaping one — the truth envelope, the record kind,
evidence-only metadata, unverified-kind neutralization, the application URL —
lives in ``backend.lib.public_projection.project_public_opportunity_payload``,
which is the single place any of that happens.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException

from src.evidence import target_truth

# Keyed by the contract's reason codes. The sentence explains the refusal in
# the terms the source stated it, never as a generic failure.
_REASON_MESSAGES: dict[str, str] = {
    "listing_closed": (
        "This listing is closed and is kept for reference only. "
        "Check the source for current openings."
    ),
    "reference_only": (
        "This record is published as reference material, not as an open listing."
    ),
    # Attributed to the source, not asserted by us, and says nothing about the
    # lab or about graduate study — only what this profile states about
    # undergraduates.
    "faculty_not_accepting": (
        "This faculty profile states that the faculty member is not currently "
        "accepting undergraduate students."
    ),
    "inactive": "This record is no longer active.",
    # Says what is unverified — the record's type — rather than implying the
    # opening ended. Nothing here claims there ever was one.
    "record_kind_unverified": (
        "This record's type is unverified, so it is not presented as an open "
        "listing. Check the source for current details."
    ),
}
_FALLBACK_MESSAGE = "This target is not currently open to action."

# Set on refusals that happen before any billable work. The rate limiter reads
# it to release the GLOBAL spend slot it reserved — never the per-IP one, which
# counts arrivals and is what eventually throttles a client sending nothing but
# bad requests. Deliberately not every 409: a conflict raised *after* a
# provider call has already cost us the call, and refunding that would uncap
# real spend.
REFUSED_BEFORE_WORK_HEADER = "X-Refused-Before-Work"


def prework_refusal(status_code: int, detail: object) -> HTTPException:
    """A refusal raised before the request could cost anything.

    Tagging is per-site and deliberate rather than inferred from the status
    code. The same 409 means "nothing was spent" when the target is closed and
    "the provider call already happened" elsewhere, so only the site knows.
    Fresh headers dict per call: one shared mapping would be handed to every
    exception, and a single mutation would retag refusals it never described.
    """
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers={REFUSED_BEFORE_WORK_HEADER: "1"},
    )


def actionable_opportunities(records: Iterable[dict]) -> list[dict]:
    """Drop stated-closed / reference / inactive records from a candidate set.

    Applied *before* scoring and counting, so totals, facets, coverage numbers
    and "what's due soon" describe the same universe the user can act on rather
    than one padded with dead listings.

    Layer this on top of a call site's existing activity test rather than
    replacing it. The six spellings of "is this active" scattered through the
    discovery routes disagree at the edges — one drops a present-but-null flag,
    another keeps it — and swapping any of them for this contract would widen
    that site. Intersecting only ever narrows.
    """
    return [record for record in records if target_truth(record).actionable]


def assert_target_actionable(opp: dict) -> None:
    """Refuse a target action before any provider call, spend, or write.

    409 rather than 404: the record exists and stays viewable, so "gone" would
    be a lie, and rather than 403, which would suggest the caller lacks
    permission. ``retryable`` is false — a closed listing does not reopen
    because the client tried again.
    """
    truth = target_truth(opp)
    if truth.actionable:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": "TARGET_NOT_ACTIONABLE",
            "reason": truth.reason_code,
            "message": _REASON_MESSAGES.get(truth.reason_code, _FALLBACK_MESSAGE),
            "retryable": False,
        },
        # Tells the rate limiter to release the GLOBAL spend slot only. This
        # refusal happens before any provider call, usage write or outbound
        # mail, so charging it against the shared ceiling would let one client
        # holding stale ids exhaust every other user's budget with the one
        # request that costs us nothing. The per-IP bucket keeps its count —
        # that one measures arrivals, and a client hammering closed ids should
        # still reach its own cap.
        headers={REFUSED_BEFORE_WORK_HEADER: "1"},
    )
