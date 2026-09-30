"""Full local source saving must not expand the existing model payload."""
import json

import pytest
import requests

from src.collectors import url_parser
from src.collectors.base import RawOpportunity

URL = 'https://example.edu/program'
TAIL = 'LATE_SOURCE_END'


@pytest.mark.parametrize('metadata,expected_hint', [
    ('<meta property="og:description" content="Exact OG hint"><meta name="description" content="Other hint">', 'Exact OG hint'),
    ('<meta name="description" content="Exact meta hint">', 'Exact meta hint'),
    ('', ('Body paragraph. ' * 500 + TAIL)[:2000]),
])
def test_old_hint_and_excerpt_remain_exact_when_full_source_is_saved(monkeypatch, metadata, expected_hint):
    calls = []
    body = 'Body paragraph. ' * 500 + TAIL
    html = '<html><head><title>Original title</title>' + metadata + '</head><body><main>' + body + '</main></body></html>'
    response = requests.Response()
    response.url = URL
    response.status_code = 200
    response._content = html.encode()
    response.encoding = 'utf-8'
    response.headers['Content-Type'] = 'text/html'
    monkeypatch.setattr(url_parser, '_safe_fetch', lambda _url: response)
    monkeypatch.setattr('backend.lib.llm.is_configured', lambda: True)
    def model(messages, **kwargs):
        calls.append(messages)
        return json.dumps({'title': 'Suggested', 'ai_input_scope': 'full_source'})
    monkeypatch.setattr('backend.lib.llm.chat_completion', model)
    result = url_parser.parse_url_llm(URL)
    expected_excerpt = ('Original title ' + body)[:4000]
    expected_user = (f'URL: {URL}\nTitle (from OG meta): Original title\n'
                     f'Description (from OG meta): {expected_hint}\n\n'
                     f'Page body excerpt:\n{expected_excerpt}')
    assert calls[0][1]['content'] == expected_user
    assert TAIL not in expected_user
    assert result.description_raw == body
    assert result.extra_fields['ai_input_scope'] == 'source_excerpt'


@pytest.mark.parametrize('configured,answer', [(False, None), (True, None), (True, 'invalid JSON')])
def test_failed_model_pass_cannot_keep_inherited_full_scope(monkeypatch, configured, answer):
    monkeypatch.setattr('backend.lib.llm.is_configured', lambda: configured)
    monkeypatch.setattr('backend.lib.llm.chat_completion', lambda *a, **k: answer)
    base = RawOpportunity(source='test', source_url=URL, url=URL, title='Source',
                          description_raw='Full source', extra_fields={'ai_input_scope':'full_source'})
    result = url_parser._run_llm_extraction(base, body_excerpt='Full', url_hint=URL, title_hint='Source', description_hint='')
    if result is not None:
        assert 'ai_input_scope' not in result.extra_fields
