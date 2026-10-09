"""B54 real email entry routes, controlled model replies, and manual-draft checks."""
import json
import socket
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from backend.routes import cold_email as ce
from tests.experience_fixtures import confirmed_experience
from tests.test_cold_email_selection_refine import payload as selection_payload
from tests.test_cold_email_writing_quality import PROFILE
from tests.test_email_contact_context import FIRST, post, result
from tests.test_email_paper_reading import writing_client  # noqa: F401


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs): pytest.fail('No external provider or network')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(ce, 'chat_completion', forbidden)


def conditions_record(opp, *, verified=True):
    opp['url'] = opp['source_url'] = 'https://example.edu/research/apply'
    opp['description_raw'] = ('Research on Python parser tools. U.S. citizenship or permanent residence is required. '
        'The minimum GPA is 3.5. Python experience is preferred. Deadline: March 15. A resume is required.')
    opp['eligibility'].update(skills_preferred=['Python'], min_gpa=3.5, citizenship_required=True,
                              eligibility_text_raw='U.S. citizenship or permanent residence is required. The minimum GPA is 3.5.')
    opp['application'].update(requires_resume=True, contact_method='email')
    if verified:
        opp['metadata']['contact_instruction_sources'] = [{
            'source_url': opp['url'], 'record_source_url': opp['url'],
            'checked_at': datetime.now(UTC).isoformat(),
            'sections': [
                {'heading': 'Undergraduate applicants — Eligibility',
                 'text': 'Applicants must be U.S. citizens or permanent residents. Minimum GPA: 3.5. Python experience is preferred.'},
                {'heading': 'Undergraduate applicants — Deadline', 'text': 'Application deadline: March 15.'},
                {'heading': 'Undergraduate applicants — Application materials',
                 'text': 'Email us with a resume. Include your resume with your application.'},
            ],
        }]
    return opp


def body(claim):
    return f'Dear Pat Lee,\n\n{claim}\n\nI am interested in Python parser tools.\n\nBest regards,\nAudit Student'


def manual_payload(opp, text, **updates):
    return {'profile': PROFILE, 'opportunity_id': opp['id'], 'subject': 'Research inquiry', 'body': text,
            'expected_target_version': writing_target_version(project_public_detail(opp)), **updates}


BAD = [
    ('I meet the citizenship requirement.', 'unsupported_eligibility_claim'),
    ('My GPA meets the minimum requirement.', 'unsupported_eligibility_claim'),
    ('I satisfy all eligibility requirements.', 'unsupported_eligibility_claim'),
    ('Python experience is required for applicants.', 'unsupported_eligibility_claim'),
    ('The application deadline is March 15, 2027 at 11:59 p.m. Pacific time.', 'unsupported_deadline_claim'),
    ('I have attached my resume.', 'unsupported_attachment_claim'),
]
GOOD = [
    'Could you clarify the citizenship requirement?',
    'Could you confirm the year and time zone for the March 15 deadline?',
    'Would you like me to prepare a resume?',
]


@pytest.mark.parametrize('path', ['', 'stream', 'refine', 'selection'])
@pytest.mark.parametrize('claim,issue', BAD)
def test_bad_conditions_are_rejected_by_actual_generation_and_edit_routes(writing_client, monkeypatch, path, claim, issue):  # noqa: F811
    client, opp = writing_client; conditions_record(opp); calls = []
    old = body('Could we discuss this work?')
    def provider(messages, **_kwargs):
        calls.append(deepcopy(messages))
        if path == 'selection': return json.dumps({'replacement': claim})
        return body(claim) if path == 'refine' else 'Subject: Research inquiry\n\n' + body(claim)
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, 'chat_completion', provider)
    value = {'profile': PROFILE, 'opportunity_id': opp['id'], 'contact_context': FIRST}
    if path == 'selection':
        response = client.post('/api/cold-email/refine', json=selection_payload(old, 'Could we discuss this work?', **value))
    elif path == 'refine':
        response = client.post('/api/cold-email/refine', json={**value, 'current_body': old,
            'subject': 'Research inquiry', 'instruction': 'Make it shorter'})
    else: response = post(client, path, FIRST, opportunity_id=opp['id'], engine='ai')
    out = result(response, path)
    assert out['target_conditions']['version'] == 1 and calls
    if path in ('refine', 'selection'):
        assert out['outcome'] == 'no_change' and out['reason'] == 'target_conditions'
        assert issue in out['condition_issues']
        if path == 'refine': assert out['body'] == old
        else: assert 'proposal' not in out and 'body' not in out
    else:
        assert out['method'] == 'template' and claim not in out['body']
    assert all('APPLICATION CONDITIONS' in call[1]['content'] for call in calls)


@pytest.mark.parametrize('path', ['', 'stream', 'refine', 'selection'])
@pytest.mark.parametrize('claim', GOOD)
def test_specific_questions_remain_usable(writing_client, monkeypatch, path, claim):  # noqa: F811
    client, opp = writing_client; conditions_record(opp)
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, 'chat_completion', lambda *_a, **_k:
                        json.dumps({'replacement': claim}) if path == 'selection' else
                        (body(claim) if path == 'refine' else 'Subject: Research inquiry\n\n' + body(claim)))
    if path == 'selection':
        response = client.post('/api/cold-email/refine', json=selection_payload(opportunity_id=opp['id']))
        out = response.json(); assert out['outcome'] == 'proposal' and out['proposal']['replacement'] == claim
    else:
        out = result(post(client, path, FIRST, opportunity_id=opp['id'], engine='ai'), path)
        assert out['method'] == ('llm' if path == 'refine' else 'ai') and claim in out['body']
    assert out['target_conditions']['version'] == 1


@pytest.mark.parametrize('claim,issue', BAD)
def test_manual_edits_are_checked_without_provider_or_body_replacement(writing_client, claim, issue):  # noqa: F811
    client, opp = writing_client; conditions_record(opp)
    value = manual_payload(opp, body(claim)); before = deepcopy(value)
    response = client.post('/api/cold-email/validate', json=value)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out['outcome'] == 'review_required' and issue in out['issues']
    assert out['target_version'] == value['expected_target_version'] and out['target_conditions']['version'] == 1
    assert 'body' not in out and value == before


@pytest.mark.parametrize('claim', GOOD + ['I would like to discuss a novel zephyrgraph system.'])
def test_manual_checks_do_not_turn_vocabulary_whitelist_into_general_truth_judgment(writing_client, claim):  # noqa: F811
    client, opp = writing_client; conditions_record(opp)
    response = client.post('/api/cold-email/validate', json=manual_payload(opp, body(claim)))
    assert response.status_code == 200 and response.json()['outcome'] == 'ready', response.text
    assert response.json()['issues'] == []


def test_manual_confirmed_gpa_is_a_personal_fact_but_does_not_prove_all_requirements(writing_client):  # noqa: F811
    client, opp = writing_client; conditions_record(opp)
    evidence = confirmed_experience(['GPA 3.8/4.0.'])
    valid = client.post('/api/cold-email/validate', json=manual_payload(opp, body('I have a 3.8 GPA.'), experience_evidence=evidence))
    assert valid.status_code == 200 and valid.json()['outcome'] == 'ready', valid.text
    invalid = client.post('/api/cold-email/validate', json=manual_payload(opp, body('I meet all eligibility requirements.'), experience_evidence=evidence))
    assert invalid.status_code == 200 and invalid.json()['outcome'] == 'review_required', invalid.text


@pytest.mark.parametrize('change,expected', [('target_changed', 409), ('missing_version', 422), ('long_body', 422), ('long_subject', 422), ('unicode', 422)])
def test_manual_prework_guards_remain_provider_free(writing_client, change, expected):  # noqa: F811
    client, opp = writing_client; conditions_record(opp)
    value = manual_payload(opp, body(GOOD[0]))
    if change == 'target_changed': opp['title'] += ' changed'
    elif change == 'missing_version': value.pop('expected_target_version')
    elif change == 'long_body': value['body'] = '🧪' * 2501
    elif change == 'long_subject': value['subject'] = 'x' * 2001
    else: value['body'] = 'PRIVATE_MARKER' + '\ud800'
    response = client.post('/api/cold-email/validate', content=json.dumps(value), headers={'Content-Type': 'application/json'})
    assert response.status_code == expected and 'PRIVATE_MARKER' not in response.text


@pytest.mark.parametrize('path', ['', 'stream', 'variants', 'refine', 'selection'])
def test_every_successful_consumer_returns_current_target_conditions(writing_client, path):  # noqa: F811
    client, opp = writing_client; conditions_record(opp)
    if path == 'selection':
        response = client.post('/api/cold-email/refine', json=selection_payload(opportunity_id=opp['id']))
    else: response = post(client, path, FIRST, opportunity_id=opp['id'])
    out = result(response, path)
    assert out['target_conditions']['version'] == 1 and out['target_version'].startswith('wt1:')
    if path == 'variants':
        assert all(item['target_conditions'] == out['target_conditions'] for item in out['variants'])


def material_record(opp):
    conditions_record(opp)
    opp['application']['requires_resume'] = 'yes'
    opp['metadata']['contact_instruction_sources'][0]['sections'] = [{
        'heading': 'Undergraduate applicants',
        'text': 'Applicants must submit a resume. Minimum GPA: 3.5. Application deadline: 2099-03-15.',
    }]
    opp['deadline'] = '2099-03-15'
    return opp


@pytest.mark.parametrize('path', ['', 'stream', 'refine', 'selection'])
def test_exact_source_terms_remain_target_facts_not_student_credentials(writing_client, monkeypatch, path):  # noqa: F811
    client, opp = writing_client; material_record(opp)
    claim = 'Applicants must submit a resume. The application deadline is 2099-03-15.'
    calls = []
    def provider(messages, **_kwargs):
        calls.append(deepcopy(messages))
        return json.dumps({'replacement': claim}) if path == 'selection' else (body(claim) if path == 'refine' else 'Subject: Research inquiry\n\n' + body(claim))
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, 'chat_completion', provider)
    if path == 'selection':
        out = client.post('/api/cold-email/refine', json=selection_payload(opportunity_id=opp['id'])).json()
        assert out['outcome'] == 'proposal' and out['proposal']['replacement'] == claim
    else:
        out = result(post(client, path, FIRST, opportunity_id=opp['id'], engine='ai'), path)
        assert out['method'] == ('llm' if path == 'refine' else 'ai') and claim in out['body']
    assert calls and all('Applicants must submit a resume.' in call[1]['content'] for call in calls)
    assert next(c for c in out['target_conditions']['conditions'] if c['field'] == 'application.requires_resume')['status'] == 'stated'


@pytest.mark.parametrize('path', ['', 'stream', 'variants'])
def test_template_has_one_material_request_from_actual_source(writing_client, path):  # noqa: F811
    client, opp = writing_client; material_record(opp)
    out = result(post(client, path, FIRST, opportunity_id=opp['id'], engine='template'), path)
    request = out['target_conditions']['template_request']
    assert request and 'resume' in request
    for variant in out.get('variants', [out]):
        assert request in variant['body'] and variant['body'].count(request) == 1
        assert 'I meet' not in variant['body'] and 'attached' not in variant['body']
        assert 'eligibility requirements and application materials' not in variant['body']


@pytest.mark.parametrize('faculty', [False, True])
def test_absent_conditions_do_not_create_generic_eligibility_checklist(writing_client, faculty):  # noqa: F811
    client, opp = writing_client
    if faculty:
        opp['source_type'] = 'faculty_research'
        opp['metadata']['record_kind'] = 'faculty_contact'
    response = post(client, '', FIRST, opportunity_id=opp['id'], engine='template')
    assert response.status_code == 200, response.text
    out = response.json()
    assert out['target_conditions']['template_request'] is None
    assert 'eligibility requirements and application materials' not in out['body']
    assert 'application deadline' not in out['body']


@pytest.mark.parametrize('draft,evidence,issue', [
    ('The application deadline is 2099-03-15 at 11:59 p.m. Pacific time.', [], 'unsupported_deadline_claim'),
    ('I am a U.S. citizen.', ['I am not a U.S. citizen.'], 'unsupported_eligibility_claim'),
    ('I have a 3.8 GPA.', ['My teammate has a 3.8 GPA.'], 'unsupported_eligibility_claim'),
    ('我满足全部申请资格。', [], 'unsupported_eligibility_claim'),
    ('我已附上简历。', [], 'unsupported_attachment_claim'),
])
def test_manual_route_does_not_borrow_denied_or_other_actor_credentials(writing_client, draft, evidence, issue):  # noqa: F811
    client, opp = writing_client; material_record(opp)
    response = client.post('/api/cold-email/validate', json=manual_payload(opp, body(draft), experience_evidence=confirmed_experience(evidence)))
    assert response.status_code == 200 and issue in response.json()['issues'], response.text


@pytest.mark.parametrize('draft', ['I meet with my mentor.', 'I attached the sensor to the robot.', 'I submitted a paper.'])
def test_manual_unrelated_activity_is_not_rejected_as_application_claim(writing_client, draft):  # noqa: F811
    client, opp = writing_client; material_record(opp)
    response = client.post('/api/cold-email/validate', json=manual_payload(opp, body(draft)))
    assert response.status_code == 200 and response.json()['outcome'] == 'ready', response.text


@pytest.mark.parametrize('path', ['', 'stream', 'variants', 'refine', 'selection'])
def test_condition_sources_count_toward_existing_preflight_budget(writing_client, monkeypatch, path):  # noqa: F811
    client, opp = writing_client; material_record(opp)
    source = opp['metadata']['contact_instruction_sources'][0]
    source['sections'] = [{'heading': 'Undergraduate applicants', 'text': 'Applicants must submit a resume. ' + 'x' * 3900 + str(i)} for i in range(32)]
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    if path == 'selection': response = client.post('/api/cold-email/refine', json=selection_payload(opportunity_id=opp['id']))
    else: response = post(client, path, FIRST, opportunity_id=opp['id'], engine='ai')
    if path == 'stream':
        frames = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert not any(frame.get('stage') == 'done' for frame in frames)
        assert any(frame.get('code') == 'EMAIL_INPUT_TOO_LARGE' and frame.get('status') == 413 for frame in frames)
    elif path == 'variants':
        assert response.status_code == 200
        assert len(response.json()['variants']) == 3
        assert all(item['body'] for item in response.json()['variants'])
    else:
        assert response.status_code == 413 and response.json()['detail']['code'] == 'EMAIL_INPUT_TOO_LARGE'


@pytest.mark.parametrize('original', [
    'Hello,\n\nI would like to discuss a novel zephyrgraph system.\n\nThank you.',
    'Dear Pat Lee,\n\nI meet all eligibility requirements.\n\nThank you.',
])
def test_condition_rejected_refinement_preserves_manual_draft_even_when_it_needs_review(writing_client, monkeypatch, original):  # noqa: F811
    client, opp = writing_client; material_record(opp)
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, 'chat_completion', lambda *_a, **_k: body('I have attached my resume.'))
    response = client.post('/api/cold-email/refine', json={
        'profile': PROFILE, 'opportunity_id': opp['id'], 'subject': 'My custom inquiry',
        'current_body': original, 'instruction': 'Make it clearer',
    })
    assert response.status_code == 200, response.text
    out = response.json()
    assert out['outcome'] == 'no_change' and out['reason'] == 'target_conditions'
    assert out['body'] == original and 'unsupported_attachment_claim' in out['condition_issues']
    assert 'subject' not in out
    if 'I meet' in original: assert 'unsupported_eligibility_claim' in out['condition_issues']


@pytest.mark.parametrize('policy', ['not_accepted', 'form_only', 'conflicting'])
def test_manual_validation_keeps_existing_contact_prework_refusal(writing_client, monkeypatch, policy):  # noqa: F811
    from tests.test_email_contact_instructions import POLICY
    client, opp = writing_client; material_record(opp)
    value = deepcopy(POLICY); value['email_policy'] = policy
    if policy == 'conflicting': value['status'] = 'conflicting'
    monkeypatch.setattr('backend.lib.public_opportunity_detail.contact_instructions_for', lambda _record: value)
    response = client.post('/api/cold-email/validate', json=manual_payload(opp, body(GOOD[0])))
    assert response.status_code == 409 and response.json()['detail']['code'] == 'EMAIL_CONTACT_INSTRUCTIONS'


def test_conditions_reach_judge_critic_and_reviser_and_revised_claim_is_rejected(writing_client, monkeypatch):  # noqa: F811
    client, opp = writing_client; material_record(opp); calls = []
    def provider(messages, **_kwargs):
        system = messages[0]['content']
        if 'You are judging candidate' in system: stage, answer = 'judge', '{"winner":1}'
        elif 'You are a strict reviewer' in system: stage, answer = 'critique', '{"verdict":"revise","revision_notes":"Clarify the request."}'
        elif 'You are revising' in system: stage, answer = 'revise', 'Subject: Research inquiry\n\n' + body('I meet all eligibility requirements.')
        else: stage, answer = 'draft', 'Subject: Research inquiry\n\n' + body('Would you like me to prepare a resume?')
        calls.append((stage, deepcopy(messages)))
        return answer
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, 'chat_completion', provider)
    monkeypatch.setenv('OFE_COLD_EMAIL_NDRAFT', '2'); monkeypatch.setenv('OFE_COLD_EMAIL_CRITIQUE', '1')
    out = result(post(client, '', FIRST, opportunity_id=opp['id'], engine='ai'), '')
    assert {stage for stage, _ in calls} == {'draft', 'judge', 'critique', 'revise'}
    assert all('APPLICATION CONDITIONS' in messages[1]['content'] and 'Applicants must submit a resume.' in messages[1]['content'] for _, messages in calls)
    assert 'I meet all eligibility requirements.' not in out['body']
    assert out['method'] == 'ai'
    assert [line for line in out['body'].splitlines() if line] == [line for line in body('Would you like me to prepare a resume?').splitlines() if line]


@pytest.mark.parametrize('configured', [False, True])
@pytest.mark.parametrize('faculty', [False, True])
def test_local_refinement_condition_failure_preserves_original(writing_client, monkeypatch, configured, faculty):  # noqa: F811
    client, opp = writing_client; material_record(opp)
    if faculty:
        opp.update(source_type='faculty_research', keywords=[], description_raw='')
        opp['metadata'].pop('recent_works', None)
        opp['metadata'].pop('publication_attribution_status', None)
    original = 'Hello,\n\nI meet all eligibility requirements.\n\nI have attached my resume.'
    monkeypatch.setattr(ce, 'is_configured', lambda: configured)
    if configured: monkeypatch.setattr(ce, 'chat_completion', lambda *_a, **_k: None)
    response = client.post('/api/cold-email/refine', json={'profile':PROFILE, 'opportunity_id':opp['id'],
        'subject':'Research inquiry', 'current_body':original, 'instruction':'Make it clearer'})
    assert response.status_code == 200, response.text
    out = response.json()
    assert out['outcome'] == 'no_change' and out['body'] == original
    assert set(out['condition_issues']) == {'unsupported_eligibility_claim', 'unsupported_attachment_claim'}


def test_legacy_skill_and_application_fields_are_not_labeled_source_confirmed_requirements(writing_client, monkeypatch):  # noqa: F811
    client, opp = writing_client; conditions_record(opp, verified=False); captured = []
    opp['eligibility']['skills_required'] = ['Python']
    def provider(messages, **_kwargs):
        captured.extend(deepcopy(messages))
        return 'Subject: Research inquiry\n\n' + body('Could you clarify which skills are required for applicants?')
    monkeypatch.setattr(ce, 'is_configured', lambda: True); monkeypatch.setattr(ce, 'chat_completion', provider)
    out = result(post(client, '', FIRST, opportunity_id=opp['id'], engine='ai'), '')
    content = captured[1]['content']
    assert '- Recorded skills (check application-condition evidence): ["Python"]' in content
    assert '- Required skills:' not in content and '- Source-stated application URL:' not in content
    assert '- Recorded application URL (not proof of submission):' in content
    assert next(c for c in out['target_conditions']['conditions'] if c['field'] == 'eligibility.skills_required')['status'] == 'unverified'
