from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from backend.lib.email_target_conditions import (
    build_target_conditions,
    target_condition_claim_violations,
    target_conditions_brief,
    target_conditions_template_request,
    target_conditions_vocabulary,
)

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)
URL = 'https://example.edu/program'


def record(text='', **changes):
    value = {'id': 'test-program', 'source_type': 'summer_program', 'url': URL,
             'source_url': URL, 'eligibility': {}, 'application': {}, 'metadata': {}}
    if text:
        value['metadata']['contact_instruction_sources'] = [{
            'source_url': URL, 'record_source_url': URL, 'checked_at': NOW.isoformat(),
            'sections': [{'heading': 'Undergraduate applicants', 'text': text}],
        }]
    value.update(changes)
    return value


def rows(value):
    return {item['field']: item for item in build_target_conditions(value, now=NOW)['conditions']}


def test_absent_inference_stamp_does_not_mean_stated():
    value = record(eligibility={'citizenship_required': False, 'preferred_year': ['freshman']},
                   application={'requires_resume': 'yes'}, is_rolling=True)
    result = rows(value)
    assert all(item['status'] == 'unverified' for item in result.values())
    assert result['eligibility.citizenship_required']['value'] is False
    assert not target_conditions_vocabulary(build_target_conditions(value, now=NOW))


def test_explicit_sources_use_complete_quote_without_mutating_record():
    text = 'Minimum GPA: 3.0. Applicants must submit a resume. Application deadline: 2026-10-01.'
    value = record(text)
    before = deepcopy(value)
    result = rows(value)
    assert result['eligibility.min_gpa']['value'] == 3.0
    assert result['application.requires_resume']['value'] == 'yes'
    assert result['deadline']['value'] == '2026-10-01'
    assert all(item['status'] == 'stated' and item['usage'] == 'usable' for item in result.values())
    assert result['deadline']['sources'][0]['quote'] == text
    assert value == before


@pytest.mark.parametrize('method,status', [('llm:tagger','inferred'), ('policy:nsf_reu_solicitation','policy'), ('estimate:start_date','inferred')])
def test_inference_and_general_policy_are_not_program_source(method, status):
    value = record(deadline='2026-10-01')
    value['metadata']['inferred_fields'] = {'deadline': method}
    assert rows(value)['deadline']['status'] == status


@pytest.mark.parametrize('change,reason', [('old', 'source_stale'), ('url', 'source_binding_mismatch'), ('future', 'source_unavailable'), ('naive', 'source_unavailable')])
def test_freshness_and_binding(change, reason):
    value = record('Minimum GPA: 3.0.', eligibility={'min_gpa': 3.0})
    source = value['metadata']['contact_instruction_sources'][0]
    if change == 'old': source['checked_at'] = (NOW - timedelta(days=61)).isoformat()
    if change == 'url': source['record_source_url'] = 'https://example.edu/other'
    if change == 'future': source['checked_at'] = (NOW + timedelta(seconds=1)).isoformat()
    if change == 'naive': source['checked_at'] = '2026-09-28T12:00:00'
    item = rows(value)['eligibility.min_gpa']
    assert item['usage'] != 'usable'
    assert item['reason'] == reason


def test_source_removal_cannot_promote_normalized_cache():
    value = record('Minimum GPA: 3.0.', eligibility={'min_gpa': 3.0})
    assert rows(value)['eligibility.min_gpa']['usage'] == 'usable'
    value['metadata']['contact_instruction_sources'] = []
    assert rows(value)['eligibility.min_gpa']['status'] == 'unverified'


@pytest.mark.parametrize('text', ['If selected, applicants must submit a resume.', 'Graduate students must submit a resume.', 'Applicants may submit a resume.', 'Undergraduate and graduate applicants must submit a resume.'])
def test_unsupported_scope_and_optional_language_not_required(text):
    value = record(text, application={'requires_resume': 'yes'})
    assert rows(value)['application.requires_resume']['usage'] != 'usable'


def test_source_conflict_and_normalized_conflict_remain_visible():
    value = record('Minimum GPA: 3.0.', eligibility={'min_gpa': 2.0})
    assert rows(value)['eligibility.min_gpa']['reason'] == 'normalized_source_conflict'
    value['eligibility'] = {}
    value['metadata']['contact_instruction_sources'][0]['sections'].append({'heading':'All applicants', 'text':'Minimum GPA: 3.5.'})
    assert rows(value)['eligibility.min_gpa']['reason'] == 'source_conflict'


def test_faculty_identity_and_no_blanket_checklist():
    value = record(source_type='faculty_research', pi_name='Jane Doe', eligibility={'min_gpa': 3.0})
    context = build_target_conditions(value, now=NOW)
    assert context['conditions'] == []
    assert target_conditions_template_request(context) is None
    value = record('Applicants must submit a resume.', source_type='faculty_research', pi_name='Jane Doe')
    value['metadata']['contact_instruction_sources'][0]['identity_name'] = 'Other Person'
    assert not any(item['usage']=='usable' for item in rows(value).values())


def test_zero_and_false_not_unknown():
    value = record('Minimum GPA: 0.0. A resume is not required.', eligibility={'min_gpa': 0.0}, application={'requires_resume':'no'})
    result = rows(value)
    assert result['eligibility.min_gpa']['value'] == 0
    assert result['application.requires_resume']['value'] == 'no'
    assert all(item['usage']=='usable' for item in result.values())


def test_template_asks_about_materials_never_attachment_and_one_question():
    context = build_target_conditions(record('Applicants must submit a resume and transcript.'), now=NOW)
    request = target_conditions_template_request(context)
    assert request and request.count('?') == 1
    assert 'attached' not in request.lower()
    assert 'resume' in request.lower()
    assert 'stated' in target_conditions_brief(context)


@pytest.mark.parametrize('text,code', [
    ('I meet all eligibility requirements.', 'unsupported_eligibility_claim'),
    ('I am a U.S. citizen.', 'unsupported_eligibility_claim'),
    ('I have attached my resume.', 'unsupported_attachment_claim'),
    ('Your application deadline is October 1, 2026.', 'unsupported_deadline_claim'),
    ('Your program requires a resume.', 'unsupported_material_claim'),
])
def test_unverified_target_or_student_claims_are_rejected(text,code):
    assert code in target_condition_claim_violations(text, build_target_conditions(record(), now=NOW))


@pytest.mark.parametrize('text', [
    'Could you confirm the application deadline?',
    'Could you let me know which application materials are required?',
    'I would be happy to prepare a resume.',
    'My GPA is 3.8.',
])
def test_questions_preparation_and_confirmed_gpa_can_be_used(text):
    assert target_condition_claim_violations(text, build_target_conditions(record(), now=NOW), ['My GPA is 3.8.']) == []


def test_stated_target_does_not_authorize_personal_eligibility():
    context = build_target_conditions(record('Minimum GPA: 3.0.'), now=NOW)
    assert target_condition_claim_violations('The program requires a minimum GPA of 3.0.',context) == []
    assert 'unsupported_eligibility_claim' in target_condition_claim_violations('I meet the GPA requirement.',context,['My GPA is 3.8.'])


def test_overflow_does_not_expose_partial_proof():
    value = record('Minimum GPA: 3.0.', eligibility={'min_gpa':3.0})
    value['metadata']['contact_instruction_sources'][0]['sections'][0]['text'] = 'Minimum GPA: 3.0.' + 'x'*4000
    assert rows(value)['eligibility.min_gpa']['usage'] != 'usable'


def test_heading_and_body_preserve_separate_source_text():
    value = record('3.0')
    value['metadata']['contact_instruction_sources'][0]['sections'][0]['heading'] = 'Minimum GPA'
    item = rows(value)['eligibility.min_gpa']
    assert item['usage'] == 'usable' and item['value'] == 3.0
    assert item['sources'][0]['quote'] == '3.0'
    assert item['sources'][0]['heading'] == 'Minimum GPA'


@pytest.mark.parametrize('heading,text', [('Undergraduate applicants > Deadline', 'February 15, 5 PM.'), ('申请条件', '申请人平均成绩至少为3.0。')])
def test_incomplete_date_and_unsupported_language_remain_reviewable(heading, text):
    value = record(text)
    value['metadata']['contact_instruction_sources'][0]['sections'][0]['heading'] = heading
    items = rows(value).values()
    assert items and all(item['usage'] != 'usable' for item in items)
    assert any(proof['quote'] == text and proof['heading'] == heading for item in items for proof in item['sources'])


@pytest.mark.parametrize('text', ['Minimum GPA: 3.0 is not required.', 'Applicants must submit a resume or transcript.', 'Recommended minimum GPA: 3.0.'])
def test_negation_alternatives_and_recommendation_do_not_become_requirements(text):
    assert not any(item['usage']=='usable' for item in rows(record(text)).values())


def test_public_receipt_validation_and_no_raw_fallback():
    from backend.lib.email_target_conditions import email_target_conditions, validate_public_target_conditions
    value = record('Minimum GPA: 3.0.')
    context = build_target_conditions(value, now=NOW)
    assert validate_public_target_conditions(context) == context
    context['conditions'][0]['usage'] = 'excluded'
    value['target_conditions'] = context
    assert email_target_conditions(value)['conditions'] == []
    assert rows(value)['eligibility.min_gpa']['usage'] == 'usable'  # canonical builder ignores cache


def test_template_recomputed_after_privacy_exclusion():
    context = build_target_conditions(record('Applicants must submit a resume.'), now=NOW)
    context['conditions'][0].update(status='unknown', usage='excluded', value=None, sources=[], reason='source_not_public')
    assert target_conditions_template_request(context) is None


@pytest.mark.parametrize('source,claim,evidence,code', [
    ('Application deadline: October 1, 2026.', 'Your application deadline is October 1, 2026 at 11:59 PM Pacific.', [], 'unsupported_deadline_claim'),
    ('Preferred skills: Python.', 'Your program requires Python.', [], 'unsupported_eligibility_claim'),
    ('', 'I am a U.S. citizen.', ['I am not a U.S. citizen.'], 'unsupported_eligibility_claim'),
    ('', 'My GPA is 3.8.', ['The internship I reviewed requires a GPA of 3.8.'], 'unsupported_eligibility_claim'),
    ('', '我已附上简历。', [], 'unsupported_attachment_claim'),
    ('', '我满足所有申请资格。', [], 'unsupported_eligibility_claim'),
])
def test_independent_review_counterexamples(source,claim,evidence,code):
    context = build_target_conditions(record(source), now=NOW)
    assert code in target_condition_claim_violations(claim,context,evidence)


def test_citizenship_alternatives_preserve_the_full_restriction():
    text = 'Applicants must be U.S. citizens or permanent residents.'
    item = rows(record(text))['eligibility.citizenship_required']
    assert isinstance(item['value'], str) and 'or permanent residents' in item['value']


@pytest.mark.parametrize('text', [
    'I meet with my mentor every week.',
    'I submitted a paper to the workshop.',
    'I attached a sensor to an Arduino.',
    'I have not attached my resume.',
    'I can attach my resume if useful.',
    'Could you confirm whether I meet the GPA requirement?',
    '我没有附上简历。',
    '我可以准备简历。',
    '请问我是否满足申请资格？',
])
def test_independent_review_positive_controls(text):
    assert target_condition_claim_violations(text, build_target_conditions(record(), now=NOW)) == []


@pytest.mark.parametrize('evidence', ['My teammate has a 3.8 GPA.', 'Their student has a GPA of 3.8.', 'The internship I reviewed requires a GPA of 3.8.', 'I do not have a 3.8 GPA.'])
def test_personal_gpa_requires_positive_personal_evidence(evidence):
    assert 'unsupported_eligibility_claim' in target_condition_claim_violations('I have a 3.8 GPA.', {}, [evidence])


@pytest.mark.parametrize('evidence', ['My GPA is 3.8.', 'I have a 3.8 GPA.', 'GPA 3.8/4.0.'])
def test_personal_gpa_confirmed_decimal_positive(evidence):
    assert target_condition_claim_violations('I have a 3.8 GPA.', {}, [evidence]) == []


def test_pending_question_is_specific_and_does_not_state_unverified_value():
    value = record(deadline='2026-10-01')
    context = build_target_conditions(value, now=NOW)
    request = target_conditions_template_request(context)
    assert request == 'Could you confirm the current application deadline?'
    assert '2026' not in request


@pytest.mark.parametrize('source,claim,rejected', [
    ('Applicants must submit an unofficial transcript.', 'Your program requires an official transcript.', True),
    ('Applicants must submit an unofficial transcript.', 'Your program requires an unofficial transcript.', False),
    ('Applicants must submit two recommendation letters.', 'Your program requires three recommendation letters.', True),
    ('Applicants must submit two recommendation letters.', 'Your program requires two recommendation letters.', False),
    ('Minimum GPA: 3.0. Applicants must submit two recommendation letters.', 'Your program requires three recommendation letters.', True),
])
def test_material_qualifiers_cannot_be_added_or_borrowed(source,claim,rejected):
    issues = target_condition_claim_violations(claim,build_target_conditions(record(source),now=NOW))
    assert ('unsupported_material_claim' in issues) is rejected


@pytest.mark.parametrize('metadata', ['bad', {'inferred_fields':['bad']}])
def test_malformed_metadata_does_not_crash_or_promote(metadata):
    value = record(metadata=metadata, eligibility={'min_gpa':3.0})
    assert rows(value)['eligibility.min_gpa']['usage'] != 'usable'


def test_malformed_large_number_is_explicitly_excluded():
    value = record(eligibility={'min_gpa':10**500})
    item = rows(value)['eligibility.min_gpa']
    assert item['value'] is None and item['reason'] == 'source_overflow'


@pytest.mark.parametrize('field', ['record_kind', 'status', 'usage', 'reason'])
def test_malformed_public_enum_shapes_fail_closed(field):
    from backend.lib.email_target_conditions import email_target_conditions
    context = build_target_conditions(record('Minimum GPA: 3.0.'), now=NOW)
    target = context if field == 'record_kind' else context['conditions'][0]
    target[field] = []
    assert email_target_conditions({'target_conditions':context})['conditions'] == []


def test_unsupported_source_is_not_hidden_by_a_legacy_raw_value():
    value = record('If selected, applicants must submit a resume.', eligibility={'eligibility_text_raw':'Legacy short description'})
    item = rows(value)['eligibility.eligibility_text_raw']
    assert item['value'] == 'Legacy short description'
    assert item['sources'][0]['quote'] == 'If selected, applicants must submit a resume.'
    assert item['usage'] == 'ask_only'


def test_global_source_overflow_has_the_frozen_excluded_shape():
    value = record(eligibility={'min_gpa':3.0})
    value['metadata']['contact_instruction_sources'] = [{}] * 9
    item = rows(value)['eligibility.min_gpa']
    assert (item['status'],item['usage'],item['reason']) == ('unknown','excluded','source_overflow')
