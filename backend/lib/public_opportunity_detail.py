"""One detached anonymous full-detail projection and its writing version.

The token binds public material, not an identity, contact reveal, or a guarantee
that the corpus cannot change after a request is accepted. Object key order is
ignored; all public values and array order are retained.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

from backend.lib.position_truth import displayed_title
from backend.lib.public_projection import project_public_opportunity_payload
from backend.lib.publication_attribution import works_are_verified, works_may_be_served
from src.contact_instructions import contact_instructions_for
from src.evidence import faculty_safe_public_record
from src.lab_context import lab_context_for
from src.normalizers import host_program_terms
from src.publication_trust import exclude_reviewed_works
from src.research_context import research_context_for

REDACTED_FIELDS = {"contact_email", "pi_email", "professor_id"}
_UNVERIFIED_PUBLICATION_KEYS = ("recent_works", "publication_attribution_status", "publication_author_id")
# These are response decorations, never source material. Drop poisoned corpus
# values as well as declining to hash values later attached by a reveal route.
# detail_fields (M03) is a display projection derived from this same payload;
# the writing generators never read it, so it must not move the version. Nor
# does the footer's last_seen_listed_at, nor faculty_page: a label for the
# row's own links that also turns on how many colleagues share them.
_NON_VERSIONED_FIELDS = {
    "writing_target_version", "contact_email_status", "detail_fields", "last_seen_listed_at", "faculty_page",
} | REDACTED_FIELDS


def project_public_detail(opp: dict) -> dict:
    requirements = contact_instructions_for(opp)
    research = research_context_for(opp)
    lab = lab_context_for(opp)
    raw_metadata = opp.get("metadata")
    has_research_snapshot = isinstance(raw_metadata, dict) and "research_snapshot" in raw_metadata
    opp = faculty_safe_public_record(deepcopy(opp))
    out = {k: v for k, v in opp.items() if k not in _NON_VERSIONED_FIELDS}
    # Recompute from current source snapshots, never trust a cached public policy.
    out["contact_instructions"] = requirements
    # The central projector recomputes this from raw bound source blocks,
    # then applies the same URL/privacy boundary as every public field.
    out["target_conditions"] = None
    out["research_context"] = research
    out["lab_context"] = lab
    metadata = dict(out["metadata"]) if isinstance(out.get("metadata"), dict) else {}
    metadata.pop("research_snapshot", None)
    metadata.pop("research_refresh", None)
    metadata.pop("lab_snapshot", None)
    metadata.pop("lab_refresh", None)
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
    elif metadata.get("recent_works"):
        metadata["recent_works"] = exclude_reviewed_works(opp, metadata["recent_works"])
        if not metadata["recent_works"]:
            for key in _UNVERIFIED_PUBLICATION_KEYS:
                metadata.pop(key, None)
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
    # publications — never served. Nor is a verified list whose newest paper
    # is too old to be called recent (M152, works_may_be_served). Copy-on-write
    # — the metadata dict is shared with the in-process corpus cache.
    md = out.get("metadata")
    if (
        isinstance(md, dict)
        and any(k in md for k in _UNVERIFIED_PUBLICATION_KEYS)
        and not (works_are_verified(opp) and (
            not md.get("recent_works") or works_may_be_served(opp, md["recent_works"])))
    ):
        out["metadata"] = {
            k: v for k, v in md.items() if k not in _UNVERIFIED_PUBLICATION_KEYS
        }
    # Historical targets stay readable — a saved link must keep working — so
    # detail answers 200 and carries the truth that lets every surface refuse
    # to offer an action on it. The projector owns the contact/URL boundary,
    # the envelope and the neutralization; this function only decides which
    # fields a detail response starts from.
    projected = project_public_opportunity_payload(out, opp)
    lab = projected.get("lab_context", {})
    metadata = projected.get("metadata", {})
    if (opp.get("source") == "caltech_faculty" and lab.get("status") == "available"
            and not (metadata.get("research_areas_raw") or projected.get("research_areas"))):
        # Only a current, public, identity-bound profile may supply the missing
        # detail fact. Keep the complete annotated source in the website panel.
        snapshot = lab["snapshot"]
        note = r"\s+\((?:we are hiring!|see [^()]+(?: for a published version|, (?:19|20)\d{2}, \d+))\)$"
        topics = [re.sub(note, "", section["text"])
                  for section in snapshot["pages"][0]["sections"]
                  if section["heading"].casefold().rstrip(":") in ("research interest", "research interests")]
        if topics:
            projected["research_areas"] = topics
            metadata["research_areas_verified_at"] = snapshot["checked_at"]
    # A directory's full historical text stays readable alongside the host's current terms.
    projected.pop("reviewed_program_summary", None)
    if summary := host_program_terms.reviewed_summary(opp):
        projected["reviewed_program_summary"] = summary
    return projected



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
