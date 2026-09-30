import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
import requests

from src.collectors import openalex_enrich as oa
from src.research_context import research_context_for

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
A = 'https://openalex.org/A123'
B = 'https://openalex.org/A124'


def record(aid=A, name='Pat Lee'):
    return {'school': 'uiuc', 'pi_name': name, 'source_url': f'https://example.edu/{name.replace(" ", "_")}',
            'department': 'Computer Science', 'metadata': {'publication_author_id': aid,
            'publication_attribution_status': 'verified_author_id', 'works_gate': 3,
            'recent_works': [{'title': 'Legacy original', 'year': 2025}]}}


def author(aid=A, name='Pat Lee'):
    return {'id': aid, 'display_name': name,
            'affiliations': [{'institution': {'id': 'https://openalex.org/I157725225'}}],
            'topics': [{'field': {'display_name': 'Computer Science'}}]}


def work(n=1, aid=A, **extra):
    return {'id': f'https://openalex.org/W{n}', 'display_name': f'Full parser study {n}',
            'publication_year': 2026, 'publication_date': '2026-08-01',
            'primary_topic': {'field': {'display_name': 'Computer Science'}},
            'authorships': [{'author': {'id': aid}}],
            'doi': f'https://doi.org/10.1234/parser{n}',
            'abstract_inverted_index': {'A': [0], 'complete': [1], 'abstract.': [2]},
            'updated_date': '2026-09-01T12:00:00', **extra}


def fixture_transport(monkeypatch, *, works=None, authors=None, error=None):
    calls = []
    def get(params, *, url):
        calls.append((deepcopy(params), url))
        if url == oa._WORKS_API:
            if error:
                return None, error
            result = works if works is not None else [work()]
            return {'results': result, 'meta': {'count': len(result)}}, None
        aid = 'https://openalex.org/' + url.rsplit('/', 1)[-1]
        return (authors or {A: author()}).get(aid, author(aid)), None
    monkeypatch.setattr(oa, '_research_get', get)
    return calls


def test_success_carries_complete_abstract_identity_and_explicit_apply(monkeypatch):
    calls = fixture_transport(monkeypatch)
    original = record(); records = [deepcopy(original)]
    patch = oa.harvest_research_snapshots(records, limit=1, now=NOW)
    assert records == [original]
    assert oa.apply_research_refresh(records, patch, now=NOW) == 1
    result = research_context_for(records[0], now=NOW)
    assert result['status'] == 'available'
    w = result['snapshot']['works'][0]
    assert w['abstract'] == 'A complete abstract.' and w['title'] == 'Full parser study 1'
    assert records[0]['metadata']['recent_works'] == [{'title': 'Full parser study 1', 'year': 2026}]
    assert len(calls) == 2 and calls[-1][0]['per_page'] == 100
    assert '_eligible' not in next(iter(patch.values()))


@pytest.mark.parametrize('raw,expected', [
    (None, (None, 'missing')), ({}, (None, 'invalid')),
    ({'hello': [0], 'world': [1]}, ('hello world', 'present')),
    ({'repeat': [0, 1]}, ('repeat repeat', 'present')),
    ({'x': [False]}, (None, 'invalid')), ({'x': [-1]}, (None, 'invalid')),
    ({'x': [0, 0]}, (None, 'invalid')), ({'x': [0], 'y': [0]}, (None, 'invalid')),
    ({'x': [1]}, (None, 'invalid')), ({'x': [0, 2]}, (None, 'invalid')),
    ({'x': [12000]}, (None, 'too_long')), ({'x' * 12001: [0]}, (None, 'too_long')),
    ({'\ud800': [0]}, (None, 'invalid')), ({'x': '0'}, (None, 'invalid')),
])
def test_abstract_inversion_is_complete_or_explicitly_unavailable(raw, expected):
    assert oa.reconstruct_research_abstract(raw) == expected


def test_full_title_and_unicode_abstract_boundaries_not_legacy_truncated(monkeypatch):
    title = '学' * 1000
    fixture_transport(monkeypatch, works=[work(display_name=title, abstract_inverted_index={'😀' * 12000: [0]})])
    patch = oa.harvest_research_snapshots([record()], now=NOW)
    value = next(iter(patch.values()))['research_snapshot']['works'][0]
    assert value['title'] == title and value['abstract'] == '😀' * 12000


@pytest.mark.parametrize('error', ['request_failed', 'rate_limited', 'http_error', 'invalid_response'])
def test_refresh_failure_preserves_success_and_legacy_data(monkeypatch, error):
    fixture_transport(monkeypatch)
    records = [record()]; good = oa.harvest_research_snapshots(records, now=NOW)
    oa.apply_research_refresh(records, good, now=NOW)
    old = deepcopy(records[0]['metadata']['research_snapshot'])
    fixture_transport(monkeypatch, error=error)
    next_time = NOW.replace(day=27)
    bad = oa.harvest_research_snapshots(records, now=next_time)
    assert oa.apply_research_refresh(records, bad, now=next_time) == 1
    assert records[0]['metadata']['research_snapshot'] == old
    assert research_context_for(records[0], now=next_time)['status'] == 'available'
    assert records[0]['metadata']['research_refresh']['reason'] == error


def test_successful_empty_refresh_is_distinct_from_failure(monkeypatch):
    fixture_transport(monkeypatch, works=[])
    records = [record()]
    patch = oa.harvest_research_snapshots(records, now=NOW)
    assert oa.apply_research_refresh(records, patch, now=NOW) == 1
    assert records[0]['metadata']['research_snapshot']['works'] == []
    assert records[0]['metadata']['recent_works'] == []
    assert records[0]['metadata']['research_refresh']['status'] == 'success'


@pytest.mark.parametrize('change', [
    {'id': 'https://openalex.org/A9999999999'}, {'id': 'https://openalex.org/A5317838346'},
    {'display_name': 'Other Lee'},
    {'affiliations': [{'institution': {'id': 'https://openalex.org/I2'}}]},
    {'topics': [{'field': {'display_name': 'Medicine'}}]},
])
def test_confirmed_identity_revocation_retains_old_snapshot_but_disallows_public_use(monkeypatch, change):
    fixture_transport(monkeypatch)
    records = [record()]; oa.apply_research_refresh(records, oa.harvest_research_snapshots(records, now=NOW), now=NOW)
    old = deepcopy(records[0]['metadata']['research_snapshot'])
    fixture_transport(monkeypatch, authors={A: {**author(), **change}})
    patch = oa.harvest_research_snapshots(records, now=NOW)
    assert next(iter(patch.values()))['research_refresh']['reason'] == 'identity_revoked'
    assert oa.apply_research_refresh(records, patch, now=NOW) == 1
    assert records[0]['metadata']['research_snapshot'] == old
    assert research_context_for(records[0], now=NOW)['status'] == 'unavailable'


@pytest.mark.parametrize('change', [{'affiliations': []}, {'topics': None}, {'display_name': ''}, {'id': 'bad'}])
def test_incomplete_author_response_does_not_revoke_identity(monkeypatch, change):
    fixture_transport(monkeypatch, authors={A: {**author(), **change}})
    records = [record()]; patch = oa.harvest_research_snapshots(records, now=NOW)
    oa.apply_research_refresh(records, patch, now=NOW)
    assert records[0]['metadata']['publication_attribution_status'] == 'verified_author_id'
    assert records[0]['metadata']['research_refresh']['reason'] == 'invalid_response'


def test_own_author_fields_and_authorship_are_both_required(monkeypatch):
    raw = [work(1, aid=B), work(2, primary_topic={'field': {'display_name': 'Medicine'}}), work(3)]
    fixture_transport(monkeypatch, works=raw)
    patch = oa.harvest_research_snapshots([record()], now=NOW)
    assert [w['work_id'] for w in next(iter(patch.values()))['research_snapshot']['works']] == ['https://openalex.org/W3']


def test_crowded_batch_drops_served_author_without_calling_missing_author_empty(monkeypatch):
    calls = []
    def get(params, *, url):
        calls.append(params)
        raw = [work(i) for i in range(1, 101)] if len(calls) == 1 else [work(999, aid=B)]
        return {'results': raw, 'meta': {'count': 101 if len(calls) == 1 else 1}}, None
    monkeypatch.setattr(oa, '_research_get', get)
    result = oa.research_works_for_authors({A: {'Computer Science'}, B: {'Computer Science'}})
    assert result[A]['status'] == result[B]['status'] == 'success'
    assert len(result[A]['works']) == 3 and len(result[B]['works']) == 1
    assert calls[1]['filter'] == 'author.id:A124'


@pytest.mark.parametrize('authorships', [[], None, [{'author': {'id': B}}] * 100, [{'author': {}}]])
def test_missing_or_truncated_authorships_cannot_prove_empty_result(monkeypatch, authorships):
    fixture_transport(monkeypatch, works=[work(authorships=authorships)])
    result = oa.research_works_for_authors({A: {'Computer Science'}})
    assert result[A]['status'] == 'incomplete'


def test_budget_exhausted_page_never_renews_old_snapshot(monkeypatch):
    def get(params, *, url):
        return {'results': [work(1, aid=B)], 'meta': {'count': 500}}, None
    monkeypatch.setattr(oa, '_research_get', get)
    result = oa.research_works_for_authors({A: {'Computer Science'}})
    assert result[A] == {'status': 'incomplete', 'reason': 'incomplete_page', 'works': []}


@pytest.mark.parametrize('payload', [{}, {'results': []}, {'results': [], 'meta': {'count': True}},
                                    {'results': [None], 'meta': {'count': 1}}])
def test_malformed_success_response_is_failure_not_empty(monkeypatch, payload):
    monkeypatch.setattr(oa, '_research_get', lambda *a, **kw: (payload, None))
    result = oa.research_works_for_authors({A: {'Computer Science'}})
    assert result[A]['status'] == 'failed'


def test_changed_identity_and_stale_patch_cannot_apply(monkeypatch):
    fixture_transport(monkeypatch)
    original = record(); patch = oa.harvest_research_snapshots([original], now=NOW)
    for key, value in [('pi_name', 'Other Lee'), ('school', 'uw'), ('source_url', 'https://example.edu/other')]:
        changed = deepcopy(original); changed[key] = value
        assert oa.apply_research_refresh([changed], patch, now=NOW) == 0
    records = [record()]
    newer = oa.harvest_research_snapshots(records, now=NOW.replace(day=27))
    assert oa.apply_research_refresh(records, newer, now=NOW.replace(day=27)) == 1
    assert oa.apply_research_refresh(records, patch, now=NOW.replace(day=27)) == 0


@pytest.mark.parametrize('status', [401, 429, 500])
def test_http_error_never_becomes_json_success_or_retries(monkeypatch, status):
    calls = []
    class Response:
        status_code = status
        def json(self):
            raise AssertionError('error bodies are not interpreted or exposed')
    def get(*a, **kw):
        calls.append(kw); return Response()
    monkeypatch.setattr(oa.requests, 'get', get)
    body, reason = oa._research_get({}, url=oa._WORKS_API)
    assert body is None and reason == ('rate_limited' if status == 429 else 'http_error')
    assert len(calls) == 1


def test_transport_exception_is_sanitized(monkeypatch):
    def get(*a, **kw):
        raise requests.Timeout('secret API token and private request body')
    monkeypatch.setattr(oa.requests, 'get', get)
    assert oa._research_get({}, url=oa._WORKS_API) == (None, 'request_failed')


def test_refresh_cli_patch_and_explicit_atomic_apply_leave_legacy_cache_intact(monkeypatch, tmp_path):
    fixture_transport(monkeypatch)
    monkeypatch.setattr(oa, '_load_dotenv', lambda: None)
    source = tmp_path / 'corpus.json'; patch = tmp_path / 'patch.json'; output = tmp_path / 'new.json'
    source.write_text(json.dumps([record()])); before = source.read_bytes()
    assert oa._cli(['refresh-research', '--input', str(source), '--out', str(patch), '--limit', '1']) == 0
    assert source.read_bytes() == before
    assert oa._cli(['apply-research', '--input', str(source), '--patch', str(patch), '--out', str(output)]) == 0
    assert source.read_bytes() == before
    assert json.loads(output.read_text())[0]['metadata']['research_snapshot']['works'][0]['title'] == 'Full parser study 1'
    with pytest.raises(SystemExit):
        oa._cli(['apply-research', '--input', str(source), '--patch', str(patch), '--out', str(source)])
    with pytest.raises(SystemExit):
        oa._cli(['apply-research', '--input', str(source), '--patch', str(patch), '--out', str(output)])
    assert source.read_bytes() == before
    saved = json.loads(output.read_text())[0]
    assert saved['metadata']['recent_works'] == [{'title': 'Full parser study 1', 'year': 2026}]


def test_cli_bounds_and_existing_output_rejected_before_network(monkeypatch, tmp_path):
    monkeypatch.setattr(oa, '_load_dotenv', lambda: None)
    monkeypatch.setattr(oa, '_research_get', lambda *a, **kw: pytest.fail('must not call API'))
    source = tmp_path / 'corpus.json'; source.write_text(json.dumps([record()]))
    for extra in [['--out', str(source), '--limit', '1'], ['--out', str(tmp_path / 'x'), '--limit', '26']]:
        with pytest.raises(SystemExit):
            oa._cli(['refresh-research', '--input', str(source), *extra])


def test_shared_id_different_people_cannot_gain_new_snapshot(monkeypatch):
    monkeypatch.setattr(oa, '_research_get', lambda *a, **kw: pytest.fail('known collision must not fetch'))
    records = [record(), record(name='Other Lee')]
    patch = oa.harvest_research_snapshots(records, now=NOW)
    assert all(p['research_refresh']['reason'] == 'identity_revoked' for p in patch.values())
    assert oa.apply_research_refresh(records, patch, now=NOW) == 2
    assert all(research_context_for(r, now=NOW)['status'] == 'unavailable' for r in records)


@pytest.mark.parametrize('value', [None, [], {'reason': []}, {'status': []}, {'checked_at': []}])
def test_malformed_patch_attempt_never_throws_or_changes_current_record(monkeypatch, value):
    fixture_transport(monkeypatch)
    records = [record()]; before = deepcopy(records)
    patch = oa.harvest_research_snapshots(records, now=NOW)
    entry = next(iter(patch.values()))
    if type(value) is dict:
        entry['research_refresh'].update(value)
    else:
        entry['research_refresh'] = value
    assert oa.apply_research_refresh(records, patch, now=NOW) == 0
    assert records == before


def test_complete_titles_canonicalize_whitespace_without_truncation(monkeypatch):
    fixture_transport(monkeypatch, works=[work(display_name='  A study\nwith\tunicode 中文 ' + 'long ' * 45)])
    patch = oa.harvest_research_snapshots([record()], now=NOW)
    title = next(iter(patch.values()))['research_snapshot']['works'][0]['title']
    assert title == 'A study with unicode 中文 ' + ('long ' * 45).strip()
    assert len(title) > oa._TITLE_CAP


def carried_record(monkeypatch):
    fixture_transport(monkeypatch)
    records = [record()]
    old_time = NOW.replace(year=2000)
    oa.apply_research_refresh(records, oa.harvest_research_snapshots(records, now=old_time), now=old_time)
    return records[0]


def test_rescrape_preserves_bound_success_and_private_attempt_without_renewal(monkeypatch):
    from src.collectors.uiuc_faculty import _carry_forward_enrichment

    existing = carried_record(monkeypatch)
    incoming = {k: v for k, v in record().items() if k != 'metadata'}
    before = deepcopy(existing)
    _carry_forward_enrichment(existing, incoming)
    assert incoming['metadata']['research_snapshot'] == existing['metadata']['research_snapshot']
    assert incoming['metadata']['research_refresh'] == existing['metadata']['research_refresh']
    assert research_context_for(incoming, now=NOW)['status'] == 'stale'
    incoming['metadata']['research_snapshot']['works'][0]['title'] = 'edited copy'
    assert existing == before


@pytest.mark.parametrize('field,value', [('pi_name', 'Other Lee'), ('school', 'uw'), ('source_url', 'https://example.edu/other')])
def test_rescrape_changed_person_or_source_cannot_carry_snapshot_or_legacy_titles(monkeypatch, field, value):
    from src.collectors.uiuc_faculty import _carry_forward_enrichment

    existing = carried_record(monkeypatch)
    incoming = {k: v for k, v in record().items() if k != 'metadata'}
    incoming[field] = value
    _carry_forward_enrichment(existing, incoming)
    assert 'research_snapshot' not in incoming.get('metadata', {})
    assert 'research_refresh' not in incoming.get('metadata', {})
    assert 'recent_works' not in incoming.get('metadata', {})


@pytest.mark.parametrize('field,value', [('publication_author_id', B), ('works_gate', 4), ('publication_attribution_status', None)])
def test_rescrape_explicit_rebound_or_revoked_author_is_not_overwritten(monkeypatch, field, value):
    from src.collectors.uiuc_faculty import _carry_forward_enrichment

    existing = carried_record(monkeypatch)
    incoming = record(); incoming['metadata'] = {field: value}
    _carry_forward_enrichment(existing, incoming)
    assert incoming['metadata'][field] == value
    assert 'research_snapshot' not in incoming['metadata']
    assert 'recent_works' not in incoming['metadata']


def test_rescrape_does_not_revive_previously_revoked_identity_or_replace_explicit_new_works(monkeypatch):
    from src.collectors.uiuc_faculty import _carry_forward_enrichment

    existing = carried_record(monkeypatch)
    existing['metadata'].pop('publication_attribution_status')
    incoming = record(); incoming.pop('metadata')
    _carry_forward_enrichment(existing, incoming)
    assert 'research_snapshot' not in incoming.get('metadata', {})
    existing = carried_record(monkeypatch)
    incoming = record(); incoming['metadata'] = {'recent_works': []}
    _carry_forward_enrichment(existing, incoming)
    assert incoming['metadata'] == {'recent_works': []}


def test_successful_empty_snapshot_survives_rescrape(monkeypatch):
    from src.collectors.uiuc_faculty import _carry_forward_enrichment

    fixture_transport(monkeypatch, works=[])
    existing = record(); old_time = NOW.replace(year=2000)
    oa.apply_research_refresh([existing], oa.harvest_research_snapshots([existing], now=old_time), now=old_time)
    incoming = record(); incoming.pop('metadata')
    _carry_forward_enrichment(existing, incoming)
    assert incoming['metadata']['research_snapshot']['works'] == []
    assert incoming['metadata']['recent_works'] == []


@pytest.mark.parametrize('has_snapshot', [False, True])
def test_legacy_cache_cannot_revive_explicitly_revoked_author(monkeypatch, has_snapshot):
    fixture_transport(monkeypatch)
    records = [record()]
    good = oa.harvest_research_snapshots(records, now=NOW)
    if has_snapshot:
        oa.apply_research_refresh(records, good, now=NOW)
    revoked = deepcopy(good); entry = next(iter(revoked.values()))
    entry.pop('research_snapshot')
    entry['research_refresh'].update(status='failed', reason='identity_revoked')
    assert oa.apply_research_refresh(records, revoked, now=NOW) == 1
    before = deepcopy(records)
    cache = {oa._person_key(records[0]): {'author_id': A, 'works': [{'title': 'Old cached paper', 'year': 2025}]}}
    assert oa.apply_works(records, cache) == 0
    assert records == before
    assert research_context_for(records[0], now=NOW)['status'] == 'unavailable'


@pytest.mark.parametrize('empty', [False, True])
def test_legacy_cache_cannot_replace_a_new_snapshot_success(monkeypatch, empty):
    fixture_transport(monkeypatch, works=[] if empty else [work()])
    records = [record()]; oa.apply_research_refresh(records, oa.harvest_research_snapshots(records, now=NOW), now=NOW)
    before = deepcopy(records)
    cache = {oa._person_key(records[0]): {'author_id': B, 'works': [
        {'title': f'Cached different-author paper {i}', 'year': 2025} for i in range(3)]}}
    assert oa.apply_works(records, cache) == 0
    assert records == before


def test_ordinary_legacy_cache_still_works_after_a_network_failure_without_snapshot(monkeypatch):
    fixture_transport(monkeypatch, error='request_failed')
    records = [record()]; records[0]['metadata']['recent_works'] = []
    oa.apply_research_refresh(records, oa.harvest_research_snapshots(records, now=NOW), now=NOW)
    cache = {oa._person_key(records[0]): {'author_id': A, 'works': [{'title': 'Legacy own paper', 'year': 2025}]}}
    assert oa.apply_works(records, cache) == 1
    assert records[0]['metadata']['recent_works'][0]['title'] == 'Legacy own paper'


@pytest.mark.parametrize('status,reason', [('failed', 'identity_revoked'), ('failed', 'request_failed'),
                                         ('incomplete', 'incomplete_page'), ('success', None)])
@pytest.mark.parametrize('attempt_present', [False, True])
def test_all_patch_states_cannot_go_back_before_newer_success(monkeypatch, status, reason, attempt_present):
    fixture_transport(monkeypatch)
    records = [record()]
    newer = NOW.replace(day=27)
    oa.apply_research_refresh(records, oa.harvest_research_snapshots(records, now=newer), now=newer)
    if not attempt_present:
        records[0]['metadata'].pop('research_refresh')
    old = oa.harvest_research_snapshots([record()], now=NOW)
    entry = next(iter(old.values())); entry['research_refresh'].update(status=status, reason=reason)
    if status != 'success':
        entry.pop('research_snapshot')
    before = deepcopy(records)
    assert oa.apply_research_refresh(records, old, now=newer) == 0
    assert records == before
    assert research_context_for(records[0], now=newer)['status'] == 'available'


@pytest.mark.parametrize('status,reason', [('failed', 'request_failed'), ('incomplete', 'incomplete_page'), ('success', None)])
def test_attempt_time_is_monotonic_after_a_newer_failure(monkeypatch, status, reason):
    fixture_transport(monkeypatch)
    records = [record()]
    older = oa.harvest_research_snapshots(records, now=NOW)
    middle = NOW.replace(day=27); latest = NOW.replace(day=28)
    oa.apply_research_refresh(records, older, now=NOW)
    newest = deepcopy(older); newest_entry = next(iter(newest.values())); newest_entry.pop('research_snapshot')
    newest_entry['research_refresh'].update(checked_at=latest.isoformat().replace('+00:00', 'Z'), status='failed', reason='request_failed')
    assert oa.apply_research_refresh(records, newest, now=latest) == 1
    delayed = oa.harvest_research_snapshots([record()], now=middle)
    entry = next(iter(delayed.values())); entry['research_refresh'].update(status=status, reason=reason)
    if status != 'success':
        entry.pop('research_snapshot')
    before = deepcopy(records)
    assert oa.apply_research_refresh(records, delayed, now=latest) == 0
    assert records == before


def test_refresh_accepts_mixed_corpus_and_ignores_nullable_programs(monkeypatch):
    calls = fixture_transport(monkeypatch)
    rows = [record(), {'id': 'national-program', 'school': None, 'pi_name': None,
                       'source_type': 'nsf_reu', 'metadata': {}, 'url': 'https://example.edu/program'}]
    before = deepcopy(rows)
    patch = oa.harvest_research_snapshots(rows, schools=['uiuc'], limit=1, now=NOW)
    assert len(patch) == 1 and len(calls) == 2
    assert rows == before
    assert oa.apply_research_refresh(rows, patch, now=NOW) == 1
    assert rows[1] == before[1]


@pytest.mark.parametrize('change', [{'pi_name': None}, {'pi_name': []}, {'pi_name': ''},
                                    {'source_url': 'javascript:bad'}])
def test_malformed_selected_faculty_refuses_before_network(monkeypatch, change):
    monkeypatch.setattr(oa, '_research_get', lambda *a, **kw: pytest.fail('malformed selected target must not fetch'))
    row = {**record(), 'source_type': 'faculty_research', **change}
    with pytest.raises(ValueError, match='invalid_research_target'):
        oa.harvest_research_snapshots([row], schools=['uiuc'], now=NOW)


def test_out_of_scope_malformed_identity_does_not_block_selected_school(monkeypatch):
    calls = fixture_transport(monkeypatch)
    other = {**record(), 'school': 'uw', 'pi_name': [], 'source_type': 'faculty_research'}
    patch = oa.harvest_research_snapshots([other, record()], schools=['uiuc'], now=NOW)
    assert len(patch) == 1 and len(calls) == 2


def test_duplicate_record_ids_refuse_before_network(monkeypatch):
    monkeypatch.setattr(oa, '_research_get', lambda *a, **kw: pytest.fail('duplicate input IDs must not fetch'))
    rows = [{**record(), 'id': 'same'}, {**record(B, 'Other Person'), 'id': 'same'}]
    with pytest.raises(ValueError, match='duplicate_research_record_id'):
        oa.harvest_research_snapshots(rows, now=NOW)


def test_duplicate_record_ids_also_refuse_candidate_apply(monkeypatch):
    fixture_transport(monkeypatch)
    source = {**record(), 'id': 'same'}
    patch = oa.harvest_research_snapshots([source], now=NOW)
    rows = [deepcopy(source), {**record(B, 'Other Person'), 'id': 'same'}]
    before = deepcopy(rows)
    with pytest.raises(ValueError, match='duplicate_research_record_id'):
        oa.apply_research_refresh(rows, patch, now=NOW)
    assert rows == before
