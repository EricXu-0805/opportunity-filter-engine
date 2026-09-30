"""Current per-entry activity context; synthetic inputs and no real provider."""
# ruff: noqa: F811
import hashlib
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.lib.email_experience_attribution import experience_attribution_violations
from backend.lib.experience_evidence import select_experience
from backend.routes import cold_email as ce
from backend.schemas import ColdEmailRequest, ExperienceEvidence
from src.recommender.cold_email import _common_parts, _p1_research_hook
from tests.experience_fixtures import confirmed_experience
from tests.test_cold_email_writing_quality import OPP, PROFILE
from tests.test_email_contact_context import FIRST, post, result
from tests.test_email_paper_reading import writing_client  # noqa: F401


def fact(id, value):
    return {'id': id, 'revision': 1, 'status': 'confirmed', 'value': value, 'source': {'kind': 'manual'}}


def envelope():
    evidence = confirmed_experience(['I built the parser.', 'I tested the model.'])
    evidence.update(version=2, resume_master={
        'version': 1, 'id': 'master', 'revision': 5, 'source_signature': None,
        'basics': {'links': []}, 'education': [], 'publications': [], 'skills': [], 'other_sections': [],
        'section_order': ['basics', 'education', 'activities', 'publications', 'skills'], 'unmapped_ranges': [],
        'activities': [
            {'id': 'alpha', 'kind': 'project', 'title': fact('alpha-title', 'Project Alpha'),
             'organization': fact('alpha-org', 'Alpha Lab'), 'start': fact('alpha-start', '2023'),
             'end': fact('alpha-end', '2024'), 'details': [{'id': 'experience-0', 'revision': 1}]},
            {'id': 'beta', 'kind': 'research', 'title': fact('beta-title', 'Project Beta'),
             'organization': fact('beta-org', 'Beta Lab'), 'start': fact('beta-start', '2025'),
             'end': fact('beta-end', '2026'), 'details': [{'id': 'experience-1', 'revision': 1}]},
        ],
    })
    return evidence


def parts(evidence=None):
    request = ColdEmailRequest.model_validate({'profile': PROFILE, 'opportunity_id': OPP['id'],
                                               'experience_evidence': evidence if evidence is not None else envelope()})
    return ce._experience_parts(request, request.profile.model_dump(), OPP)


def violations(text, evidence=None):
    p, _ = parts(evidence)
    return experience_attribution_violations(text, p['resume_bullets'], activity_materials=p['experience_materials_all'])


def test_v2_keeps_complete_entry_and_own_confirmed_activity():
    data = envelope(); before = deepcopy(data); p, selection = parts(data)
    assert data == before
    material = selection.selected[0]
    assert material['excerpt'] == data['entries'][0]['text']
    context = material['context']
    assert context == {'master_id': 'master', 'master_revision': 5, 'section': 'activities', 'id': 'alpha',
                       'kind': 'project', 'fields': {key: data['resume_master']['activities'][0][key]
                       for key in ['title', 'organization', 'start', 'end']}}
    brief = ce._render_student_brief(p)
    assert json.dumps(selection.selected, ensure_ascii=False) in brief
    assert 'kind is a record category, not evidence of a student title or responsibilities' in brief


@pytest.mark.parametrize('claim', [
    'At Alpha Lab, I built the parser.', 'In Project Alpha, I built the parser.',
    'I built the parser at Alpha Lab.', 'At Alpha Lab in 2024, I built the parser.',
    'I built the parser in 2024.', 'I built the parser.',
    'At Beta Lab, I tested the model.',
])
def test_local_activity_names_dates_and_unscoped_original_remain_supported(claim):
    assert violations(claim) == []


@pytest.mark.parametrize('claim', [
    'At Beta Lab, I built the parser.', 'In Project Beta, I built the parser.',
    'I built the parser at Beta Lab.', 'At Beta Lab in 2025, I built the parser.',
    'At Alpha Lab in 2025, I built the parser.', 'I built the parser in 2025.',
    'At Beta Lab in 2024, I tested the model.',
])
def test_cannot_move_a_contribution_or_year_to_another_activity(claim):
    assert violations(claim)


def test_explicit_source_prefix_is_not_lost_or_reassigned():
    data = envelope(); data['entries'][0]['text'] = 'At Alpha Lab, I built the parser.'
    assert violations('At Alpha Lab, I built the parser.', data) == []
    data['entries'][0]['text'] = 'At Beta Lab, I built the parser.'
    assert violations('At Alpha Lab, I built the parser.', data)
    assert violations('At Beta Lab, I built the parser.', data)


@pytest.mark.parametrize('change,reason', [
    ('entry-revision', 'activity_reference_mismatch'), ('cross-record', 'activity_ambiguous'),
    ('cross-section', 'activity_ambiguous'),
])
def test_known_invalid_relationship_does_not_degrade_to_unbound(change, reason):
    data = envelope()
    if change == 'entry-revision': data['entries'][0]['revision'] = 2
    elif change == 'cross-record': data['resume_master']['activities'][1]['details'].append({'id': 'experience-0', 'revision': 1})
    else: data['resume_master']['education'] = [{'id': 'school', 'details': [{'id': 'experience-0', 'revision': 1}]}]
    p, selection = parts(data)
    assert data['entries'][0]['text'] not in p['resume_bullets']
    assert selection.excluded == [{'id': 'experience-0', 'revision': data['entries'][0]['revision'], 'reason': reason}]
    assert selection.usage()['needs_review']


@pytest.mark.parametrize('change', ['missing-master', 'no-reference', 'activity-deleted'])
def test_independent_confirmed_text_survives_relation_removal_without_old_context(change):
    data = envelope()
    if change == 'missing-master': data['resume_master'] = None
    elif change == 'no-reference': data['resume_master']['activities'][0]['details'] = []
    else: data['resume_master']['activities'].pop(0)
    p, selection = parts(data)
    assert selection.selected[0]['context'] is None
    assert data['entries'][0]['text'] in p['resume_bullets']
    assert violations('At Beta Lab, I built the parser.', data) if change != 'missing-master' else True


@pytest.mark.parametrize('bad', ['candidate', 'withdrawn', 'stale', 'quote'])
def test_unconfirmed_or_changed_background_never_enters_prompt(bad):
    data = envelope(); field = data['resume_master']['activities'][0]['organization']
    if bad in ['candidate', 'withdrawn']: field['status'] = bad
    else:
        data['resume_text'] = 'Alpha Lab'
        field['source'] = {'kind': 'resume', 'signature': hashlib.sha256(b'Alpha Lab').hexdigest(), 'quote': 'Alpha Lab', 'start': 0, 'end': 9}
        if bad == 'stale': data['resume_text'] = 'Beta Lab!'
        else: field['source']['quote'] = 'Other Lab'
    p, selection = parts(data)
    assert 'Alpha Lab' not in ce._render_student_brief(p)
    assert 'organization' not in selection.selected[0]['context']['fields']
    assert selection.usage()['needs_review'] and 'activity_context_unconfirmed' in selection.usage()['notices']


@pytest.mark.parametrize('section,field,value', [('education', 'school', 'Alpha University'), ('publications', 'title', 'Parser Study')])
def test_other_master_detail_sections_keep_explicit_relationship(section, field, value):
    data = envelope(); data['resume_master']['activities'].pop(0)
    data['resume_master'][section] = [{'id': section, field: fact(section+'-fact', value), 'details': [{'id': 'experience-0', 'revision': 1}]}]
    _, selection = parts(data)
    assert selection.selected[0]['context']['section'] == section
    assert selection.selected[0]['context']['fields'][field]['value'] == value


def test_long_context_and_original_qualifiers_are_not_prefix_truncated():
    data = envelope(); text = 'Context 王\n' * 900 + 'I did not lead the team.'
    data['resume_master']['activities'][0]['organization']['value'] = text
    data['entries'][0]['text'] = 'My role: I built the parser.\nI did not train the model.'
    p, selection = parts(data)
    assert selection.selected[0]['context']['fields']['organization']['value'] == text
    assert json.dumps(text, ensure_ascii=False) in ce._render_student_brief(p)
    assert data['entries'][0]['text'] == selection.selected[0]['excerpt']


@pytest.mark.parametrize('mutation', [
    lambda d: d.pop('resume_master'), lambda d: d.update(version=1),
    lambda d: d['resume_master']['activities'][0]['title'].update(value=''),
    lambda d: d['resume_master']['activities'][0]['title'].update(value='x'*60001),
    lambda d: d['resume_master']['activities'][0]['title'].update(value='\ud800'),
    lambda d: d['resume_master']['activities'][0]['details'].append({'id':'experience-0','revision':1}),
])
def test_invalid_wire_rejects_without_repair_or_slicing(mutation):
    data=envelope();mutation(data)
    with pytest.raises(ValidationError): ExperienceEvidence.model_validate(data)


def test_v1_compatibility_keeps_original_selection_shape():
    selection=select_experience(ExperienceEvidence.model_validate(confirmed_experience(['I built the parser.'])), {})
    assert 'context' not in selection.selected[0]


@pytest.mark.parametrize('path', ['', 'stream', 'refine'])
def test_actual_provider_inputs_and_receipts_share_bound_full_facts(writing_client, monkeypatch, path):
    calls=[]
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    monkeypatch.setattr(ce, 'chat_completion', lambda messages, **kwargs: calls.append(deepcopy(messages)))
    data=envelope()
    response=post(writing_client[0], path, FIRST, engine='ai', experience_evidence=data)
    out=result(response,path)
    assert calls
    encoded=json.dumps(calls,ensure_ascii=False)
    assert 'Alpha Lab' in encoded and 'Beta Lab' in encoded and 'I built the parser.' in encoded
    for call in calls:
        student=next(message['content'] for message in call if 'Real resume experience' in message['content'])
        assert '"id": "alpha"' in student and '"master_revision": 5' in student
    # A deterministic fallback may quote no experience, but never invent its context.
    for selected in out['experience_usage']['selected']:
        assert selected['context']['id'] in ['alpha','beta']


@pytest.mark.parametrize('value', ['population genetics', 'I want to learn about cell lineage trees.', '我希望研究细胞谱系树。'])
def test_interest_hook_accepts_nouns_or_full_sentences_without_duplicate_prefix(value):
    p=_common_parts(PROFILE,OPP);p['research_interests']=value
    hook=_p1_research_hook(p)
    assert 'I am interested in I want' not in hook
    assert 'I am interested in 我' not in hook
    assert value.rstrip('.') in hook
    assert 'experience in' not in hook


@pytest.mark.parametrize('claim', [
    'At Alpha Lab in 2030, I built the parser.',
    'Beta Lab:\nI built the parser.',
    'At Beta Lab, I tested the model. I built the parser.',
])
def test_context_carry_and_unprovided_year_fail_closed(claim):
    p, _ = parts()
    assert ce._email_grounding_findings(claim, p, OPP)[0]


def test_two_explicit_activities_in_one_sentence_are_separately_supported():
    assert violations('I tested the model at Beta Lab and built the parser at Alpha Lab.') == []


def test_current_source_body_also_supports_its_own_date():
    data=envelope(); data['entries'][0]['text']='I built the parser in 2030.'
    assert violations('At Alpha Lab in 2030, I built the parser.', data) == []
    assert violations('At Beta Lab in 2030, I built the parser.', data)


def test_source_binding_disambiguates_shared_organization_but_claim_requires_disambiguation():
    data=envelope()
    for activity in data['resume_master']['activities']:
        activity['organization']['value']='Shared Lab'
    data['entries'][0]['text']='At Shared Lab, I built the parser.'
    assert violations('In Project Alpha at Shared Lab, I built the parser.', data) == []
    assert violations('At Shared Lab, I built the parser.', data)
    assert violations('In Project Beta at Shared Lab, I built the parser.', data)


@pytest.mark.parametrize('path', ['', 'stream', 'refine'])
@pytest.mark.parametrize('correct', [True, False])
def test_final_routes_accept_own_background_and_reject_cross_project_output(writing_client, monkeypatch, path, correct):
    client, _ = writing_client; name='Alpha' if correct else 'Beta'
    claim=f'At {name} Lab in 2024, I built the parser.'
    body=f'Dear Pat Lee,\n\n{claim}\n\nWould you be open to a brief conversation?\n\nBest,\nAudit Student'
    reply=('Subject: Research inquiry\n\n'+body) if path != 'refine' else body
    monkeypatch.setattr(ce,'is_configured',lambda:True)
    monkeypatch.setattr(ce,'chat_completion',lambda *_a,**_kw:reply)
    out=result(post(client,path,FIRST,engine='ai',experience_evidence=envelope()),path)
    if correct:
        assert out['method'] == ('llm' if path == 'refine' else 'ai')
        assert claim in out['body']
        assert out['experience_usage']['selected'][0]['context']['id'] == 'alpha'
    else:
        assert out['method'] == ('local' if path == 'refine' else 'template')
        assert out['fallback_reason'] == 'fabrication'
        assert claim not in out['body']


@pytest.mark.parametrize('path', ['', 'stream', 'refine', 'selection'])
def test_full_activity_background_obeys_per_call_budget_without_truncation(writing_client, monkeypatch, path):
    from tests.test_cold_email_selection_refine import payload
    client, opp = writing_client; data=envelope()
    # Each current master field remains admitted; repeated bound data and JSON
    # escaping must still fit the existing complete-message provider limit.
    data['resume_master']['activities'][0]['organization']['value']='"'*59000
    monkeypatch.setattr(ce,'is_configured',lambda:True)
    monkeypatch.setattr(ce,'chat_completion',lambda *_a,**_kw:pytest.fail('oversized context reached provider'))
    if path == 'selection':
        response=client.post('/api/cold-email/refine',json=payload(profile=PROFILE,opportunity_id=opp['id'],experience_evidence=data))
    else: response=post(client,path,FIRST,engine='ai',experience_evidence=data)
    if path == 'stream':
        events=[json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert events[-1]['code']=='EMAIL_INPUT_TOO_LARGE' and events[-1]['status']==413
        assert not any(event.get('stage')=='done' for event in events)
    else:
        assert response.status_code==413,response.text
        assert response.json()['detail']['code']=='EMAIL_INPUT_TOO_LARGE'


def test_draft_judge_critic_and_revise_share_bound_context(monkeypatch):
    p,_=parts();brief=ce._render_student_brief(p);prof=ce._render_professor_brief(p,OPP);calls=[]
    monkeypatch.setattr(ce,'chat_completion',lambda messages,**kw:calls.append(deepcopy(messages)))
    monkeypatch.setenv('OFE_COLD_EMAIL_NDRAFT','1')
    ce._pipeline_generate(PROFILE,OPP,None,parts_cache=p)
    ce._judge_drafts(['First draft.','Second draft.'],prof,brief,None)
    ce._llm_critique('First draft.',prof,brief,None)
    ce._revise_email('First draft.',{},prof,brief,None)
    assert len(calls)==4
    expected=json.dumps(p['experience_materials'],ensure_ascii=False)
    assert all(expected in call[1]['content'] for call in calls)


@pytest.mark.parametrize('claim', [
    'At Zeta Lab, I built the parser.', 'I built the parser at Zeta Lab.',
    'At Alpha Lab Annex, I built the parser.', 'I built the parser at Alpha Lab Annex.',
    'Zeta Lab:\nI built the parser.',
])
def test_unknown_activity_names_cannot_be_treated_as_unscoped(claim):
    p,_=parts()
    assert ce._email_grounding_findings(claim,p,OPP)[0]


@pytest.mark.parametrize('linked', [False, True])
@pytest.mark.parametrize('claim', [
    'At Zeta Lab in 2024, I built the parser.', 'I built the parser at Zeta Lab in 2024.',
])
def test_independent_original_keeps_its_own_explicit_organization_and_year(linked,claim):
    data=envelope();data['entries'][0]['text']=claim
    if linked: data['resume_master']['activities'][0]['details']=[]
    else: data['resume_master']=None
    assert violations(claim,data)==[]
    assert violations('At Zeta Lab in 2025, I built the parser.',data)
    assert violations('At Other Lab in 2024, I built the parser.',data)


@pytest.mark.parametrize('path',['','stream','refine'])
@pytest.mark.parametrize('named',[False,True])
def test_deleted_activity_context_cannot_return_through_actual_output(writing_client,monkeypatch,path,named):
    data=envelope();data['resume_master']['activities'].pop(1)
    claim='At Beta Lab, I tested the model.' if named else 'I tested the model.'
    body=f'Dear Pat Lee,\n\n{claim}\n\nWould you be open to a brief conversation?'
    reply=('Subject: Research inquiry\n\n'+body) if path!='refine' else body
    monkeypatch.setattr(ce,'is_configured',lambda:True)
    monkeypatch.setattr(ce,'chat_completion',lambda *_a,**_kw:reply)
    out=result(post(writing_client[0],path,FIRST,engine='ai',experience_evidence=data),path)
    if named:
        assert out['fallback_reason']=='fabrication'
        assert claim not in out['body']
    else:
        assert out['method']==('llm' if path=='refine' else 'ai')
        assert claim in out['body']


@pytest.mark.parametrize('original', [
    'I tested the parser in Python.', 'I built the parser in Rust.',
    'I built the parser for Open Source.', 'I tested the parser in UnfamiliarLanguage.',
    'I built the parser for A New Object.', 'At Zeta Lab, I built the parser.',
])
def test_complete_bound_original_with_unclassified_method_or_object_is_not_erased(original):
    data=envelope();data['entries'][0]['text']=original
    assert violations(original,data)==[]
    assert violations('At Beta Lab, I built the parser.',data)


def test_original_method_does_not_become_an_activity_alias():
    data=envelope();data['entries'][0]['text']='I built the parser in Rust.'
    assert violations('I built the parser at Rust.',data)
    assert violations('At Rust, I built the parser.',data)
