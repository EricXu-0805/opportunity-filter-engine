"""Deterministic copy keeps source facts, not inferred fit or commitments."""
from copy import deepcopy

import pytest

from backend.lib.email_contact_context import contact_context_parts, validate_paper_reading
from src.recommender.cold_email import _common_parts, generate_cold_email, generate_variants

PROFILE = {'name': 'Alex Example', 'year': 'sophomore', 'major': 'Computer Science',
           'school': 'UIUC', 'research_interests_text': 'research tools', 'hard_skills': []}
OPP = {'id': 'template-quality', 'title': 'Research Tools', 'pi_name': 'Pat Lee',
       'source_type': 'campus_program', 'opportunity_type': 'research',
       'keywords': ['Python parser tools'], 'description_raw': 'Research on Python parser tools.',
       'eligibility': {'skills_required': []}, 'application': {}, 'metadata': {'is_active': True}}
PAPER = {'title': 'Python Parser Tools for Research', 'year': 2025}
FIRST = {'version': 1, 'purpose': 'first_contact'}


def outputs(profile=None, opp=None, context=None, experience=()):
    profile, opp = deepcopy(profile or PROFILE), deepcopy(opp or OPP)
    parts = _common_parts(profile, opp, resume_bullets=list(experience))
    if context:
        validate_paper_reading(context, opp)
        parts.update(contact_context_parts(context))
    return [generate_cold_email(profile, opp, parts_cache=parts),
            *(v['text'] for v in generate_variants(profile, opp, parts_cache=parts))]


def test_project_only_never_becomes_lab_or_inferred_fit_or_flexible_time():
    for text in outputs():
        lowered = text.lower()
        for unsupported in ('your lab', 'closely align', 'aligns with', 'resonates', 'directly applicable',
                            'work around your availability', 'i would love', 'i have experience'):
            assert unsupported not in lowered
        assert 'Python parser tools' in text
        assert 'first step' in text and '?' in text


@pytest.mark.parametrize('label', ['Example Lab', 'Example Summer Program'])
def test_explicit_target_name_remains_literal_without_changing_entity_type(label):
    for text in outputs(opp={**OPP, 'lab_or_program': label}):
        assert label in text or 'Python parser tools' in text
        assert 'your lab' not in text.lower()
    assert label in outputs(opp={**OPP, 'lab_or_program': label})[0]


def test_inferred_lab_label_cannot_enter_copy():
    opp = {**OPP, 'lab_or_program': 'Fabricated Lab',
           'metadata': {'inferred_fields': {'lab_or_program': 'heuristic:generated_lab'}}}
    for text in outputs(opp=opp):
        assert 'Fabricated Lab' not in text


@pytest.mark.parametrize('level', ['title_only', 'abstract', 'full_text'])
@pytest.mark.parametrize('purpose', ['first_contact', 'referral', 'follow_up'])
def test_exact_confirmed_reading_and_availability_appear_once_before_request(level, purpose):
    opp = deepcopy(OPP)
    opp['metadata'].update(publication_attribution_status='verified_author_id', recent_works=[PAPER])
    context = {**FIRST, 'purpose': purpose,
               'paper_reading': {**PAPER, 'level': level, 'confirmed': True},
               'availability': {'text': 'I can contribute 6 hours per week during the semester.', 'confirmed': True}}
    if purpose == 'referral':
        context['referral'] = {'referrer_name': 'Jordan Rowan', 'referral_note': 'My advisor suggested this contact.', 'confirmed': True}
    elif purpose == 'follow_up':
        context['follow_up'] = {'sent_confirmed': True, 'previous_message': 'I asked about research tools.',
                                'sent_on': '2026-09-10', 'reply_status': 'received', 'reply_text': 'Please share your interests.'}
    parts = contact_context_parts(context)
    for text in outputs(opp=opp, context=context):
        reading = parts['contact_paper_reading']
        availability = context['availability']['text']
        assert text.count(reading) == 1
        assert text.count(PAPER['title']) == 1
        assert 'caught my attention' not in text
        assert text.count(availability) == 1
        ask = text.index('?', text.index('\n\n'))
        assert text.index(reading) < text.index(availability) < ask
        if purpose == 'follow_up':
            assert 'My name is' not in text and 'I am a sophomore' not in text
            assert text.count(parts['contact_opening']) == text.count(parts['contact_reply_line']) == 1
        elif purpose == 'referral':
            assert text.count(parts['contact_opening']) == 1
        if level != 'full_text':
            assert 'I have read the full text' not in text


@pytest.mark.parametrize('source_type', ['campus_program', 'faculty_research'])
def test_no_target_data_asks_without_inventing_research_topic_or_opening(source_type):
    opp = {'id': 'sparse', 'source_type': source_type, 'opportunity_type': 'research',
           'pi_name': 'Pat Lee', 'metadata': {'faculty_title': 'Professor'}, 'eligibility': {}}
    for text in outputs(opp=opp):
        assert 'your research on' not in text and 'your work on' not in text
        assert 'your lab' not in text and 'open position' not in text
        assert '?' in text
        if source_type == 'faculty_research':
            assert 'whether you have any current or upcoming research openings' in text
        else:
            assert 'first step' in text


def test_topic_overlap_does_not_make_confirmed_skills_a_fit_claim():
    profile = {**PROFILE, 'hard_skills': [{'name': 'Python', 'level': 'experienced', 'confirmed': True},
                                      {'name': 'Linux', 'level': 'beginner', 'confirmed': True}]}
    opp = {**OPP, 'keywords': ['Python parser tools', 'Linux setup'],
           'description_raw': 'Research on Python parser tools and Linux setup.',
           'eligibility': {'skills_required': ['Python', 'Linux']}}
    for text in outputs(profile=profile, opp=opp):
        assert 'Python' in text and 'Linux' in text
        for unsupported in ('directly applicable', 'directly apply', 'relevant to your', 'could support your'):
            assert unsupported not in text


def test_confirmed_experience_is_still_quoted_without_new_outcome():
    fact = 'My role: I wrote parser tests. Outcome: My team built a Python parser. I did not build the parser.'
    for text in outputs(experience=[fact]):
        assert '\n\n' + fact in text
        assert 'One example of my experience:' not in text
        assert 'I built a Python parser.' not in text


def test_legacy_contact_method_is_not_reported_as_a_source_instruction():
    for text in outputs(opp={**OPP, 'application': {'contact_method': 'portal'}}):
        assert 'Your posting directs' not in text
        assert 'submitted' not in text and 'applied through' not in text



def test_profile_or_target_fields_cannot_supply_unadmitted_context_sentences():
    profile = {**PROFILE, 'contact_paper_reading': 'I have read the full text of a paper.',
               'contact_availability': 'I can contribute 99 hours per week.',
               'contact_context': {'availability': {'text': 'I can contribute 99 hours per week.', 'confirmed': False}}}
    opp = {**OPP, 'contact_paper_reading': 'I have read the full text of a paper.',
           'contact_availability': 'I can contribute 99 hours per week.'}
    for text in outputs(profile=profile, opp=opp):
        assert 'read the full text' not in text and '99 hours' not in text
        assert 'work around your availability' not in text


def test_wet_lab_question_does_not_promise_training_or_a_mentor():
    opp = {**OPP, 'department': 'Biology', 'keywords': ['cell culture', 'microscopy'],
           'description_raw': 'Research on cell culture and microscopy.'}
    for text in outputs(opp=opp):
        assert 'safety training' in text and '?' in text
        assert 'I am happy to complete' not in text and 'graduate mentor' not in text
