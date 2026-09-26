"""Explicit, reviewed-profile website collection. No generic URL/LLM fallback."""
from __future__ import annotations

import hashlib
import json
import math
import time
from copy import deepcopy
from datetime import UTC, datetime

import requests
from bs4 import BeautifulSoup, Comment

from backend.lib.safe_webpush import UnsafePushEndpointError, _NoRedirectSession, validate_push_endpoint
from src.collectors.ucb_common import profile_page_is_denial
from src.lab_context import (
    _same_complete_name,
    _stamp,
    _text,
    canonical_lab_url,
    reviewed_profile_policy,
    validate_lab_snapshot,
)

MAX_LAB_FETCH_BYTES = 5 * 1024 * 1024
_ERRORS = {'unsafe_url', 'redirect', 'rate_limited', 'http_error', 'request_failed', 'response_too_large',
           'invalid_content_type', 'invalid_response', 'unsupported_policy', 'unsupported_template',
           'identity_mismatch', 'missing_sections', 'invalid_snapshot', 'invalid_target'}


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
    identities = container.select(policy['identity'])
    if len(identities) != 1 or identities[0].parent is not container:
        return None, 'unsupported_template'
    identity = identities[0].get_text(' ', strip=True)
    if not _same_complete_name(identity, opp['pi_name']):
        return None, 'identity_mismatch'
    sections = []
    for selector in policy['research_fields']:
        fields = container.select(':scope > ' + selector)
        if len(fields) > 1:
            return None, 'unsupported_template'
        for field in fields:
            if field.select_one('script, style, nav, header, footer, aside, article, .related-person') is not None:
                return None, 'unsupported_template'
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
        if revoked is None and old_attempt.get('reason') == 'identity_mismatch':
            revoked = old_attempt.get('checked_at')
        if revoked is not None:
            # Keep a prior explicit identity rejection across later outages.
            # Only a newly matched profile snapshot below clears it.
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
    if error:
        attempt['reason'] = error
        if error == 'identity_mismatch':
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
