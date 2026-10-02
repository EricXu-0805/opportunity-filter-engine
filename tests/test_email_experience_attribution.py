"""Synthetic English boundaries, not an evaluation of general entailment."""
import json

import pytest

from backend.lib import email_experience_attribution as ea
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


@pytest.mark.parametrize('evidence,solo,shared', [
    ('With my team, I improved accuracy by 20%.', 'I improved accuracy by 20%.', 'With my team, I improved accuracy by 20%.'),
    ('Built a Python parser with my team.', 'I built a Python parser.', 'I built a Python parser with my team.'),
    ('I built a Python parser with my teammates.', 'I built a Python parser.', 'I built a Python parser with my teammates.'),
    ('I improved accuracy with our team by 20%.', 'I improved accuracy.', 'I improved accuracy by 20% with our team.'),
    ('I built a Python parser as part of a team.', 'I built a Python parser.', 'As part of a team, I built a Python parser.'),
])
def test_team_collaboration_qualifier_cannot_be_dropped_into_a_solo_claim(evidence, solo, shared):
    assert check(solo, [evidence])
    assert check(shared, [evidence]) == []


@pytest.mark.parametrize('mode', [False, True])
def test_team_qualifier_is_kept_in_resume_mode_and_beneficiary_is_not_collaboration(mode):
    claim = 'Built a Python parser.' if mode else 'I built a Python parser.'
    assert check(claim, ['Built a Python parser with my team.'], allow_subjectless_claims=mode)
    assert check('I built a Python parser.', ['I built a Python parser for my team.'], allow_subjectless_claims=mode) == []


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


@pytest.mark.parametrize('evidence,unsupported,supported', [
    pytest.param('My team built a Python parser. I wrote parser tests.',
                 'Built a Python parser and wrote parser tests. My team built a Python parser.',
                 'Wrote parser tests. My team built a Python parser.', id='team-quote-does-not-support-personal-fragment'),
    pytest.param('We built a Python parser. I wrote parser tests.',
                 'Built a Python parser.', 'We built a Python parser.', id='we-remains-team'),
    pytest.param('My teammate built a Python parser.',
                 'Built a Python parser.', 'My teammate built a Python parser.', id='teammate-remains-other-actor'),
    pytest.param('Helped build a parser.',
                 'Built a parser.', 'Helped build a parser.', id='help-is-not-independent-work'),
    pytest.param('Built a parser.',
                 'Independently built a parser.', 'Built a parser.', id='independence-must-be-supported'),
    pytest.param('Built a Python parser. Did not build the compiler.',
                 'Built a compiler. Did not build the compiler.',
                 'Built a Python parser. Did not build the compiler.', id='preserved-denial-does-not-justify-new-positive'),
    pytest.param('Built a parser. Did not build a parser.',
                 'Built a parser.', 'Did not build a parser.', id='explicit-denial-survives-positive-neighbor'),
    pytest.param('Tested the parser, not the model.',
                 'Tested the model.', 'Tested the parser, not the model.', id='object-negation'),
    pytest.param('Improved parser throughput by 45% and reduced parser latency by 12%.',
                 'Improved parser throughput by 12% and reduced parser latency by 45%.',
                 'Reduced parser latency by 12%. Improved parser throughput by 45%.', id='same-entry-swapped-axes'),
    pytest.param('Project A: Improved accuracy by 45%. Project B: Improved accuracy by 12%.',
                 'Project B: Improved accuracy by 45%.', 'Project B: Improved accuracy by 12%.', id='project-label'),
    pytest.param('Project A: Improved accuracy by 45%. Project B: Improved accuracy by 12%.',
                 'In Project A, improved accuracy by 12%.', 'In Project A, improved accuracy by 45%.', id='project-prefix'),
    pytest.param('Project A: Improved accuracy by 45%. Project B: Improved accuracy by 12%.',
                 'Improved accuracy by 45% in Project B.', 'Improved accuracy by 45% in Project A.', id='project-suffix'),
    pytest.param('Project A: Built a parser. Project B: Did not build a parser. My team built a parser.',
                 'Project B: Built a parser.', 'Project A: Built a parser.', id='denial-scoped-to-the-correct-project'),
    pytest.param('Changed accuracy by -5%.',
                 'Changed accuracy by 5%.', 'Changed accuracy by -5%.', id='negative-sign'),
    pytest.param('Improved accuracy by 5 percentage points.',
                 'Improved accuracy by 5 percent.', 'Improved accuracy by 5 percentage points.', id='percent-is-not-percentage-points'),
    pytest.param('Improved throughput by 45% at most.',
                 'Improved throughput by 45%.', 'Improved throughput by 45% at most.', id='quantity-bound'),
    pytest.param('Improved accuracy from 45% to 80%.',
                 'Improved accuracy to 45%.', 'Improved accuracy from 45% to 80%.', id='baseline-is-not-result'),
    pytest.param('Wrote tests for the parser.',
                 'Wrote the parser.', 'Wrote tests.', id='adjunct-is-not-the-object'),
    pytest.param('Outcome: Built a parser. My role: Wrote parser tests.',
                 'Built a parser.', 'Wrote parser tests.', id='ambiguous-outcome-not-personal-evidence'),
    pytest.param('Task: Built a parser. My role: Wrote parser tests.',
                 'Built a parser.', 'My role: Wrote parser tests.', id='ambiguous-task-not-personal-evidence'),
    pytest.param('My team built a parser and I wrote parser tests.',
                 'Built a parser and wrote parser tests.', 'Wrote parser tests. My team built a parser.', id='explicit-coordinated-actors'),
    pytest.param('Wrote parser tests.',
                 'Wrote parser tests and successfully built a parser.', 'Successfully wrote parser tests.', id='coordinated-modifier'),
    pytest.param('My team built a parser. Working with my team, I wrote parser tests.',
                 'Working with my team, I built a parser.', 'Working with my team, I wrote parser tests.', id='team-prefix-does-not-hide-i'),
])
def test_resume_mode_checks_subjectless_attribution_with_a_valid_control(evidence, unsupported, supported):
    assert check(unsupported, [evidence], allow_subjectless_claims=True)
    assert check(supported, [evidence], allow_subjectless_claims=True) == []


@pytest.mark.parametrize('evidence,claim', [
    ('Built a Python parser using NumPy.', 'Built a Python parser.'),
    ('I wrote parser tests using Python.', 'Wrote parser tests.'),
    ('Analyzed 10000 samples using Python.', 'Analyzed 10,000 samples.'),
    ('Improved throughput by 45% using Python.', 'Improved throughput by 45 percent.'),
    ('Improved throughput by 4.5 times.', 'Improved throughput by 4.5x.'),
    ('Improved throughput by 45.0%.', 'Improved throughput by 45%.'),
    ('My role: Built a parser.', 'Built a parser.'),
    ('Built a parser. Wrote parser tests.', '• Built a parser.\n- Wrote parser tests.'),
    ('My team built a parser and reduced latency by 12%.', 'My team built a parser and reduced latency by 12%.'),
])
def test_resume_mode_preserves_supported_fragments_and_local_numeric_formatting(evidence, claim):
    # 45.0 -> 45 is a helper-only equivalence; upstream resume numeric rules
    # still independently apply and are not relaxed by this option.
    assert check(claim, [evidence], allow_subjectless_claims=True) == []


def test_resume_option_is_keyword_only_and_default_email_behavior_is_unchanged():
    evidence = ['My team built a parser.']
    assert check('Built a parser.', evidence) == []
    assert check('Built a parser.', evidence, allow_subjectless_claims=False) == []
    assert check('Built a parser.', evidence, allow_subjectless_claims=True)
    assert check('I built a parser.', evidence)
    with pytest.raises(TypeError):
        check('Built a parser.', evidence, True)


@pytest.mark.parametrize('claim', [
    'Hope to build a parser.', 'Would build a parser.', 'If I built a parser, I could test it.',
    'Plan to improve accuracy by 45%.', 'Interested in research tools.',
])
def test_resume_mode_does_not_turn_plans_or_interests_into_completed_actions(claim):
    assert check(claim, [], allow_subjectless_claims=True) == []


def test_resume_mode_does_not_borrow_numbers_or_objects_from_other_entries():
    evidence = ['Improved parser throughput by 45%.', 'Reduced Linux setup time by 12%.']
    assert check('Reduced Linux setup time by 45%.', evidence, allow_subjectless_claims=True)
    assert check('Reduced Linux setup time by 12%.', evidence, allow_subjectless_claims=True) == []
    assert check('Built a Python parser.', ['Built a Python model.', 'My team built a Java parser.'], allow_subjectless_claims=True)
    assert check('Built a Python model.', ['Built a Python model.', 'My team built a Java parser.'], allow_subjectless_claims=True) == []


def test_resume_mode_keeps_unknown_labels_and_unknown_verbs_outside_personal_evidence():
    # These labels do not tell us whose result this is. They cannot authenticate
    # either an explicit I-claim or a personal resume fragment.
    assert check('Built a parser.', ['Outcome: Built a parser.'], allow_subjectless_claims=True)
    assert check('I built a parser.', ['Outcome: Built a parser.'], allow_subjectless_claims=True)
    assert check('Spearheaded a project.', [], allow_subjectless_claims=True) == []


@pytest.mark.parametrize('original,proposed', [
    ('Analyzed measurements with PyTorch across 88 samples.', 'Analyzed 88 samples with PyTorch.'),
    ('Analyzed measurement uncertainty.', 'Analyzed measurement uncertainty carefully.'),
])
def test_resume_mode_preserves_two_existing_legacy_rewrite_controls(original, proposed):
    assert check(proposed, [original], allow_subjectless_claims=True) == []
    # These are resume-only compatibility cases, not general email paraphrases.
    assert check('I ' + proposed, [original])


@pytest.mark.parametrize('original,unsupported,supported', [
    pytest.param('Analyzed measurements with PyTorch across 88 samples.',
                 'Analyzed 89 samples with PyTorch.', 'Analyzed 88 samples with PyTorch.', id='sample-count-must-match'),
    pytest.param('Analyzed measurements with PyTorch across 88 samples.',
                 'Analyzed 88 samples with TensorFlow.', 'Analyzed 88 samples with PyTorch.', id='sample-tool-must-match'),
    pytest.param('Analyzed participant measurements with PyTorch across 88 samples.',
                 'Analyzed 88 samples with PyTorch.', 'Analyzed participant measurements.', id='qualified-object-not-reassigned'),
    pytest.param('Analyzed measurements with PyTorch across 88 samples and analyzed measurements with NumPy across 12 samples.',
                 'Analyzed 88 samples with NumPy.', 'Analyzed 12 samples with NumPy.', id='tool-count-pair-not-a-bag'),
    pytest.param('Analyzed measurements with PyTorch across 2 samples. Improved throughput by 88%.',
                 'Analyzed 88 samples with PyTorch.', 'Analyzed 2 samples with PyTorch.', id='sample-count-not-from-another-action'),
    pytest.param('Analyzed measurements with PyTorch across at most 88 samples.',
                 'Analyzed 88 samples with PyTorch.', 'Analyzed measurements with PyTorch across at most 88 samples.', id='sample-bound-not-dropped'),
    pytest.param('Analyzed measurements with PyTorch across 88 samples. Did not analyze measurements.',
                 'Analyzed 88 samples with PyTorch.', 'Did not analyze measurements.', id='short-denial-of-measurements'),
    pytest.param('Analyzed measurements with PyTorch across 88 samples. Did not analyze 88 samples.',
                 'Analyzed measurements with PyTorch across 88 samples.', 'Did not analyze 88 samples.', id='short-denial-of-samples'),
    pytest.param('Analyzed 88 samples with PyTorch. Did not analyze measurements with PyTorch across 88 samples.',
                 'Analyzed 88 samples with PyTorch.', 'Did not analyze measurements with PyTorch across 88 samples.', id='equivalent-negative-structure'),
    pytest.param('My team analyzed measurements with PyTorch across 88 samples.',
                 'Analyzed 88 samples with PyTorch.', 'My team analyzed 88 samples with PyTorch.', id='sample-equivalence-preserves-team'),
    pytest.param('Analyzed measurement uncertainty not carefully.',
                 'Analyzed measurement uncertainty carefully.', 'Analyzed measurement uncertainty not carefully.', id='not-carefully-not-neutralized'),
    pytest.param('Analyzed measurement uncertainty only carefully.',
                 'Analyzed measurement uncertainty carefully.', 'Analyzed measurement uncertainty only carefully.', id='only-carefully-not-neutralized'),
    pytest.param('Analyzed measurement uncertainty.',
                 'Analyzed parser throughput carefully.', 'Analyzed measurement uncertainty carefully.', id='carefully-does-not-reassign-object'),
    pytest.param('Improved parser throughput by 45%.',
                 'Improved parser throughput by 12% carefully.', 'Improved parser throughput by 45% carefully.', id='carefully-does-not-reassign-number'),
    pytest.param('Deployed measurements with PyTorch across 88 samples.',
                 'Deployed 88 samples with PyTorch.', 'Deployed measurements with PyTorch across 88 samples.', id='sample-equivalence-only-analyze'),
])
def test_resume_legacy_compatibility_keeps_local_actors_objects_quantities_and_denials(original, unsupported, supported):
    assert check(unsupported, [original], allow_subjectless_claims=True)
    assert check(supported, [original], allow_subjectless_claims=True) == []


def test_resume_neutral_suffix_cannot_remove_the_only_recognized_object():
    assert check('Analyzed carefully.', ['Built a parser.'], allow_subjectless_claims=True)
    assert check('Analyzed carefully.', ['Analyzed carefully.'], allow_subjectless_claims=True) == []


def _resume_parse_receipt(original, proposed):
    """The full-target v6 receipt for one declared rewrite, with a reviewer that accepts."""
    from backend.lib.evidence_map import target_anchors
    from backend.lib.target_resume_ai import finalize, parse_output

    unit = {'unit_id': 'entry-1', 'section_id': 'activities', 'block_id': 'project-1',
            'evidence': {'kind': 'experience', 'id': 'experience-1', 'revision': 1},
            'original': original, 'before_text': original}
    raw = json.dumps({'units': [{'unit_id': unit['unit_id'], 'priority': 'normal', 'reason': 'method_relevance',
                                 'links': [], 'decision': 'rewrite', 'ops': [{'op': 'personal_first'}],
                                 'text': proposed, 'keep_reason': None}]})
    results, pending = parse_output(raw, [unit], target_anchors({'description': '', 'requirements': ['Python']}))
    return finalize(pending, ['accepted'] * len(pending))[0] if pending else results[0]


def _refused(receipt, original):
    """Never shown: the contract or a claim lock keeps the student's own line, with its advice."""
    return (receipt['status'] == 'unchanged' and receipt['before_text'] == original
            and receipt['reason_code'] in ('beyond_allowed_edit', 'rewrite_rejected')
            and receipt['suggestion']['proposed_text'] is None)


def _not_refused_as_fabrication(receipt):
    """A faithful edit is reviewed and suggested, or kept as a move the contract does not offer."""
    return receipt['status'] == 'suggested' or receipt['reason_code'] in ('beyond_allowed_edit', 'cosmetic_only')


@pytest.mark.parametrize('modifier', ['not', 'never', 'without', 'only', 'never entirely', 'without working', 'hardly', 'barely', 'rarely'])
def test_reviewed_carefully_restrictions_survive_retained_original_and_direct_parse(modifier):
    original = f'I analyzed measurement uncertainty, {modifier} carefully.'
    proposed = 'I analyzed measurement uncertainty carefully. ' + original
    assert check(proposed, [original], allow_subjectless_claims=True)
    assert check(original, [original], allow_subjectless_claims=True) == []
    assert _refused(_resume_parse_receipt(original, proposed), original)
    unchanged = _resume_parse_receipt(original, original)
    assert unchanged['status'] == 'unchanged' and unchanged['reason_code'] == 'cosmetic_only'
    assert unchanged['suggestion']['proposed_text'] is None


@pytest.mark.parametrize('prefix', ['', 'I '])
def test_reviewed_sample_equivalence_can_omit_only_the_confirmed_tool(prefix):
    original = prefix + 'Analyzed measurements with PyTorch across 88 samples.'
    proposed = prefix + 'Analyzed 88 samples.'
    assert check(proposed, [original], allow_subjectless_claims=True) == []
    assert _not_refused_as_fabrication(_resume_parse_receipt(original, proposed))


@pytest.mark.parametrize('original,unsupported,supported', [
    ('Analyzed measurements with PyTorch across 88 samples.', 'Analyzed 89 samples.', 'Analyzed 88 samples.'),
    ('Analyzed measurements with PyTorch across 88 samples.', 'Analyzed 88 users.', 'Analyzed 88 samples.'),
    ('Analyzed measurements with PyTorch across 12 samples. Improved throughput by 88%.', 'Analyzed 88 samples.', 'Analyzed 12 samples.'),
    ('Analyzed measurements with PyTorch across at most 88 samples.', 'Analyzed 88 samples.', 'Analyzed measurements with PyTorch across at most 88 samples.'),
    ('My team analyzed measurements with PyTorch across 88 samples.', 'Analyzed 88 samples.', 'My team analyzed 88 samples.'),
    ('Project A: Analyzed measurements with PyTorch across 88 samples. Project B: Analyzed measurements with NumPy across 12 samples.',
     'Project B: Analyzed 88 samples.', 'Project A: Analyzed 88 samples.'),
    ('Analyzed measurements with PyTorch across 88 samples. Did not analyze 88 samples.', 'Analyzed 88 samples.', 'Did not analyze 88 samples.'),
])
def test_reviewed_sample_shortening_preserves_count_unit_actor_scope_bound_and_denial(original, unsupported, supported):
    assert check(unsupported, [original], allow_subjectless_claims=True)
    assert check(supported, [original], allow_subjectless_claims=True) == []


@pytest.mark.parametrize('original,proposed', [
    ('Built Python ML models during coursework.', 'Built ML models with Python during coursework.'),
    ('Built ML models with Python during coursework.', 'Built Python ML models during coursework.'),
    ('Implemented Python machine learning projects for CS 225.', 'Implemented Python machine learning projects in CS 225.'),
    ('Implemented Python machine learning projects in CS 225.', 'Implemented Python machine learning projects during CS 225 coursework.'),
    ('Implemented Python machine learning projects during CS 225 coursework.', 'Implemented Python machine learning projects for CS 225.'),
    ('Implemented machine learning projects in Python for CS 225.', 'Implemented machine learning projects in Python during CS 225 coursework.'),
    ('Built Python ML models for CS 225.', 'Built ML models with Python during CS 225 coursework.'),
    ('Wrote MATLAB analysis for EEG recordings.', 'Wrote MATLAB analysis of EEG recordings.'),
    ('Wrote MATLAB analysis of EEG recordings.', 'Wrote MATLAB analysis for EEG recordings.'),
])
def test_reviewed_legacy_structures_preserve_full_object_tool_and_course(original, proposed):
    assert check(proposed, [original], allow_subjectless_claims=True) == []
    assert _not_refused_as_fabrication(_resume_parse_receipt(original, proposed))
    # No new equivalence leaks into email mode, even for an explicit I-claim.
    assert check('I ' + proposed, [original])


@pytest.mark.parametrize('original,unsupported,supported', [
    pytest.param('Built Python ML models during coursework.',
                 'Built ML models with MATLAB during coursework.', 'Built ML models with Python during coursework.', id='tool-swap'),
    pytest.param('Built Python ML models during coursework.',
                 'Built ML exercises with Python during coursework.', 'Built ML models with Python during coursework.', id='artifact-swap'),
    pytest.param('Implemented Python ML exercises in CS 225.',
                 'Implemented Python ML in CS 225.', 'Implemented ML exercises with Python in CS 225.', id='exercise-object-not-removed'),
    pytest.param('Implemented machine learning projects in Python for CS 225.',
                 'Implemented machine learning experiments in Python during CS 225 coursework.',
                 'Implemented machine learning projects in Python during CS 225 coursework.', id='projects-not-experiments'),
    pytest.param('Implemented Python machine learning projects for CS 225.',
                 'Implemented Python machine learning projects in CS 425.',
                 'Implemented Python machine learning projects in CS 225.', id='course-number-swap'),
    pytest.param('Implemented Python machine learning projects for CS 225.',
                 'Implemented Python machine learning projects in ECE 225.',
                 'Implemented Python machine learning projects during CS 225 coursework.', id='course-subject-swap'),
    pytest.param('Built Python ML models during coursework. Improved accuracy by 12%.',
                 'Built ML models with Python during coursework. Improved accuracy by 45%.',
                 'Built ML models with Python during coursework. Improved accuracy by 12%.', id='metric-cannot-move'),
    pytest.param('Project A: Built Python ML models during coursework. Project B: Built MATLAB ML models during coursework.',
                 'Project B: Built ML models with Python during coursework.',
                 'Project A: Built ML models with Python during coursework.', id='project-tool-association'),
    pytest.param('My team built Python ML models during coursework.',
                 'Built ML models with Python during coursework.',
                 'My team built ML models with Python during coursework.', id='team-not-personal'),
    pytest.param('Did not build Python ML models during coursework.',
                 'Built ML models with Python during coursework.',
                 'Did not build ML models with Python during coursework.', id='negative-not-positive'),
    pytest.param('Built Python ML models during coursework. Did not build ML models with Python during coursework.',
                 'Built Python ML models during coursework.',
                 'Did not build Python ML models during coursework.', id='equivalent-denial-not-hidden'),
    pytest.param('My team implemented Python machine learning projects for CS 225.',
                 'Implemented Python machine learning projects during CS 225 coursework.',
                 'My team implemented Python machine learning projects during CS 225 coursework.', id='course-keeps-team'),
    pytest.param('Did not implement Python machine learning projects for CS 225.',
                 'Implemented Python machine learning projects in CS 225.',
                 'Did not implement Python machine learning projects in CS 225.', id='course-keeps-negation'),
    pytest.param('Wrote MATLAB analysis for EEG recordings.',
                 'Wrote Python analysis of EEG recordings.', 'Wrote MATLAB analysis of EEG recordings.', id='analysis-tool-swap'),
    pytest.param('Wrote MATLAB analysis for EEG recordings.',
                 'Wrote MATLAB analysis of ECG recordings.', 'Wrote MATLAB analysis of EEG recordings.', id='analysis-object-swap'),
    pytest.param('My team wrote MATLAB analysis for EEG recordings.',
                 'Wrote MATLAB analysis of EEG recordings.', 'My team wrote MATLAB analysis of EEG recordings.', id='analysis-keeps-team'),
    pytest.param('Did not write MATLAB analysis for EEG recordings.',
                 'Wrote MATLAB analysis of EEG recordings.', 'Did not write MATLAB analysis of EEG recordings.', id='analysis-keeps-negation'),
    pytest.param('Wrote MATLAB analysis for EEG recordings. Did not write MATLAB analysis of EEG recordings.',
                 'Wrote MATLAB analysis for EEG recordings.', 'Did not write MATLAB analysis of EEG recordings.', id='analysis-equivalent-denial'),
])
def test_reviewed_legacy_structures_reject_local_fact_changes_with_positive_controls(original, unsupported, supported):
    assert check(unsupported, [original], allow_subjectless_claims=True)
    assert check(supported, [original], allow_subjectless_claims=True) == []


@pytest.mark.parametrize('original,unsupported', [
    ('Built clinical ML models during coursework.', 'Built ML models with clinical during coursework.'),
    ('Built Python ML models without coursework.', 'Built ML models with Python during coursework.'),
    ('Implemented Python ML projects for deployment.', 'Implemented Python ML projects in deployment.'),
    ('Wrote MATLAB scripts for EEG recordings.', 'Wrote MATLAB scripts of EEG recordings.'),
    ('Wrote documentation for EEG recordings.', 'Wrote documentation of EEG recordings.'),
    ('Implemented machine learning experiments in Python for CS 225.', 'Built machine learning experiments in Python during CS 225 coursework.'),
])
def test_reviewed_legacy_structures_do_not_enable_general_reordering_or_synonyms(original, unsupported):
    assert check(unsupported, [original], allow_subjectless_claims=True)
    assert check(original, [original], allow_subjectless_claims=True) == []


@pytest.mark.parametrize('prefix', ['', 'I '])
@pytest.mark.parametrize('actor', ['team', 'denial'])
@pytest.mark.parametrize('original_action,claim_action', [
    ('implement Python machine learning projects for CS 225', 'Implemented Python machine learning projects in CS 225'),
    ('process batch 12', 'Processed batch 12'),
    ('reach accuracy 0.9', 'Reached accuracy 0.9'),
])
def test_resume_numeric_sentence_boundary_cannot_hide_claim_behind_retained_source(prefix, actor, original_action, claim_action):
    if actor == 'team':
        verb, rest = original_action.split(' ', 1)
        original = 'My team ' + {'implement': 'implemented', 'process': 'processed', 'reach': 'reached'}[verb] + ' ' + rest + '. I wrote tests.'
    else:
        original = 'I did not ' + original_action + '.'
    proposed = prefix + claim_action + '. ' + original
    assert check(proposed, [original], allow_subjectless_claims=True)
    assert check(original, [original], allow_subjectless_claims=True) == []
    assert _refused(_resume_parse_receipt(original, proposed), original)


@pytest.mark.parametrize('original,proposed', [
    ('I reached accuracy 0.9. I wrote tests.', 'Reached accuracy 0.9. Wrote tests.'),
    ('I measured error 1.25. I wrote tests.', 'Measured error 1.25. Wrote tests.'),
    ('I measured error .25. I wrote tests.', 'Measured error .25. Wrote tests.'),
    ('Implemented Python ML exercises in CS 225. Wrote tests.', 'Implemented Python ML exercises during CS 225 coursework. Wrote tests.'),
])
def test_resume_numeric_sentence_boundary_preserves_decimals_and_each_personal_action(original, proposed):
    assert check(proposed, [original], allow_subjectless_claims=True) == []
    assert _not_refused_as_fabrication(_resume_parse_receipt(original, proposed))


@pytest.mark.parametrize('original,proposed', [
    ('Built Python ML models during coursework.', 'Built ML models during coursework.'),
    ('Built ML models with Python during coursework.', 'Built ML models during coursework.'),
    ('Implemented Python machine learning projects for CS 225.', 'Implemented machine learning projects in CS 225.'),
    ('Built MATLAB ML models.', 'Built ML models.'),
])
def test_resume_approved_tool_omission_is_source_direction_only(original, proposed):
    assert check(proposed, [original], allow_subjectless_claims=True) == []
    # Dropping a tool is a trim, which no route offers; it is never refused as a fabrication.
    assert _not_refused_as_fabrication(_resume_parse_receipt(original, proposed))
    # Removing a confirmed method is not permission to add that method to a
    # source that did not name it. Do not strip tools from both sides to match.
    assert check(original, [proposed], allow_subjectless_claims=True)


@pytest.mark.parametrize('original,unsupported,supported', [
    ('Built Python ML models during coursework.', 'Built ML exercises during coursework.', 'Built ML models during coursework.'),
    ('Implemented Python ML exercises in CS 225.', 'Implemented ML in CS 225.', 'Implemented ML exercises in CS 225.'),
    ('Implemented Python ML exercises in CS 225.', 'Implemented ML exercises in CS 425.', 'Implemented ML exercises in CS 225.'),
    ('Built Python ML models during coursework.', 'Built ML models during research.', 'Built ML models during coursework.'),
    ('My team built Python ML models during coursework.', 'Built ML models during coursework.', 'My team built ML models during coursework.'),
    ('Did not build Python ML models during coursework.', 'Built ML models during coursework.', 'Did not build ML models with Python during coursework.'),
    ('Project A: Built Python ML models during coursework. Project B: Built Python ML exercises during coursework.',
     'Project B: Built ML models during coursework.', 'Project A: Built ML models during coursework.'),
    ('Built Python ML models during coursework. Improved accuracy by 12%.',
     'Built ML models during coursework. Improved accuracy by 45%.', 'Built ML models during coursework. Improved accuracy by 12%.'),
    ('Built Python ML models during coursework. Did not build ML models with Python during coursework.',
     'Built ML models during coursework.', 'Did not build ML models with Python during coursework.'),
])
def test_resume_tool_omission_keeps_complete_artifact_context_and_attribution(original, unsupported, supported):
    assert check(unsupported, [original], allow_subjectless_claims=True)
    assert check(supported, [original], allow_subjectless_claims=True) == []


@pytest.mark.parametrize('positive', ['Built MATLAB ML models during coursework.', 'Built ML models with MATLAB during coursework.'])
def test_resume_tool_omission_does_not_transfer_a_denial_from_another_tool(positive):
    original = positive + ' Did not build Python ML models during coursework.'
    assert check('Built ML models during coursework.', [original], allow_subjectless_claims=True) == []


@pytest.mark.parametrize('separator', [', ', ': '])
@pytest.mark.parametrize('actor', ['team', 'denial'])
def test_resume_leading_fragment_is_not_hidden_by_later_explicit_subject(separator, actor):
    original = ('My team implemented Python machine learning projects for CS 225. I wrote tests.'
                if actor == 'team' else 'I did not implement Python machine learning projects for CS 225.')
    proposed = 'Implemented Python machine learning projects in CS 225' + separator + original
    assert check(proposed, [original], allow_subjectless_claims=True)
    assert _refused(_resume_parse_receipt(original, proposed), original)


@pytest.mark.parametrize('proposed', [
    'Built 1,000 parsers, I wrote tests.',
    'Built 1,000 parsers: I wrote tests.',
    'With my team, I built 1,000 parsers. I wrote tests.',
])
def test_resume_leading_fragment_retains_thousands_and_supported_explicit_subjects(proposed):
    original = 'I built 1000 parsers. I wrote tests.'
    assert check(proposed, [original], allow_subjectless_claims=True) == []


def test_resume_tool_omission_does_not_broaden_a_tool_specific_denial():
    original = 'Did not build Python ML models during coursework.'
    assert check('Did not build ML models during coursework.', [original], allow_subjectless_claims=True)
    assert check('Did not build ML models with Python during coursework.', [original], allow_subjectless_claims=True) == []


@pytest.mark.parametrize('positive', ['Built Python ML models during coursework.', 'Built ML models with Python during coursework.'])
def test_resume_tool_omission_keeps_a_broad_denial_for_both_tool_positions(positive):
    original = positive + ' Did not build ML models during coursework.'
    assert check('Built ML models during coursework.', [original], allow_subjectless_claims=True)
    assert check('Did not build ML models during coursework.', [original], allow_subjectless_claims=True) == []


COURSE = ('Built a PyTorch image classifier for chest X-ray triage in a CS 446 course project; '
          'reached 0.87 AUC on the NIH ChestX-ray14 validation split.')


@pytest.mark.parametrize('claim', [
    'In CS 446, I built a PyTorch image classifier for chest X-ray triage, reaching 0.87 AUC on the NIH '
    'ChestX-ray14 validation split, which gave me practical exposure to evaluating models.',
    'I built a PyTorch image classifier for chest X-ray triage, reaching 0.87 AUC on the NIH ChestX-ray14 validation split.',
    'I built a PyTorch image classifier for chest X-ray triage, which taught me how to evaluate a model.',
])
def test_a_trailing_result_phrase_is_its_own_claim_from_the_same_entry(claim):
    # Real Sonnet drafts phrase a confirmed result this way; reading the
    # participle as part of the object rejected every one of them.
    assert check(claim, [COURSE]) == []


@pytest.mark.parametrize('claim', [
    'I built a PyTorch image classifier for chest X-ray triage, reaching 0.95 AUC.',
    'I built a Python parser, reaching 0.87 AUC on the NIH ChestX-ray14 validation split.',
    'I built a PyTorch image classifier for chest X-ray triage, reducing latency by 12%.',
    'I built a PyTorch image classifier for chest X-ray triage, a compiler, and a database.',
])
def test_a_trailing_phrase_cannot_invent_or_borrow_a_result_or_add_objects(claim):
    assert check(claim, [COURSE, 'Built a Python parser.'])


def test_comma_free_source_wording_still_supports_the_same_words_with_a_comma():
    assert check('I built a Python parser, using Rust.', ['I built a Python parser using Rust.']) == []


def test_saying_i_only_helped_understates_and_is_supported_but_not_the_reverse():
    assert check('I helped build a Python parser.', ['Built a Python parser.']) == []
    assert check('I built a Python parser.', ['I helped build a Python parser.'])
    assert check('I did not help build a Python parser.', ['I did not build a Python parser.'])


@pytest.mark.parametrize('claim', [
    'I built a PyTorch image classifier for chest X-ray triage that reached 0.87 AUC on the NIH ChestX-ray14 validation split.',
    'I built a PyTorch image classifier for chest X-ray triage, which reached 0.87 AUC on the NIH ChestX-ray14 validation split.',
])
def test_a_relative_clause_result_is_checked_against_the_same_entry(claim):
    assert check(claim, [COURSE]) == []


@pytest.mark.parametrize('claim', [
    'I built a Python parser that reached 0.87 AUC on the NIH ChestX-ray14 validation split.',
    'I built a PyTorch image classifier for chest X-ray triage, which reached 0.95 AUC.',
])
def test_a_relative_clause_cannot_borrow_or_invent_a_result(claim):
    assert check(claim, [COURSE, 'Built a Python parser.'])


def test_unsupported_claims_are_reported_as_their_own_sentences():
    from backend.lib.email_experience_attribution import unsupported_experience_claims
    text = ('I built a PyTorch image classifier for chest X-ray triage. '
            'I use Python and PyTorch at an experienced level.')
    assert unsupported_experience_claims(text, [COURSE]) == ['I use Python and PyTorch at an experienced level']


@pytest.mark.parametrize('collaboration', [
    'with a teammate', 'with two classmates', 'with my research group', 'in a group of four',
    'collaboratively', 'with another student', 'with my lab partner', 'in collaboration with a postdoc',
])
def test_every_common_collaboration_phrase_keeps_team_credit(collaboration):
    source = f'Built a Python parser {collaboration}.'
    assert check('I built a Python parser.', [source])
    assert check(f'I built a Python parser {collaboration}.', [source]) == []


SURVEY = ('As part of a four-person team in PSYC 238, I helped design an online survey on sleep and memory '
          'and cleaned the 212 responses in R.')


@pytest.mark.parametrize('claim', [
    SURVEY,
    'In PSYC 238, as part of a four-person team, I helped design an online survey on sleep and memory.',
    'I helped design an online survey on sleep and memory.',
])
def test_a_source_sentence_that_opens_with_its_context_still_supports_its_own_action(claim):
    # Real drafts restated this entry almost verbatim and were rejected: the
    # source's "As part of ..., I helped design" was skipped entirely.
    assert check(claim, [SURVEY]) == []


def test_the_contextual_source_keeps_its_team_and_help_limits():
    assert check('I designed an online survey on sleep and memory.', [SURVEY])


@pytest.mark.parametrize('source', ['In CS 446, I built a Python parser.', 'During Spring 2026, I built a Python parser.'])
def test_a_prepositional_context_before_the_subject_is_not_a_reason_to_drop_the_fact(source):
    assert check('I built a Python parser.', [source]) == []


@pytest.mark.parametrize('source', ['My advisor said I should build a Python parser.', 'If I built a Python parser, I could test it.'])
def test_a_reported_or_conditional_prefix_still_supports_nothing(source):
    assert check('I built a Python parser.', [source])


# Main's patterns before they were made to read a line once; the oracle for the ones that replace them.
_ORIGINAL_PATTERNS = {
    "_CONTEXT_PREFIX": (r'(?:(?:at|in|for|on|during|within|through|while|with|as\s+part\s+of|as\s+a\s+member\s+of)\s+'
                        r'[^,]+,?\s*)+'),
    "_OBJECT_NEGATION": r'\s*,?\s+\b(?:but\s+not|not|rather\s+than|instead\s+of)\s+',
    "_PROJECT_SUFFIX": r'\s+(?:in|for|on|during)\s+((?:the\s+)?(?:project|study|experiment)\s+[\w -]{1,80})\s*$',
    "_CARE_QUALIFIER": r'\b(not|never|without|only|hardly|barely|rarely)\b[^.!?;\n]*\bcarefully\s*$',
}
_PATTERN_SAMPLES = [
    "in a lab, x", "in a in a in a, x", "within the lab", "with my team, at the lab, ", "as part of a team, as a "
    "member of the club,", "in a,, x", " in a", "into the lab", "in  a  ,  with  b", "as  part  of x", "IN A, AT B",
    "the parser, not the model", "the parser , not the model", "x   not  y", "x,not y", "x , but  not y", "a rather than b",
    "x instead  of y", "not y", "data in the project alpha", "data for the study beta  ", "x in project", "x  in  the  "
    "experiment 2", "never carefully", "only x carefully", "not x. y carefully", "x carefully", "not; carefully",
    "rarely  carefully  ", "notcarefully", "without notes carefully", "Only X Carefully"]


def _same_search(pattern, original, text):
    a, b = pattern.search(text), original.search(text)
    return (a and (a.span(), a.groups())) == (b and (b.span(), b.groups()))


class TestParserPatternsReadALineOnce:
    """Each pattern starts where a run of spaces starts and has one reading of a prefix.

    "\\s*,?\\s+" tried every split of a run, the context prefix every way to cut
    "in a in a ..." into phrases (exponential: 1.4 s for 14 phrases), and the
    closing "carefully" read the rest of the line from every limiting word.
    """

    @pytest.mark.parametrize(("name", "read", "text"), [pytest.param(*case, id=case[0]) for case in [
        ("_CONTEXT_PREFIX", lambda text: ea._CONTEXT_PREFIX.fullmatch(text), "in a " * 40 + ", x"),
        ("_CONTEXT_PREFIX long", lambda text: ea._CONTEXT_PREFIX.fullmatch(text), "in a, " * 10000 + "x"),
        ("_OBJECT_NEGATION", lambda text: ea._OBJECT_NEGATION.search(text), "x" + " " * 60000 + "y"),
        ("_OBJECT_NEGATION comma", lambda text: ea._OBJECT_NEGATION.search(text), "x" + " ," * 30000 + "y"),
        ("_PROJECT_SUFFIX", lambda text: ea._PROJECT_SUFFIX.search(text), "x" + " " * 60000 + "y"),
        ("_RESUME_COORDINATED", lambda text: ea._RESUME_COORDINATED.split(text), "x" + " " * 60000 + "y"),
        ("_RESUME_EXPLICIT_BOUNDARY", lambda text: ea._RESUME_EXPLICIT_BOUNDARY.split(text), "x" + " " * 60000 + "y"),
        ("_TRAILING", lambda text: list(ea._TRAILING.finditer(text)), "x" + " " * 60000 + "y"),
        ("_care_qualifier", lambda text: ea._care_qualifier(text), "only " * 12000 + "carefully x"),
        ("_facts carefully", lambda text: ea._facts(text, entry=0, source=True, allow_subjectless_claims=True),
         "Built x " + "only " * 12000 + "carefully x."),
        ("_facts subjects", lambda text: ea._facts(text, entry=0, source=True, allow_subjectless_claims=True),
         "x " + "we built y " * 5500),
        ("_facts object run", lambda text: ea._facts(text, entry=0, source=True, allow_subjectless_claims=True),
         "Built a" + " " * 60000 + "website and tested it.")]])
    def test_a_long_line_is_read_in_linear_time(self, name, read, text):
        import time

        started = time.perf_counter()
        read(text)
        assert time.perf_counter() - started < 1, name

    @pytest.mark.parametrize("text", _PATTERN_SAMPLES)
    def test_each_pattern_reads_a_line_as_the_original_did(self, text):
        import re

        original = {name: re.compile(pattern, re.I) for name, pattern in _ORIGINAL_PATTERNS.items()}
        assert bool(ea._CONTEXT_PREFIX.fullmatch(text)) == bool(original["_CONTEXT_PREFIX"].fullmatch(text))
        assert _same_search(ea._OBJECT_NEGATION, original["_OBJECT_NEGATION"], text)
        assert _same_search(ea._PROJECT_SUFFIX, original["_PROJECT_SUFFIX"], text)
        care = original["_CARE_QUALIFIER"].search(text)
        assert ea._care_qualifier(text) == (care[1] if care else None)

    @pytest.mark.parametrize("clause", ["if I built x", "ifI built x", "x unlesswe built y", "hope toI built x",
                                        "whether we built x", "we built x if I built y", "in a, I built x",
                                        "x we built y if z", "in a, we built y unless I built z"])
    def test_a_conditional_before_the_subject_is_read_as_before(self, clause):
        import re

        conditional = re.compile(r'\b(?:if|unless|whether|would|could|might|hope to|plan to|want to)\b', re.I)
        match = ea._CONDITIONAL.search(clause)
        lead = len(clause) - len(clause.lstrip())
        for subject in ea._SUBJECT.finditer(clause):
            before = clause[:subject.start()].strip()
            assert ea._conditional_before(clause, subject.start(), before, match, lead) == bool(
                conditional.search(before))
