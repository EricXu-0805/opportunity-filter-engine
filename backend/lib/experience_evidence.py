"""Confirmed experience selection without provider work or unbounded prompts.

The envelope is a student's explicit attestation, not verification of ownership
or real-world truth. Source signatures prevent reusing an entry against a changed
resume; they are not authentication tokens. No cloud profile is read here.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from backend.schemas import ExperienceEntry, ExperienceEvidence
from src.recommender.cold_email import resume_bullet_relevance

PROMPT_CHARACTER_BUDGET = 4000
MAX_SELECTED_ENTRIES = 8
TEMPLATE_CHARACTER_BUDGET = 220


def _within_budget(entries: list[ExperienceEntry]) -> list[dict]:
    """Select whole entries; a fragment can lose a factual qualifier."""
    selected: list[dict] = []
    remaining = PROMPT_CHARACTER_BUDGET
    for entry in entries:
        if len(selected) == MAX_SELECTED_ENTRIES:
            break
        if len(entry.text) > remaining:
            continue
        selected.append(_receipt(entry))
        remaining -= len(entry.text)
    return selected


@dataclass
class ExperienceSelection:
    eligible: list[ExperienceEntry]
    selected: list[dict]
    template: dict | None
    excluded: list[dict]
    legacy_ignored: bool

    def usage(self, selected: list[dict] | None = None, *, mode: str = "ai") -> dict:
        review = any(item["reason"] in {
            "candidate", "source_signature_mismatch", "source_quote_mismatch",
        } for item in self.excluded)
        notices = ["legacy_resume_bullets_unconfirmed"] if self.legacy_ignored else []
        if mode == "ai" and len(self.selected) < len(self.eligible):
            notices.append("experience_prompt_budget_omission")
        if mode == "template" and any(len(entry.text) > TEMPLATE_CHARACTER_BUDGET for entry in self.eligible):
            notices.append("experience_template_budget_omission")
        return {
            "version": 1, "eligible_count": len(self.eligible),
            "selected": self.selected if selected is None else selected,
            "excluded": self.excluded, "needs_review": review or self.legacy_ignored,
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
        selected = _within_budget(supplied)
        result = self.usage(selected, mode="local")
        if len(selected) < len(supplied):
            result["notices"].append("experience_usage_receipt_limit")
        return result


def _receipt(entry: ExperienceEntry) -> dict:
    source = entry.source.model_dump(exclude={"quote"})
    return {"id": entry.id, "revision": entry.revision,
            "excerpt": entry.text, "source": source}


def select_experience(
    evidence: ExperienceEvidence | None, parts: dict, *, legacy_bullets: list[str] | None = None,
) -> ExperienceSelection:
    eligible: list[ExperienceEntry] = []
    excluded: list[dict] = []
    if evidence is not None:
        signature = hashlib.sha256(evidence.resume_text.encode("utf-8")).hexdigest()
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
            if reason:
                excluded.append({"id": entry.id, "revision": entry.revision, "reason": reason})
            else:
                eligible.append(entry)
    ranked = sorted(eligible, key=lambda entry: resume_bullet_relevance(parts, entry.text), reverse=True)
    selected = _within_budget(ranked)
    template = next((_receipt(entry) for entry in ranked
                     if len(entry.text) <= TEMPLATE_CHARACTER_BUDGET
                     and resume_bullet_relevance(parts, entry.text) >= 2), None)
    return ExperienceSelection(eligible, selected, template, excluded, bool(legacy_bullets))
