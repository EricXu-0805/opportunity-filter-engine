"""B46 local source fixtures; no live ingestion, provider, or email sends."""
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from backend.lib.email_contact_context import (
    contact_context_receipt,
    email_research_works,
    paper_reading_sentence,
    validate_paper_reading,
)
from backend.lib.public_opportunity_detail import project_public_detail, writing_target_version
from backend.lib.public_projection import project_public_opportunity_payload
from backend.routes import cold_email as ce
from backend.schemas import EmailContactContext
from src.research_context import research_context_for
from tests.test_cold_email_writing_quality import OPP, PROFILE
from tests.test_email_contact_context import post, result
from tests.test_email_paper_reading import writing_client  # noqa: F401


def attach_snapshot(opp):
    opp.update(pi_name='Pat Lee', school='uiuc', source_url='https://example.edu/pat')
    snapshot = {
        'version': 1, 'source': 'openalex', 'record_source_url': opp['source_url'],
        'identity_name': opp['pi_name'], 'institution_id': 'https://openalex.org/I157725225',
        'author_id': 'https://openalex.org/A1', 'gate_version': 3,
        'checked_at': (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'works': [{'work_id': 'https://openalex.org/W1', 'title': 'Grounded Models 研究 🧪', 'year': 2025,
                   'publication_date': '2025-05-01', 'source_url': 'https://doi.org/10.1234/models',
                   'doi': 'https://doi.org/10.1234/models', 'abstract': 'The study uses electroencephalography to measure signals.',
                   'abstract_status': 'present', 'updated_date': '2026-09-01'}],
    }
    opp.setdefault('metadata', {}).update(publication_attribution_status='verified_author_id',
        publication_author_id=snapshot['author_id'], works_gate=3,
        research_snapshot=snapshot, recent_works=[{'title': 'Old unrelated cached work', 'year': 2025}])
    return snapshot


def bound_reading(opp, level='abstract'):
    snapshot = research_context_for(opp)['snapshot']; work = snapshot['works'][0]
    return {'version': 1, 'purpose': 'first_contact', 'paper_reading': {
        'title': work['title'], 'year': work['year'], 'work_id': work['work_id'],
        'snapshot_version': snapshot['snapshot_version'], 'level': level, 'confirmed': True}}


def test_public_projection_is_current_private_safe_detached_and_versioned():
    opp = deepcopy(OPP); stored = attach_snapshot(opp)
    opp['metadata']['research_refresh'] = {'error': 'private operational detail'}
    opp['research_context'] = {'poisoned': True}
    original = deepcopy(opp); public = project_public_detail(opp)
    assert public['research_context'] == research_context_for(opp)
    assert public['metadata']['recent_works'] == [{'title': stored['works'][0]['title'], 'year': 2025}]
    assert 'research_snapshot' not in public['metadata'] and 'research_refresh' not in public['metadata']
    assert opp == original
    version = writing_target_version(public)
    assert writing_target_version(project_public_detail(opp)) == version
    stored['works'][0]['abstract'] += ' A new source sentence.'
    assert writing_target_version(project_public_detail(opp)) != version
    assert public['research_context']['snapshot']['works'][0]['abstract'] != stored['works'][0]['abstract']
    card = project_public_opportunity_payload(deepcopy(opp), opp)
    assert 'research_snapshot' not in card['metadata'] and card['research_context']['snapshot']['works'][0]['abstract'] == stored['works'][0]['abstract']


@pytest.mark.parametrize('change', ['null', 'author', 'school', 'stale', 'future', 'privacy'])
def test_invalid_or_stale_new_sources_never_fall_back_to_old_title_cache(change):
    opp = deepcopy(OPP); stored = attach_snapshot(opp)
    if change == 'null': opp['metadata']['research_snapshot'] = None
    elif change == 'author': opp['metadata']['publication_author_id'] = 'https://openalex.org/A2'
    elif change == 'school': opp['school'] = 'stanford'
    elif change == 'stale': stored['checked_at'] = '2020-01-01T00:00:00Z'
    elif change == 'future': stored['checked_at'] = '2099-01-01T00:00:00Z'
    else: stored['works'][0]['abstract'] += ' Contact hidden@example.edu.'
    public = project_public_detail(opp)
    assert public['research_context']['status'] == ('stale' if change == 'stale' else 'unavailable')
    assert 'recent_works' not in public['metadata']
    assert email_research_works(public) == []
    old = {'version': 1, 'purpose': 'first_contact', 'paper_reading': {'title': 'Old unrelated cached work', 'year': 2025, 'level': 'title_only', 'confirmed': True}}
    with pytest.raises(ValueError): validate_paper_reading(old, public)
    assert 'hidden@example.edu' not in json.dumps(public)
    assert writing_target_version(public) == writing_target_version(project_public_detail(opp))


@pytest.mark.parametrize('changes', [
    {'work_id': None}, {'snapshot_version': None}, {'work_id': 'W1'}, {'work_id': True},
    {'snapshot_version': 'rs1:bad'}, {'work_id': 'https://openalex.org/A1'},
])
def test_reading_binding_schema_rejects_partial_or_invalid_ids(changes):
    opp = deepcopy(OPP); attach_snapshot(opp); value = bound_reading(opp); value['paper_reading'].update(changes)
    with pytest.raises(ValidationError): EmailContactContext.model_validate(value)


def test_same_title_and_year_do_not_allow_other_work_or_new_snapshot():
    opp = deepcopy(OPP); stored = attach_snapshot(opp); reading = bound_reading(opp)
    validate_paper_reading(reading, project_public_detail(opp))
    stored['works'][0]['work_id'] = 'https://openalex.org/W2'
    with pytest.raises(ValueError): validate_paper_reading(reading, project_public_detail(opp))
    newer = bound_reading(opp)
    assert contact_context_receipt(newer) != contact_context_receipt(reading)


@pytest.mark.parametrize('path', ['', 'variants', 'stream', 'refine'])
@pytest.mark.parametrize('level', ['title_only', 'abstract', 'full_text'])
def test_all_email_paths_keep_only_explicit_snapshot_bound_reading(writing_client, path, level):  # noqa: F811
    client, opp = writing_client; attach_snapshot(opp); value = bound_reading(opp, level)
    out = result(post(client, path, value), path)
    for variant in out.get('variants', [out]):
        assert variant['body'].count(paper_reading_sentence(value)) == 1
        assert variant['contact_context_receipt'] == contact_context_receipt(value)
        if level != 'full_text': assert 'read the full text' not in variant['body']


@pytest.mark.parametrize('path', ['', 'variants', 'stream', 'refine'])
@pytest.mark.parametrize('change', ['id', 'abstract', 'legacy'])
def test_all_email_paths_reject_changed_research_before_auth_or_provider(writing_client, monkeypatch, path, change):  # noqa: F811
    client, opp = writing_client; stored = attach_snapshot(opp); value = bound_reading(opp)
    if change == 'id': stored['works'][0]['work_id'] = 'https://openalex.org/W2'
    elif change == 'abstract': stored['works'][0]['abstract'] += ' Changed source.'
    else:
        del value['paper_reading']['work_id']; del value['paper_reading']['snapshot_version']
    async def forbidden(_authorization): pytest.fail('stale reading reached auth')
    monkeypatch.setattr(ce, 'authenticated_uid', forbidden)
    response = post(client, path, value)
    assert response.status_code == 422, response.text
    assert response.json()['detail']['code'] == 'EMAIL_READING_CHANGED'


def test_complete_abstract_is_target_vocabulary_never_student_competence_or_full_text():
    opp = deepcopy(OPP); stored = attach_snapshot(opp)
    stored['works'][0]['abstract'] = 'Electroencephalography ' + 'source text ' * 950
    public = project_public_detail(opp)
    request = ce.ColdEmailRequest(profile=PROFILE, opportunity_id=opp['id'])
    parts, _ = ce._experience_parts(request, request.profile.model_dump(), public)
    brief = ce._render_professor_brief(parts, public)
    assert stored['works'][0]['abstract'] in brief
    assert 'never full text' in brief and 'A title does not establish methods' in brief
    assert 'electroencephalography' in ce._build_email_corpus(parts, public)
    assert 'electroencephalography' not in ce._student_email_corpus(parts).lower()
    assert any(ce._email_grounding_findings('I have experience with electroencephalography.', parts, public))
    assert any(ce._email_grounding_findings('I have read your paper in full.', parts, public))
    assert parts['contact_paper_reading'] == ''


@pytest.mark.parametrize('claim', ['Your paper uses electroencephalography.', 'This study demonstrates improved accuracy.', 'The publication proves a result.'])
def test_a_title_only_snapshot_does_not_authorize_common_method_or_result_assertions(claim):
    opp = deepcopy(OPP); stored = attach_snapshot(opp)
    stored['works'][0].update(abstract=None, abstract_status='missing')
    public = project_public_detail(opp)
    request = ce.ColdEmailRequest(profile=PROFILE, opportunity_id=opp['id'])
    parts, _ = ce._experience_parts(request, request.profile.model_dump(), public)
    assert ce._title_only_paper_detail_claim(claim, public)
    assert any(ce._email_grounding_findings(claim, parts, public))
    assert not ce._title_only_paper_detail_claim('Does your paper use electroencephalography?', public)


def test_card_keeps_bounded_titles_from_the_same_source_without_copying_abstracts():
    from backend.routes.matches import _match_card
    opp = deepcopy(OPP); stored = attach_snapshot(opp)
    card = _match_card(opp)
    assert card['recent_works'] == [{'title': stored['works'][0]['title'], 'year': 2025}]
    assert 'research_context' not in card
    assert stored['works'][0]['abstract'] not in json.dumps(card)


def test_faculty_brief_preserves_all_three_maximum_length_titles_and_abstracts():
    opp = deepcopy(OPP); stored = attach_snapshot(opp)
    opp['source_type'] = 'faculty_research'; opp['metadata']['faculty_title'] = 'Professor'
    base = stored['works'][0]
    stored['works'] = [{**base, 'work_id': f'https://openalex.org/W{i + 1}',
                        'source_url': f'https://openalex.org/W{i + 1}', 'doi': None,
                        'title': '研' * 999 + str(i), 'abstract': '文' * 11999 + str(i)} for i in range(3)]
    public = project_public_detail(opp)
    request = ce.ColdEmailRequest(profile=PROFILE, opportunity_id=opp['id'])
    parts, _ = ce._experience_parts(request, request.profile.model_dump(), public)
    assert parts['is_faculty'] is True
    brief = ce._render_professor_brief(parts, public)
    for work in stored['works']:
        assert work['title'] in brief and work['abstract'] in brief
    assert 'Current opening confirmed: NO' in brief
