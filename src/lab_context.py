"""Strict, source-bound official website excerpts; no networking or LLM inference.

The historical parser preserves saved age/status. Only lab_context_for grants
current use after checking the record, reviewed policy and freshness again.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import unicodedata
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit, urlunsplit

import idna

LAB_MAX_AGE = timedelta(days=30)
LAB_POLICY_VERSION = 1
NIELSEN_RECORD_ID = 'faculty-ucb-stat-5558a1b1'
NIELSEN_PROFILE = 'https://statistics.berkeley.edu/people/rasmus-nielsen'
NIELSEN_HOME = 'https://nielsen-lab.github.io/'
NIELSEN_TEAM = NIELSEN_HOME + 'team/'
NIELSEN_RESEARCH = NIELSEN_HOME + 'research/'
NIELSEN_ROLE = 'Professor of Computational Biology in the Department of Integrative Biology and the Department of Statistics'
LAB_REVOCATION_REASONS = frozenset({'identity_mismatch', 'source_link_removed'})
_SNAPSHOT_KEYS = {'version', 'source', 'record_id', 'record_source_url', 'school', 'department',
                  'identity_name', 'policy_version', 'checked_at', 'pages'}
_PAGE_KEYS = {'kind', 'requested_url', 'source_url', 'page_title', 'identity_text', 'linked_from', 'sections'}
_STAMP = re.compile(r'[1-9][0-9]{3}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z')


def _fail():
    raise ValueError('invalid_lab_context')


def _text(value, maximum, *, blank=False):
    if type(value) is not str or len(value) > maximum or '\x00' in value or (not blank and not value.strip()):
        _fail()
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        _fail()
    return value


def canonical_lab_url(value):
    """Canonical HTTPS URL, with no credentials, fragments, query or IP literal."""
    try:
        _text(value, 2000)
        if not re.fullmatch(r'[\x21-\x7e]+', value) or any(c in value for c in '\\?#"<>`{}^'):
            return None
        p = urlsplit(value)
        if (p.scheme != 'https' or not p.hostname or p.username is not None or p.password is not None
                or p.query or p.fragment or p.port is not None):
            return None
        host = p.hostname
        if p.netloc != host or not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?', host):
            return None
        try:
            if idna.encode(idna.decode(host, uts46=True), uts46=True).decode('ascii') != host:
                return None
        except idna.IDNAError:
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return None
        canonical = urlunsplit(('https', host, p.path or '/', '', ''))
        if canonical != value or any(unquote(part).lower() in ('.', '..') for part in p.path.split('/')):
            return None
        return canonical
    except (ValueError, TypeError):
        return None


def _stamp(value):
    _text(value, 40)
    if _STAMP.fullmatch(value) is None:
        _fail()
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _now(value):
    current = datetime.now(UTC) if value is None else value
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        _fail()
    return current.astimezone(UTC)


def _same_complete_name(a, b):
    # No first/last-only or one-script-only reduction. Preserve every token;
    # spacing and Unicode canonical composition do not change the identity.
    def norm(value):
        return ' '.join(unicodedata.normalize('NFC', value).casefold().split())
    return norm(a) == norm(b)


def reviewed_profile_policy(opp):
    """Reviewed Statistics profile bindings. No generic .edu fallback.

    Collector layouts cover the preserved direct-h3 fixture and the current
    node__content/h1 layout read on 2026-09-26 from the official Peng Ding and
    Rasmus Nielsen profiles. Other schools and linked lab pages are separate
    policies; matching this binding is not a fresh observation of every page.
    """
    if type(opp) is not dict:
        return None
    url = opp.get('source_url') if opp.get('source_url') is not None else opp.get('url')
    canonical = canonical_lab_url(url)
    if (opp.get('school') != 'ucb' or opp.get('source') != 'ucb_stat_faculty'
            or opp.get('source_type') != 'faculty_research'
            or opp.get('department') != 'Department of Statistics'
            or canonical is None or re.fullmatch(r'https://statistics\.berkeley\.edu/people/[a-z0-9]+(?:-[a-z0-9]+)*/?', canonical) is None
            or canonical.rstrip('/').rsplit('/', 1)[-1] in {'faculty', 'staff', 'students', 'people', 'directory'}):
        return None
    alternate = opp.get('url')
    if alternate is not None and canonical_lab_url(alternate) != canonical:
        return None
    return {'version': 1, 'url': canonical, 'container': 'article.node--type-faculty',
            'identity': 'h3.page--title',
            'research_fields': ('div.field--name-field-research-interests', 'div.field--name-field-research-areas-ref')}


def _snapshot_v1(value):
    if type(value) is not dict or set(value) != _SNAPSHOT_KEYS:
        _fail()
    if (type(value['version']) is not int or value['version'] != 1 or value['source'] != 'official_website'
            or type(value['policy_version']) is not int or value['policy_version'] != 1):
        _fail()
    for field in ('record_id', 'school', 'department', 'identity_name'):
        _text(value[field], 200)
    if type(value['record_source_url']) is not str or canonical_lab_url(value['record_source_url']) != value['record_source_url']:
        _fail()
    _stamp(value['checked_at'])
    pages = value['pages']
    if type(pages) is not list or not 1 <= len(pages) <= 2:
        _fail()
    total = 0
    for index, page in enumerate(pages):
        if type(page) is not dict or set(page) != _PAGE_KEYS:
            _fail()
        if page['kind'] != ('faculty_profile' if index == 0 else 'lab_website'):
            _fail()
        for key in ('requested_url', 'source_url'):
            if type(page[key]) is not str or canonical_lab_url(page[key]) != page[key]:
                _fail()
        if page['requested_url'] != page['source_url']:
            _fail()
        _text(page['page_title'], 1000)
        _text(page['identity_text'], 200)
        if index == 0:
            if page['source_url'] != value['record_source_url'] or page['linked_from'] is not None:
                _fail()
        else:
            link = page['linked_from']
            if type(link) is not dict or set(link) != {'profile_url', 'anchor_text', 'href'}:
                _fail()
            if link['profile_url'] != value['record_source_url'] or link['href'] != page['requested_url']:
                _fail()
            if page['source_url'] == value['record_source_url']:
                _fail()
            _text(link['anchor_text'], 500)
        sections = page['sections']
        if type(sections) is not list or not 1 <= len(sections) <= 32:
            _fail()
        for pos, section in enumerate(sections, 1):
            if type(section) is not dict or set(section) != {'section_id', 'heading', 'text'} or section['section_id'] != f's{pos}':
                _fail()
            _text(section['heading'], 1000, blank=True)
            _text(section['text'], 4000)
            total += len(section['heading']) + len(section['text'])
    if total > 24000:
        _fail()
    return deepcopy(value)


def reviewed_lab_chain_policy(opp):
    policy = reviewed_profile_policy(opp)
    if (policy is None or opp.get('id') != NIELSEN_RECORD_ID or policy['url'] != NIELSEN_PROFILE
            or type(opp.get('pi_name')) is not str or not _same_complete_name(opp['pi_name'], 'Rasmus Nielsen')):
        return None
    return {'version': 2, 'urls': (NIELSEN_PROFILE, NIELSEN_HOME, NIELSEN_TEAM, NIELSEN_RESEARCH),
            'name': 'Rasmus Nielsen', 'role_text': NIELSEN_ROLE}


def resolve_lab_link(from_url, raw_href):
    """Only canonical absolute links, missing root '/', or single-/ paths."""
    if canonical_lab_url(from_url) != from_url or type(from_url) is not str:
        return None
    try:
        _text(raw_href, 2000)
    except ValueError:
        return None
    if raw_href.startswith('/') and not raw_href.startswith('//'):
        source = urlsplit(from_url)
        resolved = f'https://{source.netloc}' + raw_href
    else:
        resolved = raw_href
        try:
            parsed = urlsplit(resolved)
        except ValueError:
            return None
        if parsed.scheme == 'https' and parsed.netloc and parsed.path == '':
            resolved += '/'
    return resolved if canonical_lab_url(resolved) == resolved else None


def _snapshot_v2(value):
    if (type(value) is not dict or set(value) != _SNAPSHOT_KEYS | {'source_chain'}
            or type(value['version']) is not int or value['version'] != 2
            or type(value['policy_version']) is not int or value['policy_version'] != 2):
        _fail()
    pages = value['pages']
    if type(pages) is not list or len(pages) != 2:
        _fail()
    # Reuse the unchanged V1 faculty-page validation, without changing saved V1.
    profile = {key: item for key, item in value.items() if key != 'source_chain'}
    profile.update(version=1, policy_version=1, pages=[pages[0]])
    _snapshot_v1(profile)
    lab = pages[1]
    if (type(lab) is not dict or set(lab) != {'kind', 'requested_url', 'source_url', 'page_title', 'sections'}
            or lab['kind'] != 'lab_research' or type(lab['requested_url']) is not str
            or canonical_lab_url(lab['requested_url']) != lab['requested_url'] or lab['source_url'] != lab['requested_url']):
        _fail()
    _text(lab['page_title'], 1000)
    sections = lab['sections']
    if type(sections) is not list or not 1 <= len(sections) <= 32:
        _fail()
    total = sum(len(section['heading']) + len(section['text']) for section in pages[0]['sections'])
    for index, section in enumerate(sections, 1):
        if type(section) is not dict or set(section) != {'section_id', 'heading', 'text'} or section['section_id'] != f's{index}':
            _fail()
        _text(section['heading'], 1000, blank=True); _text(section['text'], 4000)
        total += len(section['heading']) + len(section['text'])
    if total > 24000:
        _fail()
    chain = value['source_chain']
    if type(chain) is not dict or set(chain) != {'documents', 'links', 'identity'}:
        _fail()
    documents, links, identity = chain['documents'], chain['links'], chain['identity']
    if type(documents) is not list or len(documents) != 4 or type(links) is not list or len(links) != 3:
        _fail()
    urls = []
    for role, document in zip(('profile', 'home', 'team', 'research'), documents, strict=True):
        if (type(document) is not dict or set(document) != {'role', 'requested_url', 'source_url', 'page_title', 'checked_at', 'body_sha256'}
                or document['role'] != role or type(document['requested_url']) is not str
                or canonical_lab_url(document['requested_url']) != document['requested_url']
                or document['source_url'] != document['requested_url'] or document['checked_at'] != value['checked_at']
                or type(document['body_sha256']) is not str or re.fullmatch(r'[0-9a-f]{64}', document['body_sha256']) is None):
            _fail()
        _text(document['page_title'], 1000)
        urls.append(document['source_url'])
    if len(set(urls)) != 4 or len({urlsplit(url).netloc for url in urls[1:]}) != 1:
        _fail()
    for page, document in ((pages[0], documents[0]), (pages[1], documents[3])):
        if page['source_url'] != document['source_url'] or page['page_title'] != document['page_title']:
            _fail()
    for (left, right), link in zip(((0, 1), (1, 2), (1, 3)), links, strict=True):
        if (type(link) is not dict or set(link) != {'from_url', 'raw_href', 'anchor_text', 'to_url'}
                or link['from_url'] != urls[left] or link['to_url'] != urls[right]
                or resolve_lab_link(link['from_url'], link['raw_href']) != link['to_url']):
            _fail()
        _text(link['anchor_text'], 500)
    if type(identity) is not dict or set(identity) != {'source_url', 'full_name', 'role_text'}:
        _fail()
    _text(identity['full_name'], 200); _text(identity['role_text'], 2000)
    if (identity['source_url'] != urls[2] or identity['full_name'] != value['identity_name']
            or identity['full_name'] != pages[0]['identity_text']):
        _fail()
    return deepcopy(value)


def _snapshot(value):
    return _snapshot_v2(value) if type(value) is dict and value.get('version') == 2 else _snapshot_v1(value)


def lab_snapshot_version(snapshot):
    value = _snapshot(snapshot)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return ('ls2:' if value['version'] == 2 else 'ls1:') + hashlib.sha256(raw).hexdigest()


def validate_public_lab_context(value):
    """Historical parsing checks exact content/hash, not today's age or policy."""
    try:
        if (type(value) is not dict or set(value) != {'version', 'status', 'snapshot'}
                or type(value['version']) is not int or value['version'] != 1):
            return False
        if value['status'] == 'unavailable':
            return value['snapshot'] is None
        if value['status'] not in ('available', 'stale') or type(value['snapshot']) is not dict:
            return False
        public = value['snapshot']
        expected = _SNAPSHOT_KEYS | {'snapshot_version'} | ({'source_chain'} if public.get('version') == 2 else set())
        if set(public) != expected:
            return False
        stored = {k: v for k, v in public.items() if k != 'snapshot_version'}
        return public['snapshot_version'] == lab_snapshot_version(stored)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False


def validate_lab_snapshot(value, opp, *, now=None):
    """Current source policy is independent from OpenAlex publication trust."""
    try:
        snapshot = _snapshot(value)
        policy = reviewed_profile_policy(opp)
        if policy is None:
            return None
        if snapshot['version'] == 1:
            if len(snapshot['pages']) != 1:
                return None
        else:
            chain_policy = reviewed_lab_chain_policy(opp)
            if chain_policy is None:
                return None
            chain = snapshot['source_chain']
            if (tuple(doc['source_url'] for doc in chain['documents']) != chain_policy['urls']
                    or chain['identity']['full_name'] != chain_policy['name']
                    or chain['identity']['role_text'] != chain_policy['role_text']
                    or chain['links'][0]['raw_href'] not in (NIELSEN_HOME, NIELSEN_HOME.rstrip('/'))
                    or chain['links'][1]['raw_href'] != '/team/' or chain['links'][2]['raw_href'] != '/research/'
                    or chain['links'][0]['anchor_text'] not in (NIELSEN_HOME, NIELSEN_HOME.rstrip('/'))
                    or chain['links'][1]['anchor_text'] != 'Team' or chain['links'][2]['anchor_text'] != 'Research'
                    or len(snapshot['pages'][1]['sections']) != 10):
                return None
        for field, record_field in (('record_id', 'id'), ('school', 'school'), ('department', 'department')):
            if snapshot[field] != opp.get(record_field):
                return None
        name = _text(opp.get('pi_name'), 200)
        if not _same_complete_name(snapshot['identity_name'], name):
            return None
        if not _same_complete_name(snapshot['pages'][0]['identity_text'], name):
            return None
        if snapshot['record_source_url'] != policy['url'] or _stamp(snapshot['checked_at']) > _now(now):
            return None
        metadata = opp.get('metadata')
        refresh = metadata.get('lab_refresh') if type(metadata) is dict else None
        if type(refresh) is dict:
            revoked = refresh.get('identity_revoked_at')
            if 'identity_revoked_at' in refresh and _stamp(revoked) >= _stamp(snapshot['checked_at']):
                return None
            if refresh.get('reason') in LAB_REVOCATION_REASONS and _stamp(refresh.get('checked_at')) >= _stamp(snapshot['checked_at']):
                return None
        return snapshot
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None


def lab_context_for(opp, *, now=None):
    unavailable = {'version': 1, 'status': 'unavailable', 'snapshot': None}
    try:
        current = _now(now)
        metadata = opp.get('metadata') if type(opp) is dict else None
        snapshot = validate_lab_snapshot(metadata.get('lab_snapshot') if type(metadata) is dict else None, opp, now=current)
        if snapshot is None:
            return unavailable
        return {'version': 1, 'status': 'stale' if current - _stamp(snapshot['checked_at']) > LAB_MAX_AGE else 'available',
                'snapshot': {**snapshot, 'snapshot_version': lab_snapshot_version(snapshot)}}
    except (ValueError, TypeError, OverflowError, RecursionError):
        return unavailable
