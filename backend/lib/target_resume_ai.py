"""One bounded, evidence-mapped model batch against complete, locally attributable evidence."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace

from backend.lib import llm_budget
from backend.lib.evidence_map import (
    GENERATION_DEADLINE_SECONDS,
    ROW_FORMAT,
    SYSTEM_PROMPT_CORE,
    Outcome,
    ReviewPair,
    Unit,
    anchor_payload,
    check_rewrite,
    gate,
    parse_rows,
    without_terms,
)
from backend.lib.llm import chat_completion, model_for
from backend.lib.target_resume_ai_grounding import SOURCE_CHECK_VERSION, language
from backend.lib.target_resume_ai_schema import (
    MAX_DIRECTION_CHARACTERS,
    MAX_EXPERIENCE_CHARACTERS,
    MAX_EXPERIENCE_UNITS,
    MAX_ORIGINAL_CHARACTERS,
    MAX_PROMPT_CHARACTERS,
    MAX_TARGET_CHARACTERS,
    PIPELINE_VERSION,
)
from backend.lib.target_resume_ai_validation import (
    InvalidTargetResume,
    canonical,
    fail,
    fingerprint,
    shape,
    text,
    units_for,
)
from backend.lib.target_resume_context import target_context_character_count
from backend.lib.target_resume_rationale import REASON_PROMPT, render_reason
from backend.lib.target_resume_support import (
    complete_source_quotes,
    resolve_support_groups,
    support_echo,
)

FULL_TARGET_ADDENDUM = """FULL RESUME. The JSON also holds "locale", "criteria" (the opportunity's published constraints: never anchors, never evidence), "student_direction" when present (the student's interests: direction only, never evidence of skills or past work) and "block_contexts" (the fact lines of each unit's block: context only). Each unit also has kind "experience" (a line about what the student did) or "fact" (a title, organization, date, skill or similar). Add to every unit's entry:
- "priority": "high", "normal" or "low" for how much this unit matters to this opportunity; "high" needs at least one link.
- "reason": one category as described above.
Fact units are protected: decision "keep", ops [], text null, keep_reason "no_link" or "already_aligned"; their links are shown to the student as advice. support_sources, when present, are other lines of the same activity that the student confirmed. Together with one of the operations above, a rewrite may add a support line's clauses word for word, every number, tool and qualifier staying with its own action; the length limit then counts the original and those lines together.
OUTPUT LANGUAGE. Write each rewrite in the language of its own original, whatever the locale: an English line stays English and a Chinese line stays Chinese. Never translate a line.
OUTPUT: one JSON object, no markdown fences, nothing after it, one entry per unit:
{"units":[""" + ROW_FORMAT[:-1] + ""","priority":"high|normal|low","reason":"<category>"}]}
List only the operations you used. "text" is null exactly when decision is "keep"."""

SYSTEM_PROMPT = REASON_PROMPT + SYSTEM_PROMPT_CORE + "\n" + FULL_TARGET_ADDENDUM
PRIORITIES = ("high", "normal", "low")
ROW_EXTRA_KEYS = ("priority", "reason")
REVIEW_UNCHECKED = "rewrite_unchecked"


def target_character_count(target):
    return target_context_character_count(target)


def build_prompt(doc, selected, locale, anchors):
    contexts = {}
    for section in doc["document"]["sections"]:
        for block in section["blocks"]:
            contexts[(section["id"], block["id"])] = [
                {"role": row["role"], "label": row["label"], "value": row["original"]}
                for row in block["lines"] if row["evidence"]["kind"] == "fact"
            ]
    # Deliberately exclude editable text, raw resume, unrelated experiences and basics.
    selected_blocks = dict.fromkeys((unit["section_id"], unit["block_id"]) for unit in selected)
    target = doc["target_snapshot"]
    payload = {"locale": locale, "opportunity": {"title": target["title"], "organization": target["organization"]},
        "anchors": anchor_payload(anchors), "criteria": deepcopy(target["criteria"]),
        "block_contexts": [{"section_id": sid, "block_id": bid, "fields": contexts[(sid, bid)]}
                           for sid, bid in selected_blocks],
        "units": [
            {"unit_id": unit["unit_id"], "section_id": unit["section_id"], "block_id": unit["block_id"],
             "kind": unit["evidence"]["kind"], "role": unit["role"], "label": unit["label"],
             "original": unit["original"],
             **({"support_sources": deepcopy(unit["support_sources"])} if unit.get("support_sources") else {})}
            for unit in selected
        ]}
    if "research_interests" in doc["base_snapshot"]:
        payload["student_direction"] = {"research_interests": doc["base_snapshot"]["research_interests"]}
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": canonical(payload)}]


def receipt(unit, code=None, suggestion=None, status=None):
    """Exactly one receipt per selected unit.

    suggested: a reviewed rewrite (experience) or advice (fact).
    unchanged: an experience kept, with advice and the keep reason.
    skipped: no usable result; the code says why and whether to retry.
    """
    result = {key: deepcopy(unit[key]) for key in ("unit_id", "section_id", "block_id", "evidence", "before_text")}
    result.update(status=status or ("skipped" if suggestion is None else "suggested"), reason_code=code,
                  suggestion=suggestion)
    return result


def response_envelope(request, doc, units, protected, receipts, logical_calls):
    skipped = sum(row["status"] == "skipped" for row in receipts)
    return {"version": 1, "pipeline_version": PIPELINE_VERSION, "request_id": request.request_id,
            # Opt-in preserves the exact response shape for older clients. This
            # identifies rule scope, not a signed proof or semantic truth claim.
            **({"check_version": SOURCE_CHECK_VERSION} if request.include_check_version else {}),
            "document_id": doc["id"], "opportunity_id": doc["opportunity_id"],
            "document_signature": request.document_signature, "base": deepcopy(doc["base"]),
            "manifest": {"unit_ids": [unit["unit_id"] for unit in units], "protected_unit_count": protected},
            "method": "unavailable" if skipped == len(receipts) else "partial" if skipped else "ai",
            "logical_calls": logical_calls, "provider_attempts_upper_bound": 2 * logical_calls,
            "receipts": receipts, **support_echo(request)}


def prepare_batch(request, doc):
    if doc["target_snapshot"].get("context_version") != 4:
        fail("legacy_target_context")
    if fingerprint(doc) != request.document_signature:
        fail("document_signature_mismatch")
    units, protected = units_for(doc)
    lookup = {unit["unit_id"]: unit for unit in units}
    ids = request.selected_unit_ids
    if any(type(ident) is not str for ident in ids) or len(set(ids)) != len(ids) or any(ident not in lookup for ident in ids):
        fail("invalid_unit_selection")
    if sum(lookup[ident]["evidence"]["kind"] == "experience" for ident in ids) > MAX_EXPERIENCE_UNITS:
        fail("invalid_unit_selection")
    support = resolve_support_groups(doc, request, ids)
    selected = [{**deepcopy(lookup[ident]), **({"support_sources": support[ident]} if ident in support else {})} for ident in ids]
    processable = [unit for unit in selected if not unit_too_large(unit)]
    sent = {item["unit_id"]: item for unit in processable for item in [unit, *unit.get("support_sources", [])]}
    if sum(len(unit["original"]) for unit in sent.values()) > MAX_ORIGINAL_CHARACTERS or sum(
        len(unit["original"]) for unit in sent.values() if unit["evidence"]["kind"] == "experience"
    ) > MAX_EXPERIENCE_CHARACTERS:
        fail("batch_too_large")
    return units, protected, selected, processable


def unit_too_large(unit):
    return len(unit["original"]) > MAX_ORIGINAL_CHARACTERS or (
        unit["evidence"]["kind"] == "experience" and len(unit["original"]) > MAX_EXPERIENCE_CHARACTERS
    )


def anchor_quote(quote, source):
    """Return the quote spanning its literal occurrence in this same field.

    Models copy text reliably but miscount offsets, so a literal quote is
    re-anchored to the occurrence nearest the model's start (ties: earliest).
    Offsets are Unicode codepoints; a quote absent from the field is None."""
    start, end, value = quote["start"], quote["end"], quote["quote"]
    if type(start) is not int or type(end) is not int or not value:
        return None
    hits = []
    hit = source.find(value)
    while hit != -1:
        hits.append(hit)
        hit = source.find(value, hit + 1)
    if not hits:
        return None
    best = min(hits, key=lambda position: (abs(position - start), position))
    return {**quote, "start": best, "end": best + len(value)}


def valid_quotes(value, target):
    """Return the target quotes with literal spans, or None if any is invalid."""
    if type(value) is not list or not value:
        return None
    anchored = []
    for quote in value:
        try:
            paper = quote.get("field") in ("paper_title", "paper_abstract") if type(quote) is dict else False
            lab = quote.get("field") in ("lab_heading", "lab_text") if type(quote) is dict else False
            shape(quote, ("field", *(("page_index", "section_index") if lab else ("paper_index" if paper else "requirement_index",)), "start", "end", "quote"))
            text(quote["quote"], nonblank=True)
            if paper:
                research = target.get("research", {})
                if target.get("context_version") not in (3, 4) or research.get("status") != "available":
                    return None
                works = research["snapshot"]["works"]
                index = quote["paper_index"]
                if type(index) is not int or not 0 <= index < len(works):
                    return None
                work = works[index]
                if quote["field"] == "paper_abstract" and work["abstract_status"] != "present":
                    return None
                source = work["title"] if quote["field"] == "paper_title" else work["abstract"]
            elif lab:
                context = target.get("lab", {})
                if target.get("context_version") != 4 or context.get("status") != "available":
                    return None
                pages = context["snapshot"]["pages"]
                index, section_index = quote["page_index"], quote["section_index"]
                if type(index) is not int or not 0 <= index < len(pages):
                    return None
                sections = pages[index]["sections"]
                if type(section_index) is not int or not 0 <= section_index < len(sections):
                    return None
                section = sections[section_index]
                source = section["heading"] if quote["field"] == "lab_heading" else section["text"]
            elif quote["field"] == "description" and quote["requirement_index"] is None:
                source = target["description"]
            elif quote["field"] == "requirement" and type(quote["requirement_index"]) is int and 0 <= quote["requirement_index"] < len(target["requirements"]):
                source = target["requirements"][quote["requirement_index"]]
            else:
                return None
            quote = anchor_quote(quote, source)
            if quote is None:
                return None
            anchored.append(quote)
        except (InvalidTargetResume, KeyError, TypeError):
            return None
    return anchored



def valid_source_quotes(quotes, originals):
    """Return the source quotes anchored in their own unit, or None if any is invalid."""
    if type(quotes) is not list or not quotes:
        return None
    anchored = []
    try:
        for quote in quotes:
            shape(quote, ("unit_id", "start", "end", "quote"))
            text(quote["quote"], nonblank=True)
            if type(quote["unit_id"]) is not str or quote["unit_id"] not in originals:
                return None
            quote = anchor_quote(quote, originals[quote["unit_id"]])
            if quote is None:
                return None
            anchored.append(quote)
    except (InvalidTargetResume, KeyError, TypeError):
        return None
    return anchored


@dataclass
class Pending:
    """A rewrite that passed the contract and the locks, waiting for the review."""
    unit: dict
    em_unit: Unit
    outcome: Outcome
    priority: str
    category: str
    ops_raw: list


def _em_unit(unit):
    return Unit(unit["unit_id"], unit["original"], unit["original"],
                support=tuple((source["unit_id"], source["original"]) for source in unit.get("support_sources", [])),
                keyed=True)


def _suggestion(unit, outcome, priority, category, locale, *, proposed=None, keep_code=None, alternative=None):
    links = [link.public() for link in outcome.links]
    targets = list({canonical(link["target_evidence"]): link["target_evidence"] for link in links}.values())
    sources = [link["source_evidence"] for link in links] or complete_source_quotes(unit)
    ops = outcome.ops if proposed is not None else []
    suggestion = {"priority": priority, "reason": render_reason(category, priority, sources, targets, locale,
                                                                links=links, ops=ops, keep_code=keep_code),
                  "target_evidence": targets, "proposed_text": proposed, "links": links, "ops": ops,
                  "alternative_text": alternative}
    if alternative is not None:
        # The wording without the posting's terms relabels nothing; its reason must not say it does.
        suggestion["alternative_reason"] = render_reason(
            category, priority, sources, targets, locale, links=links, ops=[op for op in ops if op != "relabel"],
            keep_code=keep_code)
    if unit.get("support_sources"):
        suggestion["source_evidence"] = complete_source_quotes(unit)
    return suggestion


def _advice(unit, outcome, priority, category, locale):
    """A kept experience or a fact line: its links and priority stay available."""
    if unit["evidence"]["kind"] != "experience":
        return receipt(unit, suggestion=_suggestion(unit, outcome, priority, category, locale))
    return receipt(unit, outcome.code, _suggestion(unit, outcome, priority, category, locale,
                                                   keep_code=outcome.code), status="unchanged")


def parse_output(raw, selected, anchors, locale="en"):
    """(receipts, pending): final receipts, and the rewrites that go to the review.

    A row is checked against the evidence-map contract and the claim locks.
    A fact line may only be kept; its links become advice. A kept or refused
    experience keeps its advice as "unchanged" so its priority still counts.
    """
    rows = parse_rows(raw, {unit["unit_id"] for unit in selected}, key="units")
    if rows is None:
        return [receipt(unit, "invalid_model_response") for unit in selected], []
    by_id = {anchor.id: anchor for anchor in anchors}
    results, pending = [], []
    for unit in selected:
        row = rows.get(unit["unit_id"])
        if row is None:
            results.append(receipt(unit, "missing_result"))
            continue
        if (not isinstance(row, dict) or row.get("priority") not in PRIORITIES or not isinstance(row.get("reason"), str)
                or not row["reason"].strip() or len(row["reason"]) > 6000
                or (unit["evidence"]["kind"] != "experience" and (row.get("decision") != "keep" or row.get("ops")))):
            results.append(receipt(unit, "invalid_model_response"))
            continue
        em_unit = _em_unit(unit)
        # The locale picks only the language of the server's reasons; a rewrite keeps its original's.
        outcome = check_rewrite(em_unit, row, by_id, output_language=language(unit["original"]),
                                extra_keys=ROW_EXTRA_KEYS)
        if outcome.status == "invalid":
            results.append(receipt(unit, "invalid_model_response"))
            continue
        # "high" is a claim about relevance; without a verified link it is "normal".
        priority = row["priority"] if row["priority"] != "high" or outcome.links else "normal"
        if outcome.status == "pending":
            outcome = gate(outcome, em_unit)
        if outcome.status == "pending":
            pending.append(Pending(unit, em_unit, outcome, priority, row["reason"], row["ops"]))
        else:
            results.append(_advice(unit, outcome, priority, row["reason"], locale))
    return results, pending


def review_pairs(pending):
    """The review sees the unit original plus every confirmed support line of the same activity."""
    pairs = []
    for item in pending:
        support = "".join(f"\nConfirmed source for the same activity: {source['original']}"
                          for source in item.unit.get("support_sources", []))
        used = {op.get("link") for op in item.ops_raw if op.get("op") in ("lead_with", "relabel")}
        pairs.append(ReviewPair(item.unit["original"] + support, item.outcome.text,
                                tuple(link for link in item.outcome.links if link.id in used)))
    return pairs


def finalize(pending, verdicts, locale="en"):
    """Receipts for reviewed rewrites. An unchecked one stays retryable."""
    results = []
    for item, verdict in zip(pending, verdicts, strict=True):
        unit, outcome = item.unit, item.outcome
        if verdict == "unavailable":
            results.append(receipt(unit, REVIEW_UNCHECKED))
        elif verdict == "rejected":
            results.append(_advice(unit, replace(outcome, status="kept", code="review_rejected"), item.priority,
                                   item.category, locale))
        elif outcome.text == unit["before_text"]:
            results.append(_advice(unit, replace(outcome, status="kept", code="no_change"), item.priority,
                                   item.category, locale))
        else:
            alternative = without_terms(outcome, item.em_unit, item.ops_raw)
            results.append(receipt(unit, suggestion=_suggestion(unit, outcome, item.priority, item.category, locale,
                                                                proposed=outcome.text, alternative=alternative)))
    return results


def plan_dispatch(messages):
    """The selection plan's call (full-target-plan-v4): one whole-document plan keeps its full output budget."""
    if llm_budget.exhausted():
        return None, "budget_exhausted", 0
    raw = chat_completion(messages, max_tokens=12000, temperature=0.2, reasoning_effort="low", safe_error_logging=True,
                          **model_for("tailor"))
    return raw, None if raw else "model_unavailable", 1


def dispatch(messages, n_experience=0, n_fact=0, deadline=None):
    """One suggestions call sized to its units; the plan endpoint has plan_dispatch."""
    # Recheck at the actual worker boundary; a queued batch may outlive admission.
    if llm_budget.exhausted():
        return None, "budget_exhausted", 0
    raw = chat_completion(messages, max_tokens=350 + 320 * n_experience + 120 * n_fact, temperature=0.2,
                          reasoning_effort="low", require_complete=True, safe_error_logging=True,
                          request_timeout=GENERATION_DEADLINE_SECONDS, deadline=deadline, **model_for("tailor"))
    return raw, None if raw else "model_unavailable", 1


def prompt_too_large(messages):
    return sum(len(message["content"]) for message in messages) > MAX_PROMPT_CHARACTERS


def batch_preflight(doc, processable, locale, anchors):
    """Return (messages, None), or (None, reason) where reason is one code for
    every unit or a {unit_id: code} map when only the combination overflows.
    A target with no quotable text stops with target_has_no_text."""
    if target_character_count(doc["target_snapshot"]) > MAX_TARGET_CHARACTERS:
        return None, "target_too_large"
    if len(doc["base_snapshot"].get("research_interests", "")) > MAX_DIRECTION_CHARACTERS:
        return None, "interests_too_large"
    if not anchors:
        return None, "target_has_no_text"
    messages = build_prompt(doc, processable, locale, anchors)
    if not prompt_too_large(messages):
        return messages, None
    if prompt_too_large(build_prompt(doc, [], locale, anchors)):
        return None, "target_too_large"
    if len(processable) == 1:
        return None, "context_too_large"
    # Only a unit whose own prompt overflows is permanently too large; the rest
    # are retryable in a smaller request.
    return None, {unit["unit_id"]: "context_too_large" if prompt_too_large(build_prompt(doc, [unit], locale, anchors))
                  else "batch_context_too_large" for unit in processable}
