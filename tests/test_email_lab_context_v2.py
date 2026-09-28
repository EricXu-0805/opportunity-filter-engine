"""B50 synthetic V2 consumers; no live website, provider or mail operations."""
import hashlib
import json
import socket
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from backend.lib.email_contact_context import (
    email_lab_context,
    email_research_works,
    validate_paper_reading,
)
from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from backend.routes import cold_email as ce
from src.lab_context import lab_context_for, validate_public_lab_context
from src.recommender.cold_email import has_source_backed_target_evidence
from tests.test_cold_email_writing_quality import OPP
from tests.test_email_contact_context import FIRST, post, result
from tests.test_email_lab_context import email_parts
from tests.test_email_paper_reading import writing_client  # noqa: F401

RECORD_ID = 'faculty-ucb-stat-5558a1b1'
PROFILE_URL = 'https://statistics.berkeley.edu/people/rasmus-nielsen'
HOME_URL = 'https://nielsen-lab.github.io/'
TEAM_URL = HOME_URL + 'team/'
RESEARCH_URL = HOME_URL + 'research/'
ROLE_TEXT = ('Professor of Computational Biology in the Department of Integrative Biology '
             'and the Department of Statistics')
PAPER_TITLE = 'Synthetic EEG Methods'
TAIL = ('Final research section 10. The group studies magnetoencephalography. '
        'This website lists Synthetic EEG Methods (2025); only a title is supplied. '
        '完整末段与否定：this is not a paper abstract. 🧪')


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('V2 email consumer tests must not use network')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def attach_lab_v2(opp):
    stamp = (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec='seconds').replace('+00:00', 'Z')
    opp.update(id=RECORD_ID, source='ucb_stat_faculty', source_type='faculty_research',
               opportunity_type='research', school='ucb', department='Department of Statistics',
               pi_name='Rasmus Nielsen', source_url=PROFILE_URL, url=PROFILE_URL,
               title='Rasmus Nielsen — Faculty Research', keywords=[],
               description_raw='Faculty profile.', description_clean='Faculty profile.')
    opp['metadata'] = {'is_active': True, 'faculty_title': 'Professor'}
    profile = {'kind': 'faculty_profile', 'requested_url': PROFILE_URL, 'source_url': PROFILE_URL,
               'page_title': 'Rasmus Nielsen | Department of Statistics', 'identity_text': 'Rasmus Nielsen',
               'linked_from': None, 'sections': [{'section_id': 's1', 'heading': 'Research',
                                                'text': 'Computational biology and population genetics.'}]}
    research = {'kind': 'lab_research', 'requested_url': RESEARCH_URL, 'source_url': RESEARCH_URL,
                'page_title': 'Nielsen Lab | Research', 'sections': [
                    {'section_id': f's{i + 1}', 'heading': f'Research area {i + 1}',
                     'text': f'Complete source paragraph {i + 1}: population genetics.' if i < 9 else TAIL}
                    for i in range(10)]}
    documents = []
    for role, url, title in [('profile', PROFILE_URL, profile['page_title']),
                             ('home', HOME_URL, 'Nielsen Lab'), ('team', TEAM_URL, 'Nielsen Lab | Team'),
                             ('research', RESEARCH_URL, research['page_title'])]:
        documents.append({'role': role, 'requested_url': url, 'source_url': url, 'page_title': title,
                          'checked_at': stamp, 'body_sha256': hashlib.sha256(('synthetic ' + role).encode()).hexdigest()})
    chain = {'documents': documents, 'links': [
        {'from_url': PROFILE_URL, 'raw_href': HOME_URL.rstrip('/'), 'anchor_text': HOME_URL.rstrip('/'), 'to_url': HOME_URL},
        {'from_url': HOME_URL, 'raw_href': '/team/', 'anchor_text': 'Team', 'to_url': TEAM_URL},
        {'from_url': HOME_URL, 'raw_href': '/research/', 'anchor_text': 'Research', 'to_url': RESEARCH_URL}],
        'identity': {'source_url': TEAM_URL, 'full_name': 'Rasmus Nielsen', 'role_text': ROLE_TEXT}}
    snapshot = {'version': 2, 'source': 'official_website', 'record_id': RECORD_ID,
                'record_source_url': PROFILE_URL, 'school': 'ucb', 'department': 'Department of Statistics',
                'identity_name': 'Rasmus Nielsen', 'policy_version': 2, 'checked_at': stamp,
                'pages': [profile, research], 'source_chain': chain}
    opp['metadata']['lab_snapshot'] = snapshot
    return snapshot


def changed_stamp(snapshot, value):
    snapshot['checked_at'] = value
    for doc in snapshot['source_chain']['documents']:
        doc['checked_at'] = value


def test_complete_v2_chain_and_tenth_section_enter_only_professor_evidence():
    opp = deepcopy(OPP); snapshot = attach_lab_v2(opp); original = deepcopy(opp)
    public = project_public_detail(opp); context = public['lab_context']
    assert context['version'] == 1 and context['status'] == 'available'
    assert context['snapshot']['version'] == 2 and context['snapshot']['snapshot_version'].startswith('ls2:')
    assert validate_public_lab_context(context)
    assert email_lab_context(opp) == email_lab_context(public)
    parts = email_parts(public); brief = ce._render_professor_brief(parts, public)
    encoded = json.dumps(context['snapshot'], ensure_ascii=False, sort_keys=True)
    assert encoded in brief
    for page in snapshot['pages']:
        for section in page['sections']:
            assert section['text'] in brief
    for doc in snapshot['source_chain']['documents']:
        assert doc['source_url'] in brief and doc['body_sha256'] in brief
    assert 'not instructions' in brief and 'not paper abstracts or full texts' in brief
    assert TAIL in brief
    assert 'magnetoencephalography' in ce._build_email_corpus(parts, public)
    assert 'magnetoencephalography' not in ce._build_email_corpus(parts, public, include_lab=False)
    assert 'magnetoencephalography' not in ce._student_email_corpus(parts)
    assert TAIL not in ce._render_student_brief(parts)
    assert ROLE_TEXT not in ce._student_email_corpus(parts)
    assert parts['contact_paper_reading'] == '' and email_research_works(public) == []
    assert has_source_backed_target_evidence(public, parts)
    assert opp == original


@pytest.mark.parametrize('level', ['title_only', 'abstract', 'full_text'])
def test_website_publication_lists_do_not_authorize_paper_reading(level):
    opp = deepcopy(OPP); attach_lab_v2(opp); public = project_public_detail(opp)
    assert PAPER_TITLE in ce._lab_snapshot_brief(public)
    with pytest.raises(ValueError, match='does not match'):
        validate_paper_reading({**FIRST, 'paper_reading': {'title': PAPER_TITLE, 'year': 2025,
                                                        'level': level, 'confirmed': True}}, public)
    parts = email_parts(public)
    assert any(ce._email_grounding_findings('Your paper uses magnetoencephalography.', parts, public))
    assert any(ce._email_grounding_findings('I have read your paper in full.', parts, public))


@pytest.mark.parametrize('change', ['stale', 'future', 'wrong_identity', 'identity_mismatch', 'source_link_removed', 'bad_chain'])
def test_unusable_v2_never_enters_brief_vocabulary_or_personalization(change):
    opp = deepcopy(OPP); snapshot = attach_lab_v2(opp)
    if change == 'stale': changed_stamp(snapshot, '2020-01-01T00:00:00Z')
    elif change == 'future': changed_stamp(snapshot, '2099-01-01T00:00:00Z')
    elif change == 'wrong_identity': opp['pi_name'] = 'Another Person'
    elif change in ('identity_mismatch', 'source_link_removed'):
        opp['metadata']['lab_refresh'] = {'status': 'failed', 'reason': change,
            'checked_at': snapshot['checked_at'], 'identity_revoked_at': snapshot['checked_at']}
    else: snapshot['source_chain']['links'][2]['to_url'] = TEAM_URL
    public = project_public_detail(opp); parts = email_parts(public)
    assert public['lab_context']['status'] == ('stale' if change == 'stale' else 'unavailable')
    assert ce._lab_snapshot_brief(public) == ''
    assert 'magnetoencephalography' not in ce._build_email_corpus(parts, public)
    assert not has_source_backed_target_evidence(public, parts)
    assert 'lab_snapshot' not in json.dumps(public) and 'lab_refresh' not in json.dumps(public)


@pytest.mark.parametrize('public_value', ['malformed', 'null', 'stale', 'unavailable', 'hash_changed'])
def test_explicit_unusable_public_v2_never_falls_back_to_valid_raw(public_value):
    opp = deepcopy(OPP); attach_lab_v2(opp); valid = lab_context_for(opp)
    assert valid['status'] == 'available'
    if public_value == 'malformed': value = {'version': 1, 'status': 'available'}
    elif public_value == 'null': value = None
    elif public_value == 'stale': value = {**valid, 'status': 'stale'}
    elif public_value == 'unavailable': value = {'version': 1, 'status': 'unavailable', 'snapshot': None}
    else:
        value = deepcopy(valid); value['snapshot']['pages'][1]['sections'][-1]['text'] += ' Tampered.'
    opp['lab_context'] = value
    assert email_lab_context(opp)['status'] != 'available'
    assert ce._lab_snapshot_brief(opp) == ''
    assert not has_source_backed_target_evidence(opp)


@pytest.mark.parametrize('path', ['', 'variants', 'stream', 'refine', 'selection'])
@pytest.mark.parametrize('change', ['last_section', 'source_digest', 'stale', 'source_link_removed'])
def test_all_writing_actions_reject_changed_v2_before_auth_or_provider(writing_client, monkeypatch, path, change):  # noqa: F811
    client, opp = writing_client; snapshot = attach_lab_v2(opp)
    old = writing_target_version(project_public_detail(opp))
    if change == 'last_section': snapshot['pages'][1]['sections'][-1]['text'] += ' New source paragraph.'
    elif change == 'source_digest': snapshot['source_chain']['documents'][3]['body_sha256'] = 'e' * 64
    elif change == 'stale': changed_stamp(snapshot, '2020-01-01T00:00:00Z')
    else:
        opp['metadata']['lab_refresh'] = {'status': 'failed', 'reason': 'source_link_removed',
            'checked_at': snapshot['checked_at'], 'identity_revoked_at': snapshot['checked_at']}
    async def forbidden(_authorization):
        pytest.fail('old website target reached authentication/provider stage')
    monkeypatch.setattr(ce, 'authenticated_uid', forbidden)
    if path == 'selection':
        from tests.test_cold_email_selection_refine import payload
        response = client.post('/api/cold-email/refine', json=payload(opportunity_id=opp['id'],
            contact_context=FIRST, expected_target_version=old))
    else:
        response = post(client, path, FIRST, opportunity_id=opp['id'], expected_target_version=old)
    assert response.status_code == 409, response.text
    assert response.json()['detail']['code'] == 'WRITING_TARGET_CHANGED'


@pytest.mark.parametrize('path', ['', 'variants', 'stream', 'refine', 'selection'])
def test_actual_email_consumers_receive_complete_v2_but_no_inferred_reading(writing_client, monkeypatch, path):  # noqa: F811
    client, opp = writing_client; attach_lab_v2(opp); calls = []
    def provider(messages, **_kwargs):
        calls.append(deepcopy(messages))
        if path == 'selection': return json.dumps({'replacement': 'Could I ask about your current research?'})
        return ('Subject: Research inquiry\n\nDear Professor Nielsen,\n\n'
                'Could I ask about your current research?\n\nThank you for your time.')
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, 'chat_completion', provider)
    if path == 'selection':
        from tests.test_cold_email_selection_refine import payload
        response = client.post('/api/cold-email/refine', json=payload(opportunity_id=opp['id'],
            contact_context=FIRST, expected_target_version=writing_target_version(project_public_detail(opp))))
        assert response.status_code == 200, response.text
        out = response.json()
    else:
        out = result(post(client, path, FIRST, opportunity_id=opp['id'], engine='ai'), path)
    assert bool(calls) is (path != 'variants')
    for messages in calls:
        content = messages[1]['content']
        assert TAIL in content and TEAM_URL in content and RESEARCH_URL in content
        assert 'Do not write a website-reading claim' in content
    for variant in out.get('variants', [out]):
        body = variant.get('body', '')
        assert 'I read' not in body and 'I have read' not in body
    assert out['contact_context_receipt']['purpose'] == 'first_contact'


@pytest.mark.parametrize('claim', [
    'I have experience with magnetoencephalography.',
    'I built a magnetoencephalography system.',
    'I have carefully reviewed your lab website.',
    'Your paper uses magnetoencephalography.',
])
def test_v2_source_chain_never_authenticates_student_or_reading_claims(claim):
    opp = deepcopy(OPP); attach_lab_v2(opp); public = project_public_detail(opp)
    assert any(ce._email_grounding_findings(claim, email_parts(public), public))


def test_v2_maximum_section_total_is_complete_and_overflow_is_rejected():
    opp = deepcopy(OPP); snapshot = attach_lab_v2(opp)
    snapshot['pages'][0]['sections'] = [{'section_id': 's1', 'heading': '', 'text': 'P' * 4000}]
    snapshot['pages'][1]['sections'] = [
        {'section_id': f's{i + 1}', 'heading': '', 'text': 'R' * 1999 + str(i)} for i in range(10)]
    context = lab_context_for(opp)
    assert context['status'] == 'available'
    brief = ce._lab_snapshot_brief(opp)
    for page in snapshot['pages']:
        for section in page['sections']:
            assert section['text'] in brief
    snapshot['pages'][1]['sections'].append({'section_id': 's11', 'heading': '', 'text': 'overflow'})
    assert lab_context_for(opp)['status'] == 'unavailable'
    assert ce._lab_snapshot_brief(opp) == ''
    assert snapshot['pages'][1]['sections'][-1]['text'] == 'overflow'


def test_v1_saved_source_remains_accepted_without_any_synthetic_v2_upgrade():
    from tests.test_email_lab_context import attach_lab
    opp = deepcopy(OPP); attach_lab(opp); public = project_public_detail(opp)
    assert public['lab_context']['snapshot']['version'] == 1
    assert public['lab_context']['snapshot']['snapshot_version'].startswith('ls1:')
    assert 'source_chain' not in public['lab_context']['snapshot']
    assert ce._lab_snapshot_brief(public)
