"""Offline regressions for derived major/skill labels through real writers."""
import json
import socket
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.normalizers.enricher import _extract_skills_from_text, enrich_opportunity
from src.parsers import llm_tagger


def posting(text='', **changes):
    result = {'id': 'job-1', 'source': 'manual', 'source_type': 'internship',
              'title': 'Student role', 'url': 'https://example.edu/job',
              'description_clean': text, 'keywords': [], 'paid': 'unknown',
              'metadata': {'is_active': True},
              'eligibility': {'majors': [], 'skills_required': [], 'skills_preferred': [],
                              'international_friendly': 'unknown', 'preferred_year': []}}
    result.update(changes)
    return result


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, 'connect', lambda *a, **k: pytest.fail('External network forbidden'))


def tag(record):
    llm_tagger.apply_updates(record, llm_tagger.rule_based_tag(record))
    return record


@pytest.mark.parametrize('writer', [enrich_opportunity, tag])
def test_bare_mentions_do_not_become_requirements(writer):
    row = posting('The project uses Python to explore recorded measurements and compare reports across several experiments.')
    writer(row)
    assert row['eligibility']['skills_required'] == []
    assert row['eligibility']['skills_preferred'] == []
    assert row['metadata']['skill_mentions'] == ['Python']
    assert row['metadata']['inferred_fields']['metadata.skill_mentions'] == 'rule:opportunity_terms'


@pytest.mark.parametrize('writer', [enrich_opportunity, tag])
def test_required_preferred_order_is_from_language_not_array_position(writer):
    row = posting('Python is preferred. SQL is required.')
    writer(row)
    assert row['eligibility']['skills_required'] == ['SQL']
    assert row['eligibility']['skills_preferred'] == ['Python']
    assert 'eligibility.skills_required' in row['metadata']['inferred_fields']
    assert 'eligibility.skills_preferred' in row['metadata']['inferred_fields']


@pytest.mark.parametrize('writer', [enrich_opportunity, tag])
def test_domains_do_not_fabricate_tools(writer):
    row = posting('We study machine learning, statistics and computer vision.', keywords=['robotics'])
    writer(row)
    assert row['eligibility']['skills_required'] == []
    assert row['eligibility']['skills_preferred'] == []
    assert not set(row['metadata'].get('skill_mentions', [])) & {'Python', 'R', 'PyTorch', 'OpenCV', 'C++'}


def test_r_in_research_text_survives_without_initials_or_randd():
    assert 'R' in _extract_skills_from_text('Research assistant: R programming is required. Review the description.')
    assert 'R' not in _extract_skills_from_text('Research by John R. Smith in R&D.')


@pytest.mark.parametrize('field', ['description_raw', 'description_clean', 'description'])
def test_all_supported_description_storage_shapes_survive(field):
    row = posting(); row[field] = 'Research role: R programming is required.'
    enrich_opportunity(row); tag(row)
    assert row['eligibility']['skills_required'] == ['R']


@pytest.mark.parametrize('writer', [enrich_opportunity, tag])
def test_negative_statement_is_not_a_positive_mention(writer):
    row = posting('Python is not required. SQL is preferred.')
    writer(row)
    assert 'Python' not in row['eligibility']['skills_required']
    assert 'Python' not in row['metadata'].get('skill_mentions', [])
    assert row['eligibility']['skills_preferred'] == ['SQL']


def test_enricher_stamps_derived_majors_and_keywords_but_preserves_upstream():
    row = posting('Computer science research explores machine learning.')
    enrich_opportunity(row)
    assert 'CS' in row['eligibility']['majors']
    assert row['metadata']['inferred_fields']['eligibility.majors'] == 'rule:enricher'
    assert row['metadata']['inferred_fields']['keywords'] == 'rule:enricher'
    upstream = posting('Computer science research', keywords=['official topic'])
    upstream['eligibility'].update(majors=['ECE'], skills_required=['Verilog'], skills_preferred=['MATLAB'])
    before = deepcopy(upstream['eligibility']); enrich_opportunity(upstream); tag(upstream)
    assert upstream['eligibility'] == before
    assert 'keywords' not in upstream['metadata'].get('inferred_fields', {})
    assert 'eligibility.majors' not in upstream['metadata'].get('inferred_fields', {})


@pytest.mark.parametrize('text', ['Work on machine learning.', 'Python is preferred.', 'John R. Smith visits Java island.'])
def test_cached_or_model_skill_payload_cannot_bypass_source_classification(text):
    row = posting(text)
    llm_tagger.apply_updates(row, {'skills_required': ['Python', 'R', 'Java'], 'skills_preferred': ['C']}, method='llm:llm_tagger')
    assert row['eligibility']['skills_required'] == []
    assert row['eligibility']['skills_preferred'] == []


def test_llm_batch_skill_output_is_source_bounded_without_provider_call(monkeypatch):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'results': [
            {'skills_required': ['R', 'Java'], 'skills_preferred': ['SQL'], 'paid': 'unknown'}]})))])
    fake = SimpleNamespace(OpenAI=lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setitem(sys.modules, 'openai', fake)
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-fake-key'); monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    result = llm_tagger.llm_tag_batch([posting('Python is preferred. SQL is required.')])[0]
    assert result['skills_required'] == ['SQL'] and result['skills_preferred'] == ['Python']
    assert len(calls) == 1


def test_faculty_stays_out_of_opening_label_pipeline():
    row = posting('Python is required. R programming is preferred.', source_type='faculty_research')
    enrich_opportunity(row); tag(row)
    assert row['eligibility']['skills_required'] == row['eligibility']['skills_preferred'] == []
    assert 'skill_mentions' not in row['metadata']


def test_actual_refresh_postprocess_does_not_reintroduce_domain_skills(monkeypatch, tmp_path):
    from src.collectors import refresh_all
    from tests.test_refresh_all import _stub_with_processed_file
    row = posting('Research on machine learning and computer vision.')
    path = _stub_with_processed_file(monkeypatch, tmp_path, [row])
    summary = refresh_all.refresh_all(deep=False, schools={'uw'})
    saved = json.loads(path.read_text())[0]
    assert summary['sources']['auto_tagger']['status'] == 'ok'
    assert saved['eligibility']['skills_required'] == saved['eligibility']['skills_preferred'] == []
    assert 'Python' not in saved['metadata'].get('skill_mentions', [])


@pytest.mark.parametrize('text,required,preferred,mentioned', [
    ('The project uses Python.', [], [], ['Python']),
    ('Python is preferred. SQL is required.', ['SQL'], ['Python'], []),
    ('Research role: R programming is required.', ['R'], [], []),
    ('John R. Smith studied Java island before joining R&D.', [], [], []),
])
def test_normalize_enrich_tagger_roundtrip_is_stable(text, required, preferred, mentioned):
    from src.normalizers.normalizer import normalize
    row = normalize({'id': 'job-1', 'source': 'manual', 'source_type': 'internship',
                     'title': 'Student role', 'url': 'https://example.edu/job', 'description_raw': text})
    for _ in range(2):
        enrich_opportunity(row); tag(row)
        row = json.loads(json.dumps(row))
        assert row['eligibility']['skills_required'] == required
        assert row['eligibility']['skills_preferred'] == preferred
        assert row['metadata'].get('skill_mentions', []) == mentioned


def test_recomputed_mentions_clear_old_derived_weak_signal():
    row = posting('The project uses Python.')
    enrich_opportunity(row)
    assert row['metadata']['skill_mentions'] == ['Python']
    row['description_clean'] = 'Python is not required.'
    enrich_opportunity(row); tag(row)
    assert row['metadata']['skill_mentions'] == []


def test_enricher_keeps_requirement_after_old_clean_excerpt():
    row = posting('Student role introduction.', description_raw=('Introductory details. ' * 100) + 'SQL is required.')
    enrich_opportunity(row); tag(row)
    assert row['eligibility']['skills_required'] == ['SQL']


@pytest.mark.parametrize('writer', [enrich_opportunity, tag])
def test_model_inferred_title_cannot_create_skill_signal(writer):
    row = posting('SQL is required.', title='Python developer; Python required',
                  metadata={'inferred_fields': {'title': 'llm:url_parser'}})
    writer(row)
    assert row['eligibility']['skills_required'] == ['SQL']
    assert 'Python' not in row['metadata'].get('skill_mentions', [])


def test_inferred_title_cannot_reintroduce_major_or_keyword_labels():
    row = posting('Students contribute to the project.', title='Python Java information science intern',
                  metadata={'inferred_fields': {'title': 'llm:url_parser'}})
    enrich_opportunity(row)
    assert row['eligibility']['majors'] == []
    assert row['keywords'] == []
    original = posting('Students contribute to the project.', title='Information Science Intern')
    enrich_opportunity(original)
    assert 'IS' in original['eligibility']['majors']
    assert 'internship' in original['keywords']
