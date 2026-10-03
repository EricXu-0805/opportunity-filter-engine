"""Real temporary Git/shard publication through material consumers, no network."""
import json
import socket
import subprocess
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
import requests
from fastapi.testclient import TestClient

from backend.lib import target_resume_ai as resume_ai
from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from backend.main import app
from backend.routes import cold_email as email
from backend.routes import target_resume_ai as resume
from scripts import lab_candidate as publisher
from src.collectors.lab_website import build_lab_candidate, canonical_record_sha
from tests.test_email_contact_context import FIRST, post, result
from tests.test_email_lab_context import email_parts
from tests.test_full_target_resume_attribution import _document
from tests.test_lab_context import record
from tests.test_lab_current_template import CURRENT_HTML
from tests.test_target_resume_context_v4 import PATHS, submit


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def flow(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Unexpected network or model call')
    monkeypatch.setattr(requests.Session, 'send', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(email, 'chat_completion', forbidden)
    monkeypatch.setattr(resume_ai, 'chat_completion', forbidden)
    repo = tmp_path / 'repository'; shard = repo / 'data/processed/shards/ucb.json'
    shard.parent.mkdir(parents=True)
    target = record()
    target.update(title='Research methods', organization='UC Berkeley', opportunity_type='research',
                  description_clean='Research using Python.', eligibility={'skills_required': ['Python']})
    target['metadata'].update(is_active=True, verification_scope='profile', contact_identity_status='verified',
                              research_snapshot={'unrelated_saved_original': 'unchanged'},
                              user_notes={'text': 'Keep original note 🧪'})
    shard.write_text(json.dumps([target]))
    other = shard.with_name('mit.json'); other.write_text(json.dumps([{'id':'other-record','school':'mit','metadata':{'note':'unchanged'}}]))
    git(repo, 'init', '-q'); git(repo, 'config', 'user.name', 'Local Test')
    git(repo, 'config', 'user.email', 'fixture@invalid.test'); git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'fixture base')
    def current():
        return json.loads(shard.read_text())[0]
    for module in (email, resume):
        monkeypatch.setattr(module, 'load_opportunities_by_id', lambda: {target['id']: current()})
        monkeypatch.setattr(module, 'is_configured', lambda: True)
    monkeypatch.setattr(email, 'corpus_version', lambda: git(repo, 'rev-parse', 'HEAD'))
    monkeypatch.setattr(resume_ai.llm_budget, 'exhausted', lambda: False)
    monkeypatch.setenv('OFE_COLD_EMAIL_NDRAFT', '1'); monkeypatch.setenv('OFE_COLD_EMAIL_CRITIQUE', '0')
    async def anonymous(_authorization):
        return None
    monkeypatch.setattr(email, 'authenticated_uid', anonymous)
    state = {'repo':repo, 'shard':shard, 'other':other, 'target':target, 'current':current,
             'clock':datetime.now(UTC)-timedelta(minutes=10), 'index':0, 'client':TestClient(app)}
    def publish(*, html=CURRENT_HTML, error=None):
        state['index'] += 1; state['clock'] += timedelta(seconds=1)
        records = json.loads(shard.read_text())
        def fetch(url):
            return (None,error) if error else ({'requested_url':url,'source_url':url,'html':html.encode()},None)
        envelope = build_lab_candidate(records, [target['id']], now=state['clock'], fetch=fetch)
        output = tmp_path / f"candidate-{state['index']}"
        manifest = publisher.build_candidate(envelope, repository_root=repo, base_sha=git(repo,'rev-parse','HEAD'),
                                             source_shards=['ucb'], output=output)
        digest = canonical_record_sha(envelope)
        assert manifest['candidate']['sha256'] == digest
        publisher.validate_candidate(output, repository_root=repo, expected_candidate_sha256=digest)
        applied = publisher.promote_candidate(output, repository_root=repo, expected_candidate_sha256=digest)
        assert applied['status'] == 'applied'
        frozen = shard.read_bytes()
        assert publisher.promote_candidate(output, repository_root=repo, expected_candidate_sha256=digest)['status'] == 'already_applied'
        assert shard.read_bytes() == frozen
        git(repo,'add','.');git(repo,'commit','-qm',f"test publication {state['index']}")
        return current()
    state['publish'] = publish
    return state


def test_collected_applied_fields_reach_both_writing_contexts_without_changing_student_or_papers(flow):
    other_before = flow['other'].read_bytes(); before = deepcopy(flow['target'])
    current = flow['publish'](); public = project_public_detail(current)
    assert public['lab_context']['status'] == 'available'
    assert current['metadata']['research_snapshot'] == before['metadata']['research_snapshot']
    assert current['metadata']['user_notes'] == before['metadata']['user_notes']
    assert {k:v for k,v in current.items() if k!='metadata'} == {k:v for k,v in before.items() if k!='metadata'}
    assert flow['other'].read_bytes() == other_before
    parts = email_parts(public); brief = email._render_professor_brief(parts, public)
    doc = _document(['I wrote parser tests using Python.'], current)
    assert doc['target_snapshot']['lab'] == public['lab_context']
    assert parts['contact_paper_reading'] == ''
    for section in public['lab_context']['snapshot']['pages'][0]['sections']:
        assert section['text'] in brief
        assert section['text'] not in email._render_student_brief(parts)
        assert section['text'] not in json.dumps(doc['base_snapshot'])
    assert 'lab_refresh' not in json.dumps(public) and 'lab_snapshot' not in json.dumps(public)


@pytest.mark.parametrize('change', ['text','identity_revoked'])
def test_applied_source_change_rejects_prior_email_and_resume_requests_before_provider(flow, change):
    original = flow['publish'](); public = project_public_detail(original)
    old_version = writing_target_version(public)
    doc = _document(['I wrote parser tests using Python.'], original); frozen_doc = deepcopy(doc)
    html = (CURRENT_HTML.replace('Only observational studies.', 'Only computational studies.') if change=='text'
            else CURRENT_HTML.replace('>Peng Ding<','>Other Person<'))
    updated = flow['publish'](html=html)
    assert writing_target_version(project_public_detail(updated)) != old_version
    for path in ['', 'variants', 'stream', 'refine']:
        response = post(flow['client'], path, FIRST, opportunity_id=original['id'], expected_target_version=old_version)
        assert response.status_code == 409, response.text
        assert response.json()['detail']['code'] == 'WRITING_TARGET_CHANGED'
    for path in PATHS:
        response = submit(flow['client'], path, doc)
        assert response.status_code == 409, response.text
        assert response.json()['detail']['code'] == 'target_changed'
    assert doc == frozen_doc


def test_failure_preserves_source_but_known_revocation_survives_later_outage_until_verified_recovery(flow):
    original = flow['publish'](); snapshot = deepcopy(original['metadata']['lab_snapshot'])
    failed = flow['publish'](error='request_failed')
    assert failed['metadata']['lab_snapshot'] == snapshot
    assert project_public_detail(failed)['lab_context']['status'] == 'available'
    assert writing_target_version(project_public_detail(failed)) == writing_target_version(project_public_detail(original))
    revoked = flow['publish'](html=CURRENT_HTML.replace('>Peng Ding<','>Other Person<'))
    assert project_public_detail(revoked)['lab_context']['status'] == 'unavailable'
    failed_again = flow['publish'](error='http_error')
    assert failed_again['metadata']['lab_snapshot'] == snapshot
    assert failed_again['metadata']['lab_refresh']['identity_revoked_at'] == revoked['metadata']['lab_refresh']['identity_revoked_at']
    assert project_public_detail(failed_again)['lab_context']['status'] == 'unavailable'
    recovered = flow['publish']()
    assert project_public_detail(recovered)['lab_context']['status'] == 'available'
    assert 'identity_revoked_at' not in recovered['metadata']['lab_refresh']


def test_applied_source_is_sent_whole_to_controlled_email_provider(flow, monkeypatch):
    target=flow['publish'](); calls=[]
    def model(messages, **kwargs):
        calls.append(deepcopy(messages))
        return 'Subject: Research inquiry\n\nDear Professor Ding,\n\nCould I ask about your research?\n\nThank you for your time.'
    monkeypatch.setattr(email,'chat_completion',model)
    reply = result(post(flow['client'],'',FIRST,opportunity_id=target['id'],engine='ai'), '')
    assert calls and reply['pipeline_version']=='w12.20', reply
    text = calls[0][1]['content']
    for section in target['metadata']['lab_snapshot']['pages'][0]['sections']:
        assert section['text'] in text
    assert 'I read' not in reply['body']


@pytest.mark.parametrize('change', ['stale', 'invalid', 'revoked', 'invalid_public', 'unavailable_public', 'generic'])
def test_website_only_signal_does_not_authorize_invalid_stale_or_generic_sources(flow, change):
    from src.recommender.cold_email import has_source_backed_target_evidence
    target = flow['publish']()
    assert has_source_backed_target_evidence(target)
    assert has_source_backed_target_evidence(project_public_detail(target))
    if change == 'stale':
        target['metadata']['lab_snapshot']['checked_at'] = '2020-01-01T00:00:00Z'
    elif change == 'invalid':
        target['metadata']['lab_snapshot']['pages'][0]['sections'][0]['text'] = 'x' * 4001
    elif change == 'revoked':
        target['metadata']['lab_refresh'] = {'checked_at': target['metadata']['lab_snapshot']['checked_at'], 'reason': 'identity_mismatch'}
    elif change == 'invalid_public':
        target['lab_context'] = {'version': 1, 'status': 'available', 'snapshot': {'forged': True}}
    elif change == 'unavailable_public':
        target['lab_context'] = {'version': 1, 'status': 'unavailable', 'snapshot': None}
    else:
        target['metadata']['lab_snapshot']['pages'][0]['sections'] = [{'section_id': 's1', 'heading': 'Research areas', 'text': 'Computer Science'}]
    assert not has_source_backed_target_evidence(target)
    if change not in ('invalid_public', 'unavailable_public'):
        assert not has_source_backed_target_evidence(project_public_detail(target))


@pytest.mark.parametrize('path', PATHS)
def test_applied_source_reaches_both_resume_provider_prompts_with_exact_quotes(flow, monkeypatch, path):
    target = flow['publish'](); calls=[]
    doc = _document(['I wrote parser tests using Python.'], target)
    quote = {'field':'lab_text','page_index':0,'section_index':0,'start':0,'end':6,'quote':'Causal'}
    def model(messages, **kwargs):
        calls.append(deepcopy(messages)); data=json.loads(messages[1]['content'])
        if 'units' in data:
            return json.dumps({'units':[{'unit_id':u['unit_id'],'priority':'high','reason':'Relevant source topic.', 'target_evidence':[quote], 'proposed_text':None} for u in data['units']]})
        return json.dumps({'items':[{'section_id':b['section_id'],'block_id':b['block_id'],'action':'keep','reason':'Relevant source topic.', 'target_evidence':[quote], 'source_evidence':[{'unit_id':b['lines'][0]['unit_id'],'start':0,'end':len(b['lines'][0]['original']),'quote':b['lines'][0]['original']}], 'rewrites':[]} for b in data['blocks']]})
    monkeypatch.setattr(resume_ai,'chat_completion',model)
    original=deepcopy(doc); response=submit(flow['client'],path,doc)
    assert response.status_code==200,response.text
    assert response.json()['method']=='ai' and len(calls)==1
    prompt=json.loads(calls[0][1]['content'])
    assert prompt['target']['lab']==project_public_detail(target)['lab_context']
    assert doc==original
