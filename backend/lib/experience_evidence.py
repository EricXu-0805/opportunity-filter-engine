"""Confirmed experience selection without provider work or unbounded prompts.

The envelope is a student's explicit attestation, not verification of ownership
or real-world truth. Source signatures prevent reusing an entry against a changed
resume; they are not authentication tokens. No cloud profile is read here.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass

from backend.schemas import ExperienceEntry, ExperienceEvidence
from src.recommender.cold_email import resume_bullet_relevance

PROMPT_CHARACTER_BUDGET = 4000
MAX_SELECTED_ENTRIES = 8
TEMPLATE_CHARACTER_BUDGET = 220

# A PDF prints one bullet over several lines and the import proposes each line
# as its own entry, so "reaching 0.87 AUC ..." sits one entry below the action
# it completes and every entry-local fact check rejects the student's own
# sentence. A line break is a wrap when the line before it has not ended a
# sentence and the next line continues in lower case, or with a number that is
# not a list marker ("2." / "3)"). A heading, a new bullet or a capitalised line
# is never a continuation.
_WRAP = re.compile(r"(?<=[^\s.!?])[ \t]*\r?\n[ \t]*(?=[a-z]|\d(?!\d*[.)]\s))")

# A role or heading line ("Undergraduate Research Assistant, Health Imaging Lab
# (UIUC) - Jan 2026 - Present") names a title, a place and dates but nothing
# the student did, and the template printed it as the email's one example of
# their work (walked 2026-09-30). Capitals alone cannot tell such a line from
# a short bullet of names ("Trained a CNN on CheXpert"), so a line is read as
# one only on evidence of its shape: a heading all in capitals, or a row that
# names a role in one of its first two fields, as the role row of
# frontend/src/lib/resume-input.ts reads it (RESUME_ROLE, RESUME_FIELD_SEPARATOR),
# or that carries a date range. Even then a field with two lowercase words
# that do not join, date or name the role says what was done ("Health Imaging
# Lab: trained a classifier on chest radiographs"). One such word is an
# annotation ("under Prof. Smith"), and so is anything in brackets ("(remote)").
# A word without case (Chinese) says nothing either way, and a line with no
# cased word is never read as a role line, since this rule cannot read it.
# The line stays a confirmed fact for the AI brief and every check; it is only
# never the template's one quoted example.
_LINE_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
_RESUME_ROLES = (
    "intern assistant engineer researcher developer analyst manager lead leader fellow tutor consultant "
    "scientist coordinator director president officer volunteer member designer associate specialist "
    "technician founder chair captain mentor instructor grader programmer trainee editor writer"
).split()
_ROLE_LINE_LOWERCASE = frozenset((
    "a an and as at by for from in of on or the to via with "
    "present current now spring summer fall autumn winter"
).split() + _RESUME_ROLES)
_ROLE_WORD = re.compile(r"\b(?:" + "|".join(_RESUME_ROLES) + r")s?\b", re.IGNORECASE)
_ROLE_FIELD_SEPARATOR = re.compile(r"\t|\s[|–—]\s|\s-\s|,\s|\s(?:at|@)\s")
_BRACKETED = re.compile(r"\([^()]*\)|（[^（）]*）")
_DATE = (r"(?:(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]{0,6}\.?|spring|summer|fall|autumn|winter)\s+"
         r"|\d{1,2}/)?(?:19|20)\d{2}(?:[./]\d{1,2})?")
_DATE_RANGE = re.compile(rf"(?<![\w./]){_DATE}\s*(?:[-–—~]|to)\s*(?:{_DATE}|present|current|now|date)(?!\w)",
                         re.IGNORECASE)


def names_no_action(text: str) -> bool:
    """A role or heading line, which no template quotes as the student's work."""
    words = _LINE_WORD.findall(text)
    if words and all(word == word.upper() != word.lower() for word in words):
        return True
    rest = _DATE_RANGE.sub(" ", _BRACKETED.sub(" ", text))
    if not any(word.lower() != word.upper() for word in _LINE_WORD.findall(rest)):
        return False
    fields = _ROLE_FIELD_SEPARATOR.split(rest)
    if not (_DATE_RANGE.search(text) or any(_ROLE_WORD.search(field) for field in fields[:2])):
        return False
    return all(sum(word.islower() and word not in _ROLE_LINE_LOWERCASE for word in _LINE_WORD.findall(field)) < 2
               for field in fields)


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
    resume_text: str = ""

    def materials(self) -> list[dict]:
        """The facts every deterministic check reads: one per printed bullet.

        Receipts and the prompt keep the entries exactly as confirmed.
        """
        return [_fact_receipt(bullet, self.contexts)
                for bullet in _printed_bullets(self.eligible, self.resume_text, self.contexts)]

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


def _continues(above: ExperienceEntry, below: ExperienceEntry, resume_text: str, contexts: dict | None) -> bool:
    """``below`` is the next printed line of the bullet ``above`` starts.

    Both are confirmed lines of the current resume with only a line break
    between them, and neither belongs to an activity the other does not.
    """
    if above.source.kind != "resume" or below.source.kind != "resume":
        return False
    head = above.text.rstrip()
    return (re.fullmatch(r"[ \t]*\r?\n[ \t]*", resume_text[above.source.end:below.source.start]) is not None
            and _WRAP.match(head + "\n" + below.text.lstrip(), len(head)) is not None
            and (contexts or {}).get(above.id) == (contexts or {}).get(below.id))


def _printed_bullets(entries: list[ExperienceEntry], resume_text: str,
                     contexts: dict | None) -> list[list[ExperienceEntry]]:
    lines = sorted((entry for entry in entries if entry.source.kind == "resume"), key=lambda entry: entry.source.start)
    below = {above.id: line for above, line in zip(lines, lines[1:], strict=False)
             if _continues(above, line, resume_text, contexts)}
    continuations = {entry.id for entry in below.values()}
    bullets = []
    for entry in entries:
        if entry.id in continuations:
            continue
        bullet = [entry]
        while bullet[-1].id in below:
            bullet.append(below[bullet[-1].id])
        bullets.append(bullet)
    return bullets


def _fact_receipt(bullet: list[ExperienceEntry], contexts: dict | None) -> dict:
    result = _receipt(bullet[0], contexts)
    text = "\n".join(entry.text for entry in bullet)
    # A wrap kept inside one resume entry is not a sentence boundary either. A
    # line break the student typed into a manual entry is theirs and stays.
    result["excerpt"] = _WRAP.sub(" ", text) if bullet[0].source.kind == "resume" else text
    if len(bullet) > 1:
        result["source"]["end"] = bullet[-1].source.end
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
                     and resume_bullet_relevance(parts, entry.text) >= 2
                     and not names_no_action(entry.text)), None)
    return ExperienceSelection(eligible, selected, template, excluded, bool(legacy_bullets), contexts, context_notices,
                               evidence.resume_text if evidence is not None else "")
