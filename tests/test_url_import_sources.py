"""Actual import route and disk roundtrip with bounded synthetic HTTP only."""
import json
import socket
from copy import deepcopy

import pytest
import requests
from fastapi.testclient import TestClient

from backend import data_loader
from backend.main import app
from src.collectors import url_parser
from src.collectors.manual_importer import save_opportunities
from src.contact_instructions import CAPTURE_KEY, SOURCE_KEY
from src.normalizers.normalizer import normalize

URL = 'https://example.edu/program'
HTML = '<html><head><title>Sensor research internship</title></head><body><main><h2>Application materials</h2><p>A CV is required.</p></main></body></html>'


def response(url=URL, text=HTML, status=200, location=None):
    result = requests.Response()
    result.url = url
    result.status_code = status
    result.encoding = 'utf-8'
    result._content = text.encode('utf-8')
    result._content_consumed = True
    if location:
        result.headers['Location'] = location
    return result


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    monkeypatch.setattr('backend.main._warmup', lambda: None)
    monkeypatch.setattr('backend.lib.material_cleanup.configured', lambda: False)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('No network allowed'))
    monkeypatch.setattr(url_parser, '_host_resolves_to_blocked_ip', lambda host: False)
    monkeypatch.setattr('backend.lib.llm.is_configured', lambda: False)
    monkeypatch.setattr('backend.lib.llm.chat_completion', lambda *a, **k: pytest.fail('No provider allowed'))


@pytest.mark.parametrize('requested,final', [(URL,URL),(URL,URL+'/'),('http://example.edu/program',URL+'/')])
def test_import_keeps_actual_source_and_request_binding(monkeypatch, requested, final):
    monkeypatch.setattr(url_parser.requests, 'get', lambda *a, **k: response(final))
    with TestClient(app) as client:
        result = client.post('/api/import-url',json={'url':requested})
    assert result.status_code == 200
    raw = result.json()['opportunity']
    capture = raw['extra_fields'][CAPTURE_KEY]
    assert capture['status'] == 'captured'
    assert capture['source_url'] == final
    assert capture['requested_source_url'] == requested
    assert capture['record_source_url'] == requested
    assert raw['extra_fields'][SOURCE_KEY][0]['source_url'] == final


@pytest.mark.parametrize('final', ['https://example.edu/other','https://another.edu/program',URL+'?term=new','http://example.edu/program'])
def test_cross_page_or_downgrade_does_not_import_new_page_as_old(monkeypatch,final):
    monkeypatch.setattr(url_parser.requests,'get',lambda *a,**k:response(final))
    with TestClient(app) as client:
        result=client.post('/api/import-url',json={'url':URL})
    assert result.status_code == 200
    assert result.json()['ok'] is False
    assert result.json()['opportunity'] is None
    assert result.json()['error'] == 'The link opened a different page. Open the intended page and import its address.'


@pytest.mark.parametrize('html,status,has_sources', [
    ('<main><p>Our lab studies sensors.</p></main>','empty',True),
    ('<main><h2>Minimum GPA</h2><div>3.0</div><p>Our lab studies sensors.</p></main>','unsupported',False),
    ('<html><title>Sign in</title><p>Enter your password.</p></html>','unsupported',False),
])
def test_supported_empty_and_unsupported_remain_distinct(monkeypatch,html,status,has_sources):
    monkeypatch.setattr(url_parser.requests,'get',lambda *a,**k:response(text=html))
    raw=url_parser.parse_url_llm(URL)
    assert raw.extra_fields[CAPTURE_KEY]['status'] == status
    assert (SOURCE_KEY in raw.extra_fields) is has_sources
    if has_sources: assert raw.extra_fields[SOURCE_KEY] == []


def test_route_disk_loader_and_actual_public_detail_keep_source(monkeypatch,tmp_path):
    monkeypatch.setattr(url_parser.requests,'get',lambda *a,**k:response())
    monkeypatch.setattr(data_loader,'DATA_DIR',tmp_path)
    monkeypatch.setattr(data_loader,'_opp_cache',[])
    monkeypatch.setattr(data_loader,'_opp_cache_by_id',{})
    monkeypatch.setattr(data_loader,'_opp_cache_mtime',0)
    monkeypatch.setattr(data_loader,'_prepare_ranker_corpus',lambda *a:None)
    with TestClient(app) as client:
        imported=client.post('/api/import-url',json={'url':URL}).json()
        normalized=normalize(imported['opportunity'])
        normalized['id']='b56-url-import'
        path=tmp_path/'opportunities.json'
        assert save_opportunities([normalized],str(path)) == (1,0)
        stored=json.loads(path.read_text())[0]
        assert stored['metadata'][CAPTURE_KEY]['status']=='captured'
        loaded=data_loader.load_opportunities_by_id()['b56-url-import']
        assert loaded['metadata'][SOURCE_KEY]==stored['metadata'][SOURCE_KEY]
        result=client.get('/api/opportunities/b56-url-import', params={'_release_scope':'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2'})
        assert result.status_code==200
        detail=result.json()
    # A successful fetch does not promote a user import to a verified listing.
    assert detail['target_conditions']['record_kind'] == 'unverified'
    assert all(row['usage'] != 'usable' for row in detail['target_conditions']['conditions'])
    assert any(proof['quote']=='A CV is required.' and proof['source_url']==URL
               for row in detail['target_conditions']['conditions'] for proof in row['sources'])
    assert CAPTURE_KEY not in detail.get('metadata',{})
    assert SOURCE_KEY not in detail.get('metadata',{})
    assert imported['opportunity']['extra_fields'][SOURCE_KEY] == stored['metadata'][SOURCE_KEY]


def test_llm_cannot_replace_source_receipt_or_binding(monkeypatch):
    monkeypatch.setattr(url_parser.requests,'get',lambda *a,**k:response())
    baseline=url_parser.parse_url_llm(URL)
    before=deepcopy(baseline.extra_fields)
    monkeypatch.setattr('backend.lib.llm.is_configured',lambda:True)
    monkeypatch.setattr('backend.lib.llm.chat_completion',lambda *a,**k:json.dumps({
        'title':'AI display title', 'source_url':'https://evil.example/forged','url':'https://evil.example/forged',
        CAPTURE_KEY:{'status':'captured'},SOURCE_KEY:[{'sections':[{'text':'No CV is required.'}]}],
        'extra_fields':{CAPTURE_KEY:{'status':'empty'},SOURCE_KEY:[]},
    }))
    actual=url_parser.parse_url_llm(URL)
    assert actual.source_url==baseline.source_url
    assert actual.url==baseline.url
    assert actual.extra_fields[SOURCE_KEY][0]['sections']==before[SOURCE_KEY][0]['sections']
    assert actual.extra_fields[CAPTURE_KEY]['status']=='captured'
    assert actual.extra_fields[CAPTURE_KEY]['source_url']==URL


def test_unfetched_html_has_no_capture_authority():
    raw=url_parser.parse_url(URL,html=HTML)
    assert SOURCE_KEY not in raw.extra_fields
    assert CAPTURE_KEY not in raw.extra_fields


def test_request_budget_counts_every_redirect_hop_before_get(monkeypatch):
    requests_seen, budget_seen, observed = [], [], []
    def get(url, **kwargs):
        requests_seen.append(url)
        return response(url, status=302, location='/next')
    def budget(url):
        budget_seen.append(url)
        return len(budget_seen) <= 1
    monkeypatch.setattr(url_parser.requests, 'get', get)
    result=url_parser._safe_fetch(URL, before_request=budget, on_response=lambda resp:observed.append(resp.status_code))
    assert result is None
    assert requests_seen == [URL]
    assert budget_seen == [URL,'https://example.edu/next']
    assert observed == [302]


def test_observer_receives_429_and_retry_after_and_response_is_closed(monkeypatch):
    observed, closed = [], []
    result=response(status=429)
    result.headers['Retry-After']='120'
    monkeypatch.setattr(result,'close',lambda:closed.append(True))
    monkeypatch.setattr(url_parser.requests,'get',lambda *a,**k:result)
    assert url_parser._safe_fetch(URL,on_response=lambda resp:observed.append((resp.status_code,resp.headers['Retry-After']))) is None
    assert observed == [(429,'120')]
    assert closed == [True]


@pytest.mark.parametrize('phase',['before_request','on_response'])
def test_observer_exception_stops_safely(monkeypatch,phase):
    calls,closed=[],[]
    def stop(*args): raise RuntimeError('budget stop')
    result=response()
    monkeypatch.setattr(result,'close',lambda:closed.append(True))
    monkeypatch.setattr(url_parser.requests,'get',lambda *a,**k:calls.append(True) or result)
    assert url_parser._safe_fetch(URL,**{phase:stop}) is None
    assert calls == ([] if phase=='before_request' else [True])
    assert closed == ([] if phase=='before_request' else [True])


def test_redirect_does_not_let_budget_hook_bypass_private_destination(monkeypatch):
    called=[]
    monkeypatch.setattr(url_parser.requests,'get',lambda *a,**k:response(status=302,location='http://127.0.0.1/private'))
    assert url_parser._safe_fetch(URL,before_request=lambda url:called.append(url) or True) is None
    assert called == [URL]


def test_success_observation_has_actual_final_url_and_check_time(monkeypatch):
    from datetime import UTC, datetime
    before=datetime.now(UTC)
    final=URL+'/'
    responses=[response(URL,status=302,location=final),response(final)]
    calls=[]
    monkeypatch.setattr(url_parser.requests,'get',lambda url,**kwargs:calls.append(url) or responses.pop(0))
    result=url_parser._safe_fetch(URL)
    assert calls == [URL,final]
    assert result.url == final
    assert before <= datetime.fromisoformat(result._ofe_checked_at) <= datetime.now(UTC)


def test_missing_final_address_is_explicitly_rejected(monkeypatch):
    monkeypatch.setattr(url_parser.requests,'get',lambda *a,**k:response(url=None))
    with TestClient(app) as client:
        result=client.post('/api/import-url',json={'url':URL}).json()
    assert result['ok'] is False
    assert result['opportunity'] is None
    assert result['error']=='The page address could not be verified. Try importing the page again.'


def test_actual_failed_fetch_never_creates_an_empty_source(monkeypatch):
    monkeypatch.setattr(url_parser.requests,'get',lambda *a,**k:response(status=503))
    with TestClient(app) as client:
        result=client.post('/api/import-url',json={'url':URL}).json()
    assert result['ok'] is False
    assert result['opportunity'] is None
