"""B62 actual routes with synthetic auth/storage and prohibited external calls."""
import json
import socket

import pytest
from fastapi.testclient import TestClient

from backend.lib import private_target_resolution as resolution
from backend.routes import private_import_targets as private_route
from tests.experience_fixtures import confirmed_experience
from tests.test_private_import_targets import ID, OTHER, OWNER, app, raw_record
from tests.test_private_import_targets import storage as storage_fixture


@pytest.fixture
def storage(monkeypatch):
    state = storage_fixture.__wrapped__(monkeypatch)
    state['row'] = raw_record()
    monkeypatch.setattr(resolution.storage, 'new_client', private_route.new_client)
    def forbidden(*args, **kwargs):
        raise AssertionError('No real socket, public target or model call')
    import backend.data_loader as loader
    import backend.lib.llm as llm
    import backend.lib.public_opportunity_detail as public_detail
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(llm, 'chat_completion', forbidden)
    monkeypatch.setattr(loader, 'load_opportunities_by_id', forbidden)
    monkeypatch.setattr(public_detail, 'project_public_detail', forbidden)
    return state


def context():
    response = TestClient(app).get(f'/api/private-import-targets/{ID}/email-context',
        params={'expected_owner_id': OWNER}, headers={'Authorization': 'Bearer fixture-token'})
    assert response.status_code == 200, response.text
    return response.json()


def body(**updates):
    result = {'expected_owner_id': OWNER, 'expected_target_version': context()['writing_version'],
              'profile': {'name': 'Test Student'}, 'engine': 'template',
              'contact_context': {'version': 1, 'purpose': 'first_contact'},
              'experience_evidence': confirmed_experience(['I built a Python parser for my class project.'])}
    result.update(updates)
    return result


def post(data, path='variants', *, authorized=True):
    return TestClient(app).post(f'/api/private-import-targets/{ID}/cold-email/{path}',
        content=json.dumps(data, ensure_ascii=True),
        headers={**({'Authorization': 'Bearer fixture-token'} if authorized else {}), 'Content-Type': 'application/json'})


def draft(**updates):
    return body(subject='Question about your application process',
        body='Hello, could you tell me which application process I should follow?',
        recipient='recipient@example.edu', contact_requirements_reviewed=True, **updates)


def test_template_actual_route_is_owner_bound_and_unverified(storage):
    request = body()
    response = post(request)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['method'] == 'template' and value['grounding'] == 'no_target_data'
    assert value['target_scope'] == 'private_import' and value['verification'] == 'unverified'
    assert value['owner_id'] == OWNER and value['opportunity_id'] == ID
    assert value['target_version'] == request['expected_target_version'] == value['private_context']['writing_version']
    assert value['source_version'] == value['private_context']['source_version']
    assert value['recipient_email'] == '' and value['recipient_status'] == 'unavailable'
    assert value['target_conditions'] == {'version': 1, 'record_kind': 'unverified', 'conditions': [], 'template_request': None}
    assert len(value['variants']) == 1
    variant = value['variants'][0]
    assert 'I built a Python parser for my class project.' in variant['body']
    assert 'Private research note' in variant['body']
    assert 'Professor' not in variant['body'] and 'attached' not in variant['body']
    assert variant['experience_usage']['selected'][0]['excerpt'] in variant['body']
    assert 'ImaginarySkill' not in response.text
    assert 'description_raw' not in response.text
    assert 'no-store' in response.headers['cache-control']


def test_validate_preserves_manual_text_and_does_not_call_provider(storage):
    request = draft()
    response = post(request, 'validate')
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['outcome'] == 'ready' and value['issues'] == []
    assert 'body' not in value and 'subject' not in value
    assert value['target_version'] == request['expected_target_version']


@pytest.mark.parametrize('path', ['variants', 'validate'])
@pytest.mark.parametrize('case,status,code', [
    ('unauthorized', 401, 'private_target_auth_required'),
    ('owner', 409, 'private_target_owner_changed'),
    ('changed', 409, 'private_target_changed'),
    ('deleted', 409, 'private_target_deleted'),
    ('missing', 404, 'private_target_not_found'),
])
def test_current_auth_owner_record_and_version_required(storage, path, case, status, code):
    request = draft() if path == 'validate' else body()
    if case == 'owner': request['expected_owner_id'] = OTHER
    if case == 'changed': storage['row'] = raw_record(revision=2)
    if case == 'deleted': storage['row'] = raw_record(revision=2, deleted=True)
    if case == 'missing': storage['row'] = None
    response = post(request, path, authorized=case != 'unauthorized')
    assert response.status_code == status, response.text
    assert response.json() == {'detail': {'code': code}}


@pytest.mark.parametrize('restriction', ['Do not email us.', 'Apply only through the online form.', '请勿发送邮件。'])
def test_late_source_restriction_blocks_template_and_manual_even_when_checked(storage, restriction):
    storage['row']['opportunity']['description_raw'] = 'General source paragraph.\n' * 1000 + restriction
    request = body()
    response = post(request)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'private_email_contact_blocked'
    request.update(subject='A question', body='I would like to ask about your work.',
                   recipient='person@example.edu', contact_requirements_reviewed=True)
    response = post(request, 'validate')
    assert response.status_code == 200, response.text
    assert response.json()['outcome'] == 'review_required'
    assert 'contact_blocked' in response.json()['issues']


@pytest.mark.parametrize('path', ['variants', 'validate'])
def test_ai_is_explicitly_unavailable(storage, path):
    request = draft() if path == 'validate' else body()
    request['engine'] = 'ai'
    response = post(request, path)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'private_email_ai_unavailable'


@pytest.mark.parametrize('context_value', [
    {'version': 1, 'purpose': 'follow_up'},
    {'version': 1, 'purpose': 'referral'},
    {'version': 1, 'purpose': 'first_contact', 'paper_reading': {'title': 'Made up', 'level': 'full_text', 'confirmed': True}},
])
def test_unsupported_contact_context_has_fixed_error(storage, context_value):
    response = post(body(contact_context=context_value))
    assert response.status_code == 422
    assert response.json()['detail']['code'] == 'private_email_context_unsupported'


@pytest.mark.parametrize('text,issue', [
    ('I meet all the eligibility requirements.', 'unsupported_eligibility_claim'),
    ('I have a 3.8 GPA.', 'unsupported_eligibility_claim'),
    ('Your program deadline is October 1, 2026 at 5 PM EST.', 'unsupported_deadline_claim'),
    ('Your program requires a resume.', 'unsupported_material_claim'),
    ('I have attached my resume.', 'unsupported_attachment_claim'),
    ('我已经附上我的简历。', 'unsupported_attachment_claim'),
])
def test_manual_unverified_claims_not_authorized_by_source_or_checkbox(storage, text, issue):
    storage['row']['opportunity']['description_raw'] = text
    request = draft()
    request['body'] = text
    response = post(request, 'validate')
    assert response.status_code == 200, response.text
    assert response.json()['outcome'] == 'review_required'
    assert issue in response.json()['issues']
    assert 'body' not in response.json()


@pytest.mark.parametrize('value', ['', 'two@example.edu,other@example.edu', 'Name <a@example.edu>', 'x@y', 'a@example.edu\nBcc:x@y.edu'])
def test_manual_recipient_must_be_single_address(storage, value):
    request = draft(); request['recipient'] = value
    response = post(request, 'validate')
    assert response.status_code == 200, response.text
    assert 'invalid_recipient' in response.json()['issues']


def test_unknown_contact_policy_requires_explicit_review_but_is_not_verified(storage):
    request = draft(); request['contact_requirements_reviewed'] = False
    value = post(request, 'validate').json()
    assert value['issues'] == ['contact_review_required']
    assert value['private_context']['contact_policy']['state'] == 'unknown'


@pytest.mark.parametrize('status', ['candidate', 'withdrawn', 'rejected'])
def test_only_current_confirmed_experience_can_be_quoted(storage, status):
    evidence = confirmed_experience(['I won a secret award.', 'I built the parser.'])
    evidence['entries'][0]['status'] = status
    value = post(body(experience_evidence=evidence)).json()
    assert 'secret award' not in value['variants'][0]['body']
    assert value['experience_usage']['excluded'][0]['reason'] == status
    assert value['experience_usage']['selected'][0]['id'] == 'experience-1'


def test_raw_resume_and_private_extras_do_not_authenticate_student_facts(storage):
    evidence = {'version': 1, 'resume_text': 'I have a 3.8 GPA.', 'entries': []}
    request = draft(experience_evidence=evidence); request['body'] = 'I have a 3.8 GPA.'
    assert post(request, 'validate').json()['issues'] == ['unsupported_eligibility_claim']
    evidence = confirmed_experience(['I have a 3.8 GPA.'])
    request['experience_evidence'] = evidence
    assert post(request, 'validate').json()['issues'] == []


@pytest.mark.parametrize('field,value', [('body', '🙂' * 2501), ('subject', '🙂' * 1001), ('body', '\ud800')])
def test_private_validation_text_limits_and_unicode_never_reflect_content(storage, field, value):
    request = draft(); request[field] = value
    response = post(request, 'validate')
    assert response.status_code == 422
    assert 'input' not in response.json()['detail'] and 'ctx' not in response.json()['detail']
    assert value not in response.text


def test_forged_authority_and_dynamic_private_key_are_not_echoed(storage):
    request = draft(); request['PRIVATE_SECRET_KEY'] = {'profile': 'PRIVATE_SECRET_VALUE'}
    response = post(request, 'validate')
    assert response.status_code == 422
    assert 'PRIVATE_SECRET' not in response.text


def test_profile_private_validation_and_empty_name_are_safe(storage):
    request = body(); request['profile']['research_interests_text'] = 'PRIVATE_SECRET' * 10000
    response = post(request)
    assert response.status_code == 422 and 'PRIVATE_SECRET' not in response.text
    request = body(profile={'name': ' '})
    response = post(request)
    assert response.status_code == 422 and response.json()['detail']['code'] == 'student_name_required'


@pytest.mark.parametrize('field', ['expected_owner_id', 'expected_target_version'])
@pytest.mark.parametrize('path', ['variants', 'validate'])
def test_binding_fields_cannot_be_omitted(storage, field, path):
    request = draft() if path == 'validate' else body()
    del request[field]
    assert post(request, path).status_code == 422


@pytest.mark.parametrize('version', ['pit1:' + '0' * 64, 'wt1:' + '0' * 64, 'pwt1:' + 'f' * 64])
def test_public_or_source_version_cannot_replace_reviewed_writing_version(storage, version):
    response = post(body(expected_target_version=version))
    assert response.status_code == (409 if version.startswith('pwt1:') else 422)


def test_confirmed_original_with_qualifier_is_whole_and_target_poison_stays_unused(storage):
    text = 'I tested the parser.\nI did not train the model.'
    data = body(experience_evidence=confirmed_experience([text]))
    storage['row']['opportunity']['extra_fields'].update({
        'faculty_name': 'FAKE_PERSON', 'contact_email': 'fake@example.edu',
        'target_conditions': {'conditions': [{'field': 'eligibility.min_gpa', 'value': 3.8}]},
        'research_context': {'status': 'available'}, 'lab_context': {'status': 'available'},
    })
    # An import edit changes pit1/pwt1 even when the ignored data has no authority.
    data['expected_target_version'] = context()['writing_version']
    response = post(data)
    assert response.status_code == 200, response.text
    value = response.json()
    assert text in value['variants'][0]['body']
    assert value['experience_usage']['selected'][0]['excerpt'] == text
    assert 'FAKE_PERSON' not in response.text and 'fake@example.edu' not in response.text


def test_resume_signature_and_activity_revision_must_still_match(storage):
    from tests.test_email_activity_context import envelope
    evidence = envelope()
    evidence['entries'][0]['revision'] = 2
    value = post(body(experience_evidence=evidence)).json()
    assert 'I built the parser.' not in value['variants'][0]['body']
    assert value['experience_usage']['excluded'][0]['reason'] == 'activity_reference_mismatch'
    import hashlib
    text = 'I have a 3.8 GPA.'
    evidence = confirmed_experience([text])
    evidence['resume_text'] = 'CHANGED'
    evidence['entries'][0]['source'] = {'kind': 'resume', 'signature': hashlib.sha256(text.encode()).hexdigest(),
                                      'start': 0, 'end': len(text), 'quote': text}
    request = draft(experience_evidence=evidence); request['body'] = text
    assert post(request, 'validate').json()['issues'] == ['unsupported_eligibility_claim']


def test_template_omits_whole_oversized_experience_with_receipt_not_a_fragment(storage):
    text = '🙂' * 2500 + 'TAIL_KEEP_WHOLE'
    response = post(body(experience_evidence=confirmed_experience([text])))
    assert response.status_code == 200, response.text
    value = response.json()
    assert value['experience_usage']['selected'] == []
    assert 'experience_template_budget_omission' in value['experience_usage']['notices']
    assert '🙂' not in value['variants'][0]['body']


def test_template_keeps_full_accepted_identity_title_and_availability(storage):
    title = '🙂' * 1000
    name = '🙂' * 256
    storage['row']['opportunity']['title'] = title
    contact = {'version': 1, 'purpose': 'first_contact',
               'availability': {'text': '🙂' * 500, 'confirmed': True}}
    response = post(body(profile={'name': name}, contact_context=contact, experience_evidence=None))
    assert response.status_code == 200, response.text
    rendered = response.json()['variants'][0]['body']
    assert f'“{title}”' in rendered and rendered.count(name) >= 2
    assert contact['availability']['text'] in rendered
    assert len(rendered.encode('utf-16-le')) // 2 <= 5000


@pytest.mark.parametrize('title,displayed', [
    ('Synthetic "source" title 中文😀', 'Synthetic "source" title 中文😀'),
    ('One\nTwo\rThree\tFour\u2028五\u2029六', 'One Two Three Four 五 六'),
    ('A\\B “quoted” and 中文🙂', 'A\\B “quoted” and 中文🙂'),
])
def test_imported_title_readable_quote_formats_only_separators(storage, title, displayed):
    storage['row']['opportunity']['title'] = title
    response = post(body())
    assert response.status_code == 200, response.text
    value = response.json()
    assert f'note titled “{displayed}” and' in value['variants'][0]['body']
    assert value['private_context']['title'] == title
    assert storage['row']['opportunity']['title'] == title
    assert '\\"' not in value['variants'][0]['body']


def test_confirmed_availability_and_context_receipt_are_exact(storage):
    contact = {'version': 1, 'purpose': 'first_contact',
               'availability': {'text': 'I am available five hours a week this semester.', 'confirmed': True}}
    response = post(body(contact_context=contact))
    assert response.status_code == 200, response.text
    from backend.lib.email_contact_context import contact_context_receipt
    value = response.json()
    assert contact['availability']['text'] in value['variants'][0]['body']
    assert value['contact_context_receipt'] == contact_context_receipt(contact)


@pytest.mark.parametrize('text', ['I have attached my resume.', 'I meet all eligibility requirements.', 'I read your paper.'])
def test_template_does_not_turn_attested_work_into_attachment_eligibility_or_reading(storage, text):
    response = post(body(experience_evidence=confirmed_experience([text])))
    assert response.status_code == 200, response.text
    value = response.json()
    assert text not in value['variants'][0]['body']
    assert value['experience_usage']['selected'] == []
    assert 'private_template_claim_omission' in value['experience_usage']['notices']


@pytest.mark.parametrize('text', [
    'Could you tell me whether international students can apply?',
    'I meet with my mentor weekly.',
    'I attached a sensor to the rover.',
    'I submitted a paper about signal processing in my class.',
])
def test_manual_questions_and_unrelated_project_actions_are_not_blocked(storage, text):
    request = draft(); request['body'] = text
    response = post(request, 'validate')
    assert response.status_code == 200, response.text
    assert response.json()['issues'] == []


@pytest.mark.parametrize('value', ['true', 1, None])
def test_policy_review_requires_actual_boolean(storage, value):
    request = draft(); request['contact_requirements_reviewed'] = value
    assert post(request, 'validate').status_code == 422


def test_storage_error_fixed_and_no_draft_or_secret_echo(storage):
    request = body()
    storage['failure'] = 'XX001'
    response = post(request)
    assert response.status_code == 503 and 'PRIVATE_SECRET' not in response.text


def test_template_and_manual_repeat_real_auth_and_storage_reads(storage):
    data = body(); storage['calls'].clear()
    assert post(data).status_code == 200
    data.update(subject='Question', body='Could you tell me how to apply?', recipient='a@example.edu', contact_requirements_reviewed=True)
    assert post(data, 'validate').status_code == 200
    assert [item[1] for item in storage['calls']] == ['/auth/v1/user', '/rest/v1/rpc/read_private_import_target'] * 2


@pytest.mark.parametrize('path', ['variants', 'validate'])
def test_invalid_bearer_refused_over_the_network_before_the_draft_is_parsed(storage, path):
    storage['calls'].clear()
    # Not JSON at all: were it parsed before the token check, this would be 422.
    response = TestClient(app).post(f'/api/private-import-targets/{ID}/cold-email/{path}',
        content=b'{"profile": "' + b'x' * (4 * 1024 * 1024),
        headers={'Authorization': 'Bearer forged-token', 'Content-Type': 'application/json'})
    assert response.status_code == 401
    assert response.json() == {'detail': {'code': 'private_target_auth_required'}}
    assert storage['calls'] == [('GET', '/auth/v1/user', 'Bearer forged-token')]
    assert 'no-store' in response.headers['cache-control']


@pytest.mark.parametrize('path', ['variants', 'validate'])
def test_verified_caller_with_malformed_draft_keeps_the_fixed_error(storage, path):
    storage['calls'].clear()
    response = TestClient(app).post(f'/api/private-import-targets/{ID}/cold-email/{path}',
        content=b'{"profile": PRIVATE_SECRET',
        headers={'Authorization': 'Bearer fixture-token', 'Content-Type': 'application/json'})
    assert response.status_code == 422
    assert response.json() == {'detail': {'code': 'private_email_invalid_request'}}
    assert [call[1] for call in storage['calls']] == ['/auth/v1/user']
