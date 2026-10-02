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


def _model_that_answers(monkeypatch, calls):
    monkeypatch.setattr('backend.lib.llm.is_configured', lambda: True)
    def model(messages, **kwargs):
        calls.append(messages)
        return json.dumps({'title': 'Suggested'})
    monkeypatch.setattr('backend.lib.llm.chat_completion', model)


def _fetched(monkeypatch, html):
    response = requests.Response()
    response.url = URL
    response.status_code = 200
    response._content = html.encode()
    response.encoding = 'utf-8'
    response.headers['Content-Type'] = 'text/html'
    monkeypatch.setattr(url_parser, '_safe_fetch', lambda _url: response)


# A 640-character paste was labelled "AI processed only an excerpt, not all of
# this source text" although the model received every character of it.
def test_pasted_text_within_the_excerpt_is_labelled_as_sent_in_full(monkeypatch):
    calls = []
    _model_that_answers(monkeypatch, calls)
    text = 'Undergraduate research assistant wanted for a soil microbiology project. ' * 9
    assert len(text) <= url_parser.LLM_BODY_EXCERPT_CHARS
    result = url_parser.parse_text_llm(text)
    assert text in calls[0][1]['content']
    assert result.extra_fields['ai_input_scope'] == 'full_source'


# A repeated paste has no word past the cut that the model did not see, but
# the model saw fewer of them than the student saved.
@pytest.mark.parametrize('tail', [pytest.param(TAIL, id='unique-tail'), pytest.param('', id='repeated-text')])
def test_pasted_text_beyond_the_excerpt_stays_an_excerpt(monkeypatch, tail):
    calls = []
    _model_that_answers(monkeypatch, calls)
    text = 'Undergraduate research assistant wanted. ' * 200 + tail
    assert len(text) > url_parser.LLM_BODY_EXCERPT_CHARS
    result = url_parser.parse_text_llm(text)
    assert TAIL not in calls[0][1]['content']
    assert result.extra_fields['ai_input_scope'] == 'source_excerpt'


@pytest.mark.parametrize(('items', 'saved'), [
    pytest.param('<ol><li>CV</li><li>Transcript</li></ol>', '1. CV\n2. Transcript', id='numbered-list'),
    # A list can count from below zero, and "-2. " is the reader's marker too.
    pytest.param('<ol start="-2"><li>CV</li><li>Transcript</li></ol>', '-2. CV\n-1. Transcript', id='negative-start'),
])
def test_short_page_whose_every_saved_word_reached_the_model_is_labelled_full(monkeypatch, items, saved):
    calls = []
    _model_that_answers(monkeypatch, calls)
    _fetched(monkeypatch, '<html><head><title>Soil lab</title></head><body><main><h1>Soil lab</h1>'
                          '<p>Undergraduates may apply by <b>June 1</b>.</p>' + items +
                          '<table><tr><td>Hours</td><td>10 per week</td></tr></table></main></body></html>')
    result = url_parser.parse_url_llm(URL)
    assert result.description_raw == f'Soil lab\nUndergraduates may apply by June 1.\n{saved}\nHours\t10 per week'
    assert result.extra_fields['ai_input_scope'] == 'full_source'


@pytest.mark.parametrize('body', [
    # The model hint drops navigation and footers; the saved page text keeps them.
    '<nav>Programs People</nav><main><p>Undergraduates may apply by June 1.</p></main>',
    '<main><p>Undergraduates may apply by June 1.</p></main><footer>Contact the lab manager for details.</footer>',
    '<main><p>' + 'Undergraduates may apply by June 1. ' * 150 + TAIL + '</p></main>',
])
def test_page_text_the_model_did_not_receive_keeps_the_excerpt_label(monkeypatch, body):
    calls = []
    _model_that_answers(monkeypatch, calls)
    _fetched(monkeypatch, '<html><head><title>Soil lab</title></head><body>' + body + '</body></html>')
    result = url_parser.parse_url_llm(URL)
    assert result.extra_fields['ai_input_scope'] == 'source_excerpt'


def test_excerpt_skips_the_same_tags_at_any_depth_and_leaves_the_shared_page_whole():
    # The reader, the contact capture and the excerpt read one parsed page now,
    # so the excerpt skips script, style, noscript, header, footer and nav
    # instead of removing them from it. Its text is the old excerpt's.
    from src.collectors.import_document import parse_import_html

    soup = parse_import_html(
        '<html><head><title>Lab</title><style>p{}</style></head><body><header><p>Site <nav>menu</nav></p></header>'
        '<main><p>Keep <b>this</b> text.</p><div><noscript>Enable JS</noscript><span>and <script>x()</script>this'
        '</span></div><nav><ul><li>Home</li></ul></nav><template><p>Template text</p></template><p>e</x>mail</p>'
        '<![CDATA[cdata words]]><!-- comment --></main><footer>Contact us</footer></body></html>')
    page = str(soup)
    assert url_parser._strip_to_text(soup) == 'Lab Keep this text. and this e mail cdata words'
    assert str(soup) == page
