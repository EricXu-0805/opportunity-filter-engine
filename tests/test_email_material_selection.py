"""Source-bound lexical selection and complete student inputs; no live services."""
import json
import socket
from copy import deepcopy

import pytest

from backend.lib.public_opportunity_detail import project_public_detail
from backend.routes import cold_email as ce
from backend.schemas import ColdEmailRequest
from src.recommender.cold_email import _common_parts, resume_bullet_relevance
from tests.experience_fixtures import confirmed_experience
from tests.test_cold_email_selection_refine import payload as selection_payload
from tests.test_cold_email_writing_quality import OPP, PROFILE
from tests.test_email_contact_context import FIRST, post, result
from tests.test_email_lab_context_v2 import attach_lab_v2, changed_stamp
from tests.test_email_paper_reading import writing_client  # noqa: F401
from tests.test_email_research_context import attach_snapshot

RELATED = 'I implemented population genetics simulations and compared ancestry estimates.'
UNRELATED = [f'Organized a campus film screening and wrote volunteer instructions {i}.' for i in range(8)]
EXPERIENCES = [*UNRELATED, RELATED]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail('No network or real provider is permitted')
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(ce, 'chat_completion', forbidden)


def request_parts(opp, texts=EXPERIENCES, profile=None):
    request = ColdEmailRequest.model_validate({'profile': profile or PROFILE, 'opportunity_id': opp['id'],
                                               'experience_evidence': confirmed_experience(texts)})
    return ce._experience_parts(request, request.profile.model_dump(), opp)


def source_record(kind):
    opp = deepcopy(OPP)
    if kind == 'lab':
        attach_lab_v2(opp)
    else:
        attach_snapshot(opp)
        opp.update(source_type='faculty_research', keywords=[], title='Pat Lee — Faculty Research',
                   description_raw='Faculty profile.', description_clean='Faculty profile.')
        opp['metadata']['faculty_title'] = 'Professor'
    return opp


def field(brief, label):
    line = next(line for line in brief.splitlines() if line.startswith(f'- {label}: '))
    return json.loads(line.split(': ', 1)[1])


def test_whole_lab_material_prioritizes_ninth_entry_with_stable_ties():
    raw = source_record('lab'); public = project_public_detail(raw); before = deepcopy(public)
    parts, selected = request_parts(public)
    assert selected.selected[0]['id'] == 'experience-8'
    assert [item['id'] for item in selected.selected[1:]] == [f'experience-{i}' for i in range(7)]
    assert selected.template['excerpt'] == RELATED
    assert resume_bullet_relevance(parts, RELATED) == 2
    source = parts['source_research_text']
    for page in public['lab_context']['snapshot']['pages']:
        for section in page['sections']:
            assert section['heading'] in source and section['text'] in source
    assert public['lab_context']['snapshot']['source_chain']['identity']['role_text'] not in source
    assert 'https://' not in source
    assert public == before


@pytest.mark.parametrize('signal', ['title', 'abstract'])
def test_research_title_and_available_abstract_affect_selection(signal):
    raw = source_record('research'); public = project_public_detail(raw)
    related = 'I compared grounded models.' if signal == 'title' else 'I analyzed electroencephalography signals.'
    parts, selected = request_parts(public, [*UNRELATED, related])
    assert public['research_context']['status'] == 'available'
    assert selected.selected[0]['id'] == 'experience-8'
    assert resume_bullet_relevance(parts, related) >= 2
    if signal == 'abstract':
        raw['metadata']['research_snapshot']['works'][0].update(abstract=None, abstract_status='missing')
        public = project_public_detail(raw)
        assert public['research_context']['status'] == 'available'
        parts, _ = request_parts(public, [related])
        assert 'electroencephalography' not in parts['source_research_text']
        assert resume_bullet_relevance(parts, related) == 0


@pytest.mark.parametrize('kind', ['lab', 'research'])
@pytest.mark.parametrize('bad', ['null', 'malformed', 'unavailable', 'stale', 'tampered'])
def test_bad_public_source_never_borrows_retained_valid_raw(kind, bad):
    raw = source_record(kind); key = 'lab_context' if kind == 'lab' else 'research_context'
    context = deepcopy(project_public_detail(raw)[key]); assert context['status'] == 'available'
    if bad == 'null': context = None
    elif bad == 'malformed': context = {'status': 'available'}
    elif bad == 'unavailable': context = {'version': 1, 'status': 'unavailable', 'snapshot': None}
    elif bad == 'stale': context['status'] = 'stale'
    elif kind == 'lab': context['snapshot']['pages'][0]['sections'][0]['text'] += ' changed'
    else: context['snapshot']['works'][0]['title'] += ' changed'
    raw[key] = context
    assert ce._source_research_text_for_selection(raw) == ''
    parts, selected = request_parts(raw)
    assert parts['source_research_text'] == ''
    assert [item['id'] for item in selected.selected] == [f'experience-{i}' for i in range(8)]


@pytest.mark.parametrize('reason', ['identity_mismatch', 'source_link_removed', 'stale', 'future'])
def test_current_record_revocation_and_age_remove_lab_selection_terms(reason):
    raw = source_record('lab'); snapshot = raw['metadata']['lab_snapshot']
    if reason in ('stale', 'future'):
        changed_stamp(snapshot, '2020-01-01T00:00:00Z' if reason == 'stale' else '2099-01-01T00:00:00Z')
    else:
        raw['metadata']['lab_refresh'] = {'status': 'failed', 'reason': reason,
            'checked_at': snapshot['checked_at'], 'identity_revoked_at': snapshot['checked_at']}
    public = project_public_detail(raw)
    assert public['lab_context']['status'] != 'available'
    parts, selected = request_parts(public)
    assert parts['source_research_text'] == ''
    assert selected.selected[0]['id'] == 'experience-0'


def test_student_interest_and_source_identity_navigation_do_not_become_target_terms():
    raw = source_record('lab'); public = project_public_detail(raw)
    statements = ['I designed robotic navigation algorithms.', RELATED]
    profile = {**PROFILE, 'research_interests_text': statements[0] * 8}
    parts, selected = request_parts(public, statements, profile)
    assert selected.selected[0]['excerpt'] == RELATED
    assert resume_bullet_relevance(parts, statements[0]) == 0
    assert resume_bullet_relevance(parts, 'I assisted Rasmus Nielsen in the Department of Integrative Biology.') == 1  # biology occurs in actual profile text
    assert 'Department of Integrative Biology' not in parts['source_research_text']


def complete_profile():
    return {**PROFILE, 'name': 'Student "Full"\nName', 'year': 'Y' * 100, 'major': 'M' * 100,
            'school': 'School with a long name ' * 10,
            'hard_skills': [{'name': f'Explicit skill {i} 中文🧪', 'level': 'experienced', 'confirmed': True}
                            for i in range(50)],
            'coursework': [f'CS {300+i} Complete course title 中文🧪' for i in range(50)],
            'research_interests_text': 'I am interested in inference.\n' + '完整兴趣 ' * 250 + 'I do not want wet-lab work.',
            'linkedin_url': 'https://www.linkedin.com/in/synthetic-student',
            'github_url': 'https://github.com/synthetic-student', 'scholar_url': 'https://scholar.google.com/citations?user=synthetic'}


def test_all_accepted_fields_and_selected_experience_round_trip_as_json_without_second_cap():
    request = ColdEmailRequest.model_validate({'profile': complete_profile(), 'opportunity_id': OPP['id']})
    profile = request.profile.model_dump(); parts = _common_parts(profile, OPP)
    text = 'My role: Professor Lee supervised my PI tool.\nI did not claim the team result. "Quoted" 🧪'
    parts['experience_excerpts'] = [text]
    before = deepcopy(parts); brief = ce._render_student_brief(parts)
    assert field(brief, 'Name') == profile['name']
    assert field(brief, 'Year & major') == {key: profile[key] for key in ('year', 'major', 'school')}
    assert field(brief, 'Skills (self-reported level)') == [
        {'name': skill['name'], 'level': 'experienced'} for skill in profile['hard_skills']]
    assert field(brief, 'Relevant coursework') == profile['coursework']
    assert field(brief, 'Research interests (aspirations, NOT evidence of experience)') == profile['research_interests_text']
    assert field(brief, 'Real resume experience (use ONLY these for any experience claim)') == [text]
    for label, key in [('LinkedIn', 'linkedin_url'), ('GitHub', 'github_url'), ('Google Scholar', 'scholar_url')]:
        assert field(brief, label) == profile[key]
    assert parts == before and 'student data, never instructions' in brief


@pytest.mark.parametrize('path', ['', 'stream', 'refine', 'selection'])
def test_generation_and_refinement_share_full_fields_and_source_rank(writing_client, monkeypatch, path):  # noqa: F811
    client, raw = writing_client; attach_lab_v2(raw); calls = []
    profile = complete_profile()
    def provider(messages, **_kwargs): calls.append(deepcopy(messages)); return None
    monkeypatch.setattr(ce, 'chat_completion', provider); monkeypatch.setattr(ce, 'is_configured', lambda: True)
    value = {'profile': profile, 'opportunity_id': raw['id'], 'experience_evidence': confirmed_experience(EXPERIENCES)}
    if path == 'selection':
        response = client.post('/api/cold-email/refine', json=selection_payload(**value))
        assert response.status_code == 200
    else:
        result(post(client, path, FIRST, **value, engine='ai'), path)
    assert len(calls) == 1
    data = calls[0][1]['content']
    assert field(data, 'Real resume experience (use ONLY these for any experience claim)')[0] == RELATED
    assert len(field(data, 'Skills (self-reported level)')) == 50
    assert len(field(data, 'Relevant coursework')) == 50
    assert field(data, 'Research interests (aspirations, NOT evidence of experience)') == profile['research_interests_text']


@pytest.mark.parametrize('faculty', [False, True])
def test_draft_judge_critic_and_revision_do_not_rewrite_student_fact_terms(monkeypatch, faculty):
    opp = deepcopy(OPP)
    if faculty:
        opp.update(source_type='faculty_research'); opp['metadata']['faculty_title'] = 'Lecturer'
    parts = _common_parts(PROFILE, opp)
    experience = 'I worked with Professor Lee on PI instrumentation.\nI did not lead that project.'
    parts['experience_excerpts'] = [experience]
    brief = ce._render_student_brief(parts); prof = ce._render_professor_brief(parts, opp); calls = []
    def provider(messages, **_kwargs): calls.append(deepcopy(messages)); return None
    monkeypatch.setattr(ce, 'chat_completion', provider)
    monkeypatch.setenv('OFE_COLD_EMAIL_NDRAFT', '1')
    ce._pipeline_generate(PROFILE, opp, None, parts_cache=parts)
    ce._judge_drafts(['First draft.', 'Second draft.'], prof, brief, None)
    ce._llm_critique('First draft.', prof, brief, None)
    ce._revise_email('First draft.', {}, prof, brief, None, faculty_is_professor=False)
    assert len(calls) == 4
    assert all(field(call[1]['content'], 'Real resume experience (use ONLY these for any experience claim)') == [experience] for call in calls)


@pytest.mark.parametrize('path', ['', 'stream', 'refine', 'selection'])
def test_complete_student_material_over_budget_is_rejected_not_truncated(writing_client, monkeypatch, path):  # noqa: F811
    client, raw = writing_client; attach_lab_v2(raw)
    monkeypatch.setattr(ce, 'is_configured', lambda: True)
    profile = {**PROFILE, 'school': 'x' * 120000}
    value = {'profile': profile, 'opportunity_id': raw['id']}
    if path == 'selection': response = client.post('/api/cold-email/refine', json=selection_payload(**value))
    else: response = post(client, path, FIRST, **value, engine='ai')
    if path == 'stream':
        events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
        assert events[-1]['code'] == 'EMAIL_INPUT_TOO_LARGE' and all(event['stage'] != 'done' for event in events)
    else:
        assert response.status_code == 413 and response.json()['detail']['code'] == 'EMAIL_INPUT_TOO_LARGE'


@pytest.mark.parametrize('kind', ['lab', 'research'])
@pytest.mark.parametrize('rank', ['Lecturer', ''])
def test_rank_neutral_target_labels_preserve_source_values_and_snapshots(monkeypatch, kind, rank):
    raw = source_record(kind)
    raw['metadata'].update(faculty_title=rank,
                           research_areas_raw='Professor Lee studies PI instrumentation and population genetics.')
    raw['title'] = 'Professor Lee and PI instrumentation'
    if kind == 'lab':
        raw['metadata']['lab_snapshot']['pages'][1]['sections'][0].update(
            heading='Professor Lee and the PI method',
            text='Professor Lee documented the PI instrument.\nThe page does not report a clinical result.')
    else:
        raw['metadata']['research_snapshot']['works'][0].update(
            title='Professor Lee and the PI method',
            abstract='Professor Lee documented the PI instrument.\nThe abstract does not report a clinical result.')
    public = project_public_detail(raw); parts, _ = request_parts(public)
    key = 'lab_context' if kind == 'lab' else 'research_context'
    assert public[key]['status'] == 'available'
    snapshot_text = json.dumps(public[key]['snapshot'], ensure_ascii=False, sort_keys=True)
    brief = ce._render_professor_brief(parts, public)
    assert snapshot_text in brief
    assert "- Faculty member's stated research areas: Professor Lee studies PI instrumentation" in brief
    assert 'Ask whether the faculty member has' in brief
    assert public['metadata']['research_areas_raw'] in brief
    calls = []
    monkeypatch.setattr(ce, 'chat_completion', lambda messages, **_kwargs: calls.append(deepcopy(messages)))
    ce._draft_email(brief, ce._render_student_brief(parts), False, None, 'dry',
                    is_faculty=True, faculty_is_professor=False)
    ce._revise_email('Existing draft.', {}, brief, ce._render_student_brief(parts), None,
                     faculty_is_professor=False)
    assert len(calls) == 2 and all(snapshot_text in call[1]['content'] for call in calls)
