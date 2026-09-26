"""Synthetic English boundaries, not an evaluation of general entailment."""
import pytest

from backend.lib.email_experience_attribution import experience_attribution_violations as check

TEAM = 'My role: I wrote parser tests. Outcome: My team built a Python parser. I did not build the parser.'

@pytest.mark.parametrize('claim', ['I built a Python parser.', 'I have built a Python parser.', "I've built a Python parser.", 'I independently built a Python parser.'])
def test_team_result_and_explicit_denial_never_become_my_action(claim):
    assert check(claim, [TEAM])

@pytest.mark.parametrize('claim', ['I wrote parser tests.', 'My team built a Python parser.', 'We built a Python parser.', 'I did not build the parser.', TEAM])
def test_personal_role_team_attribution_and_full_negation_are_preserved(claim):
    assert check(claim, [TEAM]) == []

@pytest.mark.parametrize('evidence,claim', [
    (['Built a Python parser.'], 'I built a Python parser.'),
    (['I improved throughput by 45% using Python.'], 'I improved throughput by 45 percent.'),
    (['Analyzed 10000 samples using Python.'], 'I analyzed 10,000 samples.'),
    (['I improved throughput by 4.5 times.'], 'I improved throughput by 4.5x.'),
    (['I wrote parser tests. My team built a model.'], 'I wrote parser tests and would like to discuss your research.'),
    (['I improved throughput by 45% and reduced latency by 12%.'], 'I reduced latency by 12%.'),
])
def test_supported_personal_actions_and_equivalent_number_notation(evidence, claim):
    assert check(claim, evidence) == []

@pytest.mark.parametrize('claim', ['I am interested in Python.', 'I hope to build a parser.', 'I would build a parser.', 'If I built a parser, I could test it.', 'Could I ask about your work?'])
def test_non_actions_and_conditional_plans_do_not_claim_past_work(claim):
    assert check(claim, [TEAM]) == []

@pytest.mark.parametrize('evidence,claim', [
    (['My team improved throughput by 45%.'], 'I improved throughput by 45%.'),
    (['I helped build a parser.'], 'I built a parser.'),
    (['I built a parser.'], 'I independently built a parser.'),
    (['I did not build the parser. My team built the parser.'], 'I built the parser.'),
    (['I built the parser. I did not build the parser.'], 'I built the parser.'),
    (['I tested the parser, not the model.'], 'I tested the model.'),
    (['My teammate built a Python parser.'], 'I built a Python parser.'),
    (['I wrote tests.'], 'I wrote tests and built a Python parser.'),
    (['I built a parser.'], 'I built a parser and I trained a model.'),
    (['If I built a parser, I could test it.'], 'I built a parser.'),
])
def test_actor_qualifier_and_negation_adversaries(evidence, claim):
    assert check(claim, evidence)

@pytest.mark.parametrize('claim', ['I reduced Linux setup time by 45%.', 'I improved Python parser throughput by 12%.'])
def test_numbers_cannot_be_borrowed_from_a_different_entry(claim):
    assert check(claim, ['I improved Python parser throughput by 45%.', 'I reduced Linux setup time by 12%.'])

@pytest.mark.parametrize('claim', ['I reduced parser latency by 45%.', 'I improved parser throughput by 12%.'])
def test_numbers_cannot_be_swapped_between_objects_in_one_entry(claim):
    assert check(claim, ['I improved parser throughput by 45% and reduced parser latency by 12%.'])

@pytest.mark.parametrize('claim', ['In Project A, I improved accuracy by 12%.', 'Project B: I improved accuracy by 45%.', 'I improved accuracy by 45% in Project B.'])
def test_explicit_project_scope_survives_shared_action_and_metric_words(claim):
    assert check(claim, ['Project A: I improved accuracy by 45%.', 'Project B: I improved accuracy by 12%.'])

@pytest.mark.parametrize('claim', ['In Project A, I improved accuracy by 45%.', 'Project B: I improved accuracy by 12%.', 'I improved accuracy by 45% in Project A.'])
def test_correct_named_project_numbers_are_allowed(claim):
    assert check(claim, ['Project A: I improved accuracy by 45%.', 'Project B: I improved accuracy by 12%.']) == []


def test_negation_in_another_named_project_does_not_erase_supported_personal_work():
    evidence = ['Project A: I built a parser.', 'Project B: I did not build a parser. My team built a parser.']
    assert check('In Project A, I built a parser.', evidence) == []
    assert check('In Project B, I built a parser.', evidence)


def test_your_in_same_sentence_does_not_disable_local_achievement_check():
    assert check('I improved parser throughput by 80% and would like to discuss your Python research.', ['I improved parser throughput by 45%.'])


def test_no_cross_entry_keyword_union_or_shared_vocabulary_proof():
    assert check('I built a Python parser.', ['I built a Python model.', 'My team built a Java parser.'])


def test_does_not_mutate_original_evidence_or_echo_private_source_in_findings():
    original = ['My team built a private-tool-123 parser.']
    before = original.copy()
    result = check('I built a private-tool-123 parser.', original)
    assert result and original == before
    assert 'private-tool-123' not in str(result)


def test_finite_vocabulary_is_explicitly_not_a_general_semantic_certificate():
    # "spearheaded" is outside the declared action vocabulary. Other grounding
    # checks and review still apply; [] must never be described as proven true.
    assert check('I spearheaded the entire expedition.', []) == []

@pytest.mark.parametrize('evidence,claim', [
    (['I wrote tests for the parser.'], 'I wrote the parser.'),
    (['I built a parser using a model.'], 'I built a model.'),
    (['I tested a parser with a model.'], 'I tested a model.'),
    (['I improved accuracy from 45% to 80%.'], 'I improved accuracy to 45%.'),
])
def test_adjunct_object_or_baseline_cannot_be_promoted_to_the_completed_action(evidence, claim):
    assert check(claim, evidence)


def test_my_role_label_cannot_hide_an_unsupported_personal_fragment():
    assert check('My role: Built a Python parser.', [TEAM])
    assert check('My role: Wrote parser tests.', [TEAM]) == []

@pytest.mark.parametrize('prefix', ['With my team, ', 'Working with my team, '])
def test_contextual_team_prefix_cannot_hide_later_unsupported_i_action(prefix):
    assert check(prefix + 'I built a Python parser.', [TEAM])
    assert check(prefix + 'I wrote parser tests.', [TEAM]) == []
    assert check(prefix + 'I built a Python parser.', [prefix + 'I built a Python parser.']) == []


def test_coordinated_modifier_keeps_each_action_separate_and_preserves_valid_controls():
    assert check('I wrote parser tests and successfully built a Python parser.', [TEAM])
    assert check('I wrote parser tests and successfully built a Python parser.', ['I wrote parser tests. I built a Python parser.']) == []

@pytest.mark.parametrize('evidence,claim', [
    (['I changed accuracy by -5%.'], 'I changed accuracy by 5%.'),
    (['I improved accuracy by 5 percentage points.'], 'I improved accuracy by 5 percent.'),
    (['I improved throughput by 45% at most.'], 'I improved throughput by 45%.'),
])
def test_quantity_sign_type_and_bound_are_not_lost(evidence, claim):
    assert check(claim, evidence)


def test_shorter_explicit_denial_still_vetoes_supported_modified_object():
    assert check('I built a Python parser.', ['I built a Python parser. I did not build the parser.'])
    assert check('I built a Python parser.', ['I built a Python parser. I did not build the model.']) == []
