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
CAPTURE_KEY = 'contact_instruction_capture'
PAGES_KEY = 'contact_instruction_pages'
_MAX_PAGES = 32
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



def same_source_page(requested_url, final_url) -> bool:
    """Permit transport/slash normalization, never a different target page."""
    requested, final = _url(requested_url), _url(final_url)
    if not requested or not final:
        return False
    try:
        before, after = urlsplit(requested), urlsplit(final)
        if before.scheme != after.scheme and (before.scheme, after.scheme) != ('http', 'https'):
            return False
        # A default-port HTTP -> HTTPS upgrade retains resource identity.
        def endpoint(parsed):
            default = 443 if parsed.scheme == 'https' else 80
            port = parsed.port or default
            return parsed.hostname.casefold(), None if port == default else port
        def path(parsed):
            return (parsed.path or '/').removesuffix('/') or '/'
        return (endpoint(before) == endpoint(after) and path(before) == path(after)
                and before.query == after.query)
    except ValueError:
        return False


def _identity(value):
    return ' '.join(value.casefold().split()) if isinstance(value, str) else ''


def capture_failure(*, source_url: str, record_source_url: str | None = None,
                    identity_name: str | None = None, checked_at: str | None = None,
                    requested_source_url: str | None = None, next_retry_at: str | None = None,
                    reason: str = 'fetch_failed', status: str = 'failed') -> dict:
    """An attempt receipt is not a successful source check.

    Callers use stable reason codes, never exception bodies, response HTML or
    credentials. A failed receipt deliberately has no replacement source list.
    """
    if status not in ('failed', 'unsupported'):
        raise ValueError('failure status must be failed or unsupported')
    result = {'version': 1, 'status': status, 'reason': reason,
              'attempted_at': checked_at or datetime.now(UTC).isoformat(),
              'source_url': source_url, 'record_source_url': record_source_url or source_url}
    if identity_name:
        result['identity_name'] = identity_name
    if requested_source_url is not None:
        result['requested_source_url'] = requested_source_url
    if next_retry_at is not None:
        result['next_retry_at'] = next_retry_at
    return result


def capture_metadata(result: dict) -> dict:
    """Detach a collector-owned result for storage, preserving explicit empty."""
    keys = ('version', 'status', 'reason', 'attempted_at', 'source_url',
            'record_source_url', 'identity_name', 'requested_source_url', 'next_retry_at')
    receipt = {key: deepcopy(result[key]) for key in keys if key in result}
    metadata = {CAPTURE_KEY: receipt}
    if result.get('status') in ('captured', 'empty'):
        sources = result.get('sources')
        if isinstance(sources, list) and len(sources) > _MAX_SOURCES:
            metadata[CAPTURE_KEY] = {**receipt, 'status':'unsupported', 'reason':'source_limit'}
            metadata[PAGES_KEY] = {'version':1, 'pages':[], 'merge_issue':'source_limit'}
        else:
            metadata[SOURCE_KEY] = retained_sources(sources)
    return metadata


def capture_from_sections(sections, *, source_url: str, record_source_url: str | None = None,
                          identity_name: str | None = None, checked_at: str | None = None,
                          requested_source_url: str | None = None) -> dict:
    """Retain complete raw DOM passages from an already verified page adapter.

    Headings and text must come from the page, not schema labels, generated
    summaries or inferred requirements. An empty input means unsupported DOM;
    nonempty readable input without relevant passages means checked and empty.
    """
    binding = dict(source_url=source_url, record_source_url=record_source_url,
                   identity_name=identity_name, checked_at=checked_at, requested_source_url=requested_source_url)
    def unsupported(reason):
        return capture_failure(**binding, status='unsupported', reason=reason)
    if not _url(source_url) or not _url(record_source_url or source_url):
        return unsupported('invalid_binding')
    if not isinstance(sections, list) or not sections:
        return unsupported('no_supported_content')
    if len(sections) > _MAX_SECTIONS:
        return unsupported('content_limit')
    for section in sections:
        if (not isinstance(section, dict) or not isinstance(section.get('heading'), str)
                or not isinstance(section.get('text'), str) or not section['text'].strip()):
            return unsupported('invalid_sections')
        if len(section['heading']) > 1000 or len(section['text']) > _MAX_TEXT:
            return unsupported('content_limit')
    selected = [deepcopy(section) for section in sections
                if _CONTACT.search(section['text'])
                or _APPLICATION_CONDITION.search(section['heading'])
                or _APPLICATION_CONDITION.search(section['text'])]
    receipt = capture_failure(**binding)
    receipt.update(status='captured' if selected else 'empty', reason=None, sources=[])
    if selected:
        source = {'source_url': source_url, 'record_source_url': record_source_url or source_url,
                  'checked_at': receipt['attempted_at'], 'sections': selected}
        if identity_name:
            source['identity_name'] = identity_name
        receipt['sources'] = [source]
    return receipt


_BLOCKED_PAGE_TITLE = re.compile(
    r'^(?:(?:sign[ -]?in|log[ -]?in|access denied|permission denied|forbidden|'
    r'just a moment|attention required|verify (?:you are|that you are) (?:a )?human|'
    r'page not found|404(?: error)?|service unavailable)(?:[.!…]+|\s*[-|:–—].*)?|'
    # Bot-check interstitials served in place of the page, by their whole
    # title: Imunify360, Anubis, SiteGround, Imperva/Distil, PerimeterX, AWS WAF,
    # Vercel, DDoS-Guard. A title that only begins with these words, such as
    # "Human verification: a psychology study", is not one of them.
    r'(?:one moment,? please|making sure you(?:\'|’)?re not a bot|robot challenge screen|'
    r'pardon our interruption|access to this page has been denied|(?:human|bot) verification|'
    r'vercel security checkpoint|ddos-guard|checking your browser)[.!…]*|'
    # DDoS-Guard and older Cloudflare checks name the site after these words.
    # The open tail ends the alternative: a run two quantifiers could share
    # was retried at every split, quadratic in the title's length.
    r'checking your browser before (?:accessing|continuing|proceeding)\b.*)$',
    re.I,
)


def capture_from_html(html, *, source_url: str, record_source_url: str | None = None,
                      identity_name: str | None = None, checked_at: str | None = None,
                          requested_source_url: str | None = None) -> dict:
    """Capture a fetched page without collapsing failure into 'no requirements'.

    Callers still own successful HTTP, final URL, target identity and page-scope
    verification. No source is created for unsupported or incomplete extraction.
    """
    from bs4 import BeautifulSoup
    binding = dict(source_url=source_url, record_source_url=record_source_url,
                   identity_name=identity_name, checked_at=checked_at, requested_source_url=requested_source_url)
    def unsupported(reason):
        return capture_failure(**binding, status='unsupported', reason=reason)
    if not _url(source_url) or not _url(record_source_url or source_url):
        return unsupported('invalid_binding')
    soup = BeautifulSoup(html, 'html.parser') if isinstance(html, str) else html
    if soup is None or not callable(getattr(soup, 'find', None)):
        return unsupported('invalid_html')
    body = soup.find('main') or soup.find('article') or soup.find('body')
    if body is None:
        return unsupported('no_supported_content')
    titles = [soup.find('title'), body.find('h1')]
    if (any(t is not None and _BLOCKED_PAGE_TITLE.fullmatch(t.get_text(' ', strip=True))
            for t in titles) or body.find('input', attrs={'type': re.compile('^password$', re.I)})):
        return unsupported('access_page')
    strings, blocks, unparsed = _page_blocks(body)
    ends = [0]
    for string in strings:
        ends.append(ends[-1] + len(string))

    def size(start, end):
        return ends[end] - ends[start] + end - start - 1 if end > start else 0

    def text(start, end):
        return ' '.join(strings[start:end])

    headings = {}
    heading = None
    sections = []
    parts = []
    length = 0
    relevant_heading = False
    for name, start, end, outside, in_list, in_heading in blocks:
        if outside or (name in ('p', 'ul', 'ol') and in_list):
            continue
        count = size(start, end)
        if not count:
            continue
        if name in _HEADINGS:
            if count > 1000:
                return unsupported('content_limit')
            # A heading inside another heading was read with it, and what
            # matches in its text matches in the outer heading's text too.
            if not relevant_heading and not in_heading:
                words = text(start, end)
                relevant_heading = bool(_CONTACT.search(words) or _APPLICATION_CONDITION.search(words))
            level = int(name[1])
            headings = {n: h for n, h in headings.items() if n < level}
            headings[level] = (start, end)
            heading = None
            continue
        if heading is None:
            heading = ' > '.join(text(*span) for span in headings.values())
        if name in ('ul', 'ol') and sections and sections[-1]['heading'] == heading:
            length += 1 + count
            if length > _MAX_TEXT:
                return unsupported('content_limit')
            parts.append(text(start, end))
            continue
        if sections:
            sections[-1]['text'] = '\n'.join(parts)
        sections.append({'heading': heading, 'text': ''})
        if len(sections) > _MAX_SECTIONS or count > _MAX_TEXT:
            return unsupported('content_limit')
        parts, length = [text(start, end)], count
    if sections:
        sections[-1]['text'] = '\n'.join(parts)
    # A supported paragraph beside an unparsed requirements field is not proof
    # that the requirements disappeared. Adapters may handle that DOM explicitly.
    if (unparsed and relevant_heading) or _CONTACT.search(unparsed) or _APPLICATION_CONDITION.search(unparsed):
        return unsupported('unparsed_relevant_content')
    return capture_from_sections(sections, **binding)


_HEADINGS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})
_SECTION_BLOCKS = _HEADINGS | {'p', 'ul', 'ol'}
_OUTSIDE_SECTIONS = frozenset({'nav', 'header', 'footer', 'aside', 'script', 'style'})
_UNPARSED_SKIP = _SECTION_BLOCKS | _OUTSIDE_SECTIONS
# Tags whose strings bs4 gives its own class, which get_text leaves out.
_STRING_CONTAINERS = frozenset({'rt', 'rp', 'style', 'script', 'template'})


def _page_blocks(body) -> tuple[list[str], list[tuple], str]:
    """One pass over body for capture_from_html.

    Returns the strings get_text(' ', strip=True) joins, in document order;
    each heading, paragraph and list as (name, first string, end, inside
    nav/header/footer/aside/script/style, inside a list, inside a heading in
    body); and the text outside all of them. An element's text is a slice of
    the one list, so a paragraph inside another is not read twice.

    The outside text is what bs4 read from a reparsed copy of body, which this
    used to build: strings with nothing between them join, and only tags
    inside body decide which strings get_text leaves out.
    """
    from bs4 import CData, NavigableString, Tag
    from bs4.element import PreformattedString

    strings: list[str] = []
    blocks: list[list] = []
    unparsed: list[str] = []
    run: list[str] = []

    def end_run(kept):
        if run:
            words = ''.join(run).strip()
            if words and kept:
                unparsed.append(words)
            run.clear()

    above = list(body.parents)
    # Each frame: the children; whether they are under a nav, header, footer,
    # aside, script or style anywhere, a list anywhere, a heading in body, a
    # tag left out of the outside text, or a tag whose strings get_text skips;
    # and the block whose end they close.
    frames = [(iter(body.contents), any(tag.name in _OUTSIDE_SECTIONS for tag in above),
               any(tag.name in ('ul', 'ol') for tag in above), False, False, False, None)]
    while frames:
        children, outside, in_list, in_heading, skipped, contained, block = frames[-1]
        node = next(children, None)
        if node is None:
            end_run(not (skipped or contained))
            frames.pop()
            if block is not None:
                blocks[block][2] = len(strings)
            continue
        if isinstance(node, Tag):
            end_run(not (skipped or contained))
            name = node.name
            slot = None
            if name in _SECTION_BLOCKS:
                slot = len(blocks)
                blocks.append([name, len(strings), len(strings), outside, in_list, in_heading])
            frames.append((iter(node.contents), outside or name in _OUTSIDE_SECTIONS,
                           in_list or name in ('ul', 'ol'), in_heading or name in _HEADINGS,
                           skipped or name in _UNPARSED_SKIP, contained or name in _STRING_CONTAINERS, slot))
            continue
        if type(node) in (NavigableString, CData):
            words = node.strip()
            if words:
                strings.append(words)
        if isinstance(node, PreformattedString):
            end_run(not (skipped or contained))
            if type(node) is CData and not skipped:
                words = node.strip()
                if words:
                    unparsed.append(words)
        elif isinstance(node, NavigableString):
            run.append(node)
    return strings, [tuple(block) for block in blocks], ' '.join(unparsed)


def source_from_html(html, *, source_url: str, record_source_url: str | None = None,
                     identity_name: str | None = None, checked_at: str | None = None) -> dict | None:
    """Compatibility reader; collectors should preserve the full capture receipt."""
    result = capture_from_html(html, source_url=source_url, record_source_url=record_source_url,
                               identity_name=identity_name, checked_at=checked_at)
    return result['sources'][0] if result['status'] == 'captured' else None


def retained_sources(value) -> list[dict]:
    """Detached transfer of collector-owned source blocks; no model field merge."""
    return deepcopy(value) if isinstance(value, list) and len(value) <= _MAX_SOURCES else []



_REVOKED_SOURCE_REASONS = frozenset({'identity_mismatch', 'source_revoked', 'url_changed', 'redirect_mismatch', 'ambiguous_program_scope'})
_PAGE_ISSUES = frozenset({'source_limit', 'page_limit', 'invalid_input'})


def _source_time(value, *, allow_future=False):
    if not isinstance(value, str) or len(value) > 80:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None and (allow_future or parsed <= datetime.now(UTC)) else None
    except ValueError:
        return None


def _source_bound(value, record):
    urls = {_url(record.get(key)) for key in ('url', 'source_url')} - {None}
    if not isinstance(value, dict) or _url(value.get('record_source_url')) not in urls or not _url(value.get('source_url')):
        return False
    faculty = record.get('source_type') == 'faculty_research' or record.get('record_kind') == 'faculty_contact'
    identity = value.get('identity_name')
    return (not faculty and identity is None) or bool(_identity(record.get('pi_name')) and _identity(identity) == _identity(record.get('pi_name')))


def _source_page_key(requested, record_url):
    """Resource identity preserves host/path case/query; permits transport/slash normalization."""
    url, binding = _url(requested), _url(record_url)
    if not url or not binding:
        return None
    try:
        page = urlsplit(url)
        default = 443 if page.scheme == 'https' else 80
        port = page.port or default
        return (page.hostname.casefold(), None if port == default else port,
                (page.path or '/').removesuffix('/') or '/', page.query, binding)
    except ValueError:
        return None


def _source_receipt(value, record):
    required = {'version', 'status', 'reason', 'attempted_at', 'source_url', 'record_source_url'}
    optional = {'identity_name', 'requested_source_url', 'next_retry_at'}
    if not isinstance(value, dict) or not required.issubset(value) or set(value) - required - optional:
        return None
    if (type(value.get('version')) is not int or value['version'] != 1
            or not isinstance(value.get('status'), str) or value['status'] not in {'captured', 'empty', 'unsupported', 'failed'}):
        return None
    if value.get('reason') is not None and (not isinstance(value['reason'], str) or len(value['reason']) > 200):
        return None
    attempted = _source_time(value.get('attempted_at'))
    if not _source_bound(value, record) or not attempted:
        return None
    if 'requested_source_url' in value and not _url(value['requested_source_url']):
        return None
    if 'next_retry_at' in value:
        retry = _source_time(value['next_retry_at'], allow_future=True)
        if value['status'] not in {'failed', 'unsupported'} or retry is None or retry < attempted:
            return None
    return deepcopy(value)


def _source_blocks(value, record):
    if not isinstance(value, list) or len(value) > _MAX_SOURCES:
        return None
    for item in value:
        if not _source_bound(item, record) or not _source_time(item.get('checked_at')):
            return None
        sections = item.get('sections')
        if not isinstance(sections, list) or not sections or len(sections) > _MAX_SECTIONS:
            return None
        for section in sections:
            if not isinstance(section, dict):
                return None
            heading, text = section.get('heading'), section.get('text')
            if (not isinstance(heading, str) or len(heading) > 1000 or not isinstance(text, str)
                    or not text or len(text) > _MAX_TEXT or any(0xD800 <= ord(char) <= 0xDFFF for char in heading + text)):
                return None
    return deepcopy(value)


def _new_source_page(value, *, requested=None):
    page = {'requested_source_url': requested or value.get('requested_source_url') or value['source_url'],
            'record_source_url': value['record_source_url'], 'receipt':None, 'last_success':None, 'last_clear':None, 'sources':[]}
    if 'identity_name' in value:
        page['identity_name'] = value['identity_name']
    return page


def _receipt_requested(receipt, pages):
    if 'requested_source_url' in receipt:
        return receipt['requested_source_url']
    if receipt.get('reason') == 'redirect_mismatch' and not same_source_page(receipt['record_source_url'], receipt['source_url']):
        # Old redirects did not record the requested page. Only a sole existing
        # profile page makes the previous single-page assumption unambiguous.
        candidates = [p for p in pages.values() if same_source_page(p['requested_source_url'], receipt['record_source_url'])]
        return candidates[0]['requested_source_url'] if len(pages) == len(candidates) == 1 else None
    return receipt['source_url']


def _page_barrier(page):
    times = [_source_time(source['checked_at']) for source in page['sources']]
    for name in ('receipt', 'last_success', 'last_clear'):
        if page.get(name):
            times.append(_source_time(page[name]['attempted_at']))
    return max(times) if times else None


def _load_source_pages(record):
    """Read a complete ledger or migrate B54/B55 metadata without inventing dates."""
    metadata = record.get('metadata') if isinstance(record.get('metadata'), dict) else {}
    raw = metadata.get(SOURCE_KEY, [])
    sources = _source_blocks(raw, record)
    if sources is None:
        return {}, 'source_limit' if isinstance(raw, list) and len(raw) > _MAX_SOURCES else 'invalid_input'
    pages = {}
    for source in sources:
        key = _source_page_key(source['source_url'], source['record_source_url'])
        if key is None:
            return {}, 'invalid_input'
        pages.setdefault(key, _new_source_page(source))['sources'].append(source)
    if PAGES_KEY in metadata:
        ledger = metadata[PAGES_KEY]
        if (not isinstance(ledger, dict) or set(ledger) - {'version', 'pages', 'merge_issue'}
                or type(ledger.get('version')) is not int or ledger['version'] != 1
                or not isinstance(ledger.get('pages'), list) or len(ledger['pages']) > _MAX_PAGES
                or ('merge_issue' in ledger and (not isinstance(ledger['merge_issue'], str) or ledger['merge_issue'] not in _PAGE_ISSUES))):
            return {}, 'invalid_input'
        output = {}
        for item in ledger['pages']:
            if (not isinstance(item, dict) or set(item) - {'requested_source_url', 'record_source_url', 'identity_name', 'receipt', 'last_success', 'last_clear'}
                    or not {'requested_source_url', 'record_source_url', 'receipt', 'last_success'}.issubset(item)):
                return {}, 'invalid_input'
            binding = {**item, 'source_url':item['requested_source_url']}
            key = _source_page_key(item['requested_source_url'], item['record_source_url'])
            if key is None or key in output or not _source_bound(binding, record):
                return {}, 'invalid_input'
            page = {**deepcopy(item), 'sources':pages.pop(key, {}).get('sources', [])}
            for name in ('receipt', 'last_success', 'last_clear'):
                value = item.get(name)
                checked = _source_receipt(value, record) if value is not None else None
                if value is not None and (checked is None or _source_page_key(checked.get('requested_source_url') or checked['source_url'], checked['record_source_url']) != key):
                    return {}, 'invalid_input'
                page[name] = checked
            latest, success = page['receipt'], page['last_success']
            cleared = page['last_clear']
            if cleared and (not latest or _source_time(cleared['attempted_at']) > _source_time(latest['attempted_at'])
                            or not (cleared['status'] == 'empty' or cleared.get('reason') in _REVOKED_SOURCE_REASONS)):
                return {}, 'invalid_input'
            if success and (success['status'] not in {'captured', 'empty'} or not latest
                            or _source_time(success['attempted_at']) > _source_time(latest['attempted_at'])):
                return {}, 'invalid_input'
            if cleared and (not success or _source_time(cleared['attempted_at']) >= _source_time(success['attempted_at'])):
                page['sources'] = []
            if latest and (latest['status'] == 'empty' or latest.get('reason') in _REVOKED_SOURCE_REASONS):
                page['sources'] = []
            elif success and success['status'] == 'empty':
                page['sources'] = []
            if page['sources'] and latest and any(_source_time(s['checked_at']) > _source_time(latest['attempted_at']) for s in page['sources']):
                return {}, 'invalid_input'
            output[key] = page
        # A ledger is authoritative; orphan sources cannot bypass page state.
        if pages:
            return {}, 'invalid_input'
        return output, ledger.get('merge_issue')
    if CAPTURE_KEY in metadata:
        receipt = _source_receipt(metadata[CAPTURE_KEY], record)
        if receipt is None:
            return {}, 'invalid_input'
        requested = _receipt_requested(receipt, pages)
        if requested is None:
            return pages, 'invalid_input'
        key = _source_page_key(requested, receipt['record_source_url'])
        if key is None:
            return {}, 'invalid_input'
        page = pages.setdefault(key, _new_source_page(receipt, requested=requested))
        if 'requested_source_url' not in receipt and requested != receipt['source_url']:
            receipt['requested_source_url'] = requested
        page['receipt'] = receipt
        if receipt['status'] in {'captured', 'empty'}:
            page['last_success'] = deepcopy(receipt)
        if receipt['status'] == 'empty' or receipt.get('reason') in _REVOKED_SOURCE_REASONS:
            page['sources'] = []
            page['last_clear'] = deepcopy(receipt)
    return pages, None


def contact_instruction_pages(record: dict) -> list[dict]:
    """Validated per-page observations for bounded refresh scheduling; no I/O."""
    if not isinstance(record, dict):
        return []
    pages, _issue = _load_source_pages(record)
    # A rejected 9th source/33rd page is not materialized. Its latest bound
    # attempt still participates in scheduling, so it cannot starve other pages.
    metadata = record.get('metadata') if isinstance(record.get('metadata'), dict) else {}
    rejected = _source_receipt(metadata.get(CAPTURE_KEY), record)
    if rejected and rejected['status'] == 'unsupported' and rejected.get('reason') in {'source_limit', 'page_limit'}:
        requested = _receipt_requested(rejected, pages)
        key = _source_page_key(requested, rejected['record_source_url']) if requested else None
        if key is not None and key not in pages:
            page = _new_source_page(rejected, requested=requested)
            page['receipt'] = rejected
            pages[key] = page
    output = []
    for page in pages.values():
        times = [s['checked_at'] for s in page['sources']]
        cleared = page.get('last_clear')
        if page['last_success'] and page['last_success']['status'] == 'empty' and not (cleared and cleared.get('reason') in _REVOKED_SOURCE_REASONS):
            times.append(page['last_success']['attempted_at'])
        value = {key:deepcopy(page[key]) for key in ('requested_source_url', 'record_source_url', 'receipt', 'sources')}
        value['source_url'] = (page['sources'][0]['source_url'] if page['sources'] else
                               page['receipt']['source_url'] if page['receipt'] else page['requested_source_url'])
        value['last_success_at'] = max(times, key=_source_time) if times else None
        if 'identity_name' in page:
            value['identity_name'] = page['identity_name']
        output.append(value)
    return output


def validated_contact_instruction_sources(record: dict) -> list[dict]:
    """Materialized sources that obey page tombstones and validated binding."""
    return [source for page in contact_instruction_pages(record) for source in page['sources']]


def _same_source_record(existing, incoming):
    def urls(record):
        return {_url(record.get(key)) for key in ('url', 'source_url')} - {None}
    return bool(existing.get('id') and existing.get('id') == incoming.get('id')
                and urls(existing) and urls(existing) == urls(incoming)
                and existing.get('source_type') == incoming.get('source_type')
                and all(_identity(existing.get(k)) == _identity(incoming.get(k)) for k in ('pi_name', 'organization')))


def merge_contact_instruction_sources(existing: dict, incoming: dict) -> None:
    """Apply observations by requested page; never drop another page's constraints."""
    if not isinstance(incoming.get('metadata'), dict):
        incoming['metadata'] = {}
    metadata = incoming['metadata']
    old_metadata = existing.get('metadata') if isinstance(existing.get('metadata'), dict) else {}
    same_record = _same_source_record(existing, incoming)
    changed_target = bool(existing.get('id')) and not same_record
    pages, old_issue = _load_source_pages(existing) if same_record else ({}, None)
    original = deepcopy(pages)
    supplied_source = SOURCE_KEY in metadata
    supplied_capture = CAPTURE_KEY in metadata
    issue = None
    last_receipt = None
    historical_issue = None

    def apply(page_key, receipt, sources, *, requested, snapshot=None):
        nonlocal issue, last_receipt, pages
        page = deepcopy(pages.get(page_key) or _new_source_page(receipt or sources[0], requested=requested))
        barrier = _page_barrier(page)
        if snapshot is not None:
            events = [_source_time(s['checked_at']) for s in snapshot['sources']]
            events += [_source_time(snapshot[n]['attempted_at']) for n in ('last_success', 'last_clear') if snapshot.get(n)]
            if page_key not in pages or (events and (barrier is None or max(events) > barrier)):
                page = deepcopy(snapshot)
        observed = _source_time(receipt['attempted_at']) if receipt else min(_source_time(s['checked_at']) for s in sources)
        clearing = receipt and (receipt['status'] == 'empty' or receipt.get('reason') in _REVOKED_SOURCE_REASONS)
        captures = receipt is None or receipt['status'] == 'captured'
        if barrier and (observed < barrier or (observed == barrier and captures and sources != page['sources'])):
            return
        candidate = deepcopy(page)
        if clearing:
            candidate['sources'] = []
            candidate['last_clear'] = deepcopy(receipt)
        elif captures:
            candidate['sources'] = deepcopy(sources)
            candidate['last_clear'] = None
            if receipt is None:
                # A strictly newer legacy source is itself a successful page
                # observation; do not leave an older empty/failure over it.
                candidate['receipt'] = candidate['last_success'] = None
        if receipt:
            candidate['receipt'] = deepcopy(receipt)
            if receipt['status'] in {'captured', 'empty'}:
                candidate['last_success'] = deepcopy(receipt)
        trial = {**pages, page_key:candidate}
        limit = ('page_limit' if len(trial) > _MAX_PAGES else
                 'source_limit' if sum(len(p['sources']) for p in trial.values()) > _MAX_SOURCES else None)
        if limit:
            issue = limit
            if receipt:
                last_receipt = {**receipt, 'status':'unsupported', 'reason':limit}
                last_receipt.pop('next_retry_at', None)
            return
        pages = trial
        if receipt:
            last_receipt = deepcopy(receipt)

    incoming_ledger = metadata.get(PAGES_KEY)
    incoming_issue = incoming_ledger.get('merge_issue') if isinstance(incoming_ledger, dict) else None
    if changed_target and (PAGES_KEY in metadata or (supplied_source and not supplied_capture)):
        # A copied old ledger is not a new observation of a different target.
        # Current collectors can establish only their explicitly captured page.
        issue = 'invalid_input'
    elif (isinstance(incoming_issue, str) and incoming_issue in {'source_limit', 'page_limit'}
            and incoming_ledger.get('pages') == []):
        # Normalization rejected an oversized raw array before creating any
        # page state. A nonempty validated ledger may instead carry history.
        issue = incoming_issue
    elif PAGES_KEY in metadata:
        updates, issue = _load_source_pages(incoming)
        if updates and issue in {'source_limit', 'page_limit'}:
            historical_issue, issue = issue, None
        if issue is None:
            for key, page in updates.items():
                if page['receipt'] or page['sources']:
                    apply(key, page['receipt'], page['sources'], requested=page['requested_source_url'], snapshot=page)
    elif supplied_capture:
        receipt = _source_receipt(metadata[CAPTURE_KEY], incoming)
        requested = _receipt_requested(receipt, pages) if receipt else None
        previous_pages, _previous_issue = _load_source_pages(existing) if changed_target else ({}, None)
        previous_times = [_page_barrier(page) for page in previous_pages.values() if _page_barrier(page)]
        copied_attempt = bool(changed_target and receipt and previous_times
                              and _source_time(receipt['attempted_at']) <= max(previous_times))
        if receipt is None or requested is None or copied_attempt:
            issue = 'invalid_input'
        else:
            if 'requested_source_url' not in receipt and requested != receipt['source_url']:
                receipt['requested_source_url'] = requested
            key = _source_page_key(requested, receipt['record_source_url'])
            raw = metadata.get(SOURCE_KEY)
            sources = _source_blocks(raw, incoming) if receipt['status'] in {'captured', 'empty'} else []
            if sources is None:
                issue = 'source_limit' if isinstance(raw, list) and len(raw) > _MAX_SOURCES else 'invalid_input'
            else:
                target_sources = [s for s in sources if _source_page_key(s['source_url'], s['record_source_url']) == key]
                successful = (receipt['status'] not in {'captured', 'empty'}
                              or (receipt['status'] == 'empty' and not target_sources)
                              or (receipt['status'] == 'captured' and bool(target_sources)
                                  and all(_source_time(s['checked_at']) == _source_time(receipt['attempted_at'])
                                          and _url(s['source_url']) == _url(receipt['source_url']) for s in target_sources)))
                if receipt['status'] in {'captured', 'empty'} and not same_source_page(requested, receipt['source_url']):
                    successful = False
                if successful:
                    apply(key, receipt, target_sources, requested=requested)
                else:
                    issue = 'invalid_input'
    elif supplied_source:
        raw = metadata[SOURCE_KEY]
        sources = _source_blocks(raw, incoming)
        if sources is None:
            issue = 'source_limit' if isinstance(raw, list) and len(raw) > _MAX_SOURCES else 'invalid_input'
        else:
            groups = {}
            for source in sources:
                key = _source_page_key(source['source_url'], source['record_source_url'])
                groups.setdefault(key, []).append(source)
            for key, group in groups.items():
                apply(key, None, group, requested=group[0]['source_url'])
    if issue:
        pages = original
        if supplied_capture:
            receipt = _source_receipt(metadata[CAPTURE_KEY], incoming)
            if receipt and issue in {'source_limit', 'page_limit'}:
                last_receipt = {**receipt, 'status':'unsupported', 'reason':issue}
                last_receipt.pop('next_retry_at', None)
                requested = _receipt_requested(last_receipt, pages)
                key = _source_page_key(requested, last_receipt['record_source_url']) if requested else None
                if issue == 'source_limit' and key is not None and (key in pages or len(pages) < _MAX_PAGES):
                    rejected = deepcopy(pages.get(key) or _new_source_page(last_receipt, requested=requested))
                    rejected['receipt'] = deepcopy(last_receipt)
                    pages[key] = rejected
        else:
            last_receipt = None
    for key in (SOURCE_KEY, CAPTURE_KEY, PAGES_KEY):
        metadata.pop(key, None)
    flattened = [deepcopy(source) for page in pages.values() for source in page['sources']]
    was_empty = any(p['last_success'] and p['last_success']['status'] == 'empty'
                    or p['receipt'] and p['receipt'].get('reason') in _REVOKED_SOURCE_REASONS for p in pages.values())
    if flattened or was_empty or (same_record and SOURCE_KEY in old_metadata):
        metadata[SOURCE_KEY] = flattened
    if pages or issue:
        ledger = {'version':1, 'pages':[{key:deepcopy(value) for key,value in page.items() if key != 'sources'} for page in pages.values()]}
        if issue:
            ledger['merge_issue'] = issue
        elif historical_issue:
            ledger['merge_issue'] = historical_issue
        elif old_issue and not (supplied_capture or supplied_source):
            ledger['merge_issue'] = old_issue
        metadata[PAGES_KEY] = ledger
    receipts = [p['receipt'] for p in pages.values() if p['receipt']]
    previous_capture = _source_receipt(old_metadata.get(CAPTURE_KEY), incoming) if same_record else None
    if previous_capture and previous_capture['status'] == 'unsupported' and previous_capture.get('reason') in {'source_limit', 'page_limit'}:
        receipts.append(previous_capture)
    if last_receipt:
        metadata[CAPTURE_KEY] = last_receipt
    elif receipts:
        metadata[CAPTURE_KEY] = deepcopy(max(receipts, key=lambda r:_source_time(r['attempted_at'])))

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
    if isinstance(metadata, dict) and PAGES_KEY in metadata:
        sources = validated_contact_instruction_sources(record)
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
