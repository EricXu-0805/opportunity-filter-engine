"""Confirmed experience selection without provider work or unbounded prompts.

The envelope is a student's explicit attestation, not verification of ownership
or real-world truth. Source signatures prevent reusing an entry against a changed
resume; they are not authentication tokens. No cloud profile is read here.
"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass

from backend.schemas import ExperienceEntry, ExperienceEvidence
from src.recommender.cold_email import resume_bullet_relevance

PROMPT_CHARACTER_BUDGET = 4000
MAX_SELECTED_ENTRIES = 8
TEMPLATE_CHARACTER_BUDGET = 220


def _within_budget(entries: list[ExperienceEntry], contexts: dict | None = None) -> list[dict]:
    """Select whole entries; a fragment can lose a factual qualifier."""
    selected: list[dict] = []
    remaining = PROMPT_CHARACTER_BUDGET
    for entry in entries:
        if len(selected) == MAX_SELECTED_ENTRIES:
            break
        if len(entry.text) > remaining:
            continue
        selected.append(_receipt(entry, contexts))
        remaining -= len(entry.text)
    return selected


@dataclass
class ExperienceSelection:
    eligible: list[ExperienceEntry]
    selected: list[dict]
    template: dict | None
    excluded: list[dict]
    legacy_ignored: bool
    contexts: dict | None = None
    context_notices: tuple[str, ...] = ()

    def materials(self) -> list[dict]:
        return [_receipt(entry, self.contexts) for entry in self.eligible]

    def usage(self, selected: list[dict] | None = None, *, mode: str = "ai") -> dict:
        review = any(item["reason"] in {
            "candidate", "source_signature_mismatch", "source_quote_mismatch",
            "activity_reference_mismatch", "activity_ambiguous",
        } for item in self.excluded)
        notices = ["legacy_resume_bullets_unconfirmed"] if self.legacy_ignored else []
        notices.extend(self.context_notices)
        if mode == "ai" and len(self.selected) < len(self.eligible):
            notices.append("experience_prompt_budget_omission")
        if mode == "template" and any(len(entry.text) > TEMPLATE_CHARACTER_BUDGET for entry in self.eligible):
            notices.append("experience_template_budget_omission")
        return {
            "version": 1, "eligible_count": len(self.eligible),
            "selected": self.selected if selected is None else selected,
            "excluded": self.excluded, "needs_review": review or self.legacy_ignored or bool(self.context_notices),
            "notices": notices,
        }

    def quoted_usage(self, body: str) -> dict:
        # Only the actual complete template example is claimed as quoted.
        selected = [self.template] if self.template and self.template["excerpt"] in body else []
        return self.usage(selected, mode="template")

    def local_usage(self, supplied_body: str) -> dict:
        # Local edits take the browser body, not the AI-selected brief. Report
        # whole confirmed entries found in that actual input, including entries
        # outside the template's one example. This is not paraphrase attribution.
        normalized = " ".join(supplied_body.split())
        supplied = [entry for entry in self.eligible if " ".join(entry.text.split()) in normalized]
        selected = _within_budget(supplied, self.contexts)
        result = self.usage(selected, mode="local")
        if len(selected) < len(supplied):
            result["notices"].append("experience_usage_receipt_limit")
        return result


def _receipt(entry: ExperienceEntry, contexts: dict | None = None) -> dict:
    source = entry.source.model_dump(exclude={"quote"})
    result = {"id": entry.id, "revision": entry.revision,
              "excerpt": entry.text, "source": source}
    if contexts is not None:
        result["context"] = deepcopy(contexts.get(entry.id))
    return result


def _activity_contexts(evidence: ExperienceEvidence, signature: str) -> tuple[dict, dict, tuple[str, ...]]:
    """Resolve explicit current references; never infer a relation from words.

    Unassigned text remains a fact. Removing a relation does not withdraw its
    text; withdrawn text is handled by entry status. Known stale or ambiguous
    relations are excluded instead of being downgraded to unassigned evidence.
    """
    master = evidence.resume_master
    if master is None:
        return {}, {}, ()
    from backend.lib.target_resume_ai_validation import ACTIVITY, EDUCATION, PUBLICATION, active
    references: dict[str, list] = {}
    for section, keys in (("activities", ACTIVITY), ("education", EDUCATION), ("publications", PUBLICATION)):
        for item in master[section]:
            for reference in item["details"]:
                references.setdefault(reference["id"], []).append((section, keys, item, reference))
    contexts, reasons, notices = {}, {}, set()
    for entry in evidence.entries:
        relations = references.get(entry.id, [])
        if not relations:
            continue
        if len(relations) != 1:
            reasons[entry.id] = "activity_ambiguous"
            continue
        section, keys, item, reference = relations[0]
        if entry.revision != reference["revision"]:
            reasons[entry.id] = "activity_reference_mismatch"
            continue
        fields = {key: deepcopy(item[key]) for key in keys if key in item
                  and active(item[key], evidence.resume_text, signature)}
        if len(fields) != sum(key in item for key in keys):
            notices.add("activity_context_unconfirmed")
        # The remaining confirmed fields are individually sourced; a withdrawn
        # title cannot reappear via an organization or a generated alias.
        if fields:
            contexts[entry.id] = {"master_id": master["id"], "master_revision": master["revision"],
                                  "section": section, "id": item["id"], "fields": fields}
            if section == "activities":
                contexts[entry.id]["kind"] = item["kind"]
    return contexts, reasons, tuple(sorted(notices))


def select_experience(
    evidence: ExperienceEvidence | None, parts: dict, *, legacy_bullets: list[str] | None = None,
) -> ExperienceSelection:
    eligible: list[ExperienceEntry] = []
    excluded: list[dict] = []
    contexts = None
    context_notices = ()
    activity_reasons = {}
    if evidence is not None:
        signature = hashlib.sha256(evidence.resume_text.encode("utf-8")).hexdigest()
        if evidence.version == 2:
            contexts, activity_reasons, context_notices = _activity_contexts(evidence, signature)
        for entry in evidence.entries:
            reason = None
            if entry.status != "confirmed":
                reason = entry.status
            elif entry.source.kind == "resume":
                source = entry.source
                if source.signature != signature:
                    reason = "source_signature_mismatch"
                elif evidence.resume_text[source.start:source.end] != source.quote:
                    reason = "source_quote_mismatch"
            reason = reason or activity_reasons.get(entry.id)
            if reason:
                excluded.append({"id": entry.id, "revision": entry.revision, "reason": reason})
            else:
                eligible.append(entry)
    ranked = sorted(eligible, key=lambda entry: resume_bullet_relevance(parts, entry.text), reverse=True)
    selected = _within_budget(ranked, contexts)
    template = next((_receipt(entry, contexts) for entry in ranked
                     if len(entry.text) <= TEMPLATE_CHARACTER_BUDGET
                     and resume_bullet_relevance(parts, entry.text) >= 2), None)
    return ExperienceSelection(eligible, selected, template, excluded, bool(legacy_bullets), contexts, context_notices)
