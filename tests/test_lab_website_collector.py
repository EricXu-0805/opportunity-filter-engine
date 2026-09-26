"""No-network tests of the reviewed HTML template, transport and candidate CLI."""
from __future__ import annotations

import json
import socket
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
import requests

from backend.lib.safe_webpush import _NoRedirectSession
from scripts.lab_refresh import main
from src.collectors.lab_website import (
    MAX_LAB_FETCH_BYTES,
    build_lab_candidate,
    collect_lab_snapshot,
    fetch_lab_page,
)
from src.lab_context import lab_context_for
from tests.test_lab_context import NOW, URL, record, sourced_record
from tests.test_ucb_stat_faculty import PROFILE_WITH_INTERESTS_HTML


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected network access')
    monkeypatch.setattr(requests.Session, 'send', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)


def read(html=PROFILE_WITH_INTERESTS_HTML):
    def fetch(url):
        assert url == URL
        return {'requested_url': url, 'source_url': url, 'html': html.encode()}, None
    return fetch


def dns(*addresses):
    return lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, 443)) for address in addresses]


class Response:
    def __init__(self, *, status=200, url=URL, content_type='text/html; charset=utf-8', chunks=None):
        self.status_code = status; self.url = url
        self.headers = {'Content-Type': content_type}; self.closed = False
        self.chunks = [b'<html>complete</html>'] if chunks is None else chunks
    def iter_content(self, chunk_size):
        assert chunk_size == 8192
        yield from self.chunks
    def close(self):
        self.closed = True


class Session:
    def __init__(self, response):
        self.response = response; self.calls = []; self.closed = False; self.endpoint = None
    def factory(self, endpoint):
        self.endpoint = endpoint
        return self
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.closed = True
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def transport(response, **kwargs):
    session = Session(response)
    result = fetch_lab_page(URL, resolver=dns('93.184.216.34'), session_factory=session.factory, **kwargs)
    return result, session


def test_reviewed_existing_template_keeps_whole_research_fields_without_description():
    item = record(); item['description_clean'] = 'UNRELATED LEGACY TEXT'; original = deepcopy(item)
    result = collect_lab_snapshot(item, now=NOW, fetch=read())
    assert result['lab_refresh']['status'] == 'success'
    source = result['lab_snapshot']; sections = source['pages'][0]['sections']
    assert len(sections) == 3
    assert sections[0]['text'] == ('causal inference, econometrics, experimental design,\n    missing data, applications in biomedical and social sciences')
    assert [x['text'] for x in sections[1:]] == ['Causal Inference', 'Nonparametric Inference']
    assert 'UNRELATED' not in json.dumps(source)
    assert item == original
    patched = deepcopy(item); patched['metadata'].update(result)
    assert lab_context_for(patched, now=NOW)['status'] == 'available'


@pytest.mark.parametrize('key,value', [
    ('school', 'uiuc'), ('source', 'user_import'), ('department', 'Department of Mathematics'),
    ('source_type', 'program'), ('url', 'https://statistics.berkeley.edu/people/someone-else'),
    ('source_url', 'https://statistics.berkeley.edu/people/'),
    ('source_url', 'https://statistics.berkeley.edu/people/faculty'),
    ('source_url', 'https://statistics.berkeley.edu.evil.example/people/peng-ding'),
    ('source_url', 'https://personal.example/peng-ding'),
])
def test_unsupported_binding_never_fetches(key, value):
    item = record(); item[key] = value
    def forbidden(_):
        pytest.fail('Invalid binding was fetched')
    result = collect_lab_snapshot(item, now=NOW, fetch=forbidden)
    assert result['lab_refresh']['reason'] == 'unsupported_policy'
    assert 'lab_snapshot' not in result


@pytest.mark.parametrize('name', ['Other Ding', 'Peng X Ding', 'P. Ding', 'Ding', 'Peng'])
def test_wrong_person_and_incomplete_name_rejected_even_when_text_mentions_target(name):
    html = PROFILE_WITH_INTERESTS_HTML.replace('>Peng Ding<', '>' + name + '<')
    html = html.replace('causal inference', 'Peng Ding collaborates here; causal inference')
    result = collect_lab_snapshot(record(), now=NOW, fetch=read(html))
    assert result['lab_refresh']['reason'] == 'identity_mismatch'
    assert 'lab_snapshot' not in result


@pytest.mark.parametrize('transform', [
    lambda s: s + s,
    lambda s: '<div class="views-row">' + s + '</div>',
    lambda s: s.replace('node node--type-faculty', 'node node--type-faculty node--view-mode-teaser'),
    lambda s: s.replace('<h3 class="page--title">', '<div><h3 class="page--title">').replace('</h3>', '</h3></div>'),
    lambda s: s.replace('</article>', '<aside>Peng Ding related profile</aside></article>'),
    lambda s: s.replace('causal inference', '<script>injected</script>causal inference'),
    lambda s: '<title>Access denied</title>' + s,
])
def test_directory_nested_or_denial_templates_do_not_mint_source(transform):
    result = collect_lab_snapshot(record(), now=NOW, fetch=read(transform(PROFILE_WITH_INTERESTS_HTML)))
    assert result['lab_refresh']['status'] == 'failed'
    assert 'lab_snapshot' not in result


def test_same_name_in_directory_does_not_prove_profile_identity():
    html = '<h1>Faculty directory: Peng Ding</h1><p>Research about Python</p>'
    result = collect_lab_snapshot(record(), now=NOW, fetch=read(html))
    assert result['lab_refresh']['reason'] == 'unsupported_template'


@pytest.mark.parametrize('replacement', ['😀' * 4001, 'x' * 4001])
def test_overlong_field_is_rejected_not_truncated(replacement):
    html = PROFILE_WITH_INTERESTS_HTML.replace('causal inference, econometrics, experimental design,', replacement)
    assert collect_lab_snapshot(record(), now=NOW, fetch=read(html))['lab_refresh']['reason'] == 'invalid_snapshot'


def test_missing_fields_never_falls_back_to_general_biography_or_old_description():
    html = '<article class="node node--type-faculty"><h3 class="page--title">Peng Ding</h3><p>Interested in Python.</p></article>'
    assert collect_lab_snapshot(record(), now=NOW, fetch=read(html))['lab_refresh']['reason'] == 'missing_sections'


@pytest.mark.parametrize('error', ['request_failed', 'rate_limited', 'invalid_response', 'PRIVATE URL secret'])
def test_failure_preserves_prior_source_without_refreshing_success_time(error):
    item = sourced_record(now=NOW - timedelta(days=31)); original = deepcopy(item)
    patch = collect_lab_snapshot(item, now=NOW, fetch=lambda _: (None, error))
    assert patch['lab_refresh']['reason'] == (error if error != 'PRIVATE URL secret' else 'request_failed')
    assert 'lab_snapshot' not in patch and item == original
    item['metadata'].update(patch)
    assert lab_context_for(item, now=NOW)['status'] == 'stale'
    assert item['metadata']['lab_snapshot']['checked_at'] == original['metadata']['lab_snapshot']['checked_at']


def test_wrong_person_revokes_retained_source_without_destroying_internal_history():
    item = sourced_record()
    patch = collect_lab_snapshot(item, now=NOW, fetch=read(PROFILE_WITH_INTERESTS_HTML.replace('>Peng Ding<', '>Other Ding<')))
    item['metadata'].update(patch)
    assert 'lab_snapshot' in item['metadata']
    assert lab_context_for(item, now=NOW)['status'] == 'unavailable'


def test_transport_one_get_closes_stream_and_uses_only_resolved_public_ip():
    response = Response(); (page, error), session = transport(response)
    assert error is None and page['html'] == b'<html>complete</html>'
    assert session.endpoint.addresses == ('93.184.216.34',)
    assert len(session.calls) == 1
    assert session.calls[0][1]['allow_redirects'] is False and session.calls[0][1]['stream'] is True
    assert session.calls[0][1]['timeout'] == 15
    assert response.closed and session.closed


def test_actual_pinned_session_disables_proxy_retries_and_preserves_tls_identity(monkeypatch):
    # Exercise real session+adapter construction, intercept before any socket.
    captured = {}; response = Response()
    def get(self, url, **kwargs):
        captured['trust_env'] = self.trust_env; captured['redirects'] = self.max_redirects
        adapter = self.get_adapter(url)
        request = requests.Request('GET', url).prepare()
        host, tls = adapter.build_connection_pool_key_attributes(request, verify=True)
        adapter.add_headers(request)
        captured.update(host=host, tls=tls, headers=dict(request.headers), retries=adapter.max_retries.total)
        return response
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:1')
    monkeypatch.setattr(_NoRedirectSession, 'get', get)
    page, error = fetch_lab_page(URL, resolver=dns('93.184.216.34'))
    assert error is None and page and response.closed
    assert captured['trust_env'] is False and captured['redirects'] == 0 and captured['retries'] == 0
    assert captured['host'] == {'scheme': 'https', 'host': '93.184.216.34', 'port': 443}
    assert captured['tls']['server_hostname'] == 'statistics.berkeley.edu'
    assert captured['tls']['assert_hostname'] == 'statistics.berkeley.edu'
    assert captured['headers']['Host'] == 'statistics.berkeley.edu'


@pytest.mark.parametrize('addresses', [('127.0.0.1',), ('10.0.0.1',), ('169.254.169.254',), ('93.184.216.34', '192.168.0.1')])
def test_ssrf_and_mixed_dns_fail_before_session(addresses):
    def forbidden(_):
        pytest.fail('Unsafe DNS reached session')
    assert fetch_lab_page(URL, resolver=dns(*addresses), session_factory=forbidden) == (None, 'unsafe_url')


@pytest.mark.parametrize('url', ['http://statistics.berkeley.edu/people/peng-ding', 'https://127.0.0.1/', URL+'?x=1', URL+'#x', 'https://user:pass@statistics.berkeley.edu/people/peng-ding', 'https://statistics.berkeley.edu:443/people/peng-ding'])
def test_noncanonical_url_rejected_before_dns(url):
    assert fetch_lab_page(url) == (None, 'unsafe_url')


@pytest.mark.parametrize('status,error', [(301,'redirect'), (302,'redirect'), (307,'redirect'), (308,'redirect'), (401,'http_error'), (429,'rate_limited'), (500,'http_error')])
def test_http_failures_not_followed_or_retried(status, error):
    response = Response(status=status)
    result, session = transport(response)
    assert result == (None, error) and len(session.calls) == 1
    assert response.closed and session.closed


def test_redirect_even_to_same_host_and_trailing_slash_is_rejected():
    response = Response(url=URL+'/')
    result, session = transport(response)
    assert result == (None, 'redirect') and len(session.calls) == 1 and response.closed


@pytest.mark.parametrize('response,error', [(Response(content_type='application/json'),'invalid_content_type'), (Response(chunks=['not bytes']),'invalid_response'), (Response(status='200'),'invalid_response')])
def test_unusable_response_is_explicit_and_closed(response, error):
    result, session = transport(response)
    assert result == (None, error) and response.closed and session.closed


def test_exact_byte_boundary_and_stream_overflow_are_distinct():
    response = Response(chunks=[b'x'*MAX_LAB_FETCH_BYTES])
    (page, error), _ = transport(response)
    assert error is None and len(page['html']) == MAX_LAB_FETCH_BYTES
    response = Response(chunks=[b'x'*MAX_LAB_FETCH_BYTES, b'!'])
    result, _ = transport(response)
    assert result == (None, 'response_too_large') and response.closed


def test_stream_timeout_stops_further_reads_and_closes():
    ticks = iter([0, 0, 0, 16])
    response = Response(chunks=[b'data', b'never consumed'])
    result, session = transport(response, clock=lambda: next(ticks))
    assert result == (None, 'request_failed') and response.closed and session.closed


def test_connection_exception_is_sanitized_and_never_retried():
    result, session = transport(requests.Timeout('secret hostname'))
    assert result == (None, 'request_failed') and len(session.calls) == 1 and session.closed


def test_candidate_is_explicit_detached_and_does_not_mutate_corpus():
    item = record(); other = {'id':'program', 'metadata':{}, 'department':None}; records = [item, other]; before=deepcopy(records)
    value = build_lab_candidate(records, [item['id']], now=NOW, fetch=read())
    assert value['kind'] == 'lab_context_candidate' and len(value['results']) == 1
    assert value['results'][0]['record_id'] == item['id']
    assert value['results'][0]['patch']['lab_refresh']['status'] == 'success'
    assert records == before
    value['results'][0]['patch']['lab_snapshot']['identity_name'] = 'changed'
    assert records == before


@pytest.mark.parametrize('ids', [[], ['missing'], ['faculty-ucb-stat-fixture']*2, [str(i) for i in range(11)]])
def test_invalid_selection_fails_before_fetch(ids):
    def forbidden(_):
        pytest.fail('Invalid selection fetched')
    with pytest.raises(ValueError):
        build_lab_candidate([record()], ids, now=NOW, fetch=forbidden)


def test_global_duplicate_ids_fail_before_fetch():
    with pytest.raises(ValueError, match='record_ids'):
        build_lab_candidate([record(), record()], [record()['id']], now=NOW, fetch=lambda _: pytest.fail())


@pytest.mark.parametrize('key', ['lab_snapshot', 'lab_refresh'])
def test_candidate_preflight_rejects_time_regression_before_any_read(key):
    item=record(); item['metadata'][key]={'checked_at':(NOW+timedelta(seconds=1)).isoformat().replace('+00:00','Z')}
    with pytest.raises(ValueError, match='time_regression'):
        build_lab_candidate([item], [item['id']], now=NOW, fetch=lambda _: pytest.fail())


def test_in_memory_target_or_other_record_changed_while_fetching_is_rejected():
    for changed_target in (True, False):
        item=record(); other={'id':'other', 'metadata':{}}; records=[item,other]
        def changing(url, item=item, changed_target=changed_target, other=other):
            (item if changed_target else other)['description_clean'] = 'changed during fetch'
            return read()(url)
        with pytest.raises(ValueError, match='changed_during_fetch'):
            build_lab_candidate(records, [item['id']], now=NOW, fetch=changing)


def args(source, output):
    return ['--input',str(source),'--record-id',record()['id'],'--out',str(output)]


def test_cli_writes_review_candidate_but_never_changes_input(tmp_path):
    source=tmp_path/'source.json'; output=tmp_path/'candidate.json'
    source.write_text(json.dumps([record()]), encoding='utf-8'); before=source.read_bytes()
    assert main(args(source,output), now=NOW, fetch=read()) == 0
    assert source.read_bytes() == before
    assert json.loads(output.read_text())['results'][0]['patch']['lab_refresh']['status'] == 'success'
    assert not list(tmp_path.glob('.lab-candidate-*'))


@pytest.mark.parametrize('kind', ['same','existing','symlink','hardlink','missing_parent'])
def test_cli_output_conflict_rejected_before_read(kind,tmp_path):
    source=tmp_path/'source.json'; source.write_text(json.dumps([record()]))
    output=tmp_path/'candidate.json'
    if kind == 'same': output=source
    elif kind == 'existing': output.write_text('keep me')
    elif kind == 'symlink': output.symlink_to(source)
    elif kind == 'hardlink': output.hardlink_to(source)
    else: output=tmp_path/'missing'/'candidate.json'
    before=source.read_bytes()
    assert main(args(source,output), now=NOW, fetch=lambda _: pytest.fail('No HTTP expected')) == 1
    assert source.read_bytes() == before


def test_cli_checks_input_bytes_again_after_fetch_and_leaves_no_candidate(tmp_path):
    source=tmp_path/'source.json'; output=tmp_path/'candidate.json'; source.write_text(json.dumps([record()]))
    def changed(url):
        source.write_text('[]')
        return read()(url)
    assert main(args(source,output), now=NOW, fetch=changed) == 1
    assert source.read_text() == '[]' and not output.exists()


def test_cli_output_race_cannot_overwrite_other_writer(tmp_path, monkeypatch):
    source=tmp_path/'source.json'; output=tmp_path/'candidate.json'; source.write_text(json.dumps([record()]))
    import scripts.lab_refresh as cli
    original_link=cli.os.link
    def raced(src,dst):
        Path(dst).write_text('other writer')
        return original_link(src,dst)
    monkeypatch.setattr(cli.os,'link',raced)
    assert main(args(source,output), now=NOW, fetch=read()) == 1
    assert output.read_text() == 'other writer' and not list(tmp_path.glob('.lab-candidate-*'))


def test_cli_errors_do_not_print_server_body_or_secret(tmp_path, capsys):
    source=tmp_path/'source.json'; output=tmp_path/'candidate.json'; source.write_text(json.dumps([record()]))
    def broken(_):
        raise RuntimeError('PRIVATE PATH and secret token')
    assert main(args(source,output), now=NOW, fetch=broken) == 1
    log=capsys.readouterr().out
    assert 'RuntimeError' in log and 'PRIVATE' not in log and 'secret' not in log and not output.exists()


def test_identity_revocation_survives_later_network_failure_until_new_identity_success():
    item=sourced_record(); before=deepcopy(item['metadata']['lab_snapshot'])
    wrong=PROFILE_WITH_INTERESTS_HTML.replace('>Peng Ding<','>Other Ding<')
    item['metadata'].update(collect_lab_snapshot(item,now=NOW,fetch=read(wrong)))
    assert lab_context_for(item,now=NOW)['status']=='unavailable'
    item['metadata'].update(collect_lab_snapshot(item,now=NOW+timedelta(hours=1),fetch=lambda _: (None,'request_failed')))
    assert item['metadata']['lab_refresh']['reason']=='request_failed'
    assert item['metadata']['lab_snapshot']==before
    assert lab_context_for(item,now=NOW+timedelta(hours=1))['status']=='unavailable'
    item['metadata'].update(collect_lab_snapshot(item,now=NOW+timedelta(hours=2),fetch=read()))
    assert item['metadata']['lab_refresh']['status']=='success'
    assert lab_context_for(item,now=NOW+timedelta(hours=2))['status']=='available'


def test_legacy_identity_rejection_without_marker_is_carried_forward():
    item=sourced_record();item['metadata']['lab_refresh']={'checked_at':'2026-09-26T12:00:00Z','reason':'identity_mismatch','status':'failed'}
    patch=collect_lab_snapshot(item,now=NOW+timedelta(hours=1),fetch=lambda _:(None,'http_error'))
    assert patch['lab_refresh']['identity_revoked_at']=='2026-09-26T12:00:00Z'
    item['metadata'].update(patch)
    assert lab_context_for(item,now=NOW+timedelta(hours=1))['status']=='unavailable'


@pytest.mark.parametrize('bad', [None, '', 'not-a-date', '2026-02-30T12:00:00Z', [], {}])
def test_invalid_persisted_revocation_fails_closed_before_fetch(bad):
    item=sourced_record();item['metadata']['lab_refresh']={'checked_at':'2026-09-26T12:00:00Z','reason':'request_failed','identity_revoked_at':bad}
    assert lab_context_for(item,now=NOW)['status']=='unavailable'
    with pytest.raises(ValueError,match='invalid_prior_lab_time'):
        build_lab_candidate([item],[item['id']],now=NOW+timedelta(hours=1),fetch=lambda _:pytest.fail('Invalid revocation fetched'))


def test_missing_legacy_identity_rejection_timestamp_cannot_be_overwritten_by_failure():
    item=sourced_record();item['metadata']['lab_refresh']={'reason':'identity_mismatch','status':'failed'}
    assert lab_context_for(item,now=NOW)['status']=='unavailable'
    with pytest.raises(ValueError,match='invalid_prior_lab_time'):
        collect_lab_snapshot(item,now=NOW,fetch=lambda _:pytest.fail('Missing revocation time fetched'))


def test_new_success_must_be_strictly_newer_than_identity_revocation():
    item=sourced_record();item['metadata']['lab_refresh']={'checked_at':'2026-09-26T12:00:00Z','reason':'identity_mismatch','status':'failed','identity_revoked_at':'2026-09-26T12:00:00Z'}
    before=deepcopy(item)
    with pytest.raises(ValueError,match='identity_recheck_not_newer'):
        collect_lab_snapshot(item,now=NOW,fetch=read())
    assert item==before and lab_context_for(item,now=NOW)['status']=='unavailable'


def test_two_failed_candidates_preserve_revocation_and_reject_old_time_replay():
    item=sourced_record();wrong=PROFILE_WITH_INTERESTS_HTML.replace('>Peng Ding<','>Other Ding<')
    first=build_lab_candidate([item],[item['id']],now=NOW,fetch=read(wrong))
    item['metadata'].update(first['results'][0]['patch'])
    second=build_lab_candidate([item],[item['id']],now=NOW+timedelta(hours=2),fetch=lambda _:(None,'http_error'))
    item['metadata'].update(second['results'][0]['patch'])
    assert lab_context_for(item,now=NOW+timedelta(hours=2))['status']=='unavailable'
    before=deepcopy(item)
    with pytest.raises(ValueError,match='time_regression'):
        build_lab_candidate([item],[item['id']],now=NOW+timedelta(hours=1),fetch=lambda _:pytest.fail('Older observation fetched'))
    assert item==before


def test_late_invalid_second_selection_fails_before_first_request():
    first=record();second=record();second['id']='second';second['metadata']['lab_refresh']={'checked_at':'2026-09-27T00:00:00Z'}
    with pytest.raises(ValueError,match='time_regression'):
        build_lab_candidate([first,second],[first['id'],second['id']],now=NOW,fetch=lambda _:pytest.fail('Global preflight missed future time'))


def test_two_same_named_records_cannot_exchange_profile_source_snapshots():
    # A complete name is not a globally unique identifier. Bind both ID and URL.
    item=sourced_record();other=record();other['id']='another-peng-ding'
    other['source_url']=other['url']='https://statistics.berkeley.edu/people/peng-ding-two'
    other['metadata']=deepcopy(item['metadata'])
    assert lab_context_for(other,now=NOW)['status']=='unavailable'


def test_unknown_custom_error_and_invalid_unicode_target_never_leak_or_fetch():
    item=record();item['pi_name']='Peng\ud800Ding'
    value=collect_lab_snapshot(item,now=NOW,fetch=lambda _:pytest.fail('Invalid Unicode target fetched'))
    assert value['lab_refresh']['reason']=='invalid_target'


def test_stream_failure_after_partial_html_is_not_a_success_and_is_closed():
    def chunks():
        yield b'<article>partial'
        raise requests.ConnectionError('private host/body')
    response=Response(chunks=chunks())
    result,session=transport(response)
    assert result==(None,'request_failed') and response.closed and session.closed and len(session.calls)==1


@pytest.mark.parametrize('changed_html', [
    PROFILE_WITH_INTERESTS_HTML.replace('<div class="field__item"><p>causal inference', '<div class="field__value"><p>causal inference'),
    PROFILE_WITH_INTERESTS_HTML.replace('social sciences</p></div>', 'social sciences</p></div><p>The group no longer studies causal inference.</p>'),
])
def test_partial_field_template_drift_cannot_mint_a_new_success(changed_html):
    item=sourced_record(now=NOW-timedelta(days=31));before=deepcopy(item)
    patch=collect_lab_snapshot(item,now=NOW,fetch=read(changed_html))
    assert patch['lab_refresh']['reason']=='unsupported_template'
    assert 'lab_snapshot' not in patch and item==before
    item['metadata'].update(patch)
    assert lab_context_for(item,now=NOW)['status']=='stale'


def test_known_field_values_preserve_all_paragraphs_inline_negation_and_numbers():
    html=PROFILE_WITH_INTERESTS_HTML.replace('social sciences</p>', 'social sciences</p><p>The group <strong>no longer</strong> studies 12 topics.</p>')
    patch=collect_lab_snapshot(record(),now=NOW,fetch=read(html))
    assert patch['lab_refresh']['status']=='success'
    text=patch['lab_snapshot']['pages'][0]['sections'][0]['text']
    assert 'social sciences' in text and text.endswith('The group no longer studies 12 topics.')
