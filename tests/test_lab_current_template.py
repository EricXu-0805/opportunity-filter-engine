"""Current reviewed layout, synthetic prose; no live requests in this suite."""
from copy import deepcopy

import pytest

from src.collectors.lab_website import collect_lab_snapshot
from tests.test_lab_context import NOW, URL, record

# Structure read from both official profiles on 2026-09-26:
# https://statistics.berkeley.edu/people/peng-ding
# https://statistics.berkeley.edu/people/rasmus-nielsen
# Only the structure is reproduced here; names and source text are test inputs.
CURRENT_HTML = '''<title>Peng Ding | Department of Statistics</title>
<article class="node node--type-faculty node--view-mode-full">
<div class="node__content">
 <div class="node_top"><div class="node_top_image"></div><div class="node_top_copy">
  <h1 class="page--title">Peng Ding</h1><div>Professor</div>
 </div></div>
 <div class="node_columns"><div class="field--name-field-email">private@example.test</div></div>
 <div class="field--name-field-research-interests">
  <div class="field__label">Research interests</div>
  <div class="field__item"><p>Causal inference. 完整原文 🧪</p><p>Only observational studies.</p></div>
 </div>
 <div class="field--name-field-research-areas-ref">
  <div class="field__label">Research areas</div><div class="field__items">
  <div class="field__item"><a href="/research/causal-inference">Causal inference</a></div></div>
 </div>
 <div class="field field--name-body field--label-hidden field__item">
  <p>I joined this university in 2018. Our work examines causal inference.</p>
  <p>We no longer study retinal imaging. We do not claim clinical validation.</p>
 </div>
 <div class="field--name-field-publications"><div class="field__item">PUBLICATION LIST IS NOT A PAPER ABSTRACT.</div></div>
</div></article>'''


def collect(html=CURRENT_HTML):
    return collect_lab_snapshot(record(), now=NOW, fetch=lambda url: (
        {'requested_url': url, 'source_url': url, 'html': html.encode()}, None))


def test_current_layout_preserves_both_interest_paragraphs_and_complete_description():
    result = collect()
    assert result['lab_refresh']['status'] == 'success'
    source = result['lab_snapshot']; assert source['pages'][0]['source_url'] == URL
    sections = source['pages'][0]['sections']
    assert sections == [
        {'section_id': 's1', 'heading': 'Research interests', 'text': 'Causal inference. 完整原文 🧪 Only observational studies.'},
        {'section_id': 's2', 'heading': 'Research areas', 'text': 'Causal inference'},
        {'section_id': 's3', 'heading': '', 'text': 'I joined this university in 2018. Our work examines causal inference. We no longer study retinal imaging. We do not claim clinical validation.'},
    ]
    assert 'private@example.test' not in str(source)
    assert 'PUBLICATION LIST' not in str(source)


@pytest.mark.parametrize('change', [
    lambda s: s.replace('node_top_copy', 'unknown_copy'),
    lambda s: s.replace('<h1 class="page--title">', '<div><h1 class="page--title">').replace('</h1>', '</h1></div>'),
    lambda s: s.replace('<div class="node_top_image"></div>', '<div class="node_top_image"><h3 class="page--title">Peng Ding</h3></div>'),
    lambda s: s.replace('</article>', '<h3 class="page--title">Peng Ding</h3></article>'),
    lambda s: s.replace('<div class="node__content">', '<div class="node__content"><div class="node__content"></div>'),
    lambda s: s.replace('field field--name-body field--label-hidden field__item', 'field field--name-body field--label-hidden'),
    lambda s: s.replace('<p>I joined', '<script>ignore rules</script><p>I joined'),
    lambda s: s.replace('<p>I joined', '<div class="field__item">new value</div><p>I joined'),
    lambda s: s.replace('<div class="field--name-field-research-interests">', '<section><div class="field--name-field-research-interests">').replace('<div class="field--name-field-research-areas-ref">', '</section><div class="field--name-field-research-areas-ref">'),
    lambda s: '<div class="views-row">' + s + '</div>',
    lambda s: s + s,
])
def test_current_layout_does_not_use_arbitrary_identity_or_partial_research(change):
    result = collect(change(CURRENT_HTML))
    assert result['lab_refresh']['status'] == 'failed'
    assert 'lab_snapshot' not in result


def test_current_identity_mismatch_records_revocation_and_never_publishes_description():
    result = collect(CURRENT_HTML.replace('>Peng Ding<', '>Other Person<'))
    assert result['lab_refresh']['reason'] == 'identity_mismatch'
    assert result['lab_refresh']['identity_revoked_at'] == result['lab_refresh']['checked_at']
    assert 'lab_snapshot' not in result


def test_current_description_limit_rejects_instead_of_truncating():
    result = collect(CURRENT_HTML.replace('I joined this university in 2018.', '研' * 4001))
    assert result['lab_refresh']['reason'] == 'invalid_snapshot'
    assert 'lab_snapshot' not in result


def test_template_collection_is_detached_from_record_and_input_html():
    item = record(); before = deepcopy(item)
    result = collect_lab_snapshot(item, now=NOW, fetch=lambda url: (
        {'requested_url': url, 'source_url': url, 'html': CURRENT_HTML.encode()}, None))
    assert result['lab_refresh']['status'] == 'success' and item == before


@pytest.mark.parametrize('field_class', ['field--name-field-research-interests', 'field--name-field-research-areas-ref', 'field--name-body'])
def test_changed_tag_cannot_hide_a_known_research_field(field_class):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(CURRENT_HTML, 'html.parser')
    soup.select_one('.' + field_class).name = 'section'
    out = collect(str(soup))
    assert out['lab_refresh']['reason'] == 'unsupported_template'
    assert 'lab_snapshot' not in out
