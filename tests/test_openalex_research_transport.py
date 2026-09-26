"""B47 collector contracts; all HTTP responses are injected, never live."""
import json
from copy import deepcopy
from datetime import timedelta
from email.utils import format_datetime

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.collectors import openalex_enrich as oa
from tests.test_openalex_research_refresh import NOW, A, author, record


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(oa.requests, 'get', lambda *args, **kwargs: pytest.fail('unexpected default HTTP request'))
    monkeypatch.delenv('OPENALEX_API_KEY', raising=False)


def identified(n):
    return {**record(f'https://openalex.org/A{1000 + n}', f'Pat Person{n}'), 'id': f'faculty-{n}'}


def injected_reader(calls):
    def read(params, *, url):
        calls.append((deepcopy(params), url))
        if url == oa._WORKS_API:
            return {'results': [], 'meta': {'count': 0}}, None
        aid = url.rsplit('/', 1)[-1]
        n = int(aid[1:]) - 1000
        return author(f'https://openalex.org/{aid}', f'Pat Person{n}'), None
    return read


def test_all_targets_reaches_beyond_legacy_prefix_and_keeps_mixed_programs():
    faculty = [identified(n) for n in range(60)]
    corpus = [{'id': 'national', 'school': None, 'pi_name': None, 'metadata': {}}] + faculty
    assert oa.research_targets(corpus) == faculty
    assert oa._research_targets(corpus, limit=25) == faculty[:25]
    assert oa.research_targets(corpus, schools=['uw']) == []
    invalid = identified(99); invalid.update(pi_name=None, source_type='faculty_research')
    # Full queue planning validates all eligible targets; old limited calls keep
    # their original stopping boundary rather than suddenly rejecting late rows.
    with pytest.raises(ValueError, match='invalid_research_target'):
        oa.research_targets(corpus + [invalid])
    assert oa._research_targets(corpus + [invalid], limit=1) == faculty[:1]


def test_explicit_ids_keep_queue_order_and_do_not_silently_take_first_ten():
    records = [identified(n) for n in range(60)]
    before = deepcopy(records); calls = []
    selected = [f'faculty-{n}' for n in range(59, 34, -1)]
    patch = oa.harvest_research_snapshots(records, selected_ids=selected, request=injected_reader(calls), now=NOW)
    assert records == before
    assert len(patch) == 25 and len(calls) == 26
    assert [url.rsplit('/', 1)[-1] for _, url in calls[:-1]] == [f'A{1000 + n}' for n in range(59, 34, -1)]
    assert all(entry['research_snapshot']['works'] == [] for entry in patch.values())
    assert calls[-1][0]['per_page'] == 100
    assert list(patch) == [oa._person_key(records[n]) for n in range(59, 34, -1)]


@pytest.mark.parametrize('selected', [None, 'faculty-0', ('faculty-0',), [1], [''], [' '], ['faculty-0'] * 2,
                                      [f'faculty-{n}' for n in range(26)], ['missing'], ['faculty-0', 'missing']])
def test_malformed_or_missing_selection_never_falls_back_or_fetches(selected):
    if selected is None:
        selected = [None]
    with pytest.raises(ValueError):
        oa.harvest_research_snapshots([identified(0)], selected_ids=selected, request=lambda *a, **k: pytest.fail('network'), now=NOW)


def test_empty_explicit_selection_is_no_work_not_default_batch():
    assert oa.harvest_research_snapshots([identified(0)], selected_ids=[], now=NOW) == {}


@pytest.mark.parametrize('change,schools', [({'school': None}, None), ({'pi_name': None}, None),
                                           ({'metadata': {}}, None), ({}, ['uw'])])
def test_ineligible_selected_id_is_rejected_before_any_request(change, schools):
    records = [identified(0), {**identified(1), **change}]
    with pytest.raises(ValueError):
        oa.harvest_research_snapshots(records, selected_ids=['faculty-0', 'faculty-1'], schools=schools,
                                     request=lambda *a, **k: pytest.fail('partial batch fetched'), now=NOW)


def test_duplicate_unselected_ids_still_reject_full_corpus():
    selected = identified(0)
    duplicate = {'id': 'national', 'school': None, 'metadata': {}}
    with pytest.raises(ValueError, match='duplicate_research_record_id'):
        oa.harvest_research_snapshots([selected, duplicate, deepcopy(duplicate)], selected_ids=[selected['id']], now=NOW)


def test_unselected_other_school_author_collision_blocks_selected_author():
    selected = identified(0)
    collision = {**record(selected['metadata']['publication_author_id'], 'Other Stranger'), 'school': 'uw', 'id': 'other'}
    patch = oa.harvest_research_snapshots([selected, collision], schools=['uiuc'], selected_ids=[selected['id']], now=NOW)
    assert len(patch) == 1
    assert next(iter(patch.values()))['research_refresh']['reason'] == 'identity_revoked'


@pytest.mark.parametrize('raise_at', [1, 2])
def test_budget_deferral_propagates_without_patch_or_corruption(raise_at):
    class Deferred(Exception):
        pass
    records = [identified(0)]; before = deepcopy(records); calls = []
    read = injected_reader(calls)
    def bounded(params, *, url):
        if len(calls) + 1 == raise_at:
            raise Deferred('budget')
        return read(params, url=url)
    with pytest.raises(Deferred, match='budget'):
        oa.harvest_research_snapshots(records, selected_ids=['faculty-0'], request=bounded, now=NOW)
    assert records == before and len(calls) == raise_at - 1


def test_works_direct_injection_does_not_use_default_transport():
    calls = []
    result = oa.research_works_for_authors({A: {'Computer Science'}}, request=injected_reader(calls))
    assert result[A] == {'status': 'success', 'reason': None, 'works': []}
    assert len(calls) == 1


class Response:
    def __init__(self, status=200, data=None, headers=None, body=None, chunks=None):
        self.status_code = status
        self.data = {} if data is None else data
        self.headers = {} if headers is None else headers
        self.body = json.dumps(self.data).encode() if body is None else body
        self.chunks = chunks
        self.read_calls = 0
        self.close_calls = 0

    def iter_content(self, chunk_size):
        self.read_calls += 1
        return iter([self.body] if self.chunks is None else self.chunks)

    def close(self):
        self.close_calls += 1


class Session:
    def __init__(self, response=None, error=None):
        self.response = response or Response()
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response


EMPTY = {'http_status': None, 'retry_after_seconds': None, 'credits_used': None, 'remaining': None, 'reset_seconds': None}


def test_http_one_bounded_call_authorization_and_numeric_receipt(monkeypatch):
    monkeypatch.setenv('OPENALEX_API_KEY', 'private-secret')
    session = Session(Response(data={'results': []}, headers={'x-ratelimit-credits-used': '0.25',
        'X-RateLimit-Remaining': '4.5', 'X-RateLimit-Reset': '20', 'Retry-After': '15', 'Private': 'secret'}))
    params = {'select': 'id'}
    data, error, telemetry = oa.research_http_read(params, url=oa._WORKS_API, timeout=0.125, session=session)
    assert data == {'results': []} and error is None
    assert telemetry == {'http_status': 200, 'retry_after_seconds': 15.0, 'credits_used': 0.25, 'remaining': 4.5, 'reset_seconds': 20.0}
    assert session.calls == [(oa._WORKS_API, {'params': {'select': 'id'},
        'headers': {**oa._HEADERS, 'Authorization': 'Bearer private-secret'}, 'timeout': 0.125, 'allow_redirects': False, 'stream': True})]
    assert params == {'select': 'id'} and 'secret' not in repr(telemetry)
    assert session.response.close_calls == 1


@pytest.mark.parametrize('url', [oa._WORKS_API, oa._API + '/A123'])
def test_http_missing_credit_headers_are_unknown_not_free(url):
    session = Session()
    assert oa.research_http_read({}, url=url, session=session) == ({}, None, {**EMPTY, 'http_status': 200})
    assert 'Authorization' not in session.calls[0][1]['headers']


@pytest.mark.parametrize('url', ['http://api.openalex.org/works', 'https://api.openalex.org:443/works',
    'https://api.openalex.org.evil.test/works', 'https://api.openalex.org@evil.test/works',
    'https://user@api.openalex.org/works', 'https://api.openalex.org/works?api_key=secret',
    'https://api.openalex.org/works#x', 'https://api.openalex.org/works/',
    'https://api.openalex.org/authors', 'https://api.openalex.org/authors/A0',
    'https://api.openalex.org/authors/A123/works', 'https://api.openalex.org/authors/A1%2Fworks',
    'https://api.openalex.org/authors/A1/../works', 'https://api.openalex.org/works\\evil',
    'https://127.0.0.1/works', None, {}, 'https://api.openalex.org/works\n'])
def test_http_rejects_nonfixed_target_without_request(url):
    session = Session()
    with pytest.raises(ValueError, match='invalid_research_url'):
        oa.research_http_read({}, url=url, session=session)
    assert session.calls == []


@pytest.mark.parametrize('timeout', [0, -1, 20.001, float('nan'), float('inf'), True, '20', None, 10**1000])
def test_http_invalid_timeout_never_fetches(timeout):
    session = Session()
    with pytest.raises(ValueError, match='invalid_research_timeout'):
        oa.research_http_read({}, url=oa._WORKS_API, timeout=timeout, session=session)
    assert session.calls == []


@pytest.mark.parametrize('params', [None, [], {1: 'a'}, {'api_key': 'secret'}, {'API_KEY': 'secret'}])
def test_http_never_allows_query_credentials(params):
    session = Session()
    with pytest.raises(ValueError, match='invalid_research_params'):
        oa.research_http_read(params, url=oa._WORKS_API, session=session)
    assert session.calls == []


@pytest.mark.parametrize('retry', [Retry(total=3), Retry(total=None, connect=2)])
def test_real_session_adapter_with_retries_is_rejected_without_request(retry, monkeypatch):
    with requests.Session() as session:
        session.mount('https://', HTTPAdapter(max_retries=retry))
        monkeypatch.setattr(session, 'get', lambda *a, **k: pytest.fail('hidden retries enabled'))
        with pytest.raises(ValueError, match='research_transport_retries'):
            oa.research_http_read({}, url=oa._WORKS_API, session=session)


def test_default_real_session_with_zero_retries_is_usable(monkeypatch):
    with requests.Session() as session:
        calls = []
        monkeypatch.setattr(session, 'get', lambda *a, **k: (calls.append(k), Response())[1])
        assert oa.research_http_read({}, url=oa._WORKS_API, session=session)[1] is None
        assert len(calls) == 1 and calls[0]['allow_redirects'] is False


@pytest.mark.parametrize('status,reason', [(429, 'rate_limited'), (500, 'server_error'), (503, 'server_error'),
    (401, 'client_error'), (404, 'client_error'), (302, 'client_error'), (204, 'client_error')])
def test_http_remote_error_classification_no_retry_redirect_or_error_body(status, reason):
    response = Response(status=status, headers={'Location': 'https://evil.test/private'}, body=b'private error body')
    session = Session(response)
    assert oa.research_http_read({}, url=oa._WORKS_API, session=session) == (None, reason, {**EMPTY, 'http_status': status})
    assert len(session.calls) == 1 and response.read_calls == 0 and response.close_calls == 1
    assert session.calls[0][1]['allow_redirects'] is False


@pytest.mark.parametrize('response', [Response(data=[]), Response(data='private body'), Response(body=b'{private-invalid-json')])
def test_http_invalid_json_is_not_empty_success(response):
    session = Session(response)
    assert oa.research_http_read({}, url=oa._WORKS_API, session=session) == (None, 'invalid_response', {**EMPTY, 'http_status': 200})
    assert len(session.calls) == 1


@pytest.mark.parametrize('error', [requests.Timeout('token=private'), requests.ConnectionError('private endpoint'),
                                  requests.TooManyRedirects('private')])
def test_http_request_failure_has_no_leaked_message_or_fake_accounting(error):
    session = Session(error=error)
    assert oa.research_http_read({}, url=oa._WORKS_API, session=session) == (None, 'request_failed', EMPTY)
    assert len(session.calls) == 1


@pytest.mark.parametrize('bad', ['NaN', 'Infinity', '-1', 'secret', '1e9999', str(2**53), '', True, [], {}, '0' * 101])
def test_http_malformed_accounting_headers_are_unknown(bad):
    response = Response(headers=dict.fromkeys(['Retry-After', 'X-RateLimit-Credits-Used', 'X-RateLimit-Remaining', 'X-RateLimit-Reset'], bad))
    assert oa.research_http_read({}, url=oa._WORKS_API, session=Session(response))[2] == {**EMPTY, 'http_status': 200}


@pytest.mark.parametrize('delta,expected', [(90, 90.0), (-90, 0.0)])
def test_retry_after_http_date_becomes_numeric_delay(monkeypatch, delta, expected):
    monkeypatch.setattr(oa.time, 'time', lambda: NOW.timestamp())
    response = Response(status=429, headers={'Retry-After': format_datetime(NOW + timedelta(seconds=delta), usegmt=True)})
    assert oa.research_http_read({}, url=oa._WORKS_API, session=Session(response))[2]['retry_after_seconds'] == expected


@pytest.mark.parametrize('reason', ['server_error', 'client_error'])
def test_new_failure_reasons_preserve_last_success_and_reject_time_regression(reason):
    records = [identified(0)]; calls = []
    good = oa.harvest_research_snapshots(records, selected_ids=['faculty-0'], request=injected_reader(calls), now=NOW)
    assert oa.apply_research_refresh(records, good, now=NOW) == 1
    old = deepcopy(records[0]['metadata']['research_snapshot'])
    next_time = NOW + timedelta(minutes=5)
    failure = oa.harvest_research_snapshots(records, selected_ids=['faculty-0'], request=lambda *a, **k: (None, reason), now=next_time)
    assert oa.apply_research_refresh(records, failure, now=next_time) == 1
    assert records[0]['metadata']['research_snapshot'] == old
    assert records[0]['metadata']['research_refresh']['reason'] == reason
    before = deepcopy(records)
    assert oa.apply_research_refresh(records, good, now=next_time) == 0
    assert records == before


@pytest.mark.parametrize('extra', [0, 1])
def test_decoded_response_byte_boundary_and_close(extra):
    # Valid JSON reaches the exact decoded-byte cap, despite a lying header.
    body = b'{"text":"' + b'x' * (oa._RESEARCH_RESPONSE_BYTES - 11 + extra) + b'"}'
    assert len(body) == oa._RESEARCH_RESPONSE_BYTES + extra
    response = Response(headers={'Content-Length': '1'}, chunks=[body[i:i + 8192] for i in range(0, len(body), 8192)])
    data, error, telemetry = oa.research_http_read({}, url=oa._WORKS_API, session=Session(response))
    assert error == ('invalid_response' if extra else None)
    assert (data is None) is bool(extra)
    assert response.close_calls == 1 and telemetry['http_status'] == 200


def test_stream_failure_closes_response_and_retains_received_accounting():
    class Interrupted(Response):
        def iter_content(self, chunk_size):
            yield b'{'
            raise requests.ConnectionError('private key or response body')
    response = Interrupted(headers={'X-RateLimit-Credits-Used': '0.5'})
    data, error, telemetry = oa.research_http_read({}, url=oa._WORKS_API, session=Session(response))
    assert data is None and error == 'request_failed'
    assert telemetry == {**EMPTY, 'http_status': 200, 'credits_used': 0.5}
    assert response.close_calls == 1


def test_stream_deadline_stops_further_reads_without_claiming_forced_socket_cancel(monkeypatch):
    now = [0.0]; delivered = []
    monkeypatch.setattr(oa.time, 'monotonic', lambda: now[0])
    class Slow(Response):
        def iter_content(self, chunk_size):
            delivered.append(1); yield b'{'
            now[0] = 20.1
            delivered.append(2); yield b'"late":1}'
            pytest.fail('must not start another read after deadline')
    response = Slow()
    data, error, telemetry = oa.research_http_read({}, url=oa._WORKS_API, session=Session(response))
    assert data is None and error == 'request_failed'
    assert delivered == [1, 2] and response.close_calls == 1
    assert telemetry['http_status'] == 200


def test_oversize_stream_does_not_consume_later_chunks():
    class Huge(Response):
        def iter_content(self, chunk_size):
            yield b'x' * (oa._RESEARCH_RESPONSE_BYTES + 1)
            pytest.fail('must not consume after over-limit response')
    response = Huge()
    assert oa.research_http_read({}, url=oa._WORKS_API, session=Session(response))[1] == 'invalid_response'
    assert response.close_calls == 1


def test_unexpected_session_error_propagates_and_closes_without_fabricated_result():
    class Broken(Response):
        def iter_content(self, chunk_size):
            raise RuntimeError('unexpected fixture implementation error')
    response = Broken()
    with pytest.raises(RuntimeError):
        oa.research_http_read({}, url=oa._WORKS_API, session=Session(response))
    assert response.close_calls == 1


@pytest.mark.parametrize('invalid_source', ['https://example.edu/profile ', 'https://example.edu/profile#bio', None])
def test_invalid_unselected_source_does_not_block_explicit_valid_target(invalid_source):
    selected = identified(0); unrelated = identified(1)
    unrelated['source_url'] = invalid_source
    corpus = [unrelated, selected]; before = deepcopy(corpus); calls = []
    patch = oa.harvest_research_snapshots(corpus, selected_ids=[selected['id']], request=injected_reader(calls), now=NOW)
    assert list(patch) == [oa._person_key(selected)]
    assert next(iter(patch.values()))['research_refresh']['status'] == 'success'
    assert len(calls) == 2 and corpus == before
    # The same source is still strictly rejected if explicitly selected; this is
    # isolation of unrelated bad rows, not a broader URL authority rule.
    calls.clear()
    with pytest.raises(ValueError, match='invalid_research_target'):
        oa.harvest_research_snapshots(corpus, selected_ids=[selected['id'], unrelated['id']], request=injected_reader(calls), now=NOW)
    assert calls == [] and corpus == before


def test_invalid_unselected_source_cannot_hide_shared_author_collision():
    selected = identified(0)
    unrelated = {**record(selected['metadata']['publication_author_id'], 'Other Stranger'),
                 'id': 'invalid-other', 'source_url': 'https://example.edu/invalid '}
    corpus = [unrelated, selected]; before = deepcopy(corpus)
    patch = oa.harvest_research_snapshots(corpus, selected_ids=[selected['id']], now=NOW)
    assert list(patch) == [oa._person_key(selected)]
    assert next(iter(patch.values()))['research_refresh']['reason'] == 'identity_revoked'
    assert 'research_snapshot' not in next(iter(patch.values())) and corpus == before
