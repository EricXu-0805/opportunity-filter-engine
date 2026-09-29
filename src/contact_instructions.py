"""Conservative contact rules from retained, identity-bound website sections.

Never infer source instructions from generated descriptions, OG summaries,
contact addresses, papers or a model response. This module makes no network calls.
"""
from __future__ import annotations

import re
from copy import deepcopy
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

SOURCE_KEY = 'contact_instruction_sources'
_MAX_SOURCES = 8
_MAX_SECTIONS = 160
_MAX_TEXT = 4000
_MAX_RULES = 40
_UG = re.compile(r'\bundergrad(?:uate)?s?\b', re.I)
_OTHER = re.compile(r'\b(?:ph\.?d\.?|doctoral|postdoc(?:toral)?s?|graduate|masters?|visiting scholars?)\b', re.I)
_ALL = re.compile(r'\ball\s+(?:(?:prospective|interested)\s+)?(?:applicants|students|researchers)\b', re.I)
_CONTACT = re.compile(r'\b(?:e-?mail|contact|apply|application|applicants|subject|form|portal|resume|curriculum vitae|CV|transcript|cover letter|statement of interest)\b', re.I)
# Retention is broader than contact-rule interpretation: the same fetched,
# identity-bound block also supplies application-condition evidence. Keep whole
# paragraphs under relevant headings, including values with no repeated label.
# This only retains source text; it does not classify a requirement or permit email.
_APPLICATION_CONDITION = re.compile(
    r"\b(?:eligib\w*|qualifications?|requirements?|citizenship|nationals?|"
    r"permanent\s+residents?|work\s+authori[sz]ation|minimum\s+GPA|GPA|"
    r"class\s+year|year\s+of\s+study|deadline|apply\s+by|applications?\s+due|"
    r"rolling\s+(?:admissions?|applications?|basis)|required|preferred|"
    r"recommendations?|references?|transcripts?|statements?\s+of\s+(?:interest|purpose))\b"
    r"|申请资格|申请条件|申请材料|所需材料|截止日期|截止时间|国籍|居留资格|工作许可|最低绩点|年级要求",
    re.I,
)

_NO_EMAIL = re.compile(
    r"\b(?:do\s+not|don['’]t|must\s+not|should\s+not)\s+(?:directly\s+)?(?:e-?mail|contact\s+(?:me|us)\s+(?:by|via)\s+e-?mail)\b"
    r'|\b(?:do\s+not|cannot)\s+accept\s+e-?mail\s+inquiries\b'
    r'|\be-?mail\s+inquiries\s+(?:are|will\s+be)\s+not\s+accepted\b', re.I,
)
_SELF_OUTGOING = re.compile(r"\b(?:we|I|our\s+staff)\s+(?:do\s+not|don['’]t|cannot|will\s+not)\s+e-?mail\b", re.I)
_APPLICATION_ONLY = re.compile(r'\be-?mail\s+(?:your\s+)?(?:application|CV|resume|transcript)\b', re.I)
_LIMITED_PURPOSE = re.compile(r'\b(?:application\s+status|status\s+of\s+(?:your|the|my|an)\s+application|grades?|grade\s+adjustments?|recommendation|reference\s+letter|deadline\s+extension)\b|\be-?mail\b[^.!?]{0,60}\b(?:about|regarding|concerning)\b', re.I)
_EMAIL_ALLOWED = re.compile(
    r'\be-?mail\s+(?:me|us|the\s+(?:lab|professor)|(?:your|the)\s+(?:completed\s+)?application)\b'
    r'|\be-?mail\s+[^\s@]+@[^\s@]+'
    r'|\bsend\b[^.!?]{0,180}\b(?:by\s+e-?mail|via\s+e-?mail|to\s+[^\s@]+@[^\s@]+)', re.I,
)
_CONDITIONAL = re.compile(r'\b(?:if|unless|except|only\s+when|until)\b', re.I)
_NEGATIVE = re.compile(r"\b(?:do\s+not|don['’]t|must\s+not|should\s+not|not|never|avoid|without|no\s+need)\b", re.I)
_OPTIONAL = re.compile(r'\b(?:may|optional|for\s+example|suggest(?:ed)?|could)\b|\bcan\s+(?:attach|include|use)\b|\be\.g\.', re.I)
_FORM = re.compile(r'\b(?:use|complete|submit|fill)\b[^.!?]{0,160}\b(?:form|portal)\b', re.I)
_SUBJECT_AFTER = re.compile(r'\bsubject(?:\s+line)?\b[^\n.!?]{0,60}?["“]([^"”\n]{1,160})["”]', re.I)
_SUBJECT_BEFORE = re.compile(r'["“]([^"”\n]{1,160})["”]\s+(?:in|as|for)\s+(?:(?:the|your)\s+)?(?:e-?mail\s+)?subject(?:\s+line)?\b', re.I)
_PLACEHOLDER = re.compile(r'\[[^\]]+\]|\{[^}]+\}|<[^>]+>')
_SUBJECT_CUE = re.compile(r'\b(?:use|put|include)\b[^.!?]{0,160}\bsubject(?:\s+line)?\b|\bsubject(?:\s+line)?\s*:', re.I)
_MATERIAL_CUE = re.compile(r'\b(?:attach|include|send|submit|provide|complete)\b|\be-?mail\b[^.!?]{0,180}\bwith\b', re.I)
_MATERIALS = (
    ('resume_cv', r'\b(?:resume|résumé|CV|curriculum vitae)\b'),
    ('unofficial_transcript', r'\bunofficial\s+transcript\b'),
    ('transcript', r'\btranscript\b'),
    ('cover_letter', r'\bcover\s+letter\b'),
    ('statement_of_interest', r'\bstatement\s+of\s+interest\b'),
    ('application_form', r'\bapplication\s+(?:form|file)\b'),
    ('single_pdf', r'\b(?:a\s+)?(?:single|one)\s+PDF\b'),
)


def _url(value):
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        p = urlsplit(value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
            return None
        return urlunsplit((p.scheme, p.netloc.lower(), p.path or '/', p.query, ''))
    except ValueError:
        return None


def _identity(value):
    return ' '.join(value.casefold().split()) if isinstance(value, str) else ''


def source_from_html(html, *, source_url: str, record_source_url: str | None = None,
                     identity_name: str | None = None, checked_at: str | None = None) -> dict | None:
    """Retain headings and whole body paragraphs only after a successful fetch.

    Callers own fetch/identity verification. The explicit binding is checked
    again at consumption. Oversized/unsupported pages fail closed, not truncated.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser') if isinstance(html, str) else html
    body = soup.find('main') or soup.find('article') or soup.find('body')
    if body is None or not _url(source_url) or not _url(record_source_url or source_url):
        return None
    headings = {}
    sections = []
    for element in body.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'ul', 'ol']):
        if element.find_parent(['nav', 'header', 'footer', 'aside', 'script', 'style']):
            continue
        if element.name in ('ul', 'ol') and element.find_parent(['ul', 'ol']):
            continue
        if element.name == 'p' and element.find_parent(['ul', 'ol']):
            continue
        text = element.get_text(' ', strip=True)
        if not text:
            continue
        if element.name.startswith('h'):
            if len(text) > 1000:
                return None
            level = int(element.name[1])
            headings = {n: h for n, h in headings.items() if n < level}
            headings[level] = text
            continue
        heading = ' > '.join(headings.values())
        if element.name in ('ul', 'ol') and sections and sections[-1]['heading'] == heading:
            sections[-1]['text'] += '\n' + text
        else:
            sections.append({'heading': heading, 'text': text})
        if len(sections) > _MAX_SECTIONS or any(len(s['text']) > _MAX_TEXT for s in sections[-1:]):
            return None
    sections = [section for section in sections
                if _CONTACT.search(section['text'])
                or _APPLICATION_CONDITION.search(section['heading'])
                or _APPLICATION_CONDITION.search(section['text'])]
    if not sections:
        return None
    result = {'source_url': source_url, 'record_source_url': record_source_url or source_url,
              'checked_at': checked_at or datetime.now(UTC).isoformat(), 'sections': sections}
    if identity_name:
        result['identity_name'] = identity_name
    return result


def retained_sources(value) -> list[dict]:
    """Detached transfer of collector-owned source blocks; no model field merge."""
    return deepcopy(value) if isinstance(value, list) and len(value) <= _MAX_SOURCES else []


def _applicable(heading, text):
    # A mixed/other-audience heading must never inherit a nearby UG paragraph.
    if _OTHER.search(heading):
        return False
    if _UG.search(heading) or _ALL.search(heading):
        return not _OTHER.search(text)
    return bool((_UG.search(text) or _ALL.search(text)) and not _OTHER.search(text))


def contact_instructions_for(record: dict) -> dict:
    output = {'version': 1, 'status': 'unknown', 'email_policy': 'unknown', 'rules': []}
    if not isinstance(record, dict):
        return output
    metadata = record.get('metadata')
    sources = metadata.get(SOURCE_KEY) if isinstance(metadata, dict) else None
    if not isinstance(sources, list) or len(sources) > _MAX_SOURCES:
        return output
    current_urls = {_url(record.get(key)) for key in ('source_url', 'url')} - {None}
    is_faculty = record.get('source_type') == 'faculty_research' or record.get('record_kind') == 'faculty_contact'
    seen = set()
    all_kinds = set()
    all_subjects = set()
    for source in sources:
        if not isinstance(source, dict) or _url(source.get('record_source_url')) not in current_urls or not _url(source.get('source_url')):
            continue
        if is_faculty and (not _identity(record.get('pi_name')) or _identity(source.get('identity_name')) != _identity(record.get('pi_name'))):
            continue
        checked_at = source.get('checked_at')
        try:
            if not isinstance(checked_at, str):
                continue
            verified_at = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
            if verified_at.tzinfo is None or verified_at > datetime.now(UTC):
                continue
        except ValueError:
            continue
        sections = source.get('sections')
        if not isinstance(sections, list) or len(sections) > _MAX_SECTIONS:
            continue
        for section in sections:
            if not isinstance(section, dict):
                continue
            heading, text = section.get('heading'), section.get('text')
            if not isinstance(heading, str) or not isinstance(text, str) or not text or len(text) > _MAX_TEXT:
                continue
            if not _applicable(heading, text) or not _CONTACT.search(text):
                continue

            def add(kind, *, _text=text, _url=source['source_url'], _checked_at=checked_at, **extra):
                item = {'kind': kind, 'quote': _text, 'source_url': _url, 'checked_at': _checked_at, **extra}
                key = (kind, _text, _url, extra.get('subject'), extra.get('subject_template'), tuple(extra.get('materials', [])))
                if key not in seen:
                    seen.add(key)
                    all_kinds.add(kind)
                    if kind == 'subject' and (extra.get('subject') or extra.get('subject_template')):
                        all_subjects.add(extra.get('subject') or extra.get('subject_template'))
                    if len(output['rules']) < _MAX_RULES:
                        output['rules'].append(item)
                    else:
                        # Do not call excess evidence unknown or invent a conflict.
                        # Both action layers must refuse until the source is reviewed.
                        output.update(review_required=True, reason='too_many_requirements')

            limited = bool(_LIMITED_PURPOSE.search(text) or _CONDITIONAL.search(text) or _SELF_OUTGOING.search(text))
            banned = bool(_NO_EMAIL.search(text)) and not limited and not _APPLICATION_ONLY.search(text)
            if banned:
                add('no_email')
                if _FORM.search(text):
                    add('form_only')
            elif not limited and not _NEGATIVE.search(text) and _EMAIL_ALLOWED.search(text):
                add('email_allowed')
            subjects = [] if _NEGATIVE.search(text) or _OPTIONAL.search(text) or _CONDITIONAL.search(text) else _SUBJECT_AFTER.findall(text) + _SUBJECT_BEFORE.findall(text)
            for subject in dict.fromkeys(subjects):
                field = 'subject_template' if _PLACEHOLDER.search(subject) else 'subject'
                add('subject', **{field: subject})
            if not subjects and not _NEGATIVE.search(text) and not _OPTIONAL.search(text) and not _CONDITIONAL.search(text) and _SUBJECT_CUE.search(text):
                add('subject')
            if _MATERIAL_CUE.search(text) and not _NEGATIVE.search(text) and not _OPTIONAL.search(text) and not _CONDITIONAL.search(text):
                materials = [name for name, pattern in _MATERIALS if re.search(pattern, text, re.I)]
                if 'unofficial_transcript' in materials:
                    materials.remove('transcript')
                if materials:
                    add('materials', materials=materials)
    kinds = all_kinds
    subjects = all_subjects
    if ('email_allowed' in kinds and 'no_email' in kinds) or len(subjects) > 1:
        output.update(status='conflicting', email_policy='conflicting')
    elif output['rules']:
        output['status'] = 'known'
        if 'form_only' in kinds:
            output['email_policy'] = 'form_only'
        elif 'no_email' in kinds:
            output['email_policy'] = 'not_accepted'
        elif 'email_allowed' in kinds:
            output['email_policy'] = 'allowed'
    return output
