"""Bounded source-backed application conditions, never student qualification.

Only retained website sections can establish a stated term. An unstamped legacy
value, source URL, review flag, award policy or generated description cannot.
This is a deliberately finite English extractor/claim check, not semantic proof.
The public projector must apply URL/contact privacy before using the result.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from src.evidence import record_kind

CONDITIONS_VERSION = 1
CONDITIONS_MAX_AGE = timedelta(days=60)
CONDITION_FIELDS = (
    'eligibility.preferred_year', 'eligibility.min_gpa', 'eligibility.majors',
    'eligibility.skills_required', 'eligibility.skills_preferred',
    'eligibility.citizenship_required', 'eligibility.international_friendly',
    'eligibility.work_auth_notes', 'eligibility.eligibility_text_raw',
    'deadline', 'is_rolling', 'application.requires_resume',
    'application.requires_cover_letter', 'application.requires_transcript',
    'application.requires_recommendation',
)
CONDITION_REASONS = frozenset({
    'source_stated', 'inferred_field', 'program_policy', 'unverified_legacy_value',
    'no_source_evidence', 'source_stale', 'source_conflict',
    'normalized_source_conflict', 'source_binding_mismatch', 'source_unavailable',
    'unsupported_source_wording', 'source_overflow', 'source_not_public',
})
_UG = re.compile(r'\bundergrad(?:uate)?s?\b', re.I)
_OTHER = re.compile(r'\b(?:graduate|masters?|doctoral|ph\.?d\.?|postdocs?|postdoctoral|high school)\b', re.I)
_ALL = re.compile(r'\ball\s+(?:(?:prospective|interested)\s+)?(?:applicants|students)\b', re.I)
_CONDITIONAL = re.compile(r'\b(?:if|unless|except|only when|until|depending|may|might|optional|could|for example|not necessarily)\b', re.I)
_CONDITION_CUE = re.compile(r'\b(?:eligib\w*|GPA|citizens?\w*|permanent resident\w*|international students|deadline|rolling|skills?|majors?|resume|résumé|CV|transcript|cover letter|recommendation|applicants?)\b', re.I)
_MATERIALS = {
    'application.requires_resume': ('resume', r'\b(?:resume|résumé|CV|curriculum vitae)\b'),
    'application.requires_cover_letter': ('cover letter', r'\bcover letter\b'),
    'application.requires_transcript': ('transcript', r'\b(?:unofficial\s+)?transcript\b'),
    'application.requires_recommendation': ('recommendation letter', r'\b(?:recommendation|reference)\s+letters?\b|\brecommendations?\b'),
}
_MONTHS = {name.casefold(): index for index, name in enumerate((
    'January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December'), 1)}
_DATE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b|\b(?:'+'|'.join(_MONTHS)+r')\s+\d{1,2},?\s+\d{4}\b', re.I)
_GPA = re.compile(r'\b(?:minimum\s+GPA\s*(?:(?:of|is)\s*)?:?\s*([0-4](?:\.\d+)?)|GPA\s+(?:of\s+)?([0-4](?:\.\d+)?)\s+(?:or\s+(?:higher|above)|is\s+required))\b', re.I)
_GPA_VALUE = re.compile(r'\bGPA\s*(?:of|is|:)?\s*([0-4](?:\.\d+)?)\b|\b([0-4](?:\.\d+)?)\s*(?:/\s*4(?:\.0)?)?\s+GPA\b', re.I)
_YEAR_WORDS = {'freshman': r'freshm[ae]n', 'sophomore': r'sophomores?', 'junior': r'juniors?', 'senior': r'seniors?'}
_CITIZEN = re.compile(r'\b(?:u\.?s\.?|united states)\s+(?:citizens?|nationals?)\b|\bpermanent residents?\b', re.I)


def _url(value):
    if not isinstance(value, str) or not value or len(value) > 2000 or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return None
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path or '/', parsed.query, ''))
    except ValueError:
        return None


def _identity(value):
    return ' '.join(value.casefold().split()) if isinstance(value, str) else ''


def _value(record, field):
    value = record
    for key in field.split('.'):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _safe_value(value):
    if value is None or isinstance(value, bool):
        return value, True
    if isinstance(value, int | float):
        try:
            return (value, True) if math.isfinite(value) else (None, False)
        except OverflowError:
            return None, False
    if isinstance(value, str):
        return (value, True) if len(value) <= 20000 and not any(0xD800 <= ord(c) <= 0xDFFF for c in value) else (None, False)
    if isinstance(value, list) and len(value) <= 512 and all(isinstance(v, str) and len(v) <= 1000 and not any(0xD800 <= ord(c) <= 0xDFFF for c in v) for v in value):
        return list(value), True
    return None, False


def _known(value):
    return value is not None and value != '' and value != [] and value != 'unknown' and value != ['unknown']


def _same(left, right):
    if isinstance(left, list) and isinstance(right, list):
        return sorted(_identity(v) for v in left) == sorted(_identity(v) for v in right)
    # False must not compare equal to a numeric zero from a malformed field.
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _parse_date(value):
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return datetime.strptime(value, '%Y-%m-%d').date().isoformat()
        month, day, year = value.replace(',', '').split()
        return datetime(int(year), _MONTHS[month.casefold()], int(day)).date().isoformat()
    except (ValueError, KeyError):
        return None


def _sentences(text):
    # Keep decimal GPA and common U.S. abbreviations intact.
    return re.split(r'\.(?=\s+[A-Z])|;\s*|\n', re.sub(r'\bU\.S\.', 'US', text, flags=re.I))


def _extract(text):
    """Return finite, unambiguous field/value candidates; no arbitrary LLM tags."""
    found = []
    for sentence in _sentences(text):
        if _CONDITIONAL.search(sentence):
            continue
        if not re.search(r'\b(?:not|no|without|preferred|recommended)\b', sentence, re.I):
            for match in _GPA.finditer(sentence):
                found.append(('eligibility.min_gpa', float(match.group(1) or match.group(2))))
        if re.search(r'\b(?:applicants must be|open (?:only )?to|eligible (?:applicants|students)(?: are|:))\b', sentence, re.I):
            years = [year for year, pattern in _YEAR_WORDS.items() if re.search(r'\b'+pattern+r'\b', sentence, re.I)]
            if years and not re.search(r'\b(?:not|no|excluding)\b', sentence, re.I):
                found.append(('eligibility.preferred_year', years))
        if _CITIZEN.search(sentence) and re.search(r'\b(?:must be|limited to|restricted to|citizens? only|citizenship (?:is )?required)\b', sentence, re.I) and not re.search(r'\b(?:not|no)\b', sentence, re.I):
            found.append(('eligibility.citizenship_required', sentence.strip() if re.search(r'\b(?:or|nationals?|permanent residents?)\b', sentence, re.I) else True))
        if re.search(r'\binternational students (?:are )?(?:eligible|welcome|can apply)\b', sentence, re.I):
            found.append(('eligibility.international_friendly', 'yes'))
        if re.search(r'\binternational students (?:are )?not eligible\b', sentence, re.I):
            found.append(('eligibility.international_friendly', 'no'))
        for label, field in ((r'required skills', 'eligibility.skills_required'), (r'preferred skills', 'eligibility.skills_preferred'), (r'eligible majors', 'eligibility.majors')):
            match = re.fullmatch(r'\s*'+label+r'\s*:\s*([^.!?]+)[.!]?\s*', sentence, re.I)
            if match:
                items = [v.strip() for v in re.split(r',|\s+and\s+', match.group(1)) if v.strip()]
                if items and not re.search(r'\b(?:not|no|or|such as|including)\b', match.group(1), re.I):
                    found.append((field, items))
        for field, (_, pattern) in _MATERIALS.items():
            if not re.search(pattern, sentence, re.I):
                continue
            # Require the negative/positive predicate to apply to the material,
            # not an unrelated clause in the same paragraph.
            negative = re.search('(?:'+pattern+r')\s+(?:is|are)\s+not required\b', sentence, re.I)
            positive = (re.search(r'\b(?:must|are required to)\s+(?:submit|include|provide|attach|send)\b', sentence, re.I)
                        or re.search(r'^\s*(?:please\s+|to apply,?\s+)(?:submit|include|provide|attach|send)\b', sentence, re.I)
                        or re.search('(?:'+pattern+r')\s+(?:is|are)\s+required\b', sentence, re.I))
            if negative:
                found.append((field, 'no'))
            elif positive and not re.search(r'\b(?:not|no|without|or|alternatively|recommended|preferred)\b', sentence, re.I):
                found.append((field, 'yes'))
        if re.search(r'\b(?:application deadline|applications? (?:are )?due|apply by|deadline for applications)\b', sentence, re.I) and not re.search(r'\b(?:not|previous|last year|extended from)\b', sentence, re.I):
            dates = [_parse_date(m.group()) for m in _DATE.finditer(sentence)]
            found.extend(('deadline', date) for date in dates if date)
        if re.search(r'\bapplications (?:are )?(?:accepted|reviewed) on a rolling basis\b', sentence, re.I):
            found.append(('is_rolling', True))
    return found


def _category(field):
    return 'eligibility' if field.startswith('eligibility.') else 'materials' if field.startswith('application.') else 'deadline'


def _condition(field, value, status, reason, sources=()):
    if reason in {'source_overflow', 'source_not_public'}:
        status = 'unknown'
    return {'field': field, 'category': _category(field), 'status': status, 'value': value,
            'usage': 'usable' if status == 'stated' else 'excluded' if reason in {'source_overflow', 'source_not_public'} else 'ask_only',
            'reason': reason, 'sources': list(sources)}


def build_target_conditions(opp: dict, *, now: datetime | None = None) -> dict:
    """Build from canonical stored evidence; never read cached public receipts."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError('Condition clock must include a timezone.')
    opp = opp if isinstance(opp, dict) else {}
    kind = record_kind(opp)
    kind = kind if kind in {'listing', 'faculty_contact'} else 'unverified'
    result = {'version': 1, 'record_kind': kind, 'conditions': [], 'template_request': None}
    meta = opp.get('metadata') if isinstance(opp.get('metadata'), dict) else {}
    sources = meta.get('contact_instruction_sources')
    if 'contact_instruction_pages' in meta:
        from src.contact_instructions import validated_contact_instruction_sources
        sources = validated_contact_instruction_sources(opp)
    candidates = {}
    rejected_reason = None
    unsupported = []
    urls = {_url(opp.get(key)) for key in ('source_url', 'url')} - {None}
    if sources is not None and (not isinstance(sources, list) or len(sources) > 8):
        sources, rejected_reason = [], 'source_overflow'
    for source in sources or []:
        if not isinstance(source, dict):
            rejected_reason = 'source_unavailable'
            continue
        if _url(source.get('record_source_url')) not in urls or not _url(source.get('source_url')):
            rejected_reason = 'source_binding_mismatch'
            continue
        if kind == 'faculty_contact' and (not _identity(opp.get('pi_name')) or _identity(source.get('identity_name')) != _identity(opp.get('pi_name'))):
            rejected_reason = 'source_binding_mismatch'
            continue
        stamp = source.get('checked_at')
        try:
            if not isinstance(stamp, str) or len(stamp) > 80:
                raise ValueError
            checked = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if checked.tzinfo is None or checked > current:
                raise ValueError
        except ValueError:
            rejected_reason = 'source_unavailable'
            continue
        sections = source.get('sections')
        if not isinstance(sections, list) or len(sections) > 160:
            rejected_reason = 'source_overflow'
            continue
        for section in sections:
            if not isinstance(section, dict):
                rejected_reason = 'source_unavailable'
                continue
            heading, text = section.get('heading'), section.get('text')
            if not isinstance(heading, str) or not isinstance(text, str) or not text:
                rejected_reason = 'source_unavailable'
                continue
            if len(text) > 4000 or len(heading) > 1000 or any(0xD800 <= ord(c) <= 0xDFFF for c in heading + text):
                rejected_reason = 'source_overflow'
                continue
            if not (_CONDITION_CUE.search(heading + ' ' + text) or re.search(r'资格|条件|截止|材料|申请|成绩|学分|公民', heading + text)):
                continue
            proof = {'quote': text, 'source_url': source['source_url'], 'checked_at': stamp, 'heading': heading}
            audience = (bool(kind == 'listing' or _UG.search(heading) or _ALL.search(heading) or _UG.search(text) or _ALL.search(text))
                        and not _OTHER.search(heading + ' ' + text))
            # An omitted audience or a conditional paragraph is retained for
            # review, never stripped down to a universal requirement.
            facts = _extract(text) if audience and not _CONDITIONAL.search(text) else []
            if audience and not _CONDITIONAL.search(heading + ' ' + text):
                leaf = heading.rsplit(' > ', 1)[-1].strip()
                if re.fullmatch(r'minimum GPA', leaf, re.I) and re.fullmatch(r'[0-4](?:\.\d+)?', text.strip()):
                    facts.append(('eligibility.min_gpa', float(text.strip())))
                elif re.fullmatch(r'(?:application )?deadline', leaf, re.I):
                    date = _parse_date(text.strip())
                    if date:
                        facts.append(('deadline', date))
            if kind == 'unverified':
                facts = []
            if not facts:
                unsupported.append(proof)
            for field, value in facts:
                candidates.setdefault(field, []).append((value, proof, current - checked > CONDITIONS_MAX_AGE))
    for field in CONDITION_FIELDS:
        stored, valid = _safe_value(_value(opp, field))
        found = candidates.get(field, [])
        # Faculty directory defaults are not applications. Only actual relevant
        # retained paragraphs may open this area on a contact-only target.
        if kind == 'faculty_contact' and not found:
            continue
        if not valid:
            result['conditions'].append(_condition(field, None, 'unknown', 'source_overflow'))
            continue
        if found:
            proofs = []
            for _, proof, _ in found:
                if proof not in proofs:
                    proofs.append(proof)
            if len(proofs) > 40:
                item = _condition(field, stored, 'unknown', 'source_overflow')
            elif any(not _same(value, found[0][0]) for value, _, _ in found):
                item = _condition(field, stored if _known(stored) else found[0][0], 'conflicting', 'source_conflict', proofs)
            elif _known(stored) and not _same(stored, found[0][0]):
                item = _condition(field, stored, 'conflicting', 'normalized_source_conflict', proofs)
            elif any(stale for _, _, stale in found):
                item = _condition(field, found[0][0], 'stale', 'source_stale', proofs)
            else:
                item = _condition(field, found[0][0], 'stated', 'source_stated', proofs)
            conflicts = meta.get('conflicts')
            if isinstance(conflicts, list) and any(isinstance(c, dict) and c.get('field') == field for c in conflicts):
                item.update(status='conflicting', usage='ask_only', reason='source_conflict')
            result['conditions'].append(item)
        elif _known(stored):
            stamps = meta.get('inferred_fields')
            method = stamps.get(field) if isinstance(stamps, dict) else None
            method = method if isinstance(method, str) and method else None
            status = 'policy' if method and method.startswith('policy:') else 'inferred' if method else 'unverified'
            reason = 'program_policy' if status == 'policy' else 'inferred_field' if method else 'unverified_legacy_value'
            if rejected_reason:
                reason = rejected_reason
            result['conditions'].append(_condition(field, stored, status, reason))
    if unsupported:
        old = next((item for item in result['conditions'] if item['field'] == 'eligibility.eligibility_text_raw'), None)
        replacement = (_condition('eligibility.eligibility_text_raw', old['value'] if old else None, 'unverified',
                                  'unsupported_source_wording', unsupported) if len(unsupported) <= 40 else
                       _condition('eligibility.eligibility_text_raw', old['value'] if old else None, 'unknown', 'source_overflow'))
        if old is not None:
            result['conditions'][result['conditions'].index(old)] = replacement
        else:
            result['conditions'].append(replacement)
    result['template_request'] = target_conditions_template_request(result)
    return result


def _usable(context):
    return [item for item in context.get('conditions', []) if isinstance(item, dict)
            and item.get('status') == 'stated' and item.get('usage') == 'usable'] if isinstance(context, dict) else []


def target_conditions_template_request(context: dict) -> str | None:
    """One practical preparation/inquiry, never a qualification or attachment."""
    if not isinstance(context, dict) or context.get('record_kind') != 'listing':
        return None
    materials = [_MATERIALS[item['field']][0] for item in _usable(context)
                 if item.get('field') in _MATERIALS and item.get('value') == 'yes']
    if materials:
        return 'I can prepare the required ' + ', '.join(materials) + '; could you confirm how I should submit the materials?'
    questions = {
        'deadline': 'Could you confirm the current application deadline?',
        'is_rolling': 'Could you confirm whether applications are currently being accepted?',
        'application.requires_resume': 'Could you confirm which application materials are required?',
        'application.requires_cover_letter': 'Could you confirm which application materials are required?',
        'application.requires_transcript': 'Could you confirm which application materials are required?',
        'application.requires_recommendation': 'Could you confirm which application materials are required?',
        'eligibility.min_gpa': 'Could you confirm whether there is a minimum GPA requirement?',
        'eligibility.citizenship_required': 'Could you clarify the current eligibility criteria?',
        'eligibility.international_friendly': 'Could you clarify the current eligibility criteria?',
        'eligibility.work_auth_notes': 'Could you clarify the current eligibility criteria?',
        'eligibility.preferred_year': 'Could you confirm which years of study are eligible?',
        'eligibility.majors': 'Could you confirm whether applicants need to be in a particular major?',
        'eligibility.skills_required': 'Could you clarify which skills are required for applicants?',
        'eligibility.skills_preferred': 'Could you clarify which skills would be useful for applicants?',
    }
    pending = [item for item in context.get('conditions', []) if isinstance(item, dict)
               and item.get('usage') == 'ask_only' and (_known(item.get('value')) or item.get('sources'))]
    for field, question in questions.items():
        if any(item.get('field') == field for item in pending):
            return question
    # Unsupported retained paragraphs have no safely parsed typed value. Their
    # headings may still identify the one practical clarification to request.
    for item in pending:
        for proof in item.get('sources', []):
            heading = proof.get('heading', '').casefold()
            if 'deadline' in heading or '截止' in heading:
                return questions['deadline']
            if 'material' in heading or '材料' in heading:
                return questions['application.requires_resume']
    return None


def target_conditions_brief(context: dict) -> str:
    """Complete receipt; explicit role fence keeps target terms out of facts."""
    return ('APPLICATION CONDITIONS — target-side only, never proof that the student qualifies or has attached files. '
            'Use only stated/usable rows as source terms; ask_only rows may support a question, not a claim. '
            'Do not turn broad policy, defaults, stale or conflicting evidence into current requirements.\n' +
            json.dumps(context, ensure_ascii=False, separators=(',', ':'), allow_nan=False))


def target_conditions_vocabulary(context: dict) -> str:
    return '\n'.join(json.dumps({'value': item['value'], 'sources': item['sources']}, ensure_ascii=False)
                     for item in _usable(context))


def _gpa_values(text):
    return {float(match.group(1) or match.group(2)) for match in _GPA_VALUE.finditer(text)}


_NEGATED = re.compile(r"\b(?:not|never|no|without|don't|do not|cannot)\b", re.I)
_PERSONAL_GPA = re.compile(r"\b(?:my GPA|I (?:have|earned|maintained|achieved)(?: a| an)? (?:[^.!?]|\.(?=\d)){0,40}GPA)\b|^\s*GPA\s*[:=]?\s*\d", re.I)
_PERSONAL_CITIZEN = re.compile(r"\b(?:I am|I'm|I’m|my (?:citizenship|immigration) status is)\b", re.I)
_DOC_OBJECT = r"(?:resume|résumé|CV|curriculum vitae|transcript|cover letter|recommendation|statement|application|materials?|documents?|files?|portfolio)"
_TIME_QUALIFIERS = re.compile(r"\b\d{1,2}:\d{2}(?:\s*[AP]M)?\b|\b\d{1,2}\s*[AP]M\b|\b(?:UTC|GMT|EST|EDT|CST|CDT|PST|PDT|Pacific|Eastern|Central|Mountain|local time|midnight|noon)\b", re.I)


def _citizen_terms(text):
    return {_identity(match.group()).replace('.', '') for match in _CITIZEN.finditer(text)}


def _required_skill_claims(sentence):
    """Only recognized requirement syntax, preserving required/preferred roles."""
    match = re.search(r"\b(?:your|the|this) (?:program|lab) requires? (.+?)[.!?]*$", sentence, re.I)
    if not match:
        match = re.search(r"^\s*(.+?) (?:experience )?is required for applicants[.!?]*$", sentence, re.I)
    if not match:
        match = re.search(r"\brequired skills\s*:\s*(.+?)[.!?]*$", sentence, re.I)
    if not match:
        return []
    body = match.group(1).strip(' .')
    if re.search(_DOC_OBJECT + r"|\b(?:GPA|citizen|eligib|minimum|deadline)", body, re.I):
        return []  # handled by the matching typed condition check
    return [re.sub(r"\s+experience$", "", item.strip(), flags=re.I)
            for item in re.split(r",|\s+and\s+", body) if item.strip()]


def _material_qualifiers(text, pattern):
    result = set()
    # A number only binds to the immediately named document, with a bounded
    # list of document adjectives; GPA numbers elsewhere cannot supply it.
    quantity = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
    numbers = {'one':'1','two':'2','three':'3','four':'4','five':'5','six':'6','seven':'7','eight':'8','nine':'9','ten':'10'}
    for match in re.finditer(r"\b("+quantity+r")\s+(?:(?:official|unofficial|signed|confidential)\s+)?(?:letters?\s+of\s+)?(?:"+pattern+r")", text, re.I):
        result.add('count:' + numbers.get(match.group(1).casefold(), match.group(1)))
    for adjective in ('official', 'unofficial', 'signed', 'confidential', 'certified'):
        if re.search(r"\b" + adjective + r"\s+(?:" + pattern + r")", text, re.I):
            result.add('kind:' + adjective)
    return result


def target_condition_claim_violations(text: str, context: dict,
                                      student_evidence_texts: Iterable[str] = ()) -> list[str]:
    """Finite high-risk claim shapes; absence of findings is NOT semantic proof.

    Questions and preparation remain possible. Confirmed personal GPA/citizenship
    may be repeated, not upgraded to eligibility. A prior project's target terms,
    or a negated student sentence, do not establish a positive personal fact.
    """
    if not isinstance(text, str):
        return []
    evidence = [item for item in student_evidence_texts if isinstance(item, str)]
    own_gpa = set().union(*(_gpa_values(item) for item in evidence
                          if _PERSONAL_GPA.search(item) and not _NEGATED.search(item))) if evidence else set()
    own_citizen = set().union(*(_citizen_terms(item) for item in evidence
                              if _PERSONAL_CITIZEN.search(item) and not _NEGATED.search(item))) if evidence else set()
    usable = {item['field']: item for item in _usable(context)}
    issues = set()
    # Protect US abbreviations during sentence splitting (source proofs remain
    # byte-for-byte originals; this normalization is local to claim matching).
    checked_text = re.sub(r"\bU\.S\.", "US", text, flags=re.I)
    for sentence in re.split(r'(?<=[!?。！？])\s*|\n|(?<=\.)\s+(?=[A-Z])', checked_text):
        low = sentence.casefold()
        question = ('?' in sentence or '？' in sentence) and bool(re.search(
            r'^\s*(?:could|would|can|do|does|is|are|am|what|which|when|how)\b|^\s*(?:请问|能否|是否|可以|能不能)', sentence, re.I))
        qualification = re.search(
            r"\bI\s+(?:(?:fully|already)\s+)?(?:meet|satisfy|fulfil[l]?)\s+(?:all\s+|the\s+|your\s+|these\s+|this\s+)*(?:eligibility|citizenship|GPA|application|entry|admission|program|lab|requirements?|criteria)\b"
            r"|\bI\s+(?:qualify|am\s+(?:fully\s+)?eligible)\s+(?:for|to)\b"
            r"|\bmy\s+(?:GPA|citizenship|status)\s+(?:meets|satisfies)\b"
            r"|我(?:已经|已|完全)?(?:符合|满足)(?:所有|全部|该|本|这个|您的)*(?:申请|报名|项目|入学|学术)?(?:资格|要求|条件)"
            r"|我(?:已经|已)?具备(?:全部|所有)?申请资格", sentence, re.I)
        if qualification and not (question and re.search(r'\b(?:whether|if|am I|do I)\b|是否|能否', sentence, re.I)):
            issues.add('unsupported_eligibility_claim')
        attachment = re.search(
            r"\bI(?:\s+have|[’']ve)?\s+(?:attached|enclosed|submitted)\s+(?:(?:my|the|a|an|all|required)\s+)*" + _DOC_OBJECT + r"\b"
            r"|\b(?:my|the)\s+" + _DOC_OBJECT + r"\s+(?:is|are|has been|have been)\s+(?:attached|enclosed|submitted)\b"
            r"|\bplease\s+find\s+(?:attached|enclosed)\b"
            r"|我(?:已经|已|随信)?(?:附上|附有|提交了?)(?:我的|全部|所需)?(?:简历|履历|成绩单|申请材料|推荐信)"
            r"|(?:简历|成绩单|申请材料)(?:已经|已)(?:附上|附在|提交)", sentence, re.I)
        if attachment and not _NEGATED.search(sentence):
            issues.add('unsupported_attachment_claim')
        if _PERSONAL_CITIZEN.search(sentence) and _CITIZEN.search(sentence) and not question and not _NEGATED.search(sentence):
            if not _citizen_terms(sentence).issubset(own_citizen):
                issues.add('unsupported_eligibility_claim')
        if _PERSONAL_GPA.search(sentence) and not question and not _NEGATED.search(sentence):
            if not _gpa_values(sentence).issubset(own_gpa):
                issues.add('unsupported_eligibility_claim')
        if question:
            continue
        skills = _required_skill_claims(sentence)
        if skills:
            required = usable.get('eligibility.skills_required', {}).get('value', [])
            required = {_identity(item) for item in required} if isinstance(required, list) else set()
            if not {_identity(item) for item in skills}.issubset(required):
                issues.add('unsupported_eligibility_claim')
        target = bool(re.search(r'\b(?:your|the|this)\s+(?:program|lab|application|minimum|GPA|deadline|eligibility|requirements?)\b|\bapplicants?\s+(?:must|are required)\b', sentence, re.I))
        if not target:
            continue
        if re.search(r'\b(?:deadline|due|apply by|rolling)\b', sentence, re.I):
            dates = [_parse_date(match.group()) for match in _DATE.finditer(sentence)]
            allowed = usable.get('deadline', {}).get('value')
            rolling = usable.get('is_rolling', {}).get('value') is True
            source_text = ' '.join(proof['quote'] for field in ('deadline','is_rolling') for proof in usable.get(field, {}).get('sources', []))
            extra_qualifiers = {_identity(match.group()) for match in _TIME_QUALIFIERS.finditer(sentence)} - {_identity(match.group()) for match in _TIME_QUALIFIERS.finditer(source_text)}
            if (not dates and not ('rolling' in low and rolling)) or any(date != allowed for date in dates) or extra_qualifiers:
                issues.add('unsupported_deadline_claim')
        if 'gpa' in low:
            claims = _gpa_values(sentence)
            allowed = usable.get('eligibility.min_gpa', {}).get('value')
            if not claims or claims != {allowed}:
                issues.add('unsupported_eligibility_claim')
        if _CITIZEN.search(sentence) or 'international students' in low:
            relevant = [item for field, item in usable.items() if field in {'eligibility.citizenship_required', 'eligibility.international_friendly'}]
            # Preserve OR/AND and exception qualifiers, rather than infer an
            # immigration verdict from the legacy boolean.
            if not any(_identity(sentence.strip(' .')) in _identity(re.sub(r"\bU\.S\.", "US", proof['quote'], flags=re.I)) for item in relevant for proof in item['sources']):
                issues.add('unsupported_eligibility_claim')
        for field, (_, pattern) in _MATERIALS.items():
            if re.search(pattern, sentence, re.I) and re.search(r'\b(?:requires?|required|must|mandatory)\b', sentence, re.I):
                claimed = 'no' if re.search(r'\b(?:not required|no .*required)\b', sentence, re.I) else 'yes'
                item = usable.get(field, {})
                source_qualifiers = set()
                for proof in item.get('sources', []):
                    for clause in _sentences(proof['quote']):
                        if any(source_field == field for source_field, _ in _extract(clause)):
                            source_qualifiers.update(_material_qualifiers(clause, pattern))
                claim_qualifiers = _material_qualifiers(sentence, pattern)
                if item.get('value') != claimed or not claim_qualifiers.issubset(source_qualifiers):
                    issues.add('unsupported_material_claim')
    return sorted(issues)


def validate_public_target_conditions(value: object) -> dict | None:
    """Validate a server-projected receipt's shape; this does NOT establish trust.

    Only the central projector may establish canonical evidence. This validator
    lets internal consumers fail closed on damaged projected data; accepting the
    shape never authorizes a caller-supplied receipt as source evidence.
    """
    if not isinstance(value, dict) or set(value) != {'version', 'record_kind', 'conditions', 'template_request'}:
        return None
    if type(value.get('version')) is not int or value['version'] != 1 or not isinstance(value.get('record_kind'), str) or value['record_kind'] not in {'listing', 'faculty_contact', 'unverified'}:
        return None
    items = value.get('conditions')
    if not isinstance(items, list) or len(items) > len(CONDITION_FIELDS):
        return None
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'field', 'category', 'status', 'value', 'usage', 'reason', 'sources'}:
            return None
        field = item.get('field')
        if not isinstance(field, str) or field not in CONDITION_FIELDS or field in seen:
            return None
        seen.add(field)
        if item.get('category') != _category(field) or not isinstance(item.get('status'), str) or item['status'] not in {'stated', 'inferred', 'policy', 'unverified', 'unknown', 'stale', 'conflicting'}:
            return None
        if not isinstance(item.get('usage'), str) or item['usage'] not in {'usable', 'ask_only', 'excluded'} or not isinstance(item.get('reason'), str) or item['reason'] not in CONDITION_REASONS or not _safe_value(item.get('value'))[1]:
            return None
        if (item['status'] == 'stated') != (item['usage'] == 'usable'):
            return None
        if item['status'] == 'stated' and (item['reason'] != 'source_stated' or not _known(item['value'])):
            return None
        if item['reason'] in {'source_overflow', 'source_not_public'} and (item['status'] != 'unknown' or item['usage'] != 'excluded'):
            return None
        proofs = item.get('sources')
        if not isinstance(proofs, list) or len(proofs) > 40 or (item['usage'] == 'usable' and not proofs):
            return None
        for proof in proofs:
            if not isinstance(proof, dict) or not {'quote', 'source_url', 'checked_at'}.issubset(proof) or set(proof) - {'quote', 'source_url', 'checked_at', 'heading'}:
                return None
            if not isinstance(proof['quote'], str) or not proof['quote'] or len(proof['quote']) > 4000 or not _safe_value(proof['quote'])[1] or not _url(proof['source_url']):
                return None
            if 'heading' in proof and (not isinstance(proof['heading'], str) or len(proof['heading']) > 1000 or not _safe_value(proof['heading'])[1]):
                return None
            try:
                stamp = proof['checked_at']
                if not isinstance(stamp, str) or len(stamp) > 80 or datetime.fromisoformat(stamp.replace('Z', '+00:00')).tzinfo is None:
                    return None
            except ValueError:
                return None
    request = value.get('template_request')
    if request is not None and (not isinstance(request, str) or len(request) > 500 or not _safe_value(request)[1]):
        return None
    result = deepcopy(value)
    # A stale cached template must not outlive a condition being excluded.
    result['template_request'] = target_conditions_template_request(result)
    return result


def email_target_conditions(opp: dict) -> dict:
    """Read an already canonical public projection or build an internal record.

    Presence of a malformed public receipt never falls back to raw fields.
    The caller must not pass untrusted request/corpus receipts as public output;
    the central projector always overwrites the cached key from canonical data.
    """
    if isinstance(opp, dict) and 'target_conditions' in opp:
        return validate_public_target_conditions(opp['target_conditions']) or {
            'version': 1, 'record_kind': 'unverified', 'conditions': [], 'template_request': None,
        }
    return build_target_conditions(opp)
