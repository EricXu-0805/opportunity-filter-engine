"""One detached anonymous full-detail projection and its writing version.

The token binds public material, not an identity, contact reveal, or a guarantee
that the corpus cannot change after a request is accepted. Object key order is
ignored; all public values and array order are retained.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from backend.lib.position_truth import displayed_title
from backend.lib.public_projection import project_public_opportunity_payload
from backend.lib.publication_attribution import works_are_verified
from src.contact_instructions import contact_instructions_for
from src.evidence import faculty_safe_public_record
from src.research_context import research_context_for

REDACTED_FIELDS = {"contact_email", "pi_email", "professor_id"}
_UNVERIFIED_PUBLICATION_KEYS = ("recent_works", "publication_attribution_status", "publication_author_id")
# These are response decorations, never source material. Drop poisoned corpus
# values as well as declining to hash values later attached by a reveal route.
_NON_VERSIONED_FIELDS = {"writing_target_version", "contact_email_status"} | REDACTED_FIELDS


def project_public_detail(opp: dict) -> dict:
    requirements = contact_instructions_for(opp)
    research = research_context_for(opp)
    raw_metadata = opp.get("metadata")
    has_research_snapshot = isinstance(raw_metadata, dict) and "research_snapshot" in raw_metadata
    opp = faculty_safe_public_record(deepcopy(opp))
    out = {k: v for k, v in opp.items() if k not in _NON_VERSIONED_FIELDS}
    # Recompute from current source snapshots, never trust a cached public policy.
    out["contact_instructions"] = requirements
    out["research_context"] = research
    metadata = dict(out["metadata"]) if isinstance(out.get("metadata"), dict) else {}
    metadata.pop("research_snapshot", None)
    metadata.pop("research_refresh", None)
    if has_research_snapshot:
        if research["status"] == "available":
            metadata["recent_works"] = [
                {"title": work["title"], "year": work["year"]}
                for work in research["snapshot"]["works"]
            ]
        else:
            # Stale/invalid new sources cannot regain writing authority through
            # a legacy title cache. Stale snapshots remain in research_context.
            metadata.pop("recent_works", None)
    out["metadata"] = metadata
    # Position truthfulness (W11): strip an unsupported "Prof." honorific
    # baked into legacy titles when the record's own stated rank contradicts
    # it. Copy-on-write on the fresh dict; the corpus object is untouched.
    honest = displayed_title(opp)
    if honest != out.get("title"):
        out["title"] = honest
    # Publication trust boundary: works whose attribution is anything but
    # explicitly verified (name_match, absent, junk) are internal candidates
    # for the recollection/verification effort, not the professor's
    # publications — never served. Copy-on-write — the metadata dict is
    # shared with the in-process corpus cache.
    md = out.get("metadata")
    if (
        isinstance(md, dict)
        and any(k in md for k in _UNVERIFIED_PUBLICATION_KEYS)
        and not works_are_verified(opp)
    ):
        out["metadata"] = {
            k: v for k, v in md.items() if k not in _UNVERIFIED_PUBLICATION_KEYS
        }
    # Historical targets stay readable — a saved link must keep working — so
    # detail answers 200 and carries the truth that lets every surface refuse
    # to offer an action on it. The projector owns the contact/URL boundary,
    # the envelope and the neutralization; this function only decides which
    # fields a detail response starts from.
    return project_public_opportunity_payload(out, opp)



def writing_target_version(public_snapshot: dict) -> str:
    """Hash only the shared anonymous projection, before any auth decorations.

    Server-produced and server-compared: unlike persisted cross-language
    resume signatures, this token does not require the browser to reserialize.
    Never hash the unprojected corpus row or a user-supplied detail object.
    """
    material = {key: value for key, value in public_snapshot.items() if key not in _NON_VERSIONED_FIELDS}
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return "wt1:" + hashlib.sha256(encoded).hexdigest()
