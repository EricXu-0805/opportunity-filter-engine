"""Private first-contact preparation; no public authority or provider input.

The finite local restriction scan is not a complete reading of contact policy.
An unknown result always needs the owner's review. Stored imports and their
metadata never become verified eligibility, recipient, publication or lab data.
"""
from __future__ import annotations

import hashlib
import json
import re
from bisect import bisect_left, bisect_right
from copy import deepcopy

from backend.lib.blocking import LOCAL_WORK_TIMEOUT_SECONDS, run_blocking
from backend.lib.private_import_targets_schema import PrivateTargetError
from backend.lib.private_target_resolution import PrivateResolvedTarget, resolve_private_import_target

PROJECTION_VERSION = 1
POLICY_VERSION = 1
MAX_SOURCE_CHARACTERS = 5 * 1024 * 1024
MAX_QUOTES = 20
MAX_QUOTE_CHARACTERS = 2000
_WRITING_VERSION = re.compile(r'^pwt1:[0-9a-f]{64}$')
_SEGMENTS = re.compile(r'[^.!?。！？\r\n]+(?:[.!?。！？]+|(?=[\r\n])|$)')
_CONTACT = re.compile(r'\b(?:e-?mails?|contact|apply|applications?|submit|portal|form)\b|邮件|联系|申请|提交|表格|系统|门户', re.I)
_RESTRICTIVE = re.compile(r"\b(?:no|not|never|only|must|prohibit|forbid)\b|不|禁止|请勿|仅|必须", re.I)
_OTHER_AUDIENCE = re.compile(r'\b(?:graduates?|graduate students?|postdocs?|postdoctoral|doctoral|ph\.?d|alumni|staff)\b|研究生|博士|博士后|教职', re.I)
_AUDIENCE = re.compile(r'\b(?:undergraduates?|graduates?|students?|applicants?|postdocs?|doctoral|ph\.?d|alumni|staff)\b|本科|研究生|博士|学生|申请人|教职', re.I)
_LIMITED = re.compile(r'\b(?:if|unless|except|whether|example|previously|formerly|last year|used to|recommendation|reference letter|visa|housing|technical support)\b|如果|除非|例如|曾经|去年|推荐信|签证|住宿|技术支持|[?？]', re.I)
_NO_EMAIL = re.compile(
    r"\b(?:do\s+not|don't|must\s+not|should\s+not|cannot|can't)\s+(?:(?:cold|directly)\s+)?e-?mail\b"
    r"|\b(?:we|i|this\s+(?:lab|program))\s+(?:do\s+not|don't|cannot|can't)\s+(?:accept|welcome|respond\s+to)\s+(?:unsolicited\s+|cold\s+)?e-?mails?\b"
    r'|\b(?:unsolicited\s+|cold\s+)?e-?mails?\s+(?:are|is)\s+(?:not\s+(?:accepted|allowed|permitted)|prohibited|forbidden)\b'
    r'|\bno\s+(?:unsolicited\s+|cold\s+)?e-?mail\s+(?:contact|inquiries|enquiries|applications)\b'
    r'|(?:请勿|不要|不得|禁止)(?:通过|使用|发送)?(?:电子)?邮件'
    r'|不(?:接受|回复)(?:任何|未经邀请的|主动)?(?:电子)?邮件', re.I)
_FORM_ONLY = re.compile(
    r'\b(?:apply|submit\s+(?:your\s+|an?\s+|the\s+)?applications?)\s+only\s+(?:via|through|using|by)\s+(?:the\s+|our\s+|an?\s+)?(?:online\s+|application\s+)?(?:form|portal)\b'
    r'|\bapplications?\s+(?:(?:must|may|can)\s+)?(?:only\s+be\s+submitted|must\s+be\s+submitted\s+only|(?:are\s+)?accepted\s+only|(?:are\s+)?only\s+accepted)\s+(?:via|through|using|by)\s+(?:the\s+|our\s+|an?\s+)?(?:online\s+|application\s+)?(?:form|portal)\b'
    r'|\b(?:we\s+)?only\s+accept\s+applications?\s+(?:via|through|using|by)\s+(?:the\s+|our\s+|an?\s+)?(?:online\s+|application\s+)?(?:form|portal)\b'
    r'|仅(?:能|可|允许)?通过(?:线上|在线)?(?:申请)?(?:表格|系统|门户)[^。！？\r\n]{0,60}(?:申请|提交)', re.I)
# (申请|材料) gap{0,60} (仅限|只能|必须) gap{0,60} (表格|系统|门户) with no 。！？ or
# line break in a gap. As one regex its nested gaps backtrack ~3,600 steps per
# anchor, about 12 s on a 5 MiB punctuation-free import; this finds the same
# matches from keyword offsets in linear time.
_CJK_SENTENCE = re.compile(r'[^。！？\r\n]+')
_CJK_APPLICATION = re.compile(r'(?=申请|材料)')
_CJK_ONLY = re.compile(r'(?=仅限|只能|必须)')
_CJK_CHANNEL = re.compile(r'(?=表格|系统|门户)')
_CJK_GAP = 60


def _cjk_application_only(text: str) -> bool:
    if not _CJK_ONLY.search(text):
        return False
    for part in _CJK_SENTENCE.finditer(text):
        sentence = part.group()
        firsts = [m.start() for m in _CJK_APPLICATION.finditer(sentence)]
        lasts = [m.start() for m in _CJK_CHANNEL.finditer(sentence)]
        if not firsts or not lasts:
            continue
        for middle in (m.start() for m in _CJK_ONLY.finditer(sentence)):
            first = bisect_right(firsts, middle - 2) - 1
            last = bisect_left(lasts, middle + 2)
            if (first >= 0 and firsts[first] >= middle - 2 - _CJK_GAP
                    and last < len(lasts) and lasts[last] <= middle + 2 + _CJK_GAP):
                return True
    return False


_NEGATED_RULE = re.compile(r"\b(?:not\s+(?:prohibited|forbidden)|no\s+longer|do\s+not\s+need|don't\s+need|not\s+required)\b|并非|不是|不必|无需|不再", re.I)


def private_contact_policy(text: str) -> dict:
    """Scan the complete stored text locally; return exact bounded quotations.

    Codepoint offsets refer to that stored text, not HTML, bytes or UTF-16.
    Quote overflow is explicit and cannot turn a detected block into unknown.
    Different/conditional applicant scopes are left for review, not guessed.
    """
    if type(text) is not str or not text.strip() or '\x00' in text:
        raise PrivateTargetError('private_target_invalid_receipt', 502)
    if len(text) > MAX_SOURCE_CHARACTERS:
        raise PrivateTargetError('private_target_too_large', 413)
    try:
        text.encode('utf-8')
    except UnicodeError:
        raise PrivateTargetError('private_target_invalid_receipt', 502) from None
    quotes, restrictions = [], set()
    needs_review = False
    audience = ''
    for match in _SEGMENTS.finditer(text):
        raw = match.group()
        left = len(raw) - len(raw.lstrip())
        quote = raw.strip()
        if not quote:
            continue
        # A short stand-alone audience heading scopes later lines until the
        # next audience heading. It does not manufacture a source heading.
        if len(quote) <= 120 and _AUDIENCE.search(quote) and not _CONTACT.search(quote) and not re.search(r'[.!?。！？]', quote):
            audience = quote
            continue
        if not _CONTACT.search(quote):
            continue
        kinds = []
        if _NO_EMAIL.search(quote):
            kinds.append('no_email')
        if _FORM_ONLY.search(quote) or _cjk_application_only(quote):
            kinds.append('form_only')
        if not kinds:
            needs_review = needs_review or bool(_RESTRICTIVE.search(quote))
            continue
        if _OTHER_AUDIENCE.search(audience) or _OTHER_AUDIENCE.search(quote) or _LIMITED.search(quote) or _NEGATED_RULE.search(quote):
            needs_review = True
            continue
        restrictions.update(kinds)
        if len(quote) > MAX_QUOTE_CHARACTERS:
            needs_review = True
            continue
        for kind in kinds:
            if len(quotes) >= MAX_QUOTES:
                needs_review = True
                continue
            start = match.start() + left
            quotes.append({'start': start, 'end': start + len(quote), 'quote': quote, 'restriction': kind})
    reason = 'policy_review_required' if needs_review else (
        'multiple_restrictions' if len(restrictions) > 1 else next(iter(restrictions), 'unverified_import'))
    return {'state': 'blocked' if restrictions else 'unknown', 'reason': reason, 'quotes': quotes}


def build_private_email_context(target: PrivateResolvedTarget) -> dict:
    """A purpose-specific owner receipt, never an Opportunity/public dictionary."""
    detail = target.detail
    context = {
        'version': 1, 'target_scope': 'private_import', 'verification': 'unverified',
        'purpose': 'first_contact', 'id': target.id, 'owner_id': target.owner_id,
        'revision': target.revision, 'source_version': target.target_version,
        'projection_version': PROJECTION_VERSION, 'policy_version': POLICY_VERSION,
        'title': detail['title'], 'organization': detail['organization'],
        'source_url': detail['source_url'] or detail['url'],
        'import_source': deepcopy(detail['import_source']),
        'contact_policy': private_contact_policy(detail['description_raw']),
        'provider_allowed': False,
    }
    # All keys are ASCII, values contain only strings, safe integers, booleans,
    # arrays and null. This canonicalization is reproducible in the browser.
    body = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    context['writing_version'] = 'pwt1:' + hashlib.sha256(body.encode('utf-8')).hexdigest()
    return context


async def resolve_private_email_context(
    target_id: str, *, authorization: str | None, expected_owner_id: str,
    expected_writing_version: str | None = None,
) -> dict:
    """Fresh owner/tombstone check; a write must supply its reviewed pwt1."""
    if expected_writing_version is not None and (
        type(expected_writing_version) is not str or not _WRITING_VERSION.fullmatch(expected_writing_version)
    ):
        raise PrivateTargetError('private_target_invalid_request', 422)
    target = await resolve_private_import_target(target_id, authorization=authorization,
                                               expected_owner_id=expected_owner_id)
    # A 5 MiB stored import is a multi-second local scan; keep it off the
    # single-worker event loop. Timeout/overload surface as a 503, never empty.
    context = await run_blocking(build_private_email_context, target, timeout_seconds=LOCAL_WORK_TIMEOUT_SECONDS)
    if expected_writing_version is not None and expected_writing_version != context['writing_version']:
        raise PrivateTargetError('private_target_changed', 409)
    return context
