"""Private render-only schema, binding, release/body and failure boundaries."""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.lib.target_resume_export import safe_link
from backend.lib.target_resume_export_schema import MAX_BODY_BYTES, ExportError, ExportRequest, export_signature
from backend.main import (
    RequestBodyLimitMiddleware,
    _export_body_limit_from_env,
    _full_target_body_limit_from_env,
    _release_feature_for_path,
    app,
)
from backend.routes import target_resume_export as route

PATH = '/api/resume/full-target/export'
FIXTURE = Path(__file__).parent / 'fixtures' / 'target-resume-export-golden.json'


def projection(text='Student 中文 😀'):
    return {'version': 1, 'template': 'standard-v1', 'locale': 'en', 'page_size': 'letter',
            'sections': [{'kind': 'basics', 'heading': '', 'blocks': [{'lines': [{'role': 'name', 'label': '', 'text': text}]}]}]}


def payload(value=None, output='pdf'):
    value = value or projection()
    return {'version': 1, 'request_id': 'export-1', 'format': output, 'document_signature': 'v1:sha256:' + 'a' * 64,
            'export_signature': export_signature(value), 'projection': value}


@pytest.fixture
def endpoint(monkeypatch):
    calls = []

    def render(value, output, *, deadline):
        calls.append((deepcopy(value), output))
        return b'%PDF-test' if output == 'pdf' else b'PK-test'

    monkeypatch.setattr(route, 'render_export', render)
    return TestClient(app), calls


def test_shared_projection_golden():
    golden = json.loads(FIXTURE.read_text())
    assert export_signature(golden['projection']) == golden['export_signature']
    request = ExportRequest.model_validate({**payload(golden['projection']), 'document_signature': golden['document_signature']})
    request.verify_signature()
    assert request.projection.model_dump() == golden['projection']
    text = json.dumps(request.projection.model_dump(), ensure_ascii=False)
    assert 'resume_text' not in text and 'evidence' not in text and 'original' not in text


@pytest.mark.parametrize('output,mime', [('pdf', 'application/pdf'), ('docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')])
def test_endpoint_returns_binary_bound_to_exact_request(endpoint, output, mime):
    client, calls = endpoint
    body = payload(output=output)
    response = client.post(PATH, json=body, headers={'Origin': 'https://joinalab.com'})
    assert response.status_code == 200
    assert response.headers['content-type'] == mime
    assert response.headers['content-disposition'] == f'attachment; filename="resume.{output}"'
    for key, value in {'x-ofe-export-request': body['request_id'], 'x-ofe-document-signature': body['document_signature'],
                       'x-ofe-export-signature': body['export_signature'], 'x-ofe-export-template': 'standard-v1'}.items():
        assert response.headers[key] == value
        assert key in response.headers['access-control-expose-headers'].lower()
    assert 'no-store' in response.headers['cache-control']
    assert calls == [(body['projection'], output)]


@pytest.mark.parametrize('mutator', [
    lambda x: x.update(raw='PRIVATE'), lambda x: x['projection'].update(base_snapshot={'private': 'SECRET'}),
    lambda x: x['projection']['sections'][0]['blocks'][0]['lines'][0].update(original='SECRET'),
    lambda x: x.update(version=True), lambda x: x['projection'].update(version=True),
    lambda x: x.update(request_id='newline\r\nX-Injected: true'), lambda x: x.update(request_id='中文'),
    lambda x: x.update(format='html'), lambda x: x['projection'].update(template='remote'),
    lambda x: x['projection']['sections'][0]['blocks'][0]['lines'][0].update(role='__proto__'),
    lambda x: x['projection']['sections'][0].update(blocks=[]),
])
def test_bad_shape_cannot_render_or_echo_input(endpoint, mutator):
    client, calls = endpoint
    body = payload(projection('PRIVATE_STUDENT_TEXT'))
    mutator(body)
    response = client.post(PATH, json=body)
    assert response.status_code == 422
    assert response.json() == {'detail': {'code': 'invalid_export_request'}}
    assert 'PRIVATE' not in response.text and 'SECRET' not in response.text
    assert calls == []
    assert 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('text', ['\x00', '\x01', '\x0b', '\x0c', '\ufffe', '\uffff', '\ud800', '\udfff'])
def test_xml_illegal_characters_reject_without_echo(endpoint, text):
    client, calls = endpoint
    body = payload()
    body['projection']['sections'][0]['blocks'][0]['lines'][0]['text'] = 'PRIVATE' + text
    response = client.post(PATH, content=json.dumps(body), headers={'Content-Type': 'application/json'})
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'invalid_export_text'
    assert 'PRIVATE' not in response.text and calls == []


@pytest.mark.parametrize('text', ['', ' \t\r\n', '\ufeff'])
def test_empty_document_rejected(endpoint, text):
    client, calls = endpoint
    response = client.post(PATH, json=payload(projection(text)))
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'empty_document'
    assert calls == []


def test_signature_mismatch_rejected_without_render(endpoint):
    client, calls = endpoint
    body = payload()
    body['projection']['sections'][0]['blocks'][0]['lines'][0]['text'] = 'later edit'
    response = client.post(PATH, json=body)
    assert response.status_code == 422 and response.json()['detail']['code'] == 'invalid_export_signature'
    assert calls == []


def test_large_valid_single_line_is_not_silently_truncated(endpoint):
    client, calls = endpoint
    text = 'Start' + 'a' * (1024 * 1024) + '中文 END'
    response = client.post(PATH, json=payload(projection(text)))
    assert response.status_code == 200
    assert calls[0][0]['sections'][0]['blocks'][0]['lines'][0]['text'] == text


@pytest.mark.parametrize('count', [601, 700])
def test_aggregate_line_count_is_bounded(count):
    body = payload()
    body['projection']['sections'][0]['blocks'] = [{'lines': [{'role': 'skill', 'label': '', 'text': 'Python'}] * 300},
                                                   {'lines': [{'role': 'skill', 'label': '', 'text': 'Python'}] * (count - 300)}]
    with pytest.raises(ValidationError):
        ExportRequest.model_validate(body)


@pytest.mark.parametrize('code,status', [('unsupported_glyph', 422), ('fonts_unavailable', 503), ('export_too_large', 413), ('export_timeout', 504)])
def test_safe_renderer_errors(endpoint, monkeypatch, code, status):
    client, _calls = endpoint
    monkeypatch.setattr(route, 'render_export', lambda *_a, **_kw: (_ for _ in ()).throw(ExportError(code)))
    response = client.post(PATH, json=payload())
    assert response.status_code == status
    assert response.json() == {'detail': {'code': code}}
    assert 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('exception,status,code', [(route.BlockingWorkOverloaded(), 503, 'export_overloaded'),
                                                   (route.BlockingWorkTimeout(), 504, 'export_timeout'),
                                                   (RuntimeError('PRIVATE_STUDENT_TEXT'), 500, 'export_failed')])
def test_work_failure_is_safe(endpoint, monkeypatch, exception, status, code, caplog):
    client, _ = endpoint

    async def fail(*args, **kwargs):
        raise exception

    monkeypatch.setattr(route, 'run_blocking', fail)
    response = client.post(PATH, json=payload())
    assert response.status_code == status
    assert response.json() == {'detail': {'code': code}}
    assert 'PRIVATE' not in response.text + caplog.text


def test_export_release_gate_blocks_before_render(endpoint, monkeypatch):
    import backend.main as main
    client, calls = endpoint
    assert _release_feature_for_path(PATH) == 'resume_renovate'
    monkeypatch.setattr(main, 'feature_enabled', lambda _: False)
    response = client.post(PATH, json=payload())
    assert response.status_code == 404 and calls == []
    assert 'no-store' in response.headers['cache-control']


def test_explicit_smaller_body_limit_preserved(monkeypatch):
    monkeypatch.setenv('OFE_MAX_REQUEST_BODY_BYTES', '4096')
    assert _full_target_body_limit_from_env() == 4096
    assert _export_body_limit_from_env() == 4096
    monkeypatch.delenv('OFE_MAX_REQUEST_BODY_BYTES')
    assert _full_target_body_limit_from_env() == MAX_BODY_BYTES
    assert _export_body_limit_from_env() == MAX_BODY_BYTES


def test_export_body_limit_uses_its_own_contract(monkeypatch):
    import backend.lib.target_resume_ai_schema as ai_schema
    import backend.lib.target_resume_export_schema as export_schema
    monkeypatch.delenv('OFE_MAX_REQUEST_BODY_BYTES', raising=False)
    monkeypatch.setattr(ai_schema, 'MAX_BODY_BYTES', 12345)
    monkeypatch.setattr(export_schema, 'MAX_BODY_BYTES', 23456)
    assert _full_target_body_limit_from_env() == 12345
    assert _export_body_limit_from_env() == 23456
    monkeypatch.setenv('OFE_MAX_REQUEST_BODY_BYTES', '18000')
    assert _full_target_body_limit_from_env() == 12345
    assert _export_body_limit_from_env() == 18000


@pytest.mark.parametrize('declared', [True, False])
def test_export_actual_and_declared_body_boundary(declared):
    async def probe(path):
        sent = []
        frames = [{'type': 'http.request', 'body': b'x' * 600, 'more_body': True},
                  {'type': 'http.request', 'body': b'x' * 600, 'more_body': False}]

        async def downstream(scope, receive, send):
            while (await receive()).get('more_body'):
                pass
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'ok'})

        async def receive():
            return frames.pop(0)

        async def send(value):
            sent.append(value)

        wrapped = RequestBodyLimitMiddleware(downstream, max_bytes=1000, full_target_max_bytes=1100, export_max_bytes=1500)
        await wrapped({'type': 'http', 'path': path, 'headers': [(b'content-length', b'1200')] if declared else []}, receive, send)
        return sent[0]['status']
    assert asyncio.run(probe(PATH)) == 200
    assert asyncio.run(probe('/api/tailor')) == 413
    assert asyncio.run(probe('/api/tailor/full-target/suggestions')) == 413


@pytest.mark.parametrize('role,text,expected', [('url', 'https://example.edu/path?q=x', 'https://example.edu/path?q=x'),
    ('url', 'javascript:alert(1)', None), ('url', 'file:///private/secret', None), ('url', 'https://x@y.edu', None),
    ('url', 'https://x.edu:abc', None), ('url', 'https://x.edu\nInjected', None), ('email', 'a@example.edu', 'mailto:a@example.edu'),
    ('doi', '10.1234/test', 'https://doi.org/10.1234/test'), ('experience', 'https://example.edu', None)])
def test_only_safe_explicit_links_are_active(role, text, expected):
    assert safe_link({'role': role, 'text': text}) == expected


def test_renderer_runs_outside_event_loop_while_health_responds(monkeypatch):
    import threading

    import httpx
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def render(*_a, **_kw):
        entered.set()
        release.wait(3)
        finished.set()
        return b'%PDF-test'

    monkeypatch.setattr(route, 'render_export', render)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            task = asyncio.create_task(client.post(PATH, json=payload()))
            try:
                assert await asyncio.to_thread(entered.wait, 1)
                response = await asyncio.wait_for(client.get('/api/health'), timeout=0.5)
                assert response.status_code == 200
                assert not finished.is_set(), 'health waited for rendering to finish'
            finally:
                release.set()
            assert (await task).status_code == 200
    asyncio.run(scenario())


def test_worker_deadline_is_inside_outer_timeout_and_includes_queue_wait(endpoint, monkeypatch):
    client, _calls = endpoint
    observed = {}
    monkeypatch.setattr(route, 'monotonic', lambda: 100.0)
    monkeypatch.setattr(route, 'LOCAL_WORK_TIMEOUT_SECONDS', 30.0)

    async def work(func, *args, **kwargs):
        observed.update(kwargs)
        return b'%PDF-test'

    monkeypatch.setattr(route, 'run_blocking', work)
    assert client.post(PATH, json=payload()).status_code == 200
    assert observed == {'deadline': 129.0, 'timeout_seconds': 30.0}
