from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from src.research_context import (
    canonical_doi,
    research_context_for,
    research_snapshot_version,
    validate_public_research_context,
    validate_research_snapshot,
)

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)


def record():
    return {'school': 'uiuc', 'pi_name': 'Pat Lee', 'source_url': 'https://example.edu/lee',
            'metadata': {'publication_attribution_status': 'verified_author_id',
                         'publication_author_id': 'https://openalex.org/A123', 'works_gate': 3}}


def snapshot():
    return {'version': 1, 'source': 'openalex', 'record_source_url': 'https://example.edu/lee',
            'identity_name': 'Pat Lee', 'institution_id': 'https://openalex.org/I157725225',
            'author_id': 'https://openalex.org/A123', 'gate_version': 3,
            'checked_at': '2026-09-26T12:00:00Z', 'works': [{
                'work_id': 'https://openalex.org/W456', 'title': 'Neural Parser 解析 😀', 'year': 2026,
                'publication_date': '2026-08-01', 'source_url': 'https://doi.org/10.1234/parser',
                'doi': 'https://doi.org/10.1234/parser', 'abstract': 'A complete abstract.',
                'abstract_status': 'present', 'updated_date': '2026-09-01T00:00:00.123456',
            }]}


def context(s=None, o=None, now=NOW):
    o = o or record()
    o['metadata']['research_snapshot'] = s or snapshot()
    return research_context_for(o, now=now)


def test_current_and_historical_status_are_separate_and_snapshots_detached():
    s = snapshot()
    result = context(s)
    assert result['status'] == 'available'
    assert validate_public_research_context(result)
    result['snapshot']['works'][0]['title'] = 'changed'
    assert s['works'][0]['title'] == 'Neural Parser 解析 😀'
    assert not validate_public_research_context(result)
    saved = context(now=NOW + timedelta(days=31))
    assert saved['status'] == 'stale' and validate_public_research_context(saved)
    saved['status'] = 'available'
    assert validate_public_research_context(saved)  # history is not evaluated with today's clock


def test_thirty_day_boundary_future_checked_time_and_successful_empty():
    assert context(now=NOW + timedelta(days=30))['status'] == 'available'
    assert context(now=NOW + timedelta(days=30, microseconds=1))['status'] == 'stale'
    assert context(now=NOW - timedelta(microseconds=1)) == {'version': 1, 'status': 'unavailable', 'snapshot': None}
    s = snapshot(); s['works'] = []
    assert context(s)['snapshot']['works'] == []


@pytest.mark.parametrize('field,value', [
    ('pi_name', 'Other Lee'), ('school', 'uw'), ('school', 'unknown'),
    ('source_url', 'https://example.edu/other'),
])
def test_current_identity_changes_invalidate(field, value):
    o = record(); o[field] = value
    assert context(o=o)['status'] == 'unavailable'


@pytest.mark.parametrize('field,value', [
    ('publication_author_id', 'https://openalex.org/A124'),
    ('publication_attribution_status', 'name_match'), ('works_gate', 4),
    ('publication_institution_id', 'https://openalex.org/I2'),
])
def test_current_attribution_changes_invalidate(field, value):
    o = record(); o['metadata'][field] = value
    assert context(o=o)['status'] == 'unavailable'


@pytest.mark.parametrize('field,value', [
    ('extra', True), ('version', True), ('source', 'google'), ('gate_version', True),
    ('gate_version', 2), ('record_source_url', 'javascript:alert(1)'),
    ('record_source_url', 'https://user:password@example.edu/lee'),
    ('record_source_url', 'https://example.edu/lee#fake'),
    ('author_id', 'A123'), ('author_id', 'https://openalex.org/A9999999999'),
    ('author_id', 'https://openalex.org/A5317838346'),
    ('checked_at', '2026-02-30T00:00:00Z'), ('checked_at', '2026-09-26T12:00:00'),
    ('identity_name', '\ud800'), ('identity_name', ''),
])
def test_reject_bad_snapshot_fields(field, value):
    s = snapshot(); s[field] = value
    assert validate_research_snapshot(s, record(), now=NOW) is None


@pytest.mark.parametrize('field,value', [
    ('extra', 1), ('title', ' '), ('title', 'x' * 1001), ('year', True), ('year', 2101),
    ('publication_date', '2025-08-01'), ('publication_date', '2026-02-30'),
    ('updated_date', '2026-13-01'), ('abstract_status', 'unknown'),
    ('abstract', None), ('abstract', '\x00'), ('abstract', 'x' * 12001),
    ('doi', 'https://evil.test/10.1234/parser'), ('source_url', 'https://evil.test/paper'),
    ('work_id', 'W456'), ('work_id', 'https://openalex.org/A456'),
])
def test_reject_bad_work_fields(field, value):
    s = snapshot(); s['works'][0][field] = value
    assert validate_research_snapshot(s, record(), now=NOW) is None


@pytest.mark.parametrize('status', ['missing', 'invalid', 'too_long'])
def test_unavailable_abstract_has_no_text(status):
    s = snapshot(); w = s['works'][0]; w['abstract_status'] = status
    assert context(s)['status'] == 'unavailable'
    w['abstract'] = None
    assert context(s)['status'] == 'available'


def test_unicode_boundaries_do_not_count_utf16_and_no_duplicate_or_excess_work_ids():
    s = snapshot(); w = s['works'][0]; w['title'] = '😀' * 1000; w['abstract'] = '中' * 12000
    assert context(s)['status'] == 'available'
    s['works'] *= 2
    assert context(s)['status'] == 'unavailable'
    s['works'] = [{**w, 'work_id': f'https://openalex.org/W{i}'} for i in range(1, 5)]
    assert context(s)['status'] == 'unavailable'


def test_hash_tracks_all_material_but_not_operational_attempt_metadata():
    original = snapshot(); a = research_snapshot_version(original)
    reordered = dict(reversed(list(original.items())))
    assert research_snapshot_version(reordered) == a
    changed = deepcopy(original); changed['works'][0]['abstract'] += ' Additional detail.'
    assert research_snapshot_version(changed) != a
    o = record(); o['metadata']['research_refresh'] = {'status': 'failed', 'checked_at': '2099-01-01'}
    assert context(o=o)['snapshot']['snapshot_version'] == a
    o['metadata']['recent_works'] = [{'title': 'Legacy', 'year': 2026}]
    o['metadata'].pop('research_snapshot')
    assert research_context_for(o, now=NOW)['status'] == 'unavailable'


@pytest.mark.parametrize('bad', [None, {}, {'version': True, 'status': 'unavailable', 'snapshot': None},
                                  {'version': 1, 'status': 'unavailable', 'snapshot': {}},
                                  {'version': 1, 'status': 'available', 'snapshot': None}])
def test_historical_context_fail_closed(bad):
    assert not validate_public_research_context(bad)


def test_doi_normalization_does_not_turn_arbitrary_links_into_sources():
    assert canonical_doi('http://dx.doi.org/10.1234/Test') == 'https://doi.org/10.1234/Test'
    assert canonical_doi('10.1234/Test') == 'https://doi.org/10.1234/Test'
    for value in ['https://example.test/10.1234/Test', '10.1234/Test#x', '10.12/foo', '10.1234/a b', None]:
        assert canonical_doi(value) is None


@pytest.mark.parametrize('field,value', [('record_source_url', 'https://example.edu\\lee'), ('record_source_url', []), ('author_id', {}), ('works', {}), ('checked_at', [])])
def test_non_scalar_candidate_fields_and_backslash_fail_closed(field, value):
    s = snapshot(); s[field] = value
    assert context(s)['status'] == 'unavailable'
    public = {'version': 1, 'status': 'available', 'snapshot': {**s, 'snapshot_version': 'rs1:' + '0' * 64}}
    assert not validate_public_research_context(public)


@pytest.mark.parametrize('doi', ['https://doi.org/10.1234/' + 'x' * 1980, 'https://doi.org/10.1234/a\\b'])
def test_doi_url_limits_match_public_browser_schema(doi):
    s = snapshot(); s['works'][0].update(doi=doi, source_url=doi)
    assert context(s)['status'] == 'unavailable'


@pytest.mark.parametrize('field', ['checked_at'])
def test_timestamp_year_matches_browser_contract(field):
    s = snapshot(); s[field] = '0001-01-01T00:00:00Z'
    assert context(s)['status'] == 'unavailable'
