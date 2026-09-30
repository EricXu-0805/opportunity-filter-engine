"""Local templates and limited manual checks for user-imported, unverified targets.

No model, public opportunity projection, source-derived qualification, research
or recipient is consumed here. A source title is quoted as the user's saved
label, not an assertion that a professor is recruiting. The manual rule check
is finite; a clean result is not a semantic truth or delivery guarantee.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from backend.lib.email_claims import unsupported_action_claims
from backend.lib.email_contact_context import contact_context_receipt
from backend.lib.email_target_conditions import target_condition_claim_violations
from backend.lib.experience_evidence import select_experience
from backend.lib.private_email_schema import PrivateEmailRequest, PrivateEmailValidationRequest
from backend.lib.private_import_targets_schema import PrivateTargetError

_EMPTY_CONDITIONS = {'version': 1, 'record_kind': 'unverified', 'conditions': [], 'template_request': None}
_SINGLE_EMAIL = re.compile(r'^[^\s@,;<>"\\]+@[^\s@,;<>"\\]+\.[^\s@,;<>"\\]+$')


def binding(data: PrivateEmailRequest, context: dict) -> dict:
    return {'owner_id': context['owner_id'], 'opportunity_id': context['id'],
            'target_version': context['writing_version'], 'source_version': context['source_version'],
            'private_context': context,
            'contact_context_receipt': contact_context_receipt(
                data.contact_context.model_dump(exclude_none=True) if data.contact_context else None),
            'target_conditions': dict(_EMPTY_CONDITIONS)}


def _selection(data: PrivateEmailRequest):
    # Stable input order, not a claim of a research match to an unverified label.
    # The shared selector still rejects withdrawn, stale and ambiguous entries.
    return select_experience(data.experience_evidence, {})


def _condition_issues(text: str, evidence: list[str]) -> list[str]:
    issues = target_condition_claim_violations(text, _EMPTY_CONDITIONS, student_evidence_texts=evidence)
    if 'unsupported attachment claim' in unsupported_action_claims(text):
        issues.append('unsupported_attachment_claim')
    return sorted(set(issues))


def _fits(subject: str, body: str) -> bool:
    return len(subject.encode('utf-16-le')) // 2 <= 2000 and len(body.encode('utf-16-le')) // 2 <= 5000


def template_variants(data: PrivateEmailRequest, context: dict) -> dict:
    selection = _selection(data)
    # This is formatting of a quoted imported label, not source normalization.
    # Keep every printable character; separators cannot create template sections.
    # The stored source and private context retain the original exact title.
    title = '“' + re.sub(r'[\r\n\t\u2028\u2029]', ' ', context['title']) + '”'
    subject = 'Inquiry about an opportunity'
    start = f"Hello,\n\nMy name is {data.profile.name}. I saved a note titled {title} and would like to ask about it."
    availability = data.contact_context.availability if data.contact_context else None
    ending = ('\n\n' + availability.text if availability else '') + (
        '\n\nCould you let me know whom I should contact and which application process I should follow?'
        f'\n\nThank you,\n{data.profile.name}')
    plain = start + ending
    if not _fits(subject, plain):
        raise PrivateTargetError('private_email_draft_too_large', 413)
    body, quoted = plain, []
    skipped_claim, skipped_size = False, False
    for material in selection.selected:
        original = material['excerpt']
        # Attested work is not proof of a completed attachment, target reading,
        # or that the user meets an imported opportunity's requirements.
        if _condition_issues(original, [original]) or unsupported_action_claims(original):
            skipped_claim = True
            continue
        candidate = start + '\n\n' + original + ending
        if not _fits(subject, candidate):
            skipped_size = True
            continue
        body, quoted = candidate, [material]
        break
    usage = selection.usage(quoted, mode='local')
    if skipped_claim:
        usage['notices'].append('private_template_claim_omission')
    if skipped_size or (selection.eligible and not selection.selected):
        usage['notices'].append('experience_template_budget_omission')
    common = binding(data, context)
    return {**common, 'generated_at': datetime.now(UTC).isoformat(),
            'experience_usage': usage,
            'variants': [{'subject': subject, 'body': body, 'experience_usage': usage,
                          'contact_context_receipt': common['contact_context_receipt'],
                          'target_conditions': common['target_conditions']}]}


def validate_manual(data: PrivateEmailValidationRequest, context: dict) -> dict:
    issues = set()
    if not data.subject.strip() or not data.body.strip():
        issues.add('empty_draft')
    if (not _SINGLE_EMAIL.fullmatch(data.recipient) or any(ord(c) < 32 or ord(c) == 127 for c in data.recipient)):
        issues.add('invalid_recipient')
    if context['contact_policy']['state'] == 'blocked':
        issues.add('contact_blocked')
    elif not data.contact_requirements_reviewed:
        issues.add('contact_review_required')
    selection = _selection(data)
    issues.update(_condition_issues(data.subject + '\n' + data.body, [entry.text for entry in selection.eligible]))
    return {**binding(data, context), 'outcome': 'review_required' if issues else 'ready', 'issues': sorted(issues)}
