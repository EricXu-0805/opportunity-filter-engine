"""Private résumé sources: the actual route on synthetic auth/storage; no network or model."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.lib.private_resume_context import validate_private_resume_context
from backend.lib.target_resume_ai_validation import fingerprint
from tests.test_private_cold_email import storage as base_storage
from tests.test_private_import_targets import ID, OPPORTUNITY, OTHER, OWNER, app, raw_record

PATH = f'/api/private-import-targets/{ID}/resume-context'
GOLDEN = json.loads((Path(__file__).parent / 'fixtures/private-resume-context-v5-golden.json').read_text())


@pytest.fixture
def storage(monkeypatch):
    return base_storage.__wrapped__(monkeypatch)


def read(**params):
    return TestClient(app).get(PATH, params={'expected_owner_id': OWNER, **params},
                               headers={'Authorization': 'Bearer fixture-token'})


def test_route_answer_matches_the_frontend_golden_receipt(storage):
    context = GOLDEN['receipt']['context']
    storage['row']['opportunity'].update(title=context['title'], description_raw=context['description'])
    response = read()
    assert response.status_code == 200, response.text
    assert response.json() == GOLDEN['receipt']


def test_complete_source_is_owner_bound_and_promotes_no_import_metadata(storage):
    source = 'Heading 😀\r\n' + 'Full paragraph.\n' * 2000 + 'END 私有来源'
    storage['row']['opportunity']['description_raw'] = source
    response = read()
    assert response.status_code == 200, response.text
    value = response.json()
    context = value['context']
    assert context['description'] == source
    assert context['requirements'] == []
    assert context['private_source']['owner_id'] == OWNER
    assert context['private_source']['verification'] == 'unverified'
    assert context['private_source']['import_source'] == {
        'version': 1, 'description_source': 'pasted_text', 'ai_input_scope': 'source_excerpt', 'llm_enriched': True}
    assert not {'criteria', 'research', 'lab', 'target_truth', 'skills_required'} & context.keys()
    assert 'ImaginarySkill' not in response.text
    assert value['target_signature'] == fingerprint(context)
    assert 'no-store' in response.headers['cache-control'] and response.headers['pragma'] == 'no-cache'


def test_a_source_longer_than_a_draft_is_returned_whole(storage):
    source = 'x' * (2 * 1024 * 1024)
    storage['row']['opportunity']['description_raw'] = source
    response = read()
    assert response.status_code == 200
    assert response.json()['context']['description'] == source


def test_link_fields_follow_the_private_syntax_gate(storage):
    storage['row']['opportunity'].update(source_url='', url='https://example.edu/lab')
    assert read().json()['context']['source_url'] == 'https://example.edu/lab'
    storage['row']['opportunity'].update(source_url='javascript:alert(1)', url='')
    assert read().json()['context']['source_url'] == ''


@pytest.mark.parametrize('case,expected', [
    ('unauthenticated', 401), ('other_owner', 409), ('guest', 401), ('deleted', 409), ('missing', 404),
    ('stale', 409), ('extra_query', 422), ('duplicate_query', 422),
])
def test_route_refuses_invalid_owner_state(storage, case, expected):
    params = {'expected_owner_id': OWNER}
    headers = {'Authorization': 'Bearer fixture-token'}
    if case == 'unauthenticated':
        headers = {}
    if case == 'other_owner':
        params['expected_owner_id'] = OTHER
    if case == 'guest':
        storage['user']['is_anonymous'] = True
    if case == 'deleted':
        storage['row'] = raw_record(deleted=True)
    if case == 'missing':
        storage['row'] = None
    if case == 'stale':
        params['expected_target_version'] = 'pit1:' + '0' * 64
    if case == 'extra_query':
        params['model'] = 'unapproved'
    if case == 'duplicate_query':
        params = [('expected_owner_id', OWNER), ('expected_owner_id', OWNER)]
    response = TestClient(app).get(PATH, params=params, headers=headers)
    assert response.status_code == expected, response.text
    assert set(response.json()['detail']) == {'code'}
    assert 'no-store' in response.headers['cache-control']
    assert OPPORTUNITY['description_raw'] not in response.text


def test_the_resume_release_switch_closes_the_route_before_any_read(storage, monkeypatch):
    import backend.main as main
    assert main._release_feature_for_path(PATH) == main._release_feature_for_path(PATH + '/') == 'resume_renovate'
    for other in ('resolved', 'email-context', 'cold-email/variants'):
        assert main._release_feature_for_path(f'/api/private-import-targets/{ID}/{other}') is None
    assert main._release_feature_for_path(f'/api/opportunities/{ID}/resume-context') is None
    monkeypatch.setattr(main, 'feature_enabled', lambda feature: feature != 'resume_renovate')
    response = read()
    assert response.status_code == 404 and response.json() == {'detail': 'Not found'}
    assert storage['calls'] == []
    assert 'no-store' in response.headers['cache-control']


def test_a_new_revision_changes_the_version_and_signature(storage):
    first = read().json()
    old = first['context']['private_source']['source_version']
    assert read(expected_target_version=old).status_code == 200
    storage['row'] = raw_record(revision=2)
    assert read(expected_target_version=old).status_code == 409
    second = read().json()
    assert second['context']['private_source']['source_version'] != old
    assert second['target_signature'] != first['target_signature']


@pytest.mark.parametrize('fault', [
    'extra', 'criteria', 'authority', 'requirements', 'public_id', 'owner', 'revision_bool', 'revision_hash',
    'revision_zero', 'purpose', 'source_version', 'source_extra', 'labels', 'label_unknown_excerpt', 'url', 'nul',
    'surrogate', 'source_blank', 'title_long', 'version',
])
def test_snapshot_cannot_gain_public_authority_or_change_its_binding(storage, fault):
    value = read().json()['context']
    source = value['private_source']
    if fault == 'extra':
        value['extra'] = True
    if fault == 'criteria':
        value['criteria'] = {}
    if fault == 'authority':
        source['verification'] = 'verified'
    if fault == 'requirements':
        value['requirements'] = ['Suggested skill']
    if fault == 'public_id':
        value['opportunity_id'] = 'public-lab'
    if fault == 'owner':
        source['owner_id'] = OTHER
    if fault == 'revision_bool':
        source['revision'] = True
    if fault == 'revision_hash':
        source['revision'] = 2
    if fault == 'revision_zero':
        source['revision'] = 0
    if fault == 'purpose':
        source['purpose'] = 'email'
    if fault == 'source_version':
        source['source_version'] += '\n'
    if fault == 'source_extra':
        source['provider_allowed'] = True
    if fault == 'labels':
        source['import_source'].update(ai_input_scope='full_source', llm_enriched=False)
    if fault == 'label_unknown_excerpt':
        source['import_source']['description_source'] = 'unknown'
    if fault == 'url':
        value['source_url'] = 'javascript:alert(1)'
    if fault == 'nul':
        value['description'] += '\0'
    if fault == 'surrogate':
        value['description'] += '\ud800'
    if fault == 'source_blank':
        value['description'] = '  '
    if fault == 'title_long':
        value['title'] = 'x' * 1001
    if fault == 'version':
        value['context_version'] = 4
    with pytest.raises((ValueError, TypeError)):
        validate_private_resume_context(value)


@pytest.mark.parametrize('owner_id', ['not-a-uuid', OWNER.upper()])
def test_a_rehashed_malformed_owner_is_refused(storage, owner_id):
    value = read().json()['context']
    source = value['private_source']
    source['owner_id'] = owner_id
    identity = json.dumps({'id': ID, 'owner_id': owner_id, 'revision': source['revision']}, separators=(',', ':'))
    source['source_version'] = 'pit1:' + hashlib.sha256(identity.encode()).hexdigest()
    with pytest.raises(ValueError):
        validate_private_resume_context(value)


def test_validator_accepts_its_own_route_output_and_the_largest_stored_values(storage):
    value = read().json()['context']
    assert validate_private_resume_context(deepcopy(value)) == value
    value.update(title='😀' * 1000, organization='o' * 2000)
    assert validate_private_resume_context(value) == value
    source = value['private_source']
    source['revision'] = 9007199254740991
    identity = json.dumps({'id': ID, 'owner_id': OWNER, 'revision': source['revision']}, separators=(',', ':'))
    source['source_version'] = 'pit1:' + hashlib.sha256(identity.encode()).hexdigest()
    assert validate_private_resume_context(value) == value
