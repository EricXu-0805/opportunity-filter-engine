"""Explicit, reviewed-profile website collection. No generic URL/LLM fallback."""
from __future__ import annotations

import hashlib
import json
import math
import time
from copy import deepcopy
from datetime import UTC, datetime

import requests
from bs4 import BeautifulSoup, Comment, NavigableString

from backend.lib.safe_webpush import UnsafePushEndpointError, _NoRedirectSession, validate_push_endpoint
from src.collectors.ucb_common import profile_page_is_denial
from src.lab_context import (
    LAB_REVOCATION_REASONS,
    NIELSEN_HOME,
    NIELSEN_PROFILE,
    NIELSEN_RESEARCH,
    NIELSEN_ROLE,
    NIELSEN_TEAM,
    _same_complete_name,
    _stamp,
    _text,
    canonical_lab_url,
    resolve_lab_link,
    reviewed_lab_chain_policy,
    reviewed_profile_policy,
    validate_lab_snapshot,
)

MAX_LAB_FETCH_BYTES = 5 * 1024 * 1024
_ERRORS = {'unsafe_url', 'redirect', 'rate_limited', 'http_error', 'request_failed', 'response_too_large',
           'invalid_content_type', 'invalid_response', 'unsupported_policy', 'unsupported_template',
           'identity_mismatch', 'source_link_removed', 'missing_sections', 'invalid_snapshot', 'invalid_target'}


def fetch_lab_page(url, *, timeout=15, resolver=None, session_factory=None, clock=None):
    """One HTTPS GET, pinned to public DNS answers, never proxy/redirect/retry.

    Reuses the already tested pinning adapter without changing Web Push. Byte
    and elapsed-time checks stop later reads; a blocked socket read still has
    its per-read timeout. This function does not establish faculty authority.
    """
    if canonical_lab_url(url) != url or not isinstance(url, str):
        return None, 'unsafe_url'
    if type(timeout) not in (int, float) or not 0 < timeout <= 15 or not math.isfinite(timeout):
        raise ValueError('invalid_lab_timeout')
    tick = time.monotonic if clock is None else clock
    deadline = tick() + timeout
    try:
        endpoint = validate_push_endpoint(url, resolver=resolver)
    except UnsafePushEndpointError:
        return None, 'unsafe_url'
    factory = _NoRedirectSession if session_factory is None else session_factory
    response = None
    try:
        if tick() >= deadline:
            return None, 'request_failed'
        with factory(endpoint) as session:
            try:
                response = session.get(url, timeout=timeout, allow_redirects=False, stream=True,
                                       headers={'User-Agent': 'OFE-WebsiteContext/1.0', 'Accept': 'text/html,application/xhtml+xml'})
                status = response.status_code
                if type(status) is not int:
                    return None, 'invalid_response'
                if 300 <= status < 400 or response.url != url:
                    return None, 'redirect'
                if status != 200:
                    return None, 'rate_limited' if status == 429 else 'http_error'
                content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                if content_type not in {'text/html', 'application/xhtml+xml'}:
                    return None, 'invalid_content_type'
                body = bytearray()
                chunks = iter(response.iter_content(chunk_size=8192))
                while True:
                    if tick() >= deadline:
                        return None, 'request_failed'
                    try:
                        chunk = next(chunks)
                    except StopIteration:
                        break
                    if tick() >= deadline:
                        return None, 'request_failed'
                    if type(chunk) is not bytes:
                        return None, 'invalid_response'
                    if len(body) + len(chunk) > MAX_LAB_FETCH_BYTES:
                        return None, 'response_too_large'
                    body.extend(chunk)
                return {'requested_url': url, 'source_url': url, 'html': bytes(body)}, None
            finally:
                if response is not None:
                    response.close()
    except requests.RequestException:
        return None, 'request_failed'


def _profile_snapshot(opp, policy, page, checked_at):
    if (type(page) is not dict or set(page) != {'requested_url', 'source_url', 'html'}
            or page['requested_url'] != policy['url'] or page['source_url'] != policy['url']):
        return None, 'redirect'
    if type(page['html']) is not bytes or len(page['html']) > MAX_LAB_FETCH_BYTES:
        return None, 'response_too_large'
    soup = BeautifulSoup(page['html'], 'html.parser')
    if profile_page_is_denial(soup):
        return None, 'unsupported_template'
    containers = soup.select(policy['container'])
    if len(containers) != 1:
        return None, 'unsupported_template'
    container = containers[0]
    if ('node--view-mode-teaser' in container.get('class', [])
            or container.select_one('article.node--type-faculty, .related-person, aside') is not None
            or container.find_parent(class_='views-row') is not None):
        return None, 'unsupported_template'
    # Two explicitly reviewed layouts, never an arbitrary descendant fallback.
    # The September 2026 site places the identity and source fields inside one
    # node__content. Keep the historical direct-h3 fixture compatible.
    wrappers = container.select(':scope > div.node__content')
    if wrappers:
        if len(wrappers) != 1 or len(container.select('.node__content')) != 1:
            return None, 'unsupported_template'
        content = wrappers[0]
        identities = content.select(':scope > div.node_top > div.node_top_copy > h1.page--title')
        selectors = (*policy['research_fields'], 'div.field--name-body')
    else:
        content = container
        identities = container.select(':scope > ' + policy['identity'])
        selectors = policy['research_fields']
    all_identities = container.select('h1.page--title, h3.page--title')
    if len(identities) != 1 or len(all_identities) != 1 or identities[0] is not all_identities[0]:
        return None, 'unsupported_template'
    identity = identities[0].get_text(' ', strip=True)
    if not _same_complete_name(identity, opp['pi_name']):
        return None, 'identity_mismatch'
    sections = []
    for selector in selectors:
        fields = content.select(':scope > ' + selector)
        # A moved or nested source field may contain a new qualification.
        # Reject it instead of reading only the remaining familiar fields.
        if len(fields) > 1 or len(container.select(selector[3:])) != len(fields):
            return None, 'unsupported_template'
        for field in fields:
            if field.select_one('script, style, nav, header, footer, aside, article, .related-person') is not None:
                return None, 'unsupported_template'
            # The current profile description is itself a field__item. Keep
            # its whole value (including biography and limitations), not selected
            # sentences. An absent heading stays absent in the source quote.
            if selector == 'div.field--name-body':
                if 'field__item' not in field.get('class', []) or field.select_one('.field__label, .field__items, .field__item'):
                    return None, 'unsupported_template'
                text = field.get_text(' ', strip=True)
                if not text:
                    return None, 'unsupported_template'
                sections.append({'section_id': f's{len(sections) + 1}', 'heading': '', 'text': text})
                continue
            # Unknown direct text/containers may hold a new qualifier. Do not
            # silently ignore them while another recognized field succeeds.
            for parent, allowed in ((field, {'field__label', 'field__item', 'field__items'}),
                                    *[(node, {'field__item'}) for node in field.select(':scope > .field__items')]):
                if any(str(node).strip() for node in parent.find_all(string=True, recursive=False)
                       if not isinstance(node, Comment)):
                    return None, 'unsupported_template'
                for child in parent.find_all(recursive=False):
                    if len(set(child.get('class', [])) & allowed) != 1:
                        return None, 'unsupported_template'
            labels = field.select(':scope > .field__label')
            if len(labels) > 1:
                return None, 'unsupported_template'
            heading = labels[0].get_text(' ', strip=True) if labels else ''
            values = field.select(':scope > .field__item, :scope > .field__items > .field__item')
            if not values:
                return None, 'unsupported_template'
            for element in values:
                # One complete reviewed field value. Preserve all paragraphs,
                # qualifiers and numbers; never truncate or synthesize a summary.
                text = element.get_text(' ', strip=True)
                if not text:
                    return None, 'unsupported_template'
                sections.append({'section_id': f's{len(sections) + 1}', 'heading': heading, 'text': text})
    if not sections:
        return None, 'missing_sections'
    snapshot = {'version': 1, 'source': 'official_website', 'record_id': opp['id'],
                'record_source_url': policy['url'], 'school': opp['school'], 'department': opp['department'],
                'identity_name': opp['pi_name'], 'policy_version': 1, 'checked_at': checked_at,
                'pages': [{'kind': 'faculty_profile', 'requested_url': policy['url'], 'source_url': policy['url'],
                           'page_title': soup.title.get_text(' ', strip=True) if soup.title else identity,
                           'identity_text': identity, 'linked_from': None, 'sections': sections}]}
    # A new successful observation is checked without an older failed-attempt
    # tombstone. Candidate preflight rejects observations older than that attempt;
    # this module does not apply candidates to the source corpus.
    probe = deepcopy(opp); probe.setdefault('metadata', {}).pop('lab_refresh', None)
    checked = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
    valid = validate_lab_snapshot(snapshot, probe, now=checked)
    return (valid, None) if valid is not None else (None, 'invalid_snapshot')


def _chain_soup(page, url):
    if (type(page) is not dict or set(page) != {'requested_url', 'source_url', 'html'}
            or page['requested_url'] != url or page['source_url'] != url):
        return None, 'redirect'
    if type(page['html']) is not bytes or len(page['html']) > MAX_LAB_FETCH_BYTES:
        return None, 'response_too_large'
    soup = BeautifulSoup(page['html'], 'html.parser')
    if profile_page_is_denial(soup) or soup.find('base') is not None or len(soup.find_all('title')) != 1:
        return None, 'unsupported_template'
    return soup, None


def _only_reviewed_children(node, children):
    """Do not discard qualifiers next to a reviewed source link or identity."""
    return (list(node.find_all(recursive=False)) == children
            and not any(str(value).strip() for value in node.find_all(string=True, recursive=False)
                        if not isinstance(value, Comment)))


def _profile_home_link(soup):
    containers = soup.select('article.node--type-faculty > div.node__content')
    if len(containers) != 1:
        return None, 'unsupported_template'
    content = containers[0]
    columns = content.select(':scope > div.node_columns')
    fields = content.select(':scope > div.node_columns > div.field--name-field-website')
    all_fields = content.select('.field--name-field-website')
    if len(columns) != 1 or len(fields) != len(all_fields) or len(fields) > 1:
        return None, 'unsupported_template'
    if not fields:
        # If the original link merely moved into an unknown container, that is
        # template drift, not a verified removal of the official chain.
        if any(resolve_lab_link(NIELSEN_PROFILE, a.get('href')) == NIELSEN_HOME for a in content.select('a[href]')):
            return None, 'unsupported_template'
        return None, 'source_link_removed'
    field = fields[0]
    labels = field.select(':scope > .field__label')
    items = field.select(':scope > .field__item')
    if len(labels) != 1 or labels[0].get_text(' ', strip=True) != 'Website' or len(items) != 1:
        return None, 'unsupported_template'
    if not _only_reviewed_children(field, [labels[0], items[0]]):
        return None, 'unsupported_template'
    anchors = items[0].select(':scope > a[href]')
    if len(anchors) != len(items[0].select('a')) or len(anchors) > 1:
        return None, 'unsupported_template'
    if not anchors:
        return None, 'source_link_removed' if not items[0].get_text(strip=True) else 'unsupported_template'
    anchor = anchors[0]; raw = anchor.get('href')
    if not _only_reviewed_children(items[0], [anchor]):
        return None, 'unsupported_template'
    resolved = resolve_lab_link(NIELSEN_PROFILE, raw)
    if resolved is None:
        return None, 'unsupported_template'
    if resolved != NIELSEN_HOME:
        return None, 'source_link_removed'
    if anchor.get_text(' ', strip=True) not in (NIELSEN_HOME, NIELSEN_HOME.rstrip('/')):
        return None, 'unsupported_template'
    return {'from_url': NIELSEN_PROFILE, 'raw_href': raw,
            'anchor_text': anchor.get_text(' ', strip=True), 'to_url': NIELSEN_HOME}, None


def _home_links(soup):
    navs = soup.select('body > div#header > nav.navbar')
    if len(navs) != 1 or len(soup.select('#header')) != 1:
        return None, 'unsupported_template'
    menus = navs[0].select(':scope > div.container > div#navbarNav.navbar-collapse > ul.navbar-nav')
    if len(menus) != 1:
        return None, 'unsupported_template'
    anchors = menus[0].select(':scope > li.nav-link > a[href]')
    if not anchors or len(anchors) != len(menus[0].select('a[href]')):
        return None, 'unsupported_template'
    items = menus[0].select(':scope > li.nav-link')
    if (not _only_reviewed_children(menus[0], items)
            or any(not _only_reviewed_children(item, item.select(':scope > a[href]'))
                   or len(item.select(':scope > a[href]')) != 1 for item in items)):
        return None, 'unsupported_template'
    links = []
    for path, name in (('/team/', 'Team'), ('/research/', 'Research')):
        matching = [a for a in anchors if a.get('href') == path]
        if len(matching) > 1:
            return None, 'unsupported_template'
        if not matching:
            destination = NIELSEN_HOME.rstrip('/') + path
            if any(resolve_lab_link(NIELSEN_HOME, a.get('href')) == destination for a in soup.select('a[href]')):
                return None, 'unsupported_template'
            named = [a for a in anchors if a.get_text(' ', strip=True) == name]
            if any(resolve_lab_link(NIELSEN_HOME, a.get('href')) is None for a in named):
                return None, 'unsupported_template'
            return None, 'source_link_removed'
        anchor = matching[0]
        if anchor.get_text(' ', strip=True) != name:
            return None, 'unsupported_template'
        links.append({'from_url': NIELSEN_HOME, 'raw_href': path, 'anchor_text': name,
                      'to_url': NIELSEN_HOME.rstrip('/') + path})
    return links, None


def _team_identity(soup):
    containers = soup.select('body > div.container.mt-4')
    if len(containers) != 1:
        return None, 'unsupported_template'
    main = containers[0]
    titles = main.select(':scope > div.row > div.col-lg-12 > div.title')
    if ([title.get_text(' ', strip=True) for title in titles] != ['Current members', 'Recent past members']
            or len(main.select('.title')) != 2):
        return None, 'unsupported_template'
    current = False; cards = []; all_cards = []
    for child in main.find_all(recursive=False):
        label = child.select_one(':scope > div.col-lg-12 > div.title')
        if label is not None:
            current = label.get_text(' ', strip=True) == 'Current members'
        else:
            direct_cards = child.select(':scope > div.memberbox')
            all_cards.extend(direct_cards)
            if current:
                cards.extend(direct_cards)
    if len(all_cards) != len(main.select('.memberbox')):
        return None, 'unsupported_template'
    candidates = []
    for card in cards:
        heads = card.select(':scope > div.media > div.media-body > div.head > a[href]')
        # A matching identity/path in an unrecognized card cannot be ignored.
        mentions = [a for a in card.select('a[href]') if a.get('href') == '/team/rasmus-nielsen/'
                    or a.get_text(' ', strip=True) == 'Rasmus Nielsen']
        if mentions and len(heads) != 1:
            return None, 'unsupported_template'
        if heads and (heads[0].get('href') == '/team/rasmus-nielsen/' or heads[0].get_text(' ', strip=True) == 'Rasmus Nielsen'):
            candidates.append((card, heads[0]))
    if not candidates:
        return None, 'identity_mismatch'
    if len(candidates) != 1:
        return None, 'unsupported_template'
    card, anchor = candidates[0]
    bodies = card.select(':scope > div.media > div.media-body')
    if len(bodies) != 1:
        return None, 'unsupported_template'
    body = bodies[0]; notes = body.select(':scope > p.note')
    heads = body.select(':scope > div.head')
    media = card.select(':scope > div.media')
    spacers = card.select(':scope > div.bigspacer')
    if (len(notes) != 1 or len(heads) != 1 or len(media) != 1
            or not _only_reviewed_children(body, [heads[0], notes[0]])
            or not _only_reviewed_children(heads[0], [anchor])
            or not _only_reviewed_children(card, [media[0], *spacers])
            or any(spacer.get_text(strip=True) or spacer.find() for spacer in spacers)):
        return None, 'unsupported_template'
    photos = media[0].select(':scope > a.float-left')
    if len(photos) != 1 or not _only_reviewed_children(media[0], [photos[0], body]):
        return None, 'unsupported_template'
    images = photos[0].select(':scope > img')
    if len(images) != 1 or not _only_reviewed_children(photos[0], images):
        return None, 'unsupported_template'
    name, role = anchor.get_text(' ', strip=True), notes[0].get_text(' ', strip=True)
    if name != 'Rasmus Nielsen' or anchor.get('href') != '/team/rasmus-nielsen/' or role != NIELSEN_ROLE:
        return None, 'identity_mismatch'
    return {'source_url': NIELSEN_TEAM, 'full_name': name, 'role_text': role}, None


def _research_sections(soup):
    containers = soup.select('body > div.container.mt-4')
    if len(containers) != 1:
        return None, 'unsupported_template'
    content = containers[0]
    if content.select_one('script, style, nav, header, footer, aside, article') is not None:
        return None, 'unsupported_template'
    headings = content.select(':scope > h1')
    if len(headings) != 10 or len(content.select('h1')) != 10:
        return None, 'unsupported_template'
    sections = []; parts = []; heading = None
    def finish():
        text = ' '.join(' '.join(parts).split())
        if not text:
            raise ValueError('empty_lab_section')
        sections.append({'section_id': f's{len(sections) + 1}', 'heading': heading, 'text': text})
    try:
        for node in content.children:
            if isinstance(node, Comment):
                continue
            if getattr(node, 'name', None) == 'h1':
                if heading is not None:
                    finish()
                heading = node.get_text(' ', strip=True); parts = []
            else:
                text = str(node) if isinstance(node, NavigableString) else node.get_text(' ', strip=True)
                if heading is None and text.strip():
                    return None, 'unsupported_template'
                if text.strip():
                    parts.append(text)
        finish()
    except ValueError:
        return None, 'missing_sections'
    return sections, None


def _nielsen_snapshot(opp, profile, profile_receipt, read, stamp):
    """Four reviewed documents, three actual links, one explicit Team identity."""
    receipts = [profile_receipt]; soups = []
    soup, error = _chain_soup(profile_receipt, NIELSEN_PROFILE)
    if error:
        return None, error
    soups.append(soup)
    first_link, error = _profile_home_link(soup)
    if error:
        return None, error
    for url in (NIELSEN_HOME, NIELSEN_TEAM, NIELSEN_RESEARCH):
        receipt, error = read(url)
        if error:
            return None, error if type(error) is str and error in _ERRORS else 'request_failed'
        soup, error = _chain_soup(receipt, url)
        if error:
            return None, error
        receipts.append(receipt); soups.append(soup)
        if url == NIELSEN_HOME:
            nav_links, error = _home_links(soup)
        elif url == NIELSEN_TEAM:
            identity, error = _team_identity(soup)
        else:
            sections, error = _research_sections(soup)
        if error:
            return None, error
    source = deepcopy(profile)
    source.update(version=2, policy_version=2, identity_name=source['pages'][0]['identity_text'])
    source['pages'].append({'kind': 'lab_research', 'requested_url': NIELSEN_RESEARCH, 'source_url': NIELSEN_RESEARCH,
                            'page_title': soups[3].title.get_text(' ', strip=True), 'sections': sections})
    source['source_chain'] = {'documents': [
        {'role': role, 'requested_url': receipt['requested_url'], 'source_url': receipt['source_url'],
         'page_title': soup.title.get_text(' ', strip=True), 'checked_at': stamp,
         'body_sha256': hashlib.sha256(receipt['html']).hexdigest()}
        for role, receipt, soup in zip(('profile', 'home', 'team', 'research'), receipts, soups, strict=True)],
        'links': [first_link, *nav_links], 'identity': identity}
    probe = deepcopy(opp); probe.setdefault('metadata', {}).pop('lab_refresh', None)
    valid = validate_lab_snapshot(source, probe, now=_stamp(stamp))
    return (valid, None) if valid is not None else (None, 'invalid_snapshot')


def _preflight_previous_observation(opp, current):
    """Preserve monotonic success, attempt and explicit revocation times."""
    metadata = opp.get('metadata') if type(opp) is dict else None
    if type(metadata) is not dict:
        return
    for key in ('lab_snapshot', 'lab_refresh'):
        old = metadata.get(key)
        if old is None:
            continue
        if type(old) is not dict:
            raise ValueError('invalid_prior_lab_time')
        try:
            prior_time = _stamp(old.get('checked_at'))
            if 'identity_revoked_at' in old:
                revoked = _stamp(old['identity_revoked_at'])
                if revoked > current:
                    raise ValueError('lab_candidate_time_regression')
        except (ValueError, TypeError):
            raise ValueError('invalid_prior_lab_time') from None
        if prior_time > current:
            raise ValueError('lab_candidate_time_regression')


def collect_lab_snapshot(opp, *, now=None, fetch=None):
    """Return a detached successful source or explicit attempt; never mutate."""
    current = datetime.now(UTC) if now is None else now
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('invalid_lab_time')
    _preflight_previous_observation(opp, current)
    stamp = current.astimezone(UTC).isoformat().replace('+00:00', 'Z')
    attempt = {'checked_at': stamp, 'status': 'failed', 'reason': 'unsupported_policy'}
    old_metadata = opp.get('metadata') if type(opp) is dict else None
    old_attempt = old_metadata.get('lab_refresh') if type(old_metadata) is dict else None
    if type(old_attempt) is dict:
        revoked = old_attempt.get('identity_revoked_at')
        if revoked is None and old_attempt.get('reason') in LAB_REVOCATION_REASONS:
            revoked = old_attempt.get('checked_at')
        if revoked is not None:
            # Keep a prior explicit identity rejection across later outages.
            # Only a newly verified complete source snapshot below clears it.
            _stamp(revoked)
            attempt['identity_revoked_at'] = revoked
    policy = reviewed_profile_policy(opp)
    if policy is None:
        return {'lab_refresh': attempt}
    if (type(opp.get('id')) is not str or not opp['id'].strip() or len(opp['id']) > 200
            or type(opp.get('pi_name')) is not str or not opp['pi_name'].strip() or len(opp['pi_name']) > 200
            or type(opp.get('metadata', {})) is not dict):
        attempt['reason'] = 'invalid_target'
        return {'lab_refresh': attempt}
    try:
        _text(opp['id'], 200); _text(opp['pi_name'], 200)
    except ValueError:
        attempt['reason'] = 'invalid_target'
        return {'lab_refresh': attempt}
    read = fetch_lab_page if fetch is None else fetch
    page, error = read(policy['url'])
    if error:
        attempt['reason'] = error if type(error) is str and error in _ERRORS else 'request_failed'
        return {'lab_refresh': attempt}
    snapshot, error = _profile_snapshot(opp, policy, page, stamp)
    if error is None and reviewed_lab_chain_policy(opp) is not None:
        snapshot, error = _nielsen_snapshot(opp, snapshot, page, read, stamp)
    if error:
        attempt['reason'] = error
        if error in LAB_REVOCATION_REASONS:
            attempt['identity_revoked_at'] = stamp
        return {'lab_refresh': attempt}
    if 'identity_revoked_at' in attempt and _stamp(attempt['identity_revoked_at']) >= current:
        raise ValueError('lab_identity_recheck_not_newer')
    return {'lab_snapshot': snapshot, 'lab_refresh': {'checked_at': stamp, 'status': 'success', 'reason': None}}


def canonical_record_sha(record):
    raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def build_lab_candidate(records, selected_ids, *, now=None, fetch=None):
    """Collect explicit record IDs into a new review artifact, never a corpus write."""
    if (type(records) is not list or any(type(r) is not dict or type(r.get('metadata', {})) is not dict for r in records)
            or type(selected_ids) is not list or not 1 <= len(selected_ids) <= 10
            or any(type(rid) is not str or not rid.strip() for rid in selected_ids)
            or len(set(selected_ids)) != len(selected_ids)):
        raise ValueError('invalid_lab_selection')
    index = {}
    for record in records:
        rid = record.get('id')
        if rid is not None:
            if type(rid) is not str or not rid or rid in index:
                raise ValueError('invalid_lab_record_ids')
            index[rid] = record
    if any(rid not in index for rid in selected_ids):
        raise ValueError('missing_lab_selected_record')
    current = datetime.now(UTC) if now is None else now
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError('invalid_lab_time')
    # Preflight every selected target before the first network read.
    for rid in selected_ids:
        _preflight_previous_observation(index[rid], current)
    corpus_sha = canonical_record_sha(records)
    results = []
    for rid in selected_ids:
        record = index[rid]
        before_sha = canonical_record_sha(record)
        patch = collect_lab_snapshot(record, now=current, fetch=fetch)
        if canonical_record_sha(record) != before_sha:
            raise ValueError('lab_record_changed_during_fetch')
        results.append({'record_id': rid, 'before_sha256': before_sha, 'patch': patch})
    if canonical_record_sha(records) != corpus_sha:
        raise ValueError('lab_corpus_changed_during_fetch')
    return {'version': 1, 'kind': 'lab_context_candidate', 'created_at': current.astimezone(UTC).isoformat().replace('+00:00', 'Z'),
            'corpus_sha256': corpus_sha, 'results': results}
