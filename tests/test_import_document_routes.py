"""Real endpoints save complete static source while model processing remains excerpt-only."""
import json
import socket
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from backend.main import app
from src.collectors import url_parser

URL = 'https://example.edu/program?session=private-token-for-test'
END = 'END OF COMPLETE SOURCE: SQL is preferred, not required.'


def response(text, content_type='text/html; charset=utf-8'):
    result = requests.Response()
    result.url = URL
    result.status_code = 200
    result.headers['Content-Type'] = content_type
    result.encoding = 'utf-8'
    result._content = text.encode('utf-8')
    result._content_consumed = True
    return result


@pytest.fixture
def importer(monkeypatch):
    monkeypatch.setattr('backend.main._warmup', lambda: None)
    monkeypatch.setattr('backend.lib.material_cleanup.configured', lambda: False)
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('No external network'))
    monkeypatch.setattr(url_parser, '_host_resolves_to_blocked_ip', lambda host: False)
    monkeypatch.setattr('backend.lib.llm.is_configured', lambda: True)
    calls = []
    def model(messages, **kwargs):
        calls.append(messages)
        return json.dumps({'title':'AI suggested title', 'description':'AI summary', 'skills_required':['Python']})
    monkeypatch.setattr('backend.lib.llm.chat_completion', model)
    return TestClient(app), calls


@pytest.mark.parametrize('kind', ['url', 'text'])
def test_tail_saved_without_expanding_model_payload(importer, monkeypatch, tmp_path, kind):
    client, calls = importer
    source = ('Original project explanation with applicant information. ' * 170) + '\n' + END
    if kind == 'url':
        html = '<html><head><title>Source title</title><meta name="description" content="Short summary"></head><body><p>'+source+'</p></body></html>'
        monkeypatch.setattr(url_parser.requests, 'get', lambda *a, **k: response(html))
        result = client.post('/api/import-url', json={'url':URL})
    else:
        result = client.post('/api/import-text', json={'text':source})
    assert result.status_code == 200, result.text
    raw = result.json()['opportunity']
    assert raw['description_raw'].endswith(END)
    assert len(calls) == 1
    assert sum(message['content'].count(END) for message in calls[0]) == 0
    assert raw['extra_fields']['ai_input_scope'] == 'source_excerpt'
    assert raw['extra_fields']['description_source'] == ('page_text' if kind == 'url' else 'pasted_text')
    (tmp_path / f'{kind}-success.json').write_text(json.dumps(result.json(), ensure_ascii=False))
    assert raw['extra_fields']['needs_manual_review'] is True
    assert 'Python' not in raw['description_raw']
    assert raw['extra_fields']['suggested_skills'] == ['Python']


def test_large_local_source_does_not_expand_model_payload(importer, monkeypatch):
    client, calls = importer
    source = 'Complete original source text. ' * 4000 + END
    html = '<html><body><p>' + source + '</p></body></html>'
    monkeypatch.setattr(url_parser.requests, 'get', lambda *a, **k: response(html))
    result = client.post('/api/import-url', json={'url':URL})
    assert result.status_code == 200
    assert result.json()['opportunity']['description_raw'] == source
    assert len(calls) == 1
    # Legacy description hint (2k) and body excerpt (4k), not the full body.
    assert END not in calls[0][1]['content']
    assert len(calls[0][1]['content']) < 6500


@pytest.mark.parametrize('html,content_type,reason', [
    ('<html><head><meta name="description" content="Metadata only"></head><body></body></html>', 'text/html', 'metadata_only'),
    ('<html><body></body></html>', 'text/html', 'empty_page'),
    ('%PDF-1.7 fake PDF stream', 'application/pdf', 'unsupported_content_type'),
])
def test_unreadable_source_has_typed_error_without_model_or_source_echo(importer, monkeypatch, tmp_path, html, content_type, reason):
    client, calls = importer
    monkeypatch.setattr(url_parser.requests, 'get', lambda *a, **k: response(html, content_type))
    result = client.post('/api/import-url', json={'url':URL})
    assert result.status_code == 422
    detail = result.json()['detail']
    assert detail['code'] == 'import_source_unreadable'
    assert detail['reason'] == reason
    assert detail['retryable'] is False
    (tmp_path / f'{reason}-error.json').write_text(json.dumps(result.json()))
    assert 'private-token-for-test' not in result.text
    assert not calls


def test_full_url_fallback_keeps_source_but_does_not_claim_model_reading(importer, monkeypatch):
    client, calls = importer
    monkeypatch.setattr('backend.lib.llm.is_configured', lambda: False)
    source = 'Visible source description. ' * 240 + END
    monkeypatch.setattr(url_parser.requests, 'get', lambda *a, **k: response('<html><body>'+source+'</body></html>'))
    result = client.post('/api/import-url', json={'url':URL})
    assert result.status_code == 200
    raw = result.json()['opportunity']
    assert raw['description_raw'].endswith(END)
    assert not result.json()['llm_enriched']
    assert raw['extra_fields'].get('ai_input_scope') != 'full_source'
    assert not calls


@pytest.mark.parametrize('reason,status,code', [
    ('too_large', 413, 'import_input_too_large'),
    ('private-token-for-test', 422, 'import_source_unreadable'),
])
def test_fixed_source_error_mapping(importer, monkeypatch, tmp_path, reason, status, code):
    from src.collectors.import_document import ImportDocumentError
    client, calls = importer
    def refused(_url):
        raise ImportDocumentError(reason)
    monkeypatch.setattr('backend.routes.import_url.parse_url_llm', refused)
    result = client.post('/api/import-url', json={'url':URL})
    assert result.status_code == status
    assert result.json()['detail']['code'] == code
    assert 'private-token-for-test' not in result.text
    assert not calls
    # This proves exception routing, not a currently implemented model budget.
    (tmp_path / f'{status}-injected-error.json').write_text(json.dumps(result.json()))


def test_late_source_requirement_survives_normalization_and_disk_reload(importer, monkeypatch, tmp_path):
    from backend import data_loader
    from src.collectors.manual_importer import save_opportunities
    from src.normalizers.normalizer import normalize

    client, calls = importer
    monkeypatch.setattr('backend.lib.llm.is_configured', lambda: False)
    tail = 'END OF COMPLETE SOURCE: SQL is preferred.'
    source = 'Our research program investigates environmental measurements. ' * 170 + '\n' + tail
    monkeypatch.setattr(url_parser.requests, 'get', lambda *a, **k: response('<html><body><p>' + source + '</p></body></html>'))
    result = client.post('/api/import-url', json={'url': URL})
    assert result.status_code == 200
    normalized = normalize(result.json()['opportunity'])
    normalized['id'] = 'b58-full-local-source'
    assert normalized['description_raw'].endswith(tail)
    assert 'SQL' in normalized['eligibility']['skills_preferred']
    assert 'SQL' not in normalized['eligibility']['skills_required']
    monkeypatch.setattr(data_loader, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(data_loader, '_opp_cache', [])
    monkeypatch.setattr(data_loader, '_opp_cache_by_id', {})
    monkeypatch.setattr(data_loader, '_opp_cache_mtime', 0)
    monkeypatch.setattr(data_loader, '_prepare_ranker_corpus', lambda *a: None)
    path = tmp_path / 'opportunities.json'
    assert save_opportunities([normalized], str(path)) == (1, 0)
    loaded = data_loader.load_opportunities_by_id()[normalized['id']]
    assert loaded['description_raw'] == normalized['description_raw']
    assert loaded['eligibility']['skills_preferred'] == normalized['eligibility']['skills_preferred']
    assert not calls


def test_bot_verification_page_is_refused_before_any_model_call(importer, monkeypatch):
    # On 2026-09-30 a real UIUC posting URL gave the production server an
    # Imunify360 check titled "One moment, please...". It came back ok:true,
    # llm_enriched:true, and could be saved as an opportunity. Only its title
    # and text were kept, so this is Imunify360's WebShield template rebuilt
    # around them, not the captured page.
    client, calls = importer
    html = ('<!DOCTYPE html><html><head><title>One moment, please...</title></head><body>'
            '<h1>Please wait while your request is being verified...</h1>'
            '<form id="wsidchk-form" style="display:none;" action="/z0f76a1d14fd" method="GET">'
            '<input type="hidden" id="wsidchk" name="wsidchk"/></form>'
            '<script>(function(){})();</script></body></html>')
    monkeypatch.setattr(url_parser.requests, 'get', lambda *a, **k: response(html))
    result = client.post('/api/import-url', json={'url': URL})
    assert result.status_code == 422
    detail = result.json()['detail']
    assert (detail['code'], detail['reason']) == ('import_source_unreadable', 'access_page')
    assert 'opportunity' not in result.json()
    assert 'private-token-for-test' not in result.text
    assert not calls


def test_anubis_check_under_the_site_title_is_refused_before_any_model_call(importer, monkeypatch):
    # The captured BotStopper page (tests/fixtures). Through this route it used
    # to come back ok:true, llm_enriched:true, after one model call.
    client, calls = importer
    html = (Path(__file__).parent / 'fixtures' / 'anubis_botstopper_challenge.html').read_text(encoding='utf-8')
    monkeypatch.setattr(url_parser.requests, 'get', lambda *a, **k: response(html))
    result = client.post('/api/import-url', json={'url': URL})
    assert result.status_code == 422
    detail = result.json()['detail']
    assert (detail['code'], detail['reason']) == ('import_source_unreadable', 'access_page')
    assert not calls
