"""Website-chain publication through both writing consumers, with no live providers."""
import json
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
import requests
from fastapi.testclient import TestClient

from backend.lib import target_resume_ai as ai
from backend.lib.evidence_map import term_span
from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from backend.main import app
from backend.routes import cold_email as email
from backend.routes import target_resume_ai as resume
from scripts import lab_candidate as publisher
from src.collectors.lab_website import build_lab_candidate, canonical_record_sha
from tests.lab_nielsen_fixtures import nielsen_pages, nielsen_record
from tests.test_email_contact_context import FIRST, post
from tests.test_full_target_resume_attribution import _document
from tests.test_lab_publication_consumers import git
from tests.test_target_resume_context_v4 import PATHS, submit


@pytest.fixture
def chain_flow(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Unexpected network or provider call')
    monkeypatch.setattr(requests.Session, 'send', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(email, 'chat_completion', forbidden)
    monkeypatch.setattr(ai, 'chat_completion', forbidden)
    repo = tmp_path / 'repository'
    shard = repo / 'data/processed/shards/ucb.json'
    shard.parent.mkdir(parents=True)
    original = nielsen_record()
    original.update(title='Research methods', organization='UC Berkeley', opportunity_type='research',
                    description_clean='Research using Python.', eligibility={'skills_required': ['Python']})
    original.setdefault('metadata', {}).update(is_active=True, verification_scope='profile', contact_identity_status='verified')
    shard.write_text(json.dumps([original]))
    git(repo, 'init', '-q'); git(repo, 'config', 'user.name', 'Local Test')
    git(repo, 'config', 'user.email', 'fixture@invalid.test'); git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'fixture base')
    def current():
        return json.loads(shard.read_text())[0]
    for module in (email, resume):
        monkeypatch.setattr(module, 'load_opportunities_by_id', lambda: {original['id']: current()})
        monkeypatch.setattr(module, 'is_configured', lambda: True)
    monkeypatch.setattr(email, 'corpus_version', lambda: git(repo, 'rev-parse', 'HEAD'))
    monkeypatch.setattr(ai.llm_budget, 'exhausted', lambda: False)
    async def anonymous(_authorization):
        return None
    monkeypatch.setattr(email, 'authenticated_uid', anonymous)
    state = {'clock': datetime.now(UTC)-timedelta(minutes=10), 'index': 0, 'client': TestClient(app)}
    def publish(pages=None):
        pages = nielsen_pages() if pages is None else pages
        state['index'] += 1; state['clock'] += timedelta(seconds=1)
        def fetch(url):
            return {'requested_url': url, 'source_url': url, 'html': pages[url]}, None
        envelope = build_lab_candidate([current()], [original['id']], now=state['clock'], fetch=fetch)
        output = tmp_path / f"candidate-{state['index']}"
        publisher.build_candidate(envelope, repository_root=repo, base_sha=git(repo, 'rev-parse', 'HEAD'),
                                  source_shards=['ucb'], output=output)
        digest = canonical_record_sha(envelope)
        publisher.validate_candidate(output, repository_root=repo, expected_candidate_sha256=digest)
        assert publisher.promote_candidate(output, repository_root=repo, expected_candidate_sha256=digest)['status']=='applied'
        assert publisher.promote_candidate(output, repository_root=repo, expected_candidate_sha256=digest)['status']=='already_applied'
        git(repo, 'add', '.'); git(repo, 'commit', '-qm', f"publication {state['index']}")
        return current()
    state['publish'] = publish
    return state


@pytest.mark.parametrize('path', PATHS)
def test_published_chain_and_tenth_section_reach_both_resume_providers(chain_flow, monkeypatch, path):
    target = chain_flow['publish']()
    public = project_public_detail(target)
    assert public['lab_context']['snapshot']['version']==2
    doc = _document(['I wrote parser tests using Python.'], target); frozen = deepcopy(doc)
    text = doc['target_snapshot']['lab']['snapshot']['pages'][1]['sections'][9]['text']
    quote = {'field': 'lab_text', 'page_index': 1, 'section_index': 9, 'start': 0, 'end': len(text), 'quote': text}
    calls, linked = [], {}
    def model(messages, **kwargs):
        calls.append(deepcopy(messages)); data = json.loads(messages[1]['content'])
        if 'units' in data:  # full-target-v6 links a few words of a server-cut anchor from the tenth section
            anchor = next(a for a in data['anchors'] if a['from'] == 'lab_text' and a['text'] in text)
            words = anchor['text'].split()
            linked['term'] = next(' '.join(words[i:i + n]) for n in range(min(6, len(words)), 0, -1)
                                  for i in range(len(words) - n + 1) if term_span(anchor['text'], ' '.join(words[i:i + n])))
            link = {'id': 'L1', 'anchor': anchor['id'], 'term': linked['term'], 'source': 'Python', 'relation': 'broader'}
            return json.dumps({'units': [{'unit_id': u['unit_id'], 'priority': 'high', 'reason': 'topic_relevance', 'links': [link],
                'decision': 'keep', 'ops': [], 'text': None, 'keep_reason': 'no_link'} for u in data['units']]})
        return json.dumps({'items': [{'section_id': b['section_id'], 'block_id': b['block_id'], 'action': 'keep',
            'reason': 'Related official research topic.', 'target_evidence': [quote],
            'source_evidence': [{'unit_id': b['lines'][0]['unit_id'], 'start': 0, 'end': len(b['lines'][0]['original']),
                                 'quote': b['lines'][0]['original']}], 'rewrites': []} for b in data['blocks']]})
    monkeypatch.setattr(ai, 'chat_completion', model)
    response = submit(chain_flow['client'], path, doc)
    assert response.status_code==200, response.text
    data=response.json(); assert data['method']=='ai' and len(calls)==1
    if path.endswith('selection-plan'):
        assert json.loads(calls[0][1]['content'])['target']['lab']==public['lab_context']
        assert '"page_index": 1' in json.dumps(data) and text in json.dumps(data)
    else:
        prompt = json.loads(calls[0][1]['content'])
        assert any(a['from'] == 'lab_text' and a['text'] in text for a in prompt['anchors'])
        assert '"page_index": 1' in json.dumps(data) and linked['term'] in json.dumps(data) and linked['term'] in text
    assert doc==frozen and text not in json.dumps(doc['base_snapshot'])


@pytest.mark.parametrize('change', ['research', 'identity', 'link'])
def test_published_change_revokes_prior_all_email_and_both_resume_requests(chain_flow, change):
    target = chain_flow['publish'](); old = writing_target_version(project_public_detail(target))
    doc = _document(['I wrote parser tests using Python.'], target); frozen = deepcopy(doc)
    pages = nielsen_pages()
    if change=='research':
        url='https://nielsen-lab.github.io/research/'
        pages[url] = pages[url].replace(b'</body>', b'<!-- Changed source version -->\n</body>')
    elif change=='identity':
        url='https://nielsen-lab.github.io/team/'
        pages[url] = pages[url].replace(b'Rasmus Nielsen', b'Another Person')
    else:
        url='https://statistics.berkeley.edu/people/rasmus-nielsen'
        pages[url] = pages[url].replace(b'href="https://nielsen-lab.github.io"', b'href="https://other-lab.example/"')
    updated = chain_flow['publish'](pages)
    assert writing_target_version(project_public_detail(updated))!=old
    for path in ['', 'variants', 'stream', 'refine']:
        response=post(chain_flow['client'], path, FIRST, opportunity_id=target['id'], expected_target_version=old)
        assert response.status_code==409 and response.json()['detail']['code']=='WRITING_TARGET_CHANGED', response.text
    for path in PATHS:
        response=submit(chain_flow['client'], path, doc)
        assert response.status_code==409 and response.json()['detail']['code']=='target_changed', response.text
    assert doc==frozen
