"""Official-source résumé contracts with synthetic source/provider responses only."""
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.lib import evidence_map as em
from backend.lib import public_opportunity_detail, public_projection
from backend.lib import target_resume_ai as ai
from backend.lib.target_resume_ai_validation import fingerprint, validate_document
from backend.lib.target_resume_context import public_target_context, target_context_character_count
from backend.main import app
from backend.routes import target_resume_ai as route
from src.lab_context import lab_context_for
from tests.test_full_target_resume_attribution import _document
from tests.test_lab_context import NOW, sourced_record

GOLDEN = json.loads((Path(__file__).parent / 'fixtures/target-resume-context-v4-golden.json').read_text())
PATHS = ['/api/tailor/full-target/suggestions', '/api/tailor/full-target/selection-plan']
QUOTE = {'field': 'lab_heading', 'page_index': 0, 'section_index': 0, 'start': 0, 'end': 6, 'quote': '实验室😀研究'}
# The suggestions route (full-target-v6) links to server-cut anchors; the mock finds one by its text.
# The selection plan (full-target-plan-v4) still quotes target fields by offset (QUOTE).
LINK = {'anchor_text': '实验室😀研究', 'term': '实验室😀研究', 'source': 'Python', 'relation': 'broader'}
SENTENCE = 'We study Python sensors. 实验室方法😀仅用于相关性'


def v6_row(unit, anchors, state):
    link = state['link']
    ident = next((anchor['id'] for anchor in anchors if anchor['text'] == link.get('anchor_text')), link.get('anchor', 't99'))
    rewrite = state['replacement'] is not None and unit['kind'] == 'experience'
    return {'unit_id': unit['unit_id'], 'priority': 'high', 'reason': 'topic_relevance',
            'links': [{'id': 'L1', 'anchor': ident, 'term': link['term'], 'source': link['source'], 'relation': link['relation']}],
            'decision': 'rewrite' if rewrite else 'keep', 'ops': [{'op': 'lead_with', 'link': 'L1'}] if rewrite else [],
            'text': state['replacement'] if rewrite else None, 'keep_reason': None if rewrite else 'no_link'}


def test_v4_shared_exact_target_hash_document_and_complete_budget():
    public = deepcopy(GOLDEN['public_opportunity']); before = deepcopy(public)
    target = public_target_context(public)
    assert target == GOLDEN['draft']['target_snapshot']
    assert fingerprint(target) == GOLDEN['draft']['base']['target_signature']
    assert target_context_character_count(target) == GOLDEN['target_character_count']
    assert validate_document(GOLDEN['draft']) == GOLDEN['draft']
    assert fingerprint(GOLDEN['draft']) == GOLDEN['document_signature']
    assert public == before


@pytest.fixture
def endpoint(monkeypatch):
    opp = sourced_record()
    opp.update(title='Research methods', organization='UC Berkeley', description_clean='Python research.',
               opportunity_type='research', eligibility={'skills_required': ['Python']})
    opp['metadata'].update(is_active=True, verification_scope='profile', contact_identity_status='verified')
    opp['metadata']['lab_snapshot']['pages'][0]['sections'] = deepcopy(GOLDEN['draft']['target_snapshot']['lab']['snapshot']['pages'][0]['sections'])
    for module in (public_opportunity_detail, public_projection):
        monkeypatch.setattr(module, 'lab_context_for', lambda value: lab_context_for(value, now=NOW))
    monkeypatch.setattr(route, 'load_opportunities_by_id', lambda: {opp['id']: opp})
    monkeypatch.setattr(route, 'is_configured', lambda: True)
    monkeypatch.setattr(ai.llm_budget, 'exhausted', lambda: False)
    state = {'calls': [], 'quote': deepcopy(QUOTE), 'link': dict(LINK), 'replacement': None}
    monkeypatch.setattr(em, 'ai_review', lambda pairs, deadline=None: ['accepted'] * len(pairs))

    def model(messages, **kwargs):
        state['calls'].append(deepcopy(messages)); data = json.loads(messages[1]['content'])
        if 'units' in data:
            return json.dumps({'units': [v6_row(unit, data['anchors'], state) for unit in data['units']]}, ensure_ascii=False)
        return json.dumps({'items': [{'section_id': block['section_id'], 'block_id': block['block_id'],
            'action': 'compress' if state['replacement'] else 'keep', 'reason': 'Related official research topic.',
            'target_evidence': [state['quote']], 'source_evidence': [{'unit_id': block['lines'][0]['unit_id'], 'start': 0,
                'end': len(block['lines'][0]['original']), 'quote': block['lines'][0]['original']}],
            'rewrites': [{'unit_id': line['unit_id'], 'proposed_text': state['replacement']} for line in block['lines']
                         if line['evidence']['kind'] == 'experience' and state['replacement']]}
            for block in data['blocks']]}, ensure_ascii=False)
    monkeypatch.setattr(ai, 'chat_completion', model)
    return TestClient(app), opp, state


def document(opp, original='I wrote parser tests using Python.'):
    return _document([original], opp)


def submit(client, path, doc, locale='zh'):
    request = {'version': 1, 'request_id': 'official-resume', 'locale': locale, 'include_check_version': True,
               'draft': doc, 'document_signature': fingerprint(doc)}
    if path.endswith('suggestions'):
        request['selected_unit_ids'] = [unit['unit_id'] for unit in ai.units_for(doc)[0]]
    else:
        request['options'] = {'target_pages': 1}
    return client.post(path, json=request)


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('field,start,end,quote', [('lab_heading', 0, 6, '实验室😀研究'), ('lab_text', 25, 31, '实验室方法😀')])
def test_both_routes_use_available_exact_unicode_quotes_without_applying(endpoint, path, field, start, end, quote):
    client, opp, state = endpoint; doc = document(opp); before = deepcopy(doc)
    assert doc['target_snapshot']['lab']['status'] == 'available'
    state['quote'] = {**QUOTE, 'field': field, 'start': start, 'end': end, 'quote': quote}
    state['link'] = dict(LINK, anchor_text='实验室😀研究' if field == 'lab_heading' else SENTENCE, term=quote)
    response = submit(client, path, doc); assert response.status_code == 200, response.text
    assert response.json()['method'] == 'ai' and response.json()['check_version'] == 'target-resume-source-checks-v4'
    assert len(state['calls']) == 1 and doc == before
    prompt = json.loads(state['calls'][0][1]['content'])
    if path.endswith('selection-plan'):
        assert prompt['target']['lab'] == doc['target_snapshot']['lab']
        assert 'lab_heading' in state['calls'][0][0]['content'] and 'section_index' in state['calls'][0][0]['content']
        return
    # Headings and sentences of an available lab page are anchors; the server computes codepoint offsets.
    assert {'from': field, 'text': state['link']['anchor_text']} in [{k: a[k] for k in ('from', 'text')} for a in prompt['anchors']]
    experience = next(row for row in response.json()['receipts'] if row['evidence']['kind'] == 'experience')
    assert experience['suggestion']['target_evidence'] == [state['quote']] and experience['suggestion']['priority'] == 'high'


@pytest.mark.parametrize('path', PATHS[1:])  # the suggestions route's links: see the next test
@pytest.mark.parametrize('quote', [{**QUOTE, 'page_index': 1}, {**QUOTE, 'section_index': 1}, {**QUOTE, 'page_index': True},
    {**QUOTE, 'section_index': -1}, {**QUOTE, 'field': 'lab_text', 'section_index': 1, 'quote': '实验室方法😀'}, {**QUOTE, 'quote': 'Invented'},
    {**QUOTE, 'paper_index': 0}, {**QUOTE, 'requirement_index': None}, {**QUOTE, 'field': 'lab_url'}])
def test_invalid_target_quote_cannot_be_accepted(endpoint, path, quote):
    client, opp, state = endpoint; state['quote'] = quote
    response = submit(client, path, document(opp)); assert response.status_code == 200
    result = response.json()
    assert result['complete'] is False and result['items'] == []
    assert len(state['calls']) == 1


@pytest.mark.parametrize('link', [
    dict(LINK, anchor_text=None, anchor='t99'),  # no such anchor
    dict(LINK, anchor_text='Methods', term='实验室方法😀'),  # another section's words
    dict(LINK, term='Invented'),
    dict(LINK, term='statistics.berkeley.edu'),  # the page URL is never an anchor
    dict(LINK, relation='narrower'),
])
def test_invalid_lab_link_is_dropped_and_the_line_kept(endpoint, link):
    client, opp, state = endpoint; state['link'] = link
    response = submit(client, PATHS[0], document(opp)); assert response.status_code == 200
    result = response.json()
    assert result['method'] == 'ai' and len(state['calls']) == 1
    assert all(row['suggestion']['links'] == [] and row['suggestion']['target_evidence'] == [] for row in result['receipts'])
    experience = next(row for row in result['receipts'] if row['evidence']['kind'] == 'experience')
    assert (experience['status'], experience['reason_code']) == ('unchanged', 'no_link')


@pytest.mark.parametrize('path', PATHS[1:])  # v6 suggestions never take offsets from the model
@pytest.mark.parametrize('quote,start', [({**QUOTE, 'start': 1}, 0), ({**QUOTE, 'end': 7}, 0),
    ({**QUOTE, 'field': 'lab_text', 'start': 0, 'end': 6, 'quote': '实验室方法😀'}, 25)])
def test_miscounted_lab_quote_is_reanchored_in_both_routes(endpoint, path, quote, start):
    client, opp, state = endpoint; state['quote'] = quote
    result = submit(client, path, document(opp)).json(); assert result['method'] == 'ai'
    rows = [row['suggestion'] for row in result['receipts']] if path.endswith('suggestions') else result['items']
    assert rows and all(row['target_evidence'] == [{**quote, 'start': start, 'end': start + 6}] for row in rows)


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('change', ['body', 'section_order', 'checked_at', 'identity', 'url', 'revoked'])
def test_live_source_change_refuses_before_provider(endpoint, path, change):
    client, opp, state = endpoint; doc = document(opp); snapshot = opp['metadata']['lab_snapshot']
    if change == 'body': snapshot['pages'][0]['sections'][0]['text'] += ' Changed'
    elif change == 'section_order': snapshot['pages'][0]['sections'].reverse()
    elif change == 'checked_at': snapshot['checked_at'] = '2026-09-25T12:00:00Z'
    elif change == 'identity': opp['pi_name'] = 'Another Person'
    elif change == 'url': opp['source_url'] = 'https://statistics.berkeley.edu/people/another-person'
    else: opp['metadata']['lab_refresh'] = {'checked_at': '2026-09-26T12:00:00Z', 'reason': 'identity_mismatch'}
    response = submit(client, path, doc)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'target_changed', response.text
    assert state['calls'] == []


@pytest.mark.parametrize('path', PATHS)
def test_stale_source_is_display_only_not_prompt_or_quote(endpoint, path):
    client, opp, state = endpoint
    opp['metadata']['lab_snapshot']['checked_at'] = (NOW - timedelta(days=31)).isoformat().replace('+00:00', 'Z')
    doc = document(opp); assert doc['target_snapshot']['lab']['status'] == 'stale'
    state['quote'] = {'field': 'description', 'requirement_index': None, 'start': 0, 'end': 12, 'quote': doc['target_snapshot']['description'][:12]}
    response = submit(client, path, doc); assert response.status_code == 200
    if path.endswith('selection-plan'):
        assert response.json()['method'] == 'ai'
        assert json.loads(state['calls'][0][1]['content'])['target']['lab'] == {'version': 1, 'status': 'stale', 'snapshot': None}
    else:
        # A faculty profile's boilerplate is not quotable, so with the lab stale there is nothing to adapt to.
        assert {row['reason_code'] for row in response.json()['receipts']} == {'target_has_no_text'}
        assert state['calls'] == []
    assert not ai.valid_quotes([QUOTE], doc['target_snapshot'])
    assert doc['target_snapshot']['lab']['snapshot'] is not None


@pytest.mark.parametrize('path', PATHS)
def test_full_material_over_target_budget_has_zero_provider_calls(endpoint, path):
    client, opp, state = endpoint
    opp['metadata']['lab_snapshot']['pages'][0]['sections'] = [{'section_id': f's{i + 1}', 'heading': '', 'text': '字' * 4000} for i in range(6)]
    doc = document(opp); assert doc['target_snapshot']['lab']['status'] == 'available'
    response = submit(client, path, doc); assert response.status_code == 200
    assert state['calls'] == []
    assert 'target_too_large' in response.text
    assert len(doc['target_snapshot']['lab']['snapshot']['pages'][0]['sections']) == 6


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('supported', [False, True])
def test_official_research_is_not_student_experience_but_own_source_can_support_it(endpoint, path, supported):
    client, opp, state = endpoint; state['replacement'] = 'I study Python sensors.'
    if path.endswith('suggestions'):
        # v6: leading with the student's own "Python sensors" is a move the contract offers; the
        # lab's "We study Python sensors" as the student's work is not.
        state['link'] = dict(LINK, anchor_text=SENTENCE, term='Python sensors', source='Python sensors', relation='same')
        if supported:
            state['replacement'] = 'Studied Python sensors using NumPy.'
    original = 'Using NumPy, I studied Python sensors.' if supported and path.endswith('suggestions') else (
        'I studied Python sensors using NumPy.' if supported else 'I wrote parser tests using Python.')
    doc = document(opp, original)
    # The UI locale picks the output language; an English line is adapted in English.
    response = submit(client, path, doc, 'en'); assert response.status_code == 200
    result = response.json()
    if path.endswith('suggestions'):
        rows = [row for row in result['receipts'] if row['evidence']['kind'] == 'experience']
        assert rows and all(row['status'] == ('suggested' if supported else 'unchanged') for row in rows)
        if not supported:
            assert all(row['reason_code'] == 'beyond_allowed_edit' and row['suggestion']['proposed_text'] is None for row in rows)
        return
    rows = [row for item in result['items'] for row in item['rewrites']]
    assert rows and all(row['status'] == ('suggested' if supported else 'skipped') for row in rows)
    if not supported: assert all(row['reason_code'] == 'ungrounded_rewrite' for row in rows)


@pytest.mark.parametrize('path', PATHS)
def test_forged_lab_hash_is_rejected_even_after_document_resigning(endpoint, path):
    client, opp, state = endpoint; doc = document(opp)
    doc['target_snapshot']['lab']['snapshot']['snapshot_version'] = 'ls1:' + 'f' * 64
    doc['base']['target_signature'] = fingerprint(doc['target_snapshot'])
    assert submit(client, path, doc).status_code == 422 and state['calls'] == []


@pytest.mark.parametrize('path', PATHS)
def test_v3_saved_snapshot_stays_valid_but_cannot_be_silently_upgraded_for_ai(endpoint, path):
    client, opp, state = endpoint; doc = document(opp)
    doc['target_snapshot'].pop('lab'); doc['target_snapshot']['context_version'] = 3
    doc['base']['target_signature'] = fingerprint(doc['target_snapshot']); before = deepcopy(doc)
    assert validate_document(doc) == before
    response = submit(client, path, doc)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'legacy_target_context'
    assert doc == before and state['calls'] == []
