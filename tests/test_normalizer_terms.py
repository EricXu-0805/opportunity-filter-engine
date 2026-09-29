"""Source-to-normalized terms, including the B57 false positive regression."""
from src.normalizers.normalizer import normalize


def normalized(text, **kwargs):
    return normalize({'title': 'Research opening', 'description_raw': text, **kwargs})


def test_application_prose_is_not_information_science_or_r():
    result = normalized('Application materials: A CV is required.')
    assert result['eligibility']['majors'] == []
    assert result['eligibility']['skills_required'] == []
    assert result['eligibility']['skills_preferred'] == []


def test_required_preferred_and_positive_mentions_have_separate_roles():
    result = normalized('Python is required. SQL is preferred. We use MATLAB for analysis.')
    assert result['eligibility']['skills_required'] == ['Python']
    assert result['eligibility']['skills_preferred'] == ['SQL']
    assert result['metadata']['skill_mentions'] == ['MATLAB']
    assert result['metadata']['inferred_fields']['eligibility.skills_required'] == 'rule:opportunity_terms'
    assert result['metadata']['inferred_fields']['eligibility.skills_preferred'] == 'rule:opportunity_terms'
    assert result['metadata']['inferred_fields']['metadata.skill_mentions'] == 'rule:opportunity_terms'


def test_ambiguous_major_acronyms_need_local_education_context():
    result = normalized('This IS a notice. A CV is required. The STAT report is available.')
    assert result['eligibility']['majors'] == []
    result = normalized('Students majoring in CS, ECE, or IS are welcome.')
    assert set(result['eligibility']['majors']) == {'CS', 'ECE', 'IS'}
    assert result['metadata']['inferred_fields']['eligibility.majors'] == 'rule:opportunity_terms'


def test_normalizer_preserves_full_raw_and_b56_source_metadata():
    text = 'We use Python for analysis. ' + 'Original source content. ' * 100
    pages = {'version': 1, 'pages': [], 'merge_issue': None}
    result = normalized(text, extra_fields={'contact_instruction_pages': pages})
    assert result['description_raw'] == text
    assert result['metadata']['contact_instruction_pages'] == pages


def test_model_title_is_not_source_for_skills_majors_keywords_or_type():
    result = normalize({
        'title': 'Python machine learning internship in information science',
        'description_raw': 'Students contribute to a research project.',
        'extra_fields': {'inferred_fields': {'title': 'llm:url_parser'}},
    })
    assert result['title'].startswith('Python')  # presentation retained with its provenance
    assert result['metadata']['inferred_fields']['title'] == 'llm:url_parser'
    assert result['eligibility']['skills_required'] == []
    assert result['eligibility']['majors'] == []
    assert result['metadata']['skill_mentions'] == []
    assert 'machine learning' not in result['keywords']
    assert result['opportunity_type'] == 'research'


def test_ordinary_uppercase_is_near_students_is_not_a_major():
    assert normalized('This IS a notice for students.')['eligibility']['majors'] == []
    assert normalized('IS students are welcome.')['eligibility']['majors'] == ['IS']
    assert normalized('No CS degree is required.')['eligibility']['majors'] == []


def test_source_keywords_are_marked_as_rule_inferences():
    result = normalized('This research uses machine learning.')
    assert result['metadata']['inferred_fields']['keywords'] == 'rule:normalizer'


def test_eligibility_raw_and_late_text_reach_same_term_classifier():
    result = normalized('Background information. ' * 500, eligibility_text='R programming required. SQL preferred.')
    assert result['eligibility']['skills_required'] == ['R']
    assert result['eligibility']['skills_preferred'] == ['SQL']
