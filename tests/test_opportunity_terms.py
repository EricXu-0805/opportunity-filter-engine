"""Finite lexical classification: positive controls and ordinary prose traps."""
import pytest

from src.opportunity_terms import extract_skill_mentions, extract_skill_requirements


def classify(text):
    return extract_skill_requirements(text)


@pytest.mark.parametrize('text', [
    'Application materials: A CV is required.',
    'Research opportunities are currently open.',
    'Applicants must go to interviews and react to feedback.',
    'Dr. R. Smith and Professor C. Lee review resumes.',
    'Grade C or better is required. Vitamin C is studied.',
    'See https://example.org/R/Python/Java and contact go@react.dev.',
    'We study power transformers and use a glass flask.',
    'The island of Java and Java coffee are discussed.',
    'The team reviews rust corrosion.',
])
def test_ordinary_text_does_not_create_technical_skills(text):
    assert extract_skill_mentions(text) == []
    assert classify(text) == {'required': [], 'preferred': [], 'mentioned': []}


@pytest.mark.parametrize(('text', 'expected'), [
    ('Research using R programming.', ['R']),
    ('R programming experience is required for this research.', ['R']),
    ('Experience in C programming is preferred.', ['C']),
    ('Programming languages: R, C, Go', ['R', 'C', 'Go']),
    ('We use Go for backend development.', ['Go']),
    ('We use React to build interfaces.', ['React']),
    ('React.js development.', ['React']),
    ('Required: Python, R, C++', ['Python', 'R', 'C++']),
    ('Python and R for data analysis.', ['Python', 'R', 'data analysis']),
    ('JavaScript, TypeScript, C++, C#', ['JavaScript', 'TypeScript', 'C++', 'C#']),
    ('Java programming, C programming, R programming', ['Java', 'C', 'R']),
    ('LabVIEW Verilog VHDL FPGA PCB design CAD FEA PCR microscopy HPLC cell culture',
     ['LabVIEW', 'Verilog', 'VHDL', 'FPGA', 'PCB design', 'CAD', 'FEA', 'PCR', 'microscopy', 'HPLC', 'cell culture']),
])
def test_technical_terms_and_existing_tool_vocabulary_remain(text, expected):
    assert extract_skill_mentions(text) == expected


@pytest.mark.parametrize(('text', 'required', 'preferred', 'mentioned'), [
    ('Must know Python and R for data analysis. MATLAB preferred.', ['Python', 'R'], ['MATLAB'], ['data analysis']),
    ('Required: Python, R, C++\nPreferred: SQL', ['Python', 'R', 'C++'], ['SQL'], []),
    ('Python, SQL required.', ['Python', 'SQL'], [], []),
    ('Python required, SQL preferred.', ['Python'], ['SQL'], []),
    ('Python is required and SQL is preferred.', ['Python'], ['SQL'], []),
    ('Required skills:\n- Python\n- R programming\nPreferred skills:\n- SQL', ['Python', 'R'], ['SQL'], []),
    ('Python is required. Our research uses MATLAB.', ['Python'], [], ['MATLAB']),
    ('We use Python. A CV is required.', [], [], ['Python']),
    ('Technical skills: R, C, Go, React', [], [], ['R', 'C', 'Go', 'React']),
    ('No Python experience is required; SQL is preferred.', [], ['SQL'], []),
    ('Python is not required but SQL is preferred.', [], ['SQL'], []),
    ('We use Python, but no SQL experience is required.', [], [], ['Python']),
    ('<h2>Required skills:</h2><ul><li>Python</li><li>SQL</li></ul>', ['Python', 'SQL'], [], []),
    ('<a href="https://example.org/Python">JavaScript</a> is required.', ['JavaScript'], [], []),
])
def test_qualification_is_local_to_its_own_skill_clause(text, required, preferred, mentioned):
    assert classify(text) == {'required': required, 'preferred': preferred, 'mentioned': mentioned}


@pytest.mark.parametrize('text', [
    'No Python required.', 'Python is not required.', 'Python is optional.',
    'We do not use Python.', 'Python is required. Python is not required.',
    'Python is required. Python is preferred.',
    'Neither Python nor SQL is required.',
    'Without Python experience you can apply.',
])
def test_negation_and_conflict_never_turn_into_positive_mention(text):
    assert classify(text) == {'required': [], 'preferred': [], 'mentioned': []}
    assert extract_skill_mentions(text)  # diagnostic detection is not a positive signal


@pytest.mark.parametrize('text', ['', None, 17, [], {}])
def test_non_text_or_empty_input_has_no_labels(text):
    assert classify(text) == {'required': [], 'preferred': [], 'mentioned': []}


def test_long_source_retains_late_requirement_without_truncation():
    text = ('Application information. ' * 3000) + 'R programming is required. SQL is preferred.'
    assert classify(text) == {'required': ['R'], 'preferred': ['SQL'], 'mentioned': []}


@pytest.mark.parametrize('text', [
    'Python or R required.', 'Either Python or R is required.',
    'Applicants must know either Python or R.',
])
def test_alternative_languages_are_not_each_individually_required(text):
    assert classify(text) == {'required': [], 'preferred': [], 'mentioned': ['Python', 'R']}


@pytest.mark.parametrize('text', [
    'Python is not required but preferred.',
    'Python is preferred, not required.',
    'Python is not required. Python is preferred.',
])
def test_explicit_preference_can_coexist_with_not_required(text):
    assert classify(text) == {'required': [], 'preferred': ['Python'], 'mentioned': []}


@pytest.mark.parametrize(('text', 'mentioned'), [
    ('We use Python and do not use SQL.', ['Python']),
    ('We do not use Python and we use SQL.', ['SQL']),
    ('Rust is common on metal.', []),
    ('Rust programming is used in our software.', ['Rust']),
    ('Applicants must go home and react to stress.', []),
])
def test_mixed_claims_and_ordinary_homonyms(text, mentioned):
    assert classify(text) == {'required': [], 'preferred': [], 'mentioned': mentioned}


@pytest.mark.parametrize('text', [
    'Python or equivalent experience required.',
    'Python is required or willingness to learn.',
    'Python required unless training is provided.',
    'Python required if the project uses it.',
])
def test_equivalent_or_conditional_requirements_are_not_unconditional(text):
    assert classify(text) == {'required': [], 'preferred': [], 'mentioned': ['Python']}


def test_conjunction_really_requires_both_and_short_name_list_keeps_context():
    assert classify('Python and SQL are required.')['required'] == ['Python', 'SQL']
    assert classify('Python, R, C required.')['required'] == ['Python', 'R', 'C']


def test_contracted_not_required_can_have_explicit_preference():
    assert classify("Python isn't required but preferred.") == {'required': [], 'preferred': ['Python'], 'mentioned': []}


def test_lowercase_rust_in_metal_context_is_not_programming():
    assert extract_skill_mentions('Experience with rust in metals.') == []
    assert extract_skill_mentions('Experience with rust programming.') == ['Rust']


@pytest.mark.parametrize('text', [
    'We use Python and require a CV.',
    'A Python tutorial requires a CV.',
    'We use Python and a CV is required.',
    'The Python tutorial is required.',
    'Our project uses Python and a cover letter is preferred.',
])
def test_document_or_tutorial_requirement_does_not_become_a_skill_requirement(text):
    assert classify(text) == {'required': [], 'preferred': [], 'mentioned': ['Python']}
