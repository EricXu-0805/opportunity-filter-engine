"""Exact research snapshots and provider-mocked full-resume routes; no external calls."""
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.lib import public_opportunity_detail as public_detail
from backend.lib import public_projection
from backend.lib import target_resume_ai as ai
from backend.lib.target_resume_ai_validation import fingerprint, validate_document
from backend.lib.target_resume_context import public_target_context, target_context_character_count
from backend.main import app
from backend.routes import target_resume_ai as route
from src.research_context import research_context_for
from tests.test_full_target_resume_attribution import _document

GOLDEN = json.loads((Path(__file__).parent / 'fixtures/target-resume-context-v3-golden.json').read_text())
PATHS = ['/api/tailor/full-target/suggestions', '/api/tailor/full-target/selection-plan']
NOW = datetime(2026, 9, 26, 18, tzinfo=UTC)
PAPER = {'field': 'paper_title', 'paper_index': 0, 'start': 0, 'end': 6, 'quote': '机器人😀研究'}
# The suggestions route (full-target-v6) links to server-cut anchors; the mock finds one by its text.
# The selection plan (full-target-plan-v4) still quotes target fields by offset (PAPER).
LINK = {'anchor_text': '机器人😀研究', 'term': '机器人😀研究', 'source': 'Python', 'relation': 'broader'}


def v6_row(unit, anchors, state):
    link = state['link']
    ident = next((anchor['id'] for anchor in anchors if anchor['text'] == link.get('anchor_text')), link.get('anchor', 't99'))
    rewrite = state['replacement'] is not None and unit['kind'] == 'experience'
    return {'unit_id': unit['unit_id'], 'priority': 'high', 'reason': 'topic_relevance',
            'links': [{'id': 'L1', 'anchor': ident, 'term': link['term'], 'source': link['source'], 'relation': link['relation']}],
            'decision': 'rewrite' if rewrite else 'keep', 'ops': [{'op': 'verb_first'}] if rewrite else [],
            'text': state['replacement'] if rewrite else None, 'keep_reason': None if rewrite else 'no_link'}


def test_shared_v3_golden_complete_projection_signature_and_budget():
    public = deepcopy(GOLDEN['public_opportunity'])
    target = public_target_context(public)
    target.pop('lab')
    target['context_version'] = 3
    assert target == GOLDEN['draft']['target_snapshot']
    assert fingerprint(target) == GOLDEN['draft']['base']['target_signature']
    assert target_context_character_count(target) == GOLDEN['target_character_count']
    assert validate_document(GOLDEN['draft']) == GOLDEN['draft']
    assert fingerprint(GOLDEN['draft']) == GOLDEN['document_signature']
    assert public == GOLDEN['public_opportunity']


@pytest.fixture
def endpoint(monkeypatch):
    snapshot = deepcopy(GOLDEN['draft']['target_snapshot']['research']['snapshot'])
    snapshot.pop('snapshot_version')
    opp = {'id': 'research-target', 'school': 'uiuc', 'title': 'Research', 'organization': 'UIUC',
           'pi_name': snapshot['identity_name'], 'source_url': snapshot['record_source_url'],
           'description_clean': 'Python research.', 'source_type': 'campus_program', 'opportunity_type': 'research',
           'eligibility': {'skills_required': ['Python']}, 'metadata': {'is_active': True,
           'publication_attribution_status': 'verified_author_id', 'publication_author_id': snapshot['author_id'],
           'publication_institution_id': snapshot['institution_id'], 'works_gate': 3, 'research_snapshot': snapshot}}
    monkeypatch.setattr(public_detail, 'research_context_for', lambda value: research_context_for(value, now=NOW))
    monkeypatch.setattr(public_projection, 'research_context_for', lambda value: research_context_for(value, now=NOW))
    monkeypatch.setattr(route, 'load_opportunities_by_id', lambda: {opp['id']: opp})
    monkeypatch.setattr(route, 'is_configured', lambda: True)
    monkeypatch.setattr(ai.llm_budget, 'exhausted', lambda: False)
    state = {'quote': deepcopy(PAPER), 'link': dict(LINK), 'replacement': None, 'calls': []}

    def model(messages, **kwargs):
        state['calls'].append(deepcopy(messages))
        data = json.loads(messages[1]['content'])
        quote = state['quote']
        if 'units' in data:
            return json.dumps({'units': [v6_row(unit, data['anchors'], state) for unit in data['units']]}, ensure_ascii=False)
        return json.dumps({'items': [{'section_id': block['section_id'], 'block_id': block['block_id'],
            'action': 'compress' if state['replacement'] else 'keep', 'reason': 'Related research topic.', 'target_evidence': [quote],
            'source_evidence': [{'unit_id': block['lines'][0]['unit_id'], 'start': 0, 'end': len(block['lines'][0]['original']),
                                 'quote': block['lines'][0]['original']}],
            'rewrites': [{'unit_id': line['unit_id'], 'proposed_text': state['replacement']} for line in block['lines']
                         if line['evidence']['kind'] == 'experience' and state['replacement']]}
            for block in data['blocks']]}, ensure_ascii=False)

    monkeypatch.setattr(ai, 'chat_completion', model)
    return TestClient(app), opp, state


def document(opp):
    return _document(['I wrote parser tests using Python.'], opp)


def submit(client, path, doc):
    request = {'version': 1, 'request_id': 'research-resume', 'locale': 'zh', 'include_check_version': True, 'draft': doc, 'document_signature': fingerprint(doc)}
    if path.endswith('suggestions'):
        request['selected_unit_ids'] = [unit['unit_id'] for unit in ai.units_for(doc)[0]]
    else:
        request['options'] = {'target_pages': 1}
    return client.post(path, json=request)


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('field,quote,start,end', [('paper_title', '机器人😀研究', 0, 6), ('paper_abstract', '研究😀', 25, 28)])
def test_available_exact_codepoint_quotes_survive_both_real_routes(endpoint, path, field, quote, start, end):
    client, opp, state = endpoint
    doc = document(opp)
    assert doc['target_snapshot']['research']['status'] == 'available'
    state['quote'] = {'field': field, 'paper_index': 0, 'start': start, 'end': end, 'quote': quote}
    state['link'] = dict(LINK, term=quote)
    before = deepcopy(doc)
    response = submit(client, path, doc)
    assert response.status_code == 200, response.text
    assert response.json()['method'] == 'ai'
    assert response.json()['check_version'] == 'target-resume-source-checks-v4'
    assert len(state['calls']) == 1 and doc == before
    prompt = json.loads(state['calls'][0][1]['content'])
    if path.endswith('selection-plan'):
        assert prompt['target']['research'] == doc['target_snapshot']['research']
        assert 'paper_index' in state['calls'][0][0]['content'] and 'paper_abstract' in state['calls'][0][0]['content']
        assert 'example' in state['calls'][0][0]['content']
        return
    # Paper titles are anchors, with codepoint offsets the server computes; abstracts never are.
    assert {'from': 'paper_title', 'text': '机器人😀研究'} in [{k: a[k] for k in ('from', 'text')} for a in prompt['anchors']]
    assert '证据完整保留' not in state['calls'][0][1]['content']
    experience = next(row for row in response.json()['receipts'] if row['evidence']['kind'] == 'experience')
    expected = [state['quote']] if field == 'paper_title' else []
    assert experience['suggestion']['target_evidence'] == expected
    assert experience['suggestion']['priority'] == ('high' if expected else 'normal')


@pytest.mark.parametrize('path', PATHS)
@pytest.mark.parametrize('change', ['title', 'abstract', 'author', 'order', 'checked_at', 'revoked', 'stale'])
def test_source_change_refuses_before_provider(endpoint, path, change):
    client, opp, state = endpoint
    doc = document(opp)
    source = opp['metadata']['research_snapshot']
    if change in ('title', 'abstract'):
        source['works'][0][change] += ' Changed'
    elif change == 'author':
        opp['metadata']['publication_author_id'] = 'https://openalex.org/A124'
    elif change == 'order':
        source['works'].reverse()
    elif change == 'checked_at':
        source['checked_at'] = '2026-09-25T12:00:00Z'
    elif change == 'revoked':
        opp['metadata']['publication_attribution_status'] = 'name_match'
    else:
        source['checked_at'] = '2026-07-01T12:00:00Z'
    response = submit(client, path, doc)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'target_changed'
    assert state['calls'] == []


@pytest.mark.parametrize('path', PATHS[1:])  # the suggestions route's links: see the next test
@pytest.mark.parametrize('quote', [dict(PAPER, paper_index=1), dict(PAPER, paper_index=-1), dict(PAPER, requirement_index=None),
                                    dict(PAPER, end=13, quote='Second paper'), dict(PAPER, field='paper_abstract', paper_index=1)])
def test_bad_research_quote_is_not_accepted(endpoint, path, quote):
    client, opp, state = endpoint
    state['quote'] = quote
    response = submit(client, path, document(opp))
    assert response.status_code == 200
    result = response.json()
    assert result['method'] == 'unavailable' and len(state['calls']) == 1
    assert result['items'] == [] and result['reason_code'] == 'no_target_evidence'


@pytest.mark.parametrize('link', [
    dict(LINK, anchor_text=None, anchor='t99'),  # no such anchor
    dict(LINK, term='Second paper'),  # another paper's words
    dict(LINK, anchor_text='Second paper without abstract'),  # this paper's words in another title
    dict(LINK, term='研究😀证据完整保留'),  # an abstract is never quotable
    dict(LINK, relation='narrower'),
])
def test_a_bad_research_link_is_dropped_and_the_line_kept(endpoint, link):
    client, opp, state = endpoint
    state['link'] = link
    response = submit(client, PATHS[0], document(opp))
    assert response.status_code == 200
    result = response.json()
    assert result['method'] == 'ai' and len(state['calls']) == 1
    assert all(row['suggestion']['links'] == [] and row['suggestion']['target_evidence'] == [] for row in result['receipts'])
    experience = next(row for row in result['receipts'] if row['evidence']['kind'] == 'experience')
    assert (experience['status'], experience['reason_code']) == ('unchanged', 'no_link')


@pytest.mark.parametrize('path', PATHS[1:])  # v6 suggestions never take offsets from the model
@pytest.mark.parametrize('quote,start', [(dict(PAPER, end=7), 0), (dict(PAPER, field='paper_abstract', start=0, end=2, quote='研究😀'), 25)])
def test_miscounted_research_quote_is_reanchored_in_both_routes(endpoint, path, quote, start):
    client, opp, state = endpoint
    state['quote'] = quote
    result = submit(client, path, document(opp)).json()
    assert result['method'] == 'ai'
    rows = [row['suggestion'] for row in result['receipts']] if path.endswith('suggestions') else result['items']
    assert rows and all(row['target_evidence'] == [dict(quote, start=start, end=start + len(quote['quote']))] for row in rows)


@pytest.mark.parametrize('path', PATHS)
def test_stale_remains_signed_and_displayable_but_is_excluded_from_model(endpoint, path):
    client, opp, state = endpoint
    opp['metadata']['research_snapshot']['checked_at'] = '2026-07-01T12:00:00Z'
    doc = document(opp)
    assert doc['target_snapshot']['research']['status'] == 'stale'
    state['quote'] = {'field': 'requirement', 'requirement_index': 0, 'start': 0, 'end': 6, 'quote': 'Python'}
    state['link'] = dict(LINK, anchor_text='Python', term='Python', relation='same')
    response = submit(client, path, doc)
    assert response.status_code == 200 and response.json()['method'] == 'ai'
    prompt = json.loads(state['calls'][0][1]['content'])
    if path.endswith('selection-plan'):
        assert prompt['target']['research'] == {'version': 1, 'status': 'stale', 'snapshot': None}
    else:
        assert all(anchor['from'] != 'paper_title' for anchor in prompt['anchors'])
        assert '机器人😀研究' not in state['calls'][0][1]['content']
    assert '研究😀证据完整保留' not in state['calls'][0][1]['content']
    assert doc['target_snapshot']['research']['snapshot'] is not None


@pytest.mark.parametrize('path', PATHS)
def test_complete_research_counts_toward_budget_without_first_n_or_truncation(endpoint, path):
    client, opp, state = endpoint
    works = opp['metadata']['research_snapshot']['works']
    for work in works:
        work['abstract'] = '研' * 12000
        work['abstract_status'] = 'present'
    doc = document(opp)
    response = submit(client, path, doc)
    assert response.status_code == 200 and response.json()['method'] == 'unavailable'
    assert state['calls'] == [] and len(doc['target_snapshot']['research']['snapshot']['works'][1]['abstract']) == 12000


@pytest.mark.parametrize('path', PATHS)
def test_target_research_cannot_become_student_accomplishment(endpoint, path):
    client, opp, state = endpoint
    state['replacement'] = 'I study Python sensors.'
    response = submit(client, path, document(opp))
    assert response.status_code == 200
    result = response.json()
    if path.endswith('suggestions'):
        experience = next(row for row in result['receipts'] if row['evidence']['kind'] == 'experience')
        assert experience['status'] == 'unchanged' and experience['reason_code'] == 'beyond_allowed_edit'
        assert experience['suggestion']['proposed_text'] is None
    else:
        assert all(item['rewrites'] == [] for item in result['items']) and state['replacement'] not in response.text
    assert len(state['calls']) == 1


@pytest.mark.parametrize('path', PATHS)
def test_old_v2_document_is_readable_but_not_upgraded_for_provider(endpoint, path):
    client, opp, state = endpoint
    doc = document(opp)
    doc['target_snapshot'].pop('research')
    doc['target_snapshot'].pop('lab')
    doc['target_snapshot']['context_version'] = 2
    doc['base']['target_signature'] = fingerprint(doc['target_snapshot'])
    assert validate_document(doc) == doc
    response = submit(client, path, doc)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'legacy_target_context'
    assert state['calls'] == []


@pytest.mark.parametrize('path', PATHS)
def test_forged_snapshot_hash_is_rejected_even_with_rehashed_outer_document(endpoint, path):
    client, opp, state = endpoint
    doc = document(opp)
    doc['target_snapshot']['research']['snapshot']['snapshot_version'] = 'rs1:' + 'a' * 64
    doc['base']['target_signature'] = fingerprint(doc['target_snapshot'])
    response = submit(client, path, doc)
    assert response.status_code == 422 and state['calls'] == []
